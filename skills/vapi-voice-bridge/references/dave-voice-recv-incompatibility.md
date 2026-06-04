# DAVE Encryption Incompatibility with `discord-ext-voice-recv`

## Problem

Discord's **DAVE** (Discord Audio and Video Encryption) protocol encrypts all voice packets with per-sender MLS keys. The `discord-ext-voice-recv` library intercepts UDP packets **before** DAVE decryption, causing 100% Opus decode failure.

## Root cause

When DAVE is active:

1. Discord server sends DAVE-encrypted RTP packets
2. `discord.ext.voice_recv` intercepts UDP packets via `on_rtp_packet` hook
3. NaCl `secret_key` decryption returns data that still passes the transit-layer auth tag
4. Opus decoder throws `OpusError: corrupted stream` on every packet
5. The receive-router thread dies → `_on_listen_end` restarts it → infinite crash loop

Result: green ring flashes on/off, bot hears **zero valid audio**, assistant never speaks.

## Detection

| Signal | Meaning |
|---|---|
| `OpusError: corrupted stream` in logs | `voice_recv` receiving DAVE-encrypted frames |
| Green ring flashing on/off | Router thread crash-restart cycle |
| Bot connects but never responds | No valid PCM reaches the bridge |
| Works on some channels, fails on others | DAVE is rolled out incrementally per guild |

## Solutions

### Option A: Remove `voice_recv` (use when input not needed)

When Vapi/Gemini handles input via their own WebSocket (not Discord mic), simply use standard `discord.VoiceClient`:

```python
# Instead of:
from discord.ext import voice_recv
vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
vc.listen(MySink())  # crashes on DAVE

# Use:
vc = await channel.connect()  # standard VoiceClient, DAVE-compatible
vc.play(my_audio_source)      # output only
```

Standard `discord.VoiceClient` uses `davey` (DAVE Python bindings) for encryption and works correctly.

### Option B: Keep `voice_recv` with DAVE passthrough (use when input IS needed)

If you must receive Discord audio, implement a passthrough fallback in the sink:

```python
class MySink(voice_recv.AudioSink):
    def wants_opus(self) -> bool:
        return False  # Get decoded PCM, not raw opus

    def write(self, user, data):
        pcm = getattr(data, "pcm", b"") or b""
        if not pcm:
            return
        self._on_pcm(pcm)
```

However, with DAVE active, `voice_recv`'s PCM may still be garbage because decryption happens at a different layer. The reliable fix is:

1. Hook into `discord.py`'s `on_rtp_packet` or `decrypt_rtp`
2. Call `dave_session.decrypt()` yourself
3. Pass decrypted Opus to the decoder

See `discord.py` source `VoiceConnectionState` and `davey` bindings for the actual API.

### Option C: Disable DAVE negotiation (deprecated, no longer works)

```python
# NO LONGER EFFECTIVE as of ~2025-06
VoiceConnectionState.max_dave_protocol_version = property(lambda self: 0)
```

Discord now returns `4017` (DAVE protocol required) and refuses the connection entirely. Do not use this approach.

## Environment check

```bash
# Check if davey is installed (required for DAVE support)
python3 -c "import davey; print(davey.__version__)"

# Check discord.py version (must be recent for DAVE)
python3 -c "import discord; print(discord.__version__)"
```

If `davey` is missing, upgrade discord.py to a version that bundles it:
```bash
pip install --upgrade "discord.py[voice]>=2.5"
```

## Related

- `voice-bridge-protocols/references/voice-recv-opus-pitfall.md` — general Opus decode patterns
- `voice-bridge-protocols/references/websocket-lifecycle-patterns.md` — WebSocket loop lifecycle fixes
