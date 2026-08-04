# Vapi Discord Bridge

> Discord voice channel ↔ Vapi WebSocket transport, packaged as a [Hermes Agent](https://hermes-agent.nousresearch.com) plugin.

Drop a Vapi-powered voice assistant into a Discord voice channel. The current runtime provides full-duplex PCM audio transport, bridge lifecycle tools, a loopback health/control endpoint, autostart support, and an optional post-call summary reader for compatible JSONL files.

```text
Discord user ──► Discord UDP ──► Opus decode ──► PCM 16 kHz ──► Vapi WSS
Discord user ◄── Discord UDP ◄── PCM 48 kHz  ◄── PCM 16 kHz ◄── Vapi WSS
```

## Quick install

```bash
git clone https://github.com/Capslockb/vapi-discord-bridge.git
cd vapi-discord-bridge
python3 installer/install.py
```

The installer performs:

| Step | What happens |
|------|--------------|
| 1 | System preflight for Python, Hermes home, venv, git, and the optional `gh` CLI. |
| 2 | Discord bot token and Vapi private-key collection with live validation. |
| 3 | Copy, symlink, or local installation mode. |
| 4 | Plugin deployment, permissions, and Python dependency installation. |
| 5 | Merge selected values into the selected Hermes home’s `.env` with mode `0600`. |
| 6 | Optional autostart-file creation. |

**Custom Hermes home warning:** plugin placement and `.env` writing honor `HERMES_HOME`, but the current dependency-install step still probes `~/.hermes/hermes-agent/venv/bin/python`. With a non-default `HERMES_HOME`, it can skip required dependencies or modify an unrelated default venv. Until [Issue #24](https://github.com/Capslockb/vapi-discord-bridge/issues/24) is resolved, use the default Hermes home or install `plugin/requirements.txt` manually through the intended custom venv after verifying the interpreter path.

For a pre-seeded unattended repeat install:

```bash
python3 installer/install.py --yes
```

`--yes` does not provide required credentials. It currently succeeds only when `DISCORD_BOT_TOKEN` and `VAPI_API_KEY` already exist in the selected Hermes home’s `.env`; on a clean environment it exits during key collection. It also selects copy mode and default confirmation answers automatically. In particular, a failed Discord or Vapi network check is accepted through the default “continue anyway” response, so this mode is not a strict credential-validation gate. Deterministic fail-closed unattended installation is tracked in [Issue #10](https://github.com/Capslockb/vapi-discord-bridge/issues/10).

### Configuration warning

The installer currently collects some legacy values that the runtime does not consume, including `VAPI_VOICE`, `VAPI_FIRST_MESSAGE`, and `GEMINI_API_KEY`. Until [Issue #1](https://github.com/Capslockb/vapi-discord-bridge/issues/1) is resolved, use a saved `VAPI_ASSISTANT_ID` or manually configure the runtime keys documented in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Requirements

| Item | Notes |
|------|-------|
| Discord bot token | Create one in the Discord Developer Portal. |
| Vapi private API key | Create one in the Vapi dashboard. |
| Python 3.10+ | Required by the plugin and installer. |
| Hermes Agent | Recommended host environment for plugin registration and Discord commands. |

The Discord bot needs the intents and permissions required for your server configuration, including Voice States and permission to connect and speak in the target channel.

Vapi model, voice, and pricing availability change over time. Check the Vapi dashboard before deployment instead of relying on hard-coded model or price lists.

## Usage

### Discord slash command

```text
/voice-vapi
```

The current slash-command wrapper does not use the invoking member's Discord identity. It looks up the user configured by `DISCORD_VAPI_USER_ID` and joins that account's current voice channel. Set the variable explicitly; otherwise the repository-specific fallback is used. Invoker-aware behavior is tracked in [Issue #8](https://github.com/Capslockb/vapi-discord-bridge/issues/8).

### Hermes tools

```text
voice_vapi guild_id=1234567890 channel_id=0987654321
voice_vapi_status
voice_vapi_say guild_id=1234567890 text="Reminder: standup in 5 minutes"
voice_vapi_leave guild_id=1234567890
voice_vapi_stop
```

See [`docs/TOOLS.md`](docs/TOOLS.md) for the complete tool reference.

### Health check

```bash
curl -s http://127.0.0.1:18944/health | python3 -m json.tool
```

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown.

```text
┌─────────────────┐                    ┌──────────────────────┐
│ Discord Voice   │  ◄──PCM 48 kHz──► │ LiveAudioSource      │
│ UDP + voice recv│                    │ thread-safe queue    │
└────────┬────────┘                    └──────────┬───────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────┐                    ┌──────────────────────┐
│ VapiPCMSink     │  ──PCM 16 kHz───► │ VapiBridge           │
│ decoded receive │                    │ WSS + JSON control   │
└─────────────────┘                    └──────────┬───────────┘
                                                  │
                                                  ▼
                                       ┌──────────────────────┐
                                       │ Vapi                 │
                                       │ STT / model / TTS    │
                                       └──────────────────────┘
```

The bridge runs in process with the Hermes gateway asyncio loop. It does not require a separate bridge daemon.

## Configuration

By default, settings live in `~/.hermes/.env`. When `HERMES_HOME` is set, the installer reads and writes `$HERMES_HOME/.env` instead.

### Required

```env
DISCORD_BOT_TOKEN=...
VAPI_API_KEY=...
```

### Recommended: saved Vapi assistant

```env
VAPI_ASSISTANT_ID=...
```

A saved assistant supplies its configured provider, model, voice, tools, transcriber, first message, and fallbacks.

### Inline transient assistant

Used only when `VAPI_ASSISTANT_ID` is empty:
```env
VAPI_MODEL_NAME=gpt-4o-mini
VAPI_SYSTEM_PROMPT=You are a helpful AI assistant.
VAPI_VOICE_PROVIDER=11labs
VAPI_VOICE_ID=cjVigY5qzO86Huf0OWal
```

`VAPI_MODEL` remains a legacy alias for `VAPI_MODEL_NAME`. The current inline assistant path hard-codes the provider to OpenAI; use a saved Vapi assistant for other providers.

### Networking and idle behavior

```env
DISCORD_VAPI_PORT=18944
DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS=900
DISCORD_VAPI_AUTO_LEAVE_MIN_UPTIME_SECONDS=120
DISCORD_VAPI_IDLE_PROMPT_SECONDS=120
DISCORD_VAPI_IDLE_PROMPT_TEXT=Are you still there?
```

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for every verified runtime setting and known ineffective legacy keys.

## Local control API safety

The HTTP listener binds to `127.0.0.1`. `/health` is read-only, while `/stop` and `/say?text=...` mutate an active bridge.

The mutating routes are currently unauthenticated. Do not publish the port through a reverse proxy, public tunnel, container port mapping, or LAN bind. Authentication hardening is tracked in [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).

## Assistant and model behavior

There are two supported configuration paths:

1. **Saved assistant:** set `VAPI_ASSISTANT_ID`. This is the recommended path for production assistants, non-OpenAI providers, tools, custom first messages, and provider-specific voices.
2. **Inline transient assistant:** leave `VAPI_ASSISTANT_ID` empty and configure the runtime model name, system prompt, voice provider, and voice ID directly.

Use exact provider-specific voice IDs from Vapi. Human-readable labels such as `jennifer` are not guaranteed to be valid runtime IDs.

## Cost controls

Vapi usage and its underlying model, transcription, and voice providers may all contribute to cost. Pricing changes independently of this repository.

Use a saved assistant with explicit provider choices, set an idle timeout, and verify current pricing in the Vapi dashboard before leaving the bridge unattended.

## Transcripts and post-call summaries

The repository includes `voice_vapi_summary` and `scripts/post_call_summary.py`, which can process compatible JSONL transcript files.

**Current limitation:** normal calls do not persist those transcript files in this revision. Summary requests therefore require a manually supplied compatible file until [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2) is resolved.

Treat any transcript files as sensitive and keep them outside version control with restrictive permissions.

## Known limitations

See [`docs/KNOWN_BUGS.md`](docs/KNOWN_BUGS.md). Important current boundaries include:

1. Discord voice connection retries may make startup appear stalled on some endpoints.
2. The fixed loopback control port currently limits the entire Hermes gateway process to one active Vapi sidecar across all Discord guilds; a second concurrent start fails before Discord or Vapi connection begins. See [Issue #18](https://github.com/Capslockb/vapi-discord-bridge/issues/18).
3. Installer model/voice prompts do not yet map cleanly to the runtime configuration contract.
4. JSONL transcript persistence and Vapi function-call dispatch are not implemented in the current bridge path.
5. The localhost `/stop` and `/say` routes do not yet require authentication.
6. The installed plugin directory is `discord-vapi`; the hyphen means it cannot be imported with a normal Python `import discord-vapi` statement. Hermes loads it by path.

## Development

```bash
git clone https://github.com/Capslockb/vapi-discord-bridge.git
cd vapi-discord-bridge
pip install -r plugin/requirements.txt

# Symlink install for development
python3 installer/install.py

# Compile check after editing
python3 -m py_compile plugin/bridge.py plugin/__init__.py
```

### Project layout

```text
vapi-discord-bridge/
├── README.md
├── LICENSE
├── CHANGELOG.md
├── plugin/
│   ├── __init__.py
│   ├── bridge.py
│   ├── plugin.yaml
│   └── requirements.txt
├── installer/
│   └── install.py
├── scripts/
│   └── post_call_summary.py
├── docs/
│   ├── README.md
│   ├── TOOLS.md
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── KNOWN_BUGS.md
│   └── diagrams/
└── .github/
    └── workflows/
        └── lint.yml
```

## License

MIT. See [`LICENSE`](LICENSE).

## Credits

- Discord voice protocol: [`discord.py`](https://github.com/Rapptz/discord.py) and [`discord-ext-voice-recv`](https://github.com/imayhaveborkedit/discord-ext-voice-recv).
- Vapi: [vapi.ai](https://vapi.ai).
- Hermes Agent: [Nous Research](https://nousresearch.com).
