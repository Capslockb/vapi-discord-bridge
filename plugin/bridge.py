"""
Discord Vapi Voice Bridge
===========================
In-process bridge: Discord Voice ↔ Vapi WebSocket transport.
Handles all audio streaming and connection lifecycle.
"""

import asyncio
import json
import logging
import os
import queue
import sys
import time
from pathlib import Path
from typing import Any, Optional, Dict, Callable
from urllib.parse import parse_qs, urlparse

import aiohttp
import numpy as np
import websockets

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vapi-voice")

# ── Config ──────────────────────────────────────────────────────────────
VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")
VAPI_API_URL = "https://api.vapi.ai/call"
VAPI_VOICE_PROVIDER = os.getenv("VAPI_VOICE_PROVIDER", "11labs")
VAPI_VOICE_ID = os.getenv("VAPI_VOICE_ID", "cjVigY5qzO86Huf0OWal")
VAPI_MODEL_PROVIDER = "openai"
VAPI_MODEL_NAME = os.getenv("VAPI_MODEL_NAME") or os.getenv("VAPI_MODEL", "gpt-4o-mini")
# Vapi Assistant Config — transient call inherits a saved assistant if VAPI_ASSISTANT_ID is set.
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")
VAPI_SYSTEM_PROMPT = os.getenv(
    "VAPI_SYSTEM_PROMPT",
    "You are a helpful AI assistant.",
)

# Resampling constants
DISCORD_SR = 48000
DISCORD_CH = 2
VAPI_SR = 16000
VAPI_CH = 1
SAMPLE_WIDTH = 2
FRAME_MS = 20
FRAME_SIZE = int(DISCORD_SR * FRAME_MS / 1000) * DISCORD_CH * SAMPLE_WIDTH

# Output audio quality
OUTPUT_PREROLL_MS = int(os.getenv("DISCORD_VAPI_OUTPUT_PREROLL_MS", "320"))
OUTPUT_FADE_IN_MS = int(os.getenv("DISCORD_VAPI_OUTPUT_FADE_IN_MS", "0"))
OUTPUT_READ_WAIT_SECONDS = float(os.getenv("DISCORD_VAPI_OUTPUT_READ_WAIT_SECONDS", "0.005"))
OUTPUT_TAIL_PAD_MS = int(os.getenv("DISCORD_VAPI_OUTPUT_TAIL_PAD_MS", "240"))
OUTPUT_CLEAR_ON_INTERRUPT = os.getenv(
    "DISCORD_VAPI_CLEAR_ON_INTERRUPT", "true"
).lower() in {"1", "true", "yes", "on"}

# Auto-leave
AUTO_LEAVE_QUIET_SECONDS = float(os.getenv("DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS", "900"))
AUTO_LEAVE_MIN_UPTIME_SECONDS = float(os.getenv("DISCORD_VAPI_AUTO_LEAVE_MIN_UPTIME_SECONDS", "120"))

# Idle prompt ("are you still there?")
IDLE_PROMPT_SECONDS = float(os.getenv("DISCORD_VAPI_IDLE_PROMPT_SECONDS", "120"))
IDLE_PROMPT_GRACE_SECONDS = float(os.getenv("DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS", "60"))
IDLE_PROMPT_TEXT = os.getenv("DISCORD_VAPI_IDLE_PROMPT_TEXT", "Are you still there?")

# Keepalive: JSON control ping during silent periods
KEEPALIVE_INTERVAL_SECONDS = float(os.getenv("DISCORD_VAPI_KEEPALIVE_SECONDS", "10"))
KEEPALIVE_MESSAGE = json.dumps({"type": "conversation-update", "status": "listening"})

# Control port (must match plugin.yaml)
HTTP_PORT = int(os.getenv("DISCORD_VAPI_PORT", "18944"))


