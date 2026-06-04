# CHANGELOG — vapi-discord-bridge

## 0.1.0 — 2026-06-04

Initial public release.

### Features
- Full-duplex Discord voice ↔ Vapi.ai WSS transport.
- Configurable assistant (auto-provision if no `VAPI_ASSISTANT_ID` set).
- Configurable voice + LLM (OpenAI, Anthropic, Gemini, local via Vapi).
- First-message customization.
- In-process function-call dispatch with non-blocking executor.
- Auto-leave on `LEAVE_PHRASES` and quiet-timeout.
- Post-call JSONL transcripts at `~/.hermes/voice-vapi-notes/`.
- Oneshot TUI installer with live network validation of API keys.
- Slash commands `/voice-vapi` and `/voice-vapi-leave` (auto-infers user voice channel).
- Tools: `voice_vapi`, `voice_vapi_leave`, `voice_vapi_status`, `voice_vapi_say`, `voice_vapi_stop`.
- HTTP control API on `127.0.0.1:18944` (`/health`, `/say`, `/leave`).
- Autostart via `voice-vapi-autostart.json` (deleted on success).
- Coexistence with `discord-voice` (Gemini) via force-disconnect + separate autostart files.

### Fixes
- Stale rejoin: `voice_vapi()` now detects and replaces a stale `_active_bridges` entry instead of returning "pending" forever.
- Sidecar HTTP server: `_shutdown_watcher` polls `BRIDGE._running` and calls `server.close()` so `serve_forever()` returns cleanly.
- Cross-bridge isolation: `_disconnect_any_existing_vc()` force-clears a competing voice client before starting.

### Known issues
See [`docs/KNOWN_BUGS.md`](docs/KNOWN_BUGS.md). Key ones:
- Discord CDN handshake rejection (code 4006) — first ~5 attempts always fail; just wait ~27 s.
- Function-calling handlers must return quickly; long work must go to a background task.
- Don't leave a `voice-vapi-autostart.json` lying around — it will trigger on every boot.
