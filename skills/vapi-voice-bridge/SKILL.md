---
name: vapi-voice-bridge
description: Build and operate the Discord Vapi.ai voice bridge plugin for Hermes — transient call API, raw PCM WebSocket transport, audio resampling, Vapi-specific pitfalls, and optional native tool integration via function calling.
title: Vapi.ai Discord Voice Bridge
trigger:
  - vapi voice bridge
  - discord-vapi
  - vapi.ai websocket
  - transient call
  - pcm_s16le 16000
prerequisites:
  - VAPI_API_KEY set as environment variable
  - discord-ext-voice-recv installed
---

# Vapi.ai Discord Voice Bridge

Complete guide to the `discord-vapi` Hermes plugin — a bidirectional voice bridge between Discord voice channels and Vapi.ai's managed conversational AI.

## What This Covers

- Transient call creation via Vapi REST API
- Raw binary PCM WebSocket transport (not base64/JSON)
- 48kHz stereo ↔ 16kHz mono resampling with windowed-sinc FIR filters
- Connection ordering: Vapi first, Discord second
- Silent audio debugging (the `wants_opus`, `getattr(data, "pcm")`, `isinstance(data, bytes)` trilogy)
- Optional: native function calling / tool integration within the Vapi session
- Cost controls and assistant configuration modes

## Plugin Architecture

```
Hermes Gateway
      │
      ▼
discord-vapi/__init__.py  — registers tools, manages _active_bridges
      │
      ▼
discord-vapi/bridge.py
      ├── VapiBridge          — WebSocket ↔ Vapi (audio I/O)
      ├── VapiVoiceBridge     — Discord voice lifecycle wrapper
      ├── VapiPCMSink         — voice_recv.AudioSink (Discord mic → bridge)
      ├── LiveAudioSource     — discord.AudioSource (bridge → Discord playback)
      └── HTTP control server — /health, /stop, /say
```

## Transient Call Creation

### `assistantId` mode (preferred)

Inherit all settings from a dashboard-created assistant:

```json
POST https://api.vapi.ai/call
Authorization: Bearer {VAPI_API_KEY}
Content-Type: application/json

{
  "assistantId": "9de5352e-61ea-4b3b-9914-72fba94a009e",
  "transport": {
    "provider": "vapi.websocket",
    "audioFormat": {
      "format": "pcm_s16le",
      "container": "raw",
      "sampleRate": 16000
    }
  }
}
```

Inherits: voice, model, tools, transcriber, fallbacks, first message, compliance.

### Inline config mode (fallback)

```json
{
  "assistant": {
    "model": {
      "provider": "openai",
      "model": "gpt-4o",
      "messages": [...]
    },
    "voice": {
      "provider": "11labs",
      "voiceId": "cjVigY5qzO86Huf0OWal"
    }
  },
  "transport": {
    "provider": "vapi.websocket",
    "audioFormat": {
      "format": "pcm_s16le",
      "container": "raw",
      "sampleRate": 16000
    }
  }
}
```

### Response

```json
{
  "id": "call_abc123",
  "transport": {
    "websocketCallUrl": "wss://api.vapi.ai/v1/calls/call_abc123/websocket"
  }
}
```

## WebSocket Transport

### URL construction

Append `/transport` if missing:

```python
from urllib.parse import urlparse
ws_url = transport.get("websocketCallUrl", "")
parsed = urlparse(ws_url)
if not parsed.path.endswith("/transport"):
    ws_url = ws_url.rstrip("/") + "/transport"
```

### Send format — RAW BINARY PCM ONLY

```python
# CORRECT: raw signed 16-bit PCM, mono, 16kHz
await self._ws.send(chunk)  # bytes

# WRONG: causes immediate 1005 close
await self._ws.send(json.dumps({"type": "ping"}))  # text frame — REJECTED
```

### Receive format

```python
raw = await self._ws.recv()
if isinstance(raw, str):
    # JSON control/status
    msg = json.loads(raw)
    msg_type = msg.get("type")
    # handle "conversation-update", "transcript", etc.
    continue
# Binary: PCM audio for Discord playback
self._output_source.feed(raw)
```

### Keepalive

Do NOT implement application-level keepalive. The `websockets` library's built-in `ping_interval=20` is sufficient.

```python
self._ws = await websockets.connect(
    ws_url,
    ping_interval=20,
    ping_timeout=10,
)
```

Sending JSON/text keepalive messages causes immediate connection drops.

## Resampling Pipeline