# ── PCM helpers ────────────────────────────────────────────────────────
def _design_lowpass(cutoff: float, num_taps: int = 63) -> np.ndarray:
    """Design a lowpass FIR filter using windowed sinc.

    cutoff: normalised frequency (0-0.5, where 0.5 = Nyquist).
    num_taps: must be odd. Larger = sharper cutoff + better stopband rejection.
    Returns float32 coefficients normalised for unity DC gain.
    """
    if num_taps % 2 == 0:
        num_taps += 1
    half = num_taps // 2
    n = np.arange(-half, half + 1, dtype=np.float32)
    # Sinc lowpass: sin(2*pi*f*t)/(pi*t) → np.sinc(2*cutoff*n)
    h = np.sinc(2.0 * cutoff * n)
    # Hamming window
    w = np.hamming(num_taps).astype(np.float32)
    h = h * w
    h /= h.sum()  # unity DC gain
    return h


_RESAMPLE_LP_3 = _design_lowpass(1.0 / 3.0, num_taps=63)  # for 3:1 rate changes


def _resample_pcm(data: bytes, src_rate: int, src_ch: int, dst_rate: int, dst_ch: int) -> bytes:
    if not data:
        return b""
    raw = np.frombuffer(data, dtype=np.int16).astype(np.float32)

    # Channel conversion first
    if src_ch == 2 and dst_ch == 1:
        raw = raw.reshape(-1, 2).mean(axis=1)
    elif src_ch == 1 and dst_ch == 2:
        raw = np.repeat(raw, 2)

    if src_rate != dst_rate:
        if src_rate == 48000 and dst_rate == 16000:
            # Decimate by 3: anti-alias FIR, then decimate
            if len(raw) >= 3:
                filtered = np.convolve(raw, _RESAMPLE_LP_3, mode="same")
                raw = filtered[::3]
        elif src_rate == 16000 and dst_rate == 48000:
            # Interpolate by 3: zero-insert, FIR, scale by 3
            upsampled = np.zeros(len(raw) * 3, dtype=np.float32)
            upsampled[::3] = raw
            raw = np.convolve(upsampled, _RESAMPLE_LP_3, mode="same")
            raw = raw * 3.0  # upsampling gain
        else:
            src_len = len(raw)
            dst_len = int(src_len * dst_rate / src_rate)
            raw = np.interp(np.linspace(0, src_len - 1, dst_len), np.arange(src_len), raw)

    raw = np.clip(raw, -32768, 32767).astype(np.int16)
    return raw.tobytes()


def downsample_for_vapi(pcm_48k_stereo: bytes) -> bytes:
    return _resample_pcm(pcm_48k_stereo, DISCORD_SR, DISCORD_CH, VAPI_SR, VAPI_CH)


def upsample_for_discord(pcm_16k_mono: bytes) -> bytes:
    return _resample_pcm(pcm_16k_mono, VAPI_SR, VAPI_CH, DISCORD_SR, DISCORD_CH)


def _silence_pcm(sample_rate: int, channels: int, ms: int) -> bytes:
    samples = int(sample_rate * ms / 1000) * channels
    return b"\x00" * samples * SAMPLE_WIDTH


