# Documentation

This directory contains the detailed operator and implementation guides for Vapi Discord Bridge. For installation and basic usage, start with the project [`README.md`](../README.md).

## Guides

- [`CONFIGURATION.md`](CONFIGURATION.md) — verified environment variables, assistant setup, and known installer mismatches.
- [`TOOLS.md`](TOOLS.md) — Hermes tool arguments, examples, and operational boundaries.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Discord audio flow, Vapi WebSocket transport, lifecycle, and in-process design.
- [`KNOWN_BUGS.md`](KNOWN_BUGS.md) — detailed current limitations, workarounds, and tracking issues.
- [`diagrams/`](diagrams/) — text diagrams for the audio pipeline, protocol flow, and bridge lifecycle.

## Current support status

- A saved `VAPI_ASSISTANT_ID` is the recommended configuration path. The inline transient-assistant path currently uses an OpenAI provider.
- A custom `HERMES_HOME` is not yet applied consistently: plugin placement and `.env` handling follow the selected home, while dependency installation and the default autostart path can still target `~/.hermes`. See Issues [#24](https://github.com/Capslockb/vapi-discord-bridge/issues/24) and [#26](https://github.com/Capslockb/vapi-discord-bridge/issues/26).
- The fixed loopback control port permits one active Vapi sidecar per Hermes gateway process across all Discord guilds. See [Issue #18](https://github.com/Capslockb/vapi-discord-bridge/issues/18).
- Normal calls do not create the JSONL files required for post-call summaries. See [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).
- On current `main`, the summary helper is not packaged with the installed plugin, so summary use requires a retained checkout or manual helper copy. [PR #20](https://github.com/Capslockb/vapi-discord-bridge/pull/20) proposes the packaging correction; Issue [#19](https://github.com/Capslockb/vapi-discord-bridge/issues/19) remains open until that sensitive tool-execution change is reviewed and merged.
- The loopback `/stop` and `/say` routes are unauthenticated. Keep the listener local and unproxied. See [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).
- Tool targeting and bridge replacement do not yet provide complete caller authorization or fail-closed session preservation. Restrict these operations to trusted users. See Issues [#8](https://github.com/Capslockb/vapi-discord-bridge/issues/8) and [#17](https://github.com/Capslockb/vapi-discord-bridge/issues/17).
- Transcript files, summary inputs, and gateway logs may contain private voice-session data. Review and redact them before sharing. See Issues [#9](https://github.com/Capslockb/vapi-discord-bridge/issues/9) and [#15](https://github.com/Capslockb/vapi-discord-bridge/issues/15).

## Safe operation

- Store Discord and Vapi credentials in the selected Hermes home’s `.env` with restrictive permissions.
- Keep the HTTP control listener bound to `127.0.0.1`.
- Do not start concurrent Vapi bridges from the same gateway process.
- Do not run this bridge alongside another Discord voice bridge in the same guild.

The runtime code in `plugin/bridge.py` and `plugin/__init__.py` is authoritative when a diagram or guide differs from the implementation.