Discord: 48kHz stereo. Vapi: 16kHz mono.

```python
def _resample_pcm(data: bytes, src_rate, src_ch, dst_rate, dst_ch) -> bytes:
    raw = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    # Channel conversion
    if src_ch == 2 and dst_ch == 1:
        raw = raw.reshape(-1, 2).mean(axis=1)
    elif src_ch == 1 and dst_ch == 2:
        raw = np.repeat(raw, 2)
    # Rate conversion (pre-computed FIR filter recommended)
    if src_rate != dst_rate:
        if src_rate == 48000 and dst_rate == 16000:
            filtered = np.convolve(raw, _RESAMPLE_LP_3, mode="same")
            raw = filtered[::3]
        elif src_rate == 16000 and dst_rate == 48000:
            upsampled = np.zeros(len(raw) * 3, dtype=np.float32)
            upsampled[::3] = raw
            raw = np.convolve(upsampled, _RESAMPLE_LP_3, mode="same")
            raw = raw * 3.0  # upsampling gain correction
    return np.clip(raw, -32768, 32767).astype(np.int16).tobytes()
```

See `references/pcm-resampling-fir.md` in `voice-bridge-protocols` for filter design details.

## Connection Ordering (Critical)

Vapi transient call servers timeout after ~20s of inactivity. Discord voice connect on Amsterdam CDN takes ~27s due to 4006 handshake retries.

**Correct order:**

1. Create transient call + connect Vapi WebSocket (~1s)
2. Join Discord voice (~27s)
3. Start audio I/O

**Wrong order** (Discord first, Vapi second) causes 1005 disconnect because the WebSocket times out before Discord connects.

```python
async def start(self):
    await self._vapi.connect()  # FAST — do this first
    self._vc = await self._channel.connect(...)  # SLOW — do this second
    # Start audio I/O
```

See `references/vapi-connection-ordering.md` in `voice-bridge-protocols`.

## The Silent Audio Trilogy

Three separate bugs that cause dead-silence while all connection indicators stay green:

### Bug 1: `wants_opus() -> True`

Always return `False` so `voice_recv` handles DAVE decryption and Opus decode:

```python
def wants_opus(self) -> bool:
    return False  # CORRECT
```

### Bug 2: `getattr(data, "data")` instead of `getattr(data, "pcm")`

`VoiceData` stores PCM in `.pcm`, not `.data`:

```python
# WRONG
pcm = getattr(data, "data", b"") or b""  # always empty

# CORRECT
pcm = getattr(data, "pcm", b"") or b""
```

### Bug 3: Missing `isinstance(data, bytes)` guard

`voice_recv` sometimes passes raw `bytes` directly instead of a `VoiceData` object. Without branching on type, this silently drops 100% of audio.

```python
# CORRECT
def write(self, user, data) -> None:
    if isinstance(data, bytes):
        pcm = data
    else:
        pcm = getattr(data, "pcm", b"") or b""
    if not pcm:
        return
    self._on_pcm(pcm)
```

See `references/vapi-silent-audio-bug.md` in `voice-bridge-protocols`.

## Tool Integration (Optional)

Vapi natively supports function calling. Define tools in your assistant's configuration (dashboard or inline), and Vapi will automatically invoke them during the conversation.

### Via Assistant Dashboard

1. Create/edit assistant at https://dashboard.vapi.ai/
2. Add "Functions" under Tools
3. Define JSON schema for each function (same format as OpenAI function calling)
4. Provide a webhook URL for Vapi to POST tool call results

### Webhook Handler

Vapi sends POST requests to your tool webhook URL:

```json
{
  "toolCallId": "call_abc123",
  "function": {
    "name": "spotify_play",
    "arguments": {"query": "Daft Punk"}
  }
}
```

Your webhook server must respond with:

```json
{
  "toolCallId": "call_abc123",
  "result": "Playing Daft Punk - Around the World",
  "status": "success"
}
```

### In-Process Tool Fallback (if no webhook exposure)

If you cannot expose a webhook publicly, use the Gemini Live Spotify Tools pattern as a reference (`devops/gemini-live-spotify-tools`). For Vapi, tool calling is managed by Vapi's backend, not inline in the WebSocket. You must either:
1. Use Vapi's webhook-based tool system
2. Or handle tool calls via Vapi's server-side configuration

For webhook-less setups, consider:
- Tailscale Funnel for public webhook exposure
- `vapi listen` CLI for local development tunnels

## Cost Controls

