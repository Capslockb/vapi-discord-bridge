# Documentation

Use this directory for implementation details and operator reference beyond the project overview in the root [`README.md`](../README.md).

## Start here

- [`TOOLS.md`](TOOLS.md) — all Hermes tools, arguments, and examples, including status, stop-all, speech injection, and post-call summaries.
- [`CONFIGURATION.md`](CONFIGURATION.md) — environment variables and runtime configuration.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Discord audio, Vapi WebSocket, lifecycle, and in-process bridge design.
- [`KNOWN_BUGS.md`](KNOWN_BUGS.md) — current limitations, symptoms, and workarounds.

## Diagrams

The [`diagrams/`](diagrams/) directory contains text diagrams for the data flow, audio pipeline, Vapi WebSocket protocol, and bridge lifecycle.

## Safety notes

- Keep Discord and Vapi credentials in `~/.hermes/.env`; do not commit them.
- Treat call transcripts under `~/.hermes/voice-vapi-notes/` as potentially sensitive.
- Do not run this bridge and another Discord voice bridge in the same channel at the same time.
