# CHANGELOG — vapi-discord-bridge

> Release entries below distinguish what shipped in each version from limitations verified against the current implementation. Open capability gaps are tracked in Issues [#1](https://github.com/Capslockb/vapi-discord-bridge/issues/1)–[#4](https://github.com/Capslockb/vapi-discord-bridge/issues/4).

## 0.1.1 — 2026-06-09

### Added

- Registered `voice_vapi_say`, `voice_vapi_stop`, and the new `voice_vapi_summary` tool in `plugin/plugin.yaml`.
- Added `voice_vapi_summary`, which invokes `post_call_summary.py` for an existing compatible JSONL transcript file.

### Known limitation

- Normal bridge calls do not create JSONL transcripts under `~/.hermes/voice-vapi-notes/`, so `voice_vapi_summary` requires a compatible file that already exists. See Issue #2.

## 0.1.0 — 2026-06-04

Initial public release.

### Verified release features

- Full-duplex Discord voice ↔ Vapi WebSocket transport using raw 16 kHz mono PCM on the Vapi side and 48 kHz stereo PCM on the Discord side.
- Saved-assistant calls through `VAPI_ASSISTANT_ID`, or an inline transient assistant when no saved assistant ID is configured.
- Inline transient-assistant controls for the OpenAI model name, system prompt, voice provider, and provider-specific voice ID.
- Quiet-timeout auto-leave, idle prompting, and a leave request when a received transcript contains `disconnect`.
- Slash commands `/voice-vapi` and `/voice-vapi-leave`, with voice-channel inference from the configured Discord user.
- Source-level Hermes handlers for `voice_vapi`, `voice_vapi_leave`, `voice_vapi_status`, `voice_vapi_say`, and `voice_vapi_stop`. The 0.1.0 manifest advertised only the first three; 0.1.1 registered the remaining handlers and added `voice_vapi_summary`.
- Loopback HTTP control API on `127.0.0.1:18944` with `/health`, `/stop`, and `/say?text=...`.
- Autostart through `voice-vapi-autostart.json`; successful autostart removes the file unless persistence is explicitly requested.
- Coexistence handling that force-disconnects an existing guild voice client before starting the Vapi bridge.
- Interactive installer for plugin deployment and `.env` updates.

### Corrections to the original release claims

- The inline assistant model provider is fixed to OpenAI. The installer still offers values that the runtime does not consume, including `VAPI_VOICE`, `VAPI_FIRST_MESSAGE`, and non-OpenAI model/provider choices. See Issue #1.
- First-message customization is not read by the bridge runtime.
- Vapi function/tool-call dispatch is not implemented.
- Normal calls do not create JSONL transcripts under `~/.hermes/voice-vapi-notes/`. See Issue #2.
- The HTTP API has no `/leave` route. Its mutating `/stop` and `/say` routes are unauthenticated and must remain loopback-only and unproxied. See Issue #3.
- `/stop` and `voice_vapi_stop` disconnect media resources but can leave the sidecar task, loopback listener, and stopped registry entry alive. Prefer `/voice-vapi-leave` or `voice_vapi_leave` until Issue #4 is resolved.
- No shutdown watcher closes the sidecar server when the bridge stops.

### Verified fixes

- Stale rejoin handling detects and replaces a disconnected `_active_bridges` entry instead of returning `pending` indefinitely.
- Cross-bridge isolation force-clears a competing Discord voice client before starting.

### Known issues

See [`docs/KNOWN_BUGS.md`](docs/KNOWN_BUGS.md) for the canonical current limitation list and operator workarounds.