def _fade_in_pcm_mono(pcm: bytes, fade_ms: int, sample_rate: int) -> bytes:
    if not pcm or fade_ms <= 0:
        return pcm
    raw = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    fade_samples = min(len(raw), int(sample_rate * fade_ms / 1000))
    if fade_samples <= 1:
        return pcm
    raw[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    return np.clip(raw, -32768, 32767).astype(np.int16).tobytes()


def _has_speech_energy(pcm_48k_stereo: bytes) -> bool:
    if not pcm_48k_stereo:
        return False
    raw = np.frombuffer(pcm_48k_stereo, dtype=np.int16).astype(np.float32)
    if raw.size == 0:
        return False
    rms = float(np.sqrt(np.mean(raw * raw)))
    return rms >= 120.0


def _put_drop_oldest(q: "queue.Queue[Optional[bytes]]", item: Optional[bytes]) -> None:
    try:
        q.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        q.get_nowait()
    except queue.Empty:
        pass
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


# ── AudioSource (Discord playback) ──────────────────────────────────────
try:
    import discord as _discord_audio
    _AudioSourceBase = _discord_audio.AudioSource
except Exception:
    _AudioSourceBase = object


class LiveAudioSource(_AudioSourceBase):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=256)
        self._buffer = bytearray()
        self._stopped = False

    def feed(self, pcm_16k_mono: bytes) -> None:
        if self._stopped:
            return
        _put_drop_oldest(self._q, pcm_16k_mono)

    def wake(self) -> bool:
        return False

    def clear(self) -> None:
        try:
            with self._q.mutex:
                self._q.queue.clear()
        except Exception:
            pass
        self._buffer.clear()

    def finish(self) -> None:
        self._stopped = True
        _put_drop_oldest(self._q, None)

    def read(self) -> bytes:
        while len(self._buffer) < FRAME_SIZE:
            if self._stopped:
                return b""
            try:
                chunk = self._q.get(timeout=OUTPUT_READ_WAIT_SECONDS)
            except queue.Empty:
                return b"\x00" * FRAME_SIZE
            if chunk is None:
                self._stopped = True
                return b""
            pcm_48k_stereo = upsample_for_discord(chunk)
            self._buffer.extend(pcm_48k_stereo)
        frame = bytes(self._buffer[:FRAME_SIZE])
        self._buffer = self._buffer[FRAME_SIZE:]
        return frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        self._stopped = True


# ── VapiPCMSink (Discord receive → Vapi) ───────────────────────────────
try:
    from discord.ext import voice_recv
except Exception:
    voice_recv = None

if voice_recv is not None:
    class VapiPCMSink(voice_recv.AudioSink):
        """Receive Discord PCM (opus already decoded by Discord) and forward to Vapi."""

        def __init__(self, on_pcm_callback: Callable[[bytes], None]):
            super().__init__()
            self._on_pcm = on_pcm_callback
            self._frames = 0
            self._decoded_frames = 0
            self._skipped_bot = 0
            self._skipped_user_speaking = 0
            self._skipped_empty = 0
            self._skipped_silence = 0

        def wants_opus(self) -> bool:
            """Return False so voice_recv decodes for us — avoids DAVE-encrypted opus router crash."""
            return False

        def is_opus(self) -> bool:
            return False

        def write(self, user, data) -> None:
            if user is None:
                return
            if getattr(user, "bot", False):
                self._skipped_bot += 1
                return
            pcm = getattr(data, "pcm", b"") or b""
            if not pcm:
                self._skipped_empty += 1
                return
            # voice_recv PCM is 20ms chunks at 48k stereo
            self._frames += 1
            self._on_pcm(downsample_for_vapi(pcm))

        def cleanup(self) -> None:
            pass

        def stats(self) -> Dict[str, int]:
            return {
                "voice_sink_frames": self._frames,
                "voice_sink_skipped_bot": self._skipped_bot,
                "voice_sink_skipped_empty": self._skipped_empty,
            }

else:
    VapiPCMSink = None


