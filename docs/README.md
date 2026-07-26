# Documentation

Use this directory for implementation details and operator reference beyond the project overview in the root [`README.md`](../README.md).

## Start here

- [`TOOLS.md`](TOOLS.md) — Hermes tools, arguments, and examples, including clean per-guild leave, stop-all, speech injection, and post-call summary input.
- [`CONFIGURATION.md`](CONFIGURATION.md) — environment variables verified against the current runtime, plus installer/runtime mismatches.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Discord audio, Vapi WebSocket, lifecycle, and in-process bridge design.
- [`KNOWN_BUGS.md`](KNOWN_BUGS.md) — current limitations, symptoms, workarounds, and tracking issues.

## Diagrams

The [`diagrams/`](diagrams/) directory contains text diagrams for the data flow, audio pipeline, Vapi WebSocket protocol, and bridge lifecycle. Treat diagrams as explanatory material; when they conflict with `plugin/bridge.py` or `plugin/__init__.py`, the runtime code is authoritative.

## Current capability boundaries

- A saved `VAPI_ASSISTANT_ID` is the recommended way to configure provider, model, voice, tools, transcriber, first message, and fallbacks.
- The inline transient-assistant path currently uses an OpenAI provider with runtime keys documented in [`CONFIGURATION.md`](CONFIGURATION.md).
- Normal calls do not currently create the JSONL files required by `voice_vapi_summary`; see [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).
- `voice_vapi_summary` accepts caller-supplied `file` and `notes_dir` paths without confining them to the default transcript directory. Restrict the tool to trusted operators and known files under `~/.hermes/voice-vapi-notes/` until [Issue #9](https://github.com/Capslockb/vapi-discord-bridge/issues/9) is resolved.
- Vapi function-call dispatch is not implemented in the active WebSocket receive path.
- Hermes tools accept explicit guild, channel, and user identifiers, but the plugin does not independently authorize the caller for those targets. Restrict tool access to trusted operators until [Issue #8](https://github.com/Capslockb/vapi-discord-bridge/issues/8) is resolved.
- The localhost `/stop` and `/say` routes are unauthenticated, and `/say` places injected speech text in the request URL and echoes it in the response. Keep the listener loopback-only and unproxied; see [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).
- The HTTP `/stop` route and `voice_vapi_stop` do not reliably terminate the owning sidecar task, loopback listener, and registry entry. Prefer `voice_vapi_leave` for normal per-guild shutdown until [Issue #4](https://github.com/Capslockb/vapi-discord-bridge/issues/4) is resolved.
- `DISCORD_VAPI_KEEPALIVE_SECONDS`, `DISCORD_VAPI_OUTPUT_TAIL_PAD_MS`, and `DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS` are currently inactive controls despite being parsed or exposed. Do not use them for operational guarantees; see [Issue #14](https://github.com/Capslockb/vapi-discord-bridge/issues/14).

## Safety notes

- Keep Discord and Vapi credentials in `~/.hermes/.env` with mode `0600`; do not commit them.
- Keep the HTTP control port bound to loopback and do not publish it through a proxy, tunnel, or container port mapping.
- Treat transcript or summary input files as potentially sensitive, and do not pass arbitrary paths from untrusted input.
- Do not run this bridge and another Discord voice bridge in the same guild at the same time.