# Architecture

> A deep dive into the audio pipeline, WSS protocol, and lifecycle of the Vapi Discord bridge.

## High-level data flow

```
                                  ┌─────────────────────────────────────────────┐
                                  │              Vapi.ai cloud                 │
                                  │  ┌─────────────┐    ┌─────────────────────┐  │
                                  │  │  STT        │    │  TTS                │  │
                                  │  │  (Deepgram, │◄──►│  (11labs, PlayHT,   │  │
                                  │  │  Whisper)   │    │   OpenAI)           │  │
                                  │  └──────┬──────┘    └──────────┬──────────┘  │
                                  │         │                     │             │
                                  │         ▼                     ▲             │
                                  │  ┌─────────────┐    ┌──────────┴──────────┐  │
                                  │  │  LLM        │    │  function calls     │  │
                                  │  │  (GPT, Clau-│◄──►│  (transient or      │  │
                                  │  │  de, Gemini)│    │   server URLs)      │  │
                                  │  └─────────────┘    └─────────────────────┘  │
                                  └─────────┬──────────────────────┬────────────┘
                                            │ WSS                 │ WSS
                                  ▲ audio   │                     │ JSON ctrl
                                  │ 16 kHz  │                     │
        ┌────────────────────────┐│         │                     ▼
        │  VapiClient           ├┘         │            ┌─────────────────┐
        │  (asyncio task)       │          │            │  Tool dispatcher│
        └────────────────────────┘          │            │  (in-process)   │
                                            │            └─────────────────┘
                                  ▲ 48 kHz  │
                                  │ stereo  │
        ┌────────────────────────┐│         │
        │  VoiceListener         ├┘         │
        │  (rx thread)           │          │
        └────────────────────────┘          │
                                            │
              Opus 48 kHz                   │
        ┌────────────────────────┐         │
        │  Discord VoiceClient   │         │
        │  (UDP + NaCl decrypt)  ├─────────┘
        └────────────────────────┘
              ▲
              │  user microphone
              │
        ┌────────────────────────┐
        │  Discord voice channel │
        └────────────────────────┘
```

## Audio pipeline (detailed)

### Receive path (Discord → Vapi)

