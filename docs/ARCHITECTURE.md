# Architecture

> Source-verified description of the current Vapi Discord bridge. Capability claims here describe the shipped runtime, not planned functionality.

## Component map

| Component | File | Responsibility |
|---|---|---|
| Hermes registration layer | `plugin/__init__.py` | Registers tools and slash commands, resolves guild/channel targets, tracks active bridge tasks, and handles autostart. |
| Discord/Vapi bridge | `plugin/bridge.py` | Creates the Vapi call, opens the WebSocket transport, connects Discord voice, moves PCM audio in both directions, runs idle checks, and exposes the loopback control listener. |
| Playback source | `LiveAudioSource` | Buffers Vapi PCM, converts it to Discord's 48 kHz stereo format, and supplies 20 ms frames to Discord playback. |
| Receive sink | `VapiPCMSink` | Accepts decoded Discord PCM, ignores bot users, converts audio to 16 kHz mono, and forwards it to the Vapi send queue. |
| Summary reader | `scripts/post_call_summary.py` | Reads an already existing compatible JSONL transcript and renders summary sections. The current bridge does not create those files. |

## High-level flow

```text
Discord microphone
       │ decoded PCM, 48 kHz stereo
       ▼
VapiPCMSink
       │ resampled PCM, 16 kHz mono
       ▼
VapiBridge send queue
       │ raw binary PCM over WebSocket
       ▼
Vapi websocket transport
       │ raw binary PCM, 16 kHz mono
       ▼
LiveAudioSource
       │ resampled PCM, 48 kHz stereo
       ▼
Discord voice playback
```

JSON messages on the Vapi WebSocket are control/status messages. Audio itself is sent and received as raw binary PCM, not base64-wrapped JSON events.

## Startup sequence

The current replacement sequence is disruptive and is not fail-closed:

1. `voice_vapi` or `/voice-vapi` obtains guild and channel identifiers, then checks `_starting` and `_active_bridges` for an existing bridge record.
2. An already connected bridge in the same channel returns success without restarting. A different-channel request calls `move_to()`; a move exception is currently returned as `status: "success"` with `Active but couldn't move` in the message.
3. For a fresh or stale-entry start, the plugin verifies that the Discord client and guild exist.
4. The plugin force-disconnects any current guild voice client **before** looking up and validating the requested channel.
5. The requested channel is resolved only after that disconnect. A missing, stale, wrong, or unsuitable target can therefore leave the guild without its previous working voice session.
6. `plugin/bridge.py` is loaded, `run_sidecar()` starts as an asyncio task, and the loopback listener binds to `127.0.0.1:DISCORD_VAPI_PORT`.
7. `VapiVoiceBridge.start()` checks voice-receive support and performs a second disconnect of any connected guild voice client **before** calling `_vapi.connect()`.
8. The Vapi call and WebSocket are established before the new Discord voice connection is attempted.
9. Discord connects with `VoiceRecvClient`, starts `VapiPCMSink`, and starts playback through `LiveAudioSource`.
10. The ready result is returned and the connected voice client is stored in `_active_bridges`.