# ── VapiBridge (WebSocket ↔ Vapi core) ─────────────────────────────────
class VapiBridge:
    def __init__(
        self,
        output_source: LiveAudioSource,
        on_wake: Callable[[], None] = None,
        on_leave_request: Callable[[str], None] = None,
    ):
        self._ws = None
        self._output_source = output_source
        self._on_wake = on_wake
        self._on_leave_request = on_leave_request
        self._running = False
        self._send_q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=256)
        self._tasks: list = []
        self._call_id: Optional[str] = None
        self._metrics: Dict[str, Any] = {
            "audio_in_chunks": 0,
            "audio_out_chunks": 0,
            "audio_out_bytes": 0,
            "json_control_in": 0,
            "json_control_out": 0,
            "connect_errors": 0,
        }
        self._output_turn_open = False

    async def _create_transient_call(self) -> str:
        headers = {
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json",
        }
        # Prefer saved assistant (inherits voice, model, tools, transcriber, fallbacks, etc.)
        if VAPI_ASSISTANT_ID:
            payload: Dict[str, Any] = {
                "assistantId": VAPI_ASSISTANT_ID,
                "transport": {
                    "provider": "vapi.websocket",
                    "audioFormat": {
                        "format": "pcm_s16le",
                        "container": "raw",
                        "sampleRate": 16000,
                    },
                },
            }
        else:
            payload = {
                "assistant": {
                    "model": {
                        "provider": VAPI_MODEL_PROVIDER,
                        "model": VAPI_MODEL_NAME,
                        "messages": [
                            {"role": "system", "content": VAPI_SYSTEM_PROMPT}
                        ],
                    },
                    "voice": {
                        "provider": VAPI_VOICE_PROVIDER,
                        "voiceId": VAPI_VOICE_ID,
                    },
                },
                "transport": {
                    "provider": "vapi.websocket",
                    "audioFormat": {
                        "format": "pcm_s16le",
                        "container": "raw",
                        "sampleRate": 16000,
                    }
                }
            }
        async with aiohttp.ClientSession() as session:
            async with session.post(VAPI_API_URL, headers=headers, json=payload) as resp:
                if resp.status != 201:
                    text = await resp.text()
                    raise RuntimeError(f"Vapi POST /call failed {resp.status}: {text}")
                result = await resp.json()
                transport = result.get("transport", {})
                ws_url = transport.get("websocketCallUrl", "")
                if not ws_url:
                    raise RuntimeError(f"No websocketCallUrl in response: {result}")
                self._call_id = result.get("id")
                return ws_url

    async def connect(self):
        ws_url = await self._create_transient_call()
        # Vapi WebSocket transport may need /transport suffix if missing
        parsed = urlparse(ws_url)
        if not parsed.path.endswith("/transport"):
            ws_url = ws_url.rstrip("/") + "/transport"
        logger.info("Vapi: connecting to WebSocket %s", ws_url)
        self._ws = await websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10,
        )
        logger.info("Vapi: WebSocket connected")
        self._running = True
        self._tasks = [
            asyncio.create_task(self._send_loop()),
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._keepalive_loop()),
        ]

    async def send_text(self, text: str) -> None:
        if not self._ws or not text.strip():
            return
        msg = {"type": "text", "text": text.strip()}
        await self._ws.send(json.dumps(msg))

    def feed_audio(self, pcm_16k_mono: bytes) -> None:
        self._metrics["audio_in_chunks"] += 1
        _put_drop_oldest(self._send_q, pcm_16k_mono)

    async def disconnect(self):
        self._running = False
        _put_drop_oldest(self._send_q, None)
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _send_loop(self):
        while self._running:
            try:
                chunk = self._send_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if chunk is None:
                break
            try:
                await self._ws.send(chunk)  # raw binary PCM
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("Vapi WebSocket closed (send): %s", e)
                self._running = False
                break
            except Exception as e:
                logger.error("Vapi send error: %s", e)
                self._running = False
                break
        # Drain the send queue so producer threads don't block
        while not self._send_q.empty():
            try:
                self._send_q.get_nowait()
            except queue.Empty:
                break

    async def _receive_loop(self):
        while self._running:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("Vapi WebSocket closed (receive): %s", e)
                self._running = False
                break
            except Exception as e:
                logger.error("Vapi receive error: %s", e)
                self._running = False
                break
            if isinstance(raw, str):
                # JSON control / status message
                try:
                    msg = json.loads(raw)
                    self._metrics["json_control_in"] += 1
                    logger.debug("Vapi JSON msg: %s", msg)
                    msg_type = msg.get("type")
                    if msg_type == "assistant-started":
                        logger.info("Vapi: assistant started — %s", msg.get("assistant", {}).get("name", "unknown"))
                    elif msg_type == "conversation-update":
                        status = msg.get("status")
                        if status in ("interrupted", "ended"):
                            if OUTPUT_CLEAR_ON_INTERRUPT:
                                self._output_source.clear()
                            self._output_turn_open = False
                    elif msg_type == "transcript":
                        text = msg.get("text", "")
                        if text and "disconnect" in text.lower():
                            if self._on_leave_request:
                                try:
                                    self._on_leave_request(text)
                                except Exception:
                                    pass
                except json.JSONDecodeError:
                    pass
                continue
            # Binary PCM audio
            if raw:
                self._metrics["audio_out_chunks"] += 1
                self._metrics["audio_out_bytes"] += len(raw)
                if not self._output_turn_open:
                    self._output_source.feed(_silence_pcm(VAPI_SR, VAPI_CH, OUTPUT_PREROLL_MS))
                    if OUTPUT_FADE_IN_MS > 0:
                        raw = _fade_in_pcm_mono(raw, OUTPUT_FADE_IN_MS, VAPI_SR)
                    self._output_turn_open = True
                self._output_source.feed(raw)
                if self._on_wake:
                    try:
                        self._on_wake()
                    except Exception:
                        pass

    async def _keepalive_loop(self):
        """Send silence every 20ms to keep Vapi from timing out during Discord connect."""
        import struct
        sr = int(VAPI_SR)
        silence = struct.pack('<' + 'h' * (sr // 50), *([0] * (sr // 50)))  # 20ms @ 16kHz
        while self._running:
            await asyncio.sleep(0.02)  # 20ms = 50 chunks/sec
            if self._send_q.empty():
                self.feed_audio(silence)

    def health(self) -> Dict[str, Any]:
        return dict(self._metrics)


# ── VapiVoiceBridge (Discord I/O wrapper) ──────────────────────────────
class VapiVoiceBridge:
    def __init__(self, voice_channel, discord_adapter):
        self._channel = voice_channel
        self._vc = None
        self._guild_id = voice_channel.guild.id
        self._audio_source = LiveAudioSource()
        self._listener = None
        self._leave_requested = False
        self._vapi = VapiBridge(
            self._audio_source,
            on_wake=self._wake_playback,
            on_leave_request=self._request_leave,
        )
        self._running = False
        self._started_at = None
        self._last_activity_at = time.monotonic()
        self._idle_prompted_at = None

    def _on_playback_end(self, error=None) -> None:
        if error:
            logger.error("Playback error: %s", error)

    def _wake_playback(self) -> None:
        if not self._running or not self._vc or not self._vc.is_connected():
            return
        try:
            if not self._vc.is_playing():
                self._vc.play(self._audio_source, after=self._on_playback_end)
        except Exception:
            pass

    def _record_activity(self) -> None:
        self._last_activity_at = time.monotonic()
        self._idle_prompted_at = None

    def _feed_audio(self, pcm_16k_mono: bytes) -> None:
        self._record_activity()
        self._vapi.feed_audio(pcm_16k_mono)

    def _request_leave(self, reason: str) -> None:
        if self._leave_requested:
            return
        self._leave_requested = True
        try:
            loop = self._vc.loop if self._vc else asyncio.get_running_loop()
            loop.create_task(self._stop_from_request(reason))
        except Exception:
            pass

    async def _stop_from_request(self, reason: str) -> None:
        logger.info("Vapi: stopping from user request: %s", reason)
        await self.stop()

    async def start(self) -> bool:
        logger.info("Vapi: connecting to %s in guild %d", self._channel, self._guild_id)
        if voice_recv is None or VapiPCMSink is None:
            logger.error("discord-ext-voice-recv is not installed; cannot receive Discord voice")
            return False

        existing_vc = getattr(self._channel.guild, "voice_client", None)
        if existing_vc and existing_vc.is_connected():
            try:
                logger.info("Vapi: disconnecting existing guild voice client")
                await asyncio.wait_for(existing_vc.disconnect(force=True), timeout=10.0)
            except Exception as e:
                logger.warning("Vapi: existing voice disconnect failed: %s", e)

        # Connect Vapi FIRST — transient call server gives up after ~20s,
        # and Discord voice connect on Amsterdam CDN takes ~27s internally.
        try:
            await self._vapi.connect()
        except Exception as e:
            logger.error("Vapi connect failed: %s", e)
            return False
        logger.info("Vapi: transient call + WebSocket established (%s)", self._vapi._call_id or "no-id")

        try:
            self._vc = await self._channel.connect(
                cls=voice_recv.VoiceRecvClient,
                timeout=60.0,
                reconnect=True,
                self_deaf=False,
            )
        except Exception as e:
            logger.error("Discord voice connect failed: %s", e)
            await self._vapi.disconnect()
            return False

        try:
            self._listener = VapiPCMSink(self._feed_audio)
            self._vc.listen(self._listener)
            self._vc.play(self._audio_source, after=self._on_playback_end)
        except Exception as e:
            logger.error("Failed to start Discord voice playback: %s", e)
            await self.stop()
            return False

        self._running = True
        self._started_at = time.monotonic()
        asyncio.create_task(self._connection_watchdog())
        logger.info("Vapi: bridge active for guild %d", self._guild_id)
        return True

    async def _connection_watchdog(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)
            if not self._vc or not self._vc.is_connected():
                if not self._running:
                    return
                logger.warning("Vapi: Discord disconnected. Stopping bridge.")
                await self.stop()
                return

            now = time.monotonic()
            idle = now - self._last_activity_at

            if IDLE_PROMPT_SECONDS > 0 and self._idle_prompted_at is None:
                if idle >= IDLE_PROMPT_SECONDS and self._started_at and now - self._started_at >= AUTO_LEAVE_MIN_UPTIME_SECONDS:
                    logger.info("Vapi: idle for %.0fs — prompting user", idle)
                    self._idle_prompted_at = now
                    try:
                        await self._vapi.send_text(IDLE_PROMPT_TEXT)
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Vapi: WebSocket closed during idle prompt")
                        await self.stop()
                        return
                    except Exception as e:
                        logger.error("Vapi: idle prompt failed: %s", e)

            # Check if WebSocket is still alive by peeking at connection state
            if not self._vapi._ws or not self._vapi._running:
                logger.warning("Vapi: WebSocket or bridge stopped. Stopping bridge.")
                await self.stop()
                return

            if idle >= AUTO_LEAVE_QUIET_SECONDS and self._started_at and now - self._started_at >= AUTO_LEAVE_MIN_UPTIME_SECONDS:
                logger.info("Vapi: auto-leave after idle %.0fs", idle)
                await self.stop()
                return

            if self._should_auto_leave_quiet():
                logger.info("Vapi: auto-leaving after %.0fs of quiet", idle)
                await self.stop()
                return

    def _should_auto_leave_quiet(self) -> bool:
        if AUTO_LEAVE_QUIET_SECONDS <= 0 or self._started_at is None:
            return False
        now = time.monotonic()
        if now - self._started_at < AUTO_LEAVE_MIN_UPTIME_SECONDS:
            return False
        if self._vc and self._vc.is_playing():
            return False
        return now - self._last_activity_at >= AUTO_LEAVE_QUIET_SECONDS

    async def stop(self):
        self._running = False
        self._audio_source.finish()
        if self._vapi:
            await self._vapi.disconnect()
        if self._vc and self._vc.is_connected():
            try:
                if hasattr(self._vc, "is_listening") and self._vc.is_listening():
                    self._vc.stop_listening()
            except Exception:
                pass
            try:
                self._vc.stop()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._vc.disconnect(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass
        logger.info("Vapi: bridge stopped")

    def health(self) -> Dict[str, Any]:
        vapi_metrics = dict(self._vapi.health()) if self._vapi else {}
        sink_stats = self._listener.stats() if self._listener and hasattr(self._listener, "stats") else {}
        return {
            "status": "ok" if self._running else "stopped",
            "running": self._running,
            "guild_id": self._guild_id,
            "voice_connected": bool(self._vc and self._vc.is_connected()),
            "receiving_active": bool(
                self._vc and hasattr(self._vc, "is_listening") and self._vc.is_listening()
            ),
            "playback_active": bool(self._vc and self._vc.is_playing()),
            "uptime_seconds": round(time.monotonic() - self._started_at, 3) if self._started_at else 0,
            "quiet_seconds": round(time.monotonic() - self._last_activity_at, 3),
            "auto_leave_quiet_seconds": AUTO_LEAVE_QUIET_SECONDS,
            "idle_prompt_seconds": IDLE_PROMPT_SECONDS,
            "idle_prompt_grace_seconds": IDLE_PROMPT_GRACE_SECONDS,
            "idle_prompted_seconds": round(time.monotonic() - self._idle_prompted_at, 3) if self._idle_prompted_at else None,
            **sink_stats,
            **vapi_metrics,
        }


# ── HTTP Control Server ────────────────────────────────────────────────
BRIDGE: Optional[VapiVoiceBridge] = None


async def handle_http_request(reader, writer):
    request_data = b""
    while True:
        line = await reader.readline()
        if not line or line == b"\r\n":
            break
        request_data += line
    request_text = request_data.decode("utf-8", errors="replace")
    lines = request_text.split("\r\n")
    if not lines:
        writer.close()
        return
    method_path = lines[0].split(" ")
    if len(method_path) < 2:
        writer.close()
        return
    path = method_path[1]
    parsed_url = urlparse(path)
    route = parsed_url.path
    response_body = ""
    status = 200
    if route == "/health":
        response_body = json.dumps(BRIDGE.health() if BRIDGE else {"status": "not_started", "running": False})
    elif route == "/stop":
        if BRIDGE and BRIDGE._running:
            await BRIDGE.stop()
            response_body = json.dumps({"status": "stopped"})
        else:
            response_body = json.dumps({"status": "not_running"})
    elif route == "/say":
        text = parse_qs(parsed_url.query).get("text", [""])[0]
        if BRIDGE and BRIDGE._running and text:
            await BRIDGE._vapi.send_text(text)
            response_body = json.dumps({"status": "sent", "text": text})
        else:
            response_body = json.dumps({"status": "error", "message": "Bridge not running or text missing"})
            status = 400
    else:
        response_body = json.dumps({"status": "error", "message": "Not found"})
        status = 404
    response = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(response_body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{response_body}"
    )
    writer.write(response.encode())
    await writer.drain()
    writer.close()


async def run_sidecar(vc, adapter, ready_future=None):
    global BRIDGE
    BRIDGE = VapiVoiceBridge(vc, adapter)
    server = None
    try:
        server = await asyncio.start_server(handle_http_request, "127.0.0.1", HTTP_PORT)
        logger.info("Vapi control API on 127.0.0.1:%d", HTTP_PORT)
        ok = await BRIDGE.start()
        if not ok:
            logger.error("Vapi bridge failed to start")
            if ready_future and not ready_future.done():
                ready_future.set_result({"ok": False, "message": "Bridge failed to start"})
            return
        if ready_future and not ready_future.done():
            ready_future.set_result({"ok": True, "health": BRIDGE.health(), "vc": BRIDGE._vc})
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        if ready_future and not ready_future.done():
            ready_future.cancel()
    except Exception as exc:
        if ready_future and not ready_future.done():
            ready_future.set_result({"ok": False, "message": str(exc)})
        raise
    finally:
        if server:
            server.close()
            await server.wait_closed()
        if BRIDGE:
            await BRIDGE.stop()


if __name__ == "__main__":
    if not VAPI_API_KEY:
        print("FATAL: VAPI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    print("Vapi bridge standalone test mode — run via Hermes plugin", file=sys.stderr)