1. **Discord VoiceClient** receives Opus packets from the voice UDP socket and decrypts them with the **NaCl secret-box** session key.
2. **VoiceListener** runs in its own thread, reading decoded PCM frames at 48 kHz stereo.
3. Frames are passed to **VapiClient**, which:
   - Converts to 16 kHz mono PCM16 (Vapi's expected input format)
   - Wraps each chunk in a WSS `audio` event
   - Sends over the open WebSocket
4. Vapi's STT service transcribes the audio, the LLM processes it, and the response is generated.

### Send path (Vapi → Discord)

1. Vapi sends `audio` events on the WSS as base64-encoded PCM at 24 kHz mono.
2. **VapiClient** decodes and pushes the chunks into a **thread-safe queue** inside `LiveAudioSource` (a `discord.AudioSource` subclass).
3. **VoiceClient.play()** pulls from the queue, encodes to Opus, and sends to Discord.

## Vapi WSS protocol

The bridge opens `wss://api.vapi.ai` with the assistant ID in the URL and an auth token in the query string. The WSS carries:

### Outbound (client → Vapi)

```json
{ "type": "audio", "audio": "<base64 PCM16 mono 16kHz>" }
{ "type": "message", "role": "user", "content": "..." }   // optional text injection
{ "type": "function-call-result", "functionCallId": "...", "result": "..." }
```

### Inbound (Vapi → client)

```json
{ "type": "transcript", "role": "user",      "text": "..." }
{ "type": "transcript", "role": "assistant", "text": "..." }
{ "type": "audio",      "audio": "<base64 PCM mono 24kHz>" }
{ "type": "function-call", "functionCall": { "name": "...", "parameters": { ... } } }
{ "type": "hang" }                                          // Vapi ended the call
{ "type": "speech-update", "status": "started" | "stopped" }
{ "type": "metadata",       "call": { "id": "...", ... } }
```

The bridge dispatches:
- `audio` → `LiveAudioSource` queue
- `transcript` → JSONL notes file + console
- `function-call` → in-process tool dispatcher
- `hang` → teardown

## Threading model

| Thread / task | Owner | Role |
|---------------|-------|------|
| Gateway asyncio loop | Hermes | spawns bridge, handles slash commands, owns Vapi WSS |
| discord.py voice rx | internal | decrypts + decodes inbound Opus |
| discord.py voice tx | internal | encodes + sends outbound Opus |
| `_shutdown_watcher` (poll task) | bridge | polls `BRIDGE._running` and closes the sidecar HTTP server |

## Lifecycle

```
slash command                voice_vapi()
    │                              │
    ▼                              ▼
disconnect any existing    infer channel
voice client in guild          │
(force-disconnect for Gemini)  ▼
    │                  spawn bridge.py:run_sidecar(channel, ...)
    ▼                      │ in sidecar:
wait ~30s                  │   channel.connect()       ← may take 27s
    │                      │   VoiceClient.play(LiveAudioSource())
    ▼                      │   open Vapi WSS
ready future fires         │   send `start` event
    │                      │
    ▼                      ▼
return success         register in _active_bridges[guild_id]
                            │
                            ▼
                       bridge runs until:
                           - /voice-vapi-leave
                           - auto-leave quiet timeout
                           - Vapi sends `hang`
                           - gateway stop
```

## Coexistence with the Gemini bridge

Both plugins (`discord-voice` and `discord-vapi`) hook the same Discord voice client. To prevent a stale Gemini voice client from fighting a new Vapi session, the Vapi plugin's `voice_vapi()` calls `_disconnect_any_existing_vc()` before connecting. The same goes for the Gemini plugin.

This is enforced via the **autostart file convention**: each plugin reads its own file (`voice-live-autostart.json` vs `voice-vapi-autostart.json`) and only auto-joins if its own file exists.

## Idempotency

The plugin guards against:

- **Stale entries** — if a guild's `voice_client` is disconnected but `_active_bridges` still has an entry, the new call cancels the old task, pops the entry, and starts fresh.
- **Same-channel no-op** — calling `/voice-vapi` while already connected to that channel returns `"success": "Voice bridge is ready"` instead of reconnecting.
- **Cross-channel move** — calling `/voice-vapi` for a different channel in the same guild calls `vc.move_to()` instead of disconnect+reconnect.

## Control API (HTTP)

The sidecar HTTP server runs on `127.0.0.1:18944` (configurable via `DISCORD_VAPI_PORT`).

| Endpoint | Method | Body | Effect |
|----------|--------|------|--------|
| `/health` | GET | — | Returns the full `BRIDGE.health()` JSON |
| `/say?text=...` | GET | — | Sends a `message` event into the Vapi session (model speaks it) |
| `/leave` | GET | — | Stops the bridge, disconnects |

The server is bound to **loopback only**. Use a Tailscale / SSH tunnel to access it remotely.

## Function calling

Vapi supports both **server-side** tool calls (configure a `serverUrl` in the Vapi dashboard that Vapi POSTs to) and **client-side** tool calls (handled by the bridge in-process). The bridge is set up to dispatch the client-side variety. Example round-trip in `bridge.py`:

```python
async def _on_function_call(self, function_call):
    # dispatch to in-process tools (Hermes skills, local shell, etc.)
    result = await self._dispatch(function_call)
    await self._send_function_call_result(function_call["id"], result)
```

The receive loop never awaits long-running work — anything slow goes through `loop.run_in_executor()`.

## Failure modes

| Symptom | Where it happens | Recovery |
|---------|------------------|----------|
| `channel.connect()` hangs ~27s | Discord CDN handshake rejection (code 4006) | Wait it out. Don't restart the gateway. |
| WSS drops mid-call | Vapi server-side blip or rate limit | `run_sidecar` reconnects with backoff |
| Playback stops silently | Natural silence + 2s timeout in `LiveAudioSource` | Speak again — playback restarts via `_wake_playback` |
| "Bridge still starting" hangs | Stale entry in `_active_bridges` | Plugin auto-cleans; if not, `pkill -9` the gateway and restart |
| "Active bridge for guild X" errors on `/say` | No active session | Start the bridge first with `/voice-vapi` |