Build tier pricing (check current rates at https://docs.vapi.ai/pricing):
- **Hosting**: ~$0.05/minute
- Pass-through model costs apply if using your own API keys
- With Vapi credits + your own provider keys: effectively $0/minute hosting + provider usage

To minimize costs:
- Use `assistantId` mode to inherit optimized settings
- Set `"model.provider"` to `openai`, `anthropic`, etc. with your own key
- Use `"transport.audioFormat.sampleRate": 16000` (not higher)

## Environment Variables

```bash
# Required
VAPI_API_KEY=***  # From Vapi dashboard

# Optional
VAPI_ASSISTANT_ID=                 # Saved assistant (preferred over inline)
VAPI_VOICE_PROVIDER=11labs          # TTS engine
VAPI_VOICE_ID=                     # Specific voice
VAPI_MODEL=gpt-4o                  # LLM model

# Plugin tuning
DISCORD_VAPI_PORT=18944            # HTTP control port
DISCORD_VAPI_OUTPUT_PREROLL_MS=320 # Audio pre-roll
DISCORD_VAPI_KEEPALIVE_SECONDS=10  # JSON ping frequency (only for JSON control, not binary)
```

## Autostart Behavior

Same pattern as `discord-voice`:

1. Place `voice-vapi-autostart.json` at `~/.hermes/voice-vapi-autostart.json`
2. Gateway reads it on startup and auto-joins
3. Each voice plugin uses its OWN autostart file (`voice-live-autostart.json` vs `voice-vapi-autostart.json`)
4. The plugin checks for existing voice clients before autostarting to avoid collisions

```python
AUTOSTART_FILE = Path.home() / ".hermes" / "voice-vapi-autostart.json"
```

## Pitfalls Summary

| Symptom | Cause | Fix |
|---|---|---|
| `1005` close on connect | JSON/text sent instead of binary PCM | Remove all `send(json.dumps(...))` from PCM send loop |
| `1005` ~27s after connect | Vapi timed out waiting for Discord voice connect | Connect Vapi WebSocket BEFORE joining Discord |
| `1005` immediately after join | Vapi timed out because no audio input sent | Add `_keepalive_loop()` sending 20ms silence at 50Hz |
| Dead silence, all indicators green | `wants_opus() -> True` or `getattr(data, "data")` or missing `isinstance(data, bytes)` | See Silent Audio Trilogy |
| Audio but unintelligible | Wrong sample rate / missing resample | Ensure 48k stereo → 16k mono before sending |
| Choppy audio | Missing pre-roll / fade-in | Set `OUTPUT_PREROLL_MS` ≥ 160ms, `OUTPUT_FADE_IN_MS` ≥ 0ms |
| "Transport URL missing" | API response missing `websocketCallUrl` | Check request body has `"transport.provider": "vapi.websocket"` |
| `4017` close on Discord voice connect | Discord server requires DAVE; your client advertises max_dave_protocol_version=0 | Use standard `discord.VoiceClient` (handles DAVE via `davey`) instead of `VoiceRecvClient` |
| `OpusError: corrupted stream` loop | `voice_recv` intercepts DAVE-encrypted packets before decryption | Either remove `voice_recv` and use standard `VoiceClient`, or implement DAVE decryption in the sink |

## Compilation Check

```bash
python3 -m py_compile ~/.hermes/plugins/discord-vapi/bridge.py
python3 -m py_compile ~/.hermes/plugins/discord-vapi/__init__.py
```

## References

- `devops/voice-bridge-protocols` — shared patterns:
  - `references/vapi-websocket-requirements.md` — transport protocol details
  - `references/vapi-connection-ordering.md` — the 1005 timeout pitfall + keepalive silence mitigation
  - `references/vapi-silent-audio-bug.md` — debugging dead silence
  - `references/pcm-resampling-fir.md` — FIR filter design for resampling
  - `references/websocket-lifecycle-patterns.md` — WebSocket loop lifecycle, graceful shutdown, close-code diagnosis
  - `references/gemini-1008-reconnect.md` — WebSocket reconnect patterns
- `devops/gemini-live-spotify-tools` — pattern for tool integration (adapt to Vapi webhook model)
- `references/dave-voice-recv-incompatibility.md` — DAVE encryption breaks `voice_recv`; when to remove it vs use standard `VoiceClient`
- Vapi docs: https://docs.vapi.ai/api-reference/calls/create
- Vapi pricing: https://docs.vapi.ai/pricing
