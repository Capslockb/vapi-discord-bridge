# Documentation

Use this directory for implementation details and operator reference beyond the project overview in the root [`README.md`](../README.md).

## Start here

- [`TOOLS.md`](TOOLS.md) — Hermes tools, arguments, and examples, including status, stop-all, speech injection, and post-call summary input.
- [`CONFIGURATION.md`](CONFIGURATION.md) — environment variables verified against the current runtime, plus installer/runtime mismatches.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Discord audio, Vapi WebSocket, lifecycle, and in-process bridge design.
- [`KNOWN_BUGS.md`](KNOWN_BUGS.md) — current limitations, symptoms, workarounds, and tracking issues.

## Diagrams

The [`diagrams/`](diagrams/) directory contains text diagrams for the data flow, audio pipeline, Vapi WebSocket protocol, and bridge lifecycle. Treat diagrams as explanatory material; when they conflict with `plugin/bridge.py` or `plugin/__init__.py`, the runtime code is authoritative.

## Current capability boundaries

- A saved `VAPI_ASSISTANT_ID` is the recommended way to configure provider, model, voice, tools, transcriber, first message, and fallbacks.
- The inline transient-assistant path currently uses an OpenAI provider with runtime keys documented in [`CONFIGURATION.md`](CONFIGURATION.md).
- Normal calls do not currently create the JSONL files required by `voice_vapi_summary`; see [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).
- Vapi function-call dispatch is not implemented in the active WebSocket receive path.
- The localhost `/stop` and `/say` routes are unauthenticated; see [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).

## Safety notes

- Keep Discord and Vapi credentials in `~/.hermes/.env` with mode `0600`; do not commit them.
- Keep the HTTP control port bound to loopback and do not publish it through a proxy, tunnel, or container port mapping.
- Treat transcript or summary input files as potentially sensitive.
- Do not run this bridge and another Discord voice bridge in the same guild at the same time.