The plugin waits up to 120 seconds for the complete bridge startup. The Discord voice connection itself uses a 60-second timeout. A failed Vapi or Discord startup does not restore a voice client disconnected by the replacement path. Fail-closed validation, truthful move errors, and explicit session-preservation behavior are tracked in [Issue #17](https://github.com/Capslockb/vapi-discord-bridge/issues/17).

## Vapi call creation

The bridge sends an authenticated `POST` request to the Vapi call API and requests the `vapi.websocket` transport with raw signed 16-bit PCM at 16 kHz.

Two assistant paths exist:

### Saved assistant

When `VAPI_ASSISTANT_ID` is set, the call payload references that assistant. Provider, model, voice, tools, transcriber, first message, and other assistant-level behavior remain configured in Vapi.

### Inline transient assistant

When `VAPI_ASSISTANT_ID` is empty, the bridge creates an inline assistant from:

- `VAPI_MODEL_NAME` or legacy alias `VAPI_MODEL`;
- `VAPI_SYSTEM_PROMPT`;
- `VAPI_VOICE_PROVIDER`;
- `VAPI_VOICE_ID`.

The inline model provider is currently fixed to OpenAI in code. Installer/runtime drift is tracked in [Issue #1](https://github.com/Capslockb/vapi-discord-bridge/issues/1).

The API response supplies `websocketCallUrl`. The bridge appends `/transport` only when the returned path does not already end with it, then opens the WebSocket.

## Discord → Vapi audio

1. `discord-ext-voice-recv` decrypts and decodes Discord voice packets.
2. `VapiPCMSink.write()` ignores bot users and empty frames.
3. Decoded 48 kHz stereo PCM is converted to 16 kHz mono PCM16.
4. The converted bytes enter a bounded queue; when full, the oldest item is dropped.
5. `_send_loop()` writes each queued chunk to the WebSocket as raw binary data.
6. When the queue is empty, the current keepalive loop supplies 20 ms silence chunks.

`DISCORD_VAPI_KEEPALIVE_SECONDS` is defined but is not used by the active 20 ms silence loop. This limitation is documented in [`KNOWN_BUGS.md`](KNOWN_BUGS.md).

## Vapi → Discord audio

1. Binary WebSocket messages are treated as 16 kHz mono PCM.
2. At the start of an output turn, optional preroll silence is inserted and optional fade-in is applied.
3. `LiveAudioSource` converts the audio to 48 kHz stereo.
4. Discord pulls fixed 20 ms frames from the source and encodes them for transmission.
5. `conversation-update` messages with `interrupted` or `ended` status clear buffered output when `DISCORD_VAPI_CLEAR_ON_INTERRUPT` is enabled.

## JSON control handling

### Outbound

Text injection uses:

```json
{"type": "text", "text": "..."}
```

This is used by the Hermes `voice_vapi_say` tool, the loopback `/say` route, and the idle prompt.

### Inbound

The current receive loop recognizes a limited subset of string JSON messages:

| Message type | Current behavior |
|---|---|
| `assistant-started` | Logs the assistant name. |
| `conversation-update` | Clears buffered playback on `interrupted` or `ended`. |
| `transcript` | Checks for the word `disconnect` and requests bridge shutdown when found. |
| Other JSON | Logged at debug level, with no feature dispatch. |

The current runtime does **not**:

- persist transcript JSONL files;
- dispatch Vapi function/tool calls to Hermes;
- send function-call results back to Vapi.

Those capability gaps are tracked in [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).

## Runtime tasks and threads

| Execution context | Role |
|---|---|
| Hermes gateway asyncio loop | Owns plugin tools, slash commands, bridge tasks, Vapi WebSocket tasks, watchdog, and loopback listener. |
| Discord voice receive internals | Decrypt and decode inbound Discord audio before calling `VapiPCMSink.write()`. |
| Discord voice playback internals | Pull frames from `LiveAudioSource` and transmit them to Discord. |
| `VapiBridge._send_loop` | Sends queued PCM to Vapi. |
| `VapiBridge._receive_loop` | Receives JSON control messages and binary PCM from Vapi. |
| `VapiBridge._keepalive_loop` | Feeds silence while no user audio is queued. |
| `VapiVoiceBridge._connection_watchdog` | Applies idle prompts, quiet-timeout shutdown, and connection-state checks. |

## Lifecycle and registry

`plugin/__init__.py` stores one active bridge record per guild in `_active_bridges`.

- A second start for the same connected channel is a no-op success.
- A start for a different channel attempts to move the existing Discord voice client; a move failure is currently reported with a success status even though the existing record remains in its prior state.
- A disconnected stale entry is cancelled and removed before a fresh start.
- A fresh or replacement start may force-disconnect another voice bridge already using that guild's Discord voice-client slot before the target and replacement are known to be usable.

Supported stop paths include:

- `/voice-vapi-leave`;
- `voice_vapi_leave`;
- `voice_vapi_stop` for one guild or all guilds;
- loopback `/stop`;
- auto-leave after configured quiet time;
- a transcript containing `disconnect`;
- Discord voice disconnection;
- Vapi WebSocket closure detected by the watchdog;
- gateway/task cancellation.

### Current cleanup limitation

`BRIDGE.stop()` disconnects audio and voice resources, but `run_sidecar()` continues awaiting `server.serve_forever()` unless the owning task is cancelled. Some stop paths can therefore leave the loopback listener and stopped registry entry alive until stale-entry recovery runs. Clean task, listener, and registry termination is tracked in [Issue #4](https://github.com/Capslockb/vapi-discord-bridge/issues/4).

## Loopback control API

The listener binds to `127.0.0.1` on `DISCORD_VAPI_PORT` (default `18944`).

| Route | Input | Current effect |
|---|---|---|
| `/health` | none | Returns bridge health metrics or `not_started`. |
| `/stop` | none | Calls `BRIDGE.stop()` when running. |
| `/say?text=...` | query string | Sends text into the active Vapi session and echoes it in the JSON response. |

The parser currently does not enforce HTTP methods, authentication, Host/Origin policy, request-size limits, or a structured request body. `/stop` and `/say` are mutating and unauthenticated. Keep the listener loopback-only and do not expose it through a tunnel, reverse proxy, LAN bind, or container port mapping. Hardening is tracked in [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).

There is no `/leave` HTTP route in the current implementation.

## Autostart

Autostart is enabled when either:

- `~/.hermes/voice-vapi-autostart.json` exists; or
- `DISCORD_VAPI_AUTOSTART` is truthy.

The autostart routine retries while the gateway and Discord adapter become available. It uses explicit guild/channel values when present, otherwise it may infer the channel from `DISCORD_VAPI_USER_ID`.

After a successful start, the autostart file is deleted unless `DISCORD_VAPI_KEEP_AUTOSTART_FILE=1`.

## Failure boundaries

| Symptom | Current behavior |
|---|---|
| Target channel lookup or suitability fails | The plugin can already have disconnected the guild's existing voice client before returning the target error. |
| Vapi call creation or WebSocket setup fails | Startup returns an error, but a guild voice client disconnected by either pre-Vapi replacement layer is not restored. |
| Discord connection fails | Vapi is disconnected and startup fails; the previous guild voice session is not restored. |
| Discord playback/listener startup fails | The new bridge stops, with no rollback to the previous guild voice session. |
| Existing bridge channel move fails | The handler currently returns `status: "success"` with an error message and leaves the existing bridge record unchanged. |
| Vapi WebSocket send/receive closes | The Vapi bridge marks itself stopped; the connection watchdog tears down Discord voice. |
| Discord disconnects while running | The watchdog calls bridge shutdown. |
| Output queue is temporarily empty | `LiveAudioSource` returns a silent Discord frame rather than ending playback. |
| Bridge stop leaves sidecar task alive | Stale-entry recovery may clean it on the next start; see Issue #4. |

Operator-facing limitations and safe workarounds are maintained in [`KNOWN_BUGS.md`](KNOWN_BUGS.md).
