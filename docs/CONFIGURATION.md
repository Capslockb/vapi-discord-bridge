# Configuration

> Runtime configuration verified against `plugin/bridge.py` and `plugin/__init__.py`.

The bridge reads its process environment. A default Hermes installation normally sources settings from `~/.hermes/.env`. When the installer runs with `HERMES_HOME` set, it reads and writes `$HERMES_HOME/.env`; ensure the gateway is configured to load that selected file, or inject the same variables through its service environment. Keep environment files at mode `0600`. After changing runtime settings, restart the gateway:

```bash
systemctl --user restart hermes-gateway
```

## Required

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_BOT_TOKEN` | _(required)_ | Discord bot token. Voice States and Message Content must be enabled for the intended workflow. |
| `VAPI_API_KEY` | _(required)_ | Vapi private API key used for `POST /call`. |

## Assistant selection

### Recommended: saved Vapi assistant

| Key | Default | Notes |
|-----|---------|-------|
| `VAPI_ASSISTANT_ID` | _(empty)_ | When set, the transient call references this saved assistant and inherits its model, provider, voice, tools, transcriber, first message, and fallbacks. |

Using a saved assistant is the only currently documented path for non-OpenAI model providers and complex Vapi configuration.

### Inline transient assistant

These settings are used only when `VAPI_ASSISTANT_ID` is empty:

| Key | Default | Notes |
|-----|---------|-------|
| `VAPI_MODEL_NAME` | `gpt-4o-mini` | Model name sent to Vapi. `VAPI_MODEL` is accepted as a legacy alias. The current runtime hard-codes the model provider to `openai`. |
| `VAPI_SYSTEM_PROMPT` | `You are a helpful AI assistant.` | System message for the inline transient assistant. |
| `VAPI_VOICE_PROVIDER` | `11labs` | Vapi voice provider identifier. |
| `VAPI_VOICE_ID` | `cjVigY5qzO86Huf0OWal` | Provider-specific voice ID. Use the exact ID shown by Vapi; display names are not interchangeable with IDs. |

## Installer/runtime mismatch

The current installer still collects several keys that the runtime does not consume:

- `VAPI_VOICE`
- `VAPI_FIRST_MESSAGE`
- `GEMINI_API_KEY`

`VAPI_PUBLIC_KEY` is also not used by this headless bridge; it is relevant only to separate client-side Vapi embeds.

Until [Issue #1](https://github.com/Capslockb/vapi-discord-bridge/issues/1) is fixed, configure `VAPI_VOICE_PROVIDER`, `VAPI_VOICE_ID`, `VAPI_MODEL_NAME`, and `VAPI_SYSTEM_PROMPT` manually, or use `VAPI_ASSISTANT_ID`.

A custom `HERMES_HOME` is not yet applied consistently. Plugin placement and `.env` handling use the selected home, but dependency installation still probes the default Hermes venv, and installer/runtime autostart defaults still use `~/.hermes/voice-vapi-autostart.json`. Until Issues [#24](https://github.com/Capslockb/vapi-discord-bridge/issues/24) and [#26](https://github.com/Capslockb/vapi-discord-bridge/issues/26) are resolved, install `plugin/requirements.txt` manually through the intended custom-home venv and set `DISCORD_VAPI_AUTOSTART_FILE` explicitly inside that home.

## Networking and control API

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_PORT` | `18944` | HTTP control listener. The runtime binds to `127.0.0.1` only. |

Current routes:

- `/health` — read bridge status.
- `/stop` — stop the active bridge.
- `/say?text=...` — inject text into the active Vapi call.

The current parser dispatches solely by URL path and does not enforce the HTTP method. Unexpected methods reaching one of these paths can therefore trigger the same handler.

The mutating routes are currently unauthenticated. `/say` also places the injected text in the URL and echoes it in the JSON response; request method, `Host`, and request-size validation are not yet enforced. Keep the listener loopback-only and do not expose it through a reverse proxy, public tunnel, LAN bind, or container port mapping. Hardening is tracked in [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).

## Auto-leave and idle prompt

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS` | `900` | Stop after this many seconds since the last non-empty PCM frame from a non-bot Discord user. This is not currently a verified speech-inactivity timer. The intended disable value is `0`, but one watchdog path still stops after minimum uptime; see Issues [#11](https://github.com/Capslockb/vapi-discord-bridge/issues/11) and [#12](https://github.com/Capslockb/vapi-discord-bridge/issues/12). |
| `DISCORD_VAPI_AUTO_LEAVE_MIN_UPTIME_SECONDS` | `120` | Minimum bridge uptime before idle prompting or auto-leave may fire. |
| `DISCORD_VAPI_IDLE_PROMPT_SECONDS` | `120` | Send the idle prompt after this many seconds since the last non-empty PCM frame. `0` disables the prompt. |
| `DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS` | `60` | Exposed in health output only. The watchdog does not use it as a grace or shutdown threshold, so changing it has no behavioral effect. |
| `DISCORD_VAPI_IDLE_PROMPT_TEXT` | `Are you still there?` | Text sent through Vapi when the idle prompt fires. |

Until [Issue #11](https://github.com/Capslockb/vapi-discord-bridge/issues/11) is fixed and tested, do not rely on `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS=0` to keep a bridge open. A deliberately large positive value is only a temporary workaround; unattended calls can continue incurring provider costs.

The runtime also resets its activity clock for every non-empty PCM frame from a non-bot user. Although an energy helper exists, the active sink path does not use it, so silence or low-level noise can postpone both the idle prompt and positive auto-leave threshold. This is tracked in [Issue #12](https://github.com/Capslockb/vapi-discord-bridge/issues/12). Treat both timers as best-effort operational aids, not dependable unattended-cost controls.

## Playback tuning

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_OUTPUT_PREROLL_MS` | `320` | Silence inserted before a new output turn. |
| `DISCORD_VAPI_OUTPUT_FADE_IN_MS` | `0` | Fade-in applied to the first output chunk. |
| `DISCORD_VAPI_OUTPUT_READ_WAIT_SECONDS` | `0.005` | Queue wait before returning a silence frame to Discord playback. |
| `DISCORD_VAPI_OUTPUT_TAIL_PAD_MS` | `240` | Parsed into `OUTPUT_TAIL_PAD_MS`, but no playback or turn-completion path consumes it. Changing it currently has no effect. |
| `DISCORD_VAPI_CLEAR_ON_INTERRUPT` | `true` | Clear queued playback when Vapi reports an interrupted or ended conversation update. |

`DISCORD_VAPI_KEEPALIVE_SECONDS` is parsed, but the active keepalive loop sends silence every 20 ms on a hard-coded cadence and does not use the configured interval. The related `KEEPALIVE_MESSAGE` constant is also not sent. Together with the inactive tail-pad and idle-grace values, this configuration-contract gap is tracked in [Issue #14](https://github.com/Capslockb/vapi-discord-bridge/issues/14).

## Autostart and voice-channel inference

The plugin can start from either an autostart file or environment defaults.

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_AUTOSTART` | _(false)_ | Set to `1`, `true`, or `yes` to schedule autostart without requiring the file. |
| `DISCORD_VAPI_AUTOSTART_FILE` | `~/.hermes/voice-vapi-autostart.json` | Override the autostart JSON path. This default is currently fixed and does not follow `HERMES_HOME`; see Issue [#26](https://github.com/Capslockb/vapi-discord-bridge/issues/26). |
| `DISCORD_VAPI_KEEP_AUTOSTART_FILE` | `0` | When false, a successful autostart deletes the JSON file. |
| `DISCORD_VAPI_GUILD_ID` | _(empty)_ | Fallback guild ID when not present in the JSON file. |
| `DISCORD_VAPI_CHANNEL_ID` | _(empty)_ | Fallback voice channel ID. |
| `DISCORD_VAPI_USER_ID` | repository-specific default | User whose current voice channel is inferred when guild/channel are absent. The `/voice-vapi` and `/voice-vapi-leave` command wrappers also use this fixed ID instead of the command invoker. Set it explicitly for your deployment. |

The current slash-command wrappers do not receive or use the invoking member's Discord ID. Until [Issue #8](https://github.com/Capslockb/vapi-discord-bridge/issues/8) is resolved, both commands target the voice state of `DISCORD_VAPI_USER_ID`.

For the default Hermes home:

```bash
mkdir -p ~/.hermes
cat > ~/.hermes/voice-vapi-autostart.json <<'EOF'
{
  "guild_id": "123456789012345678",
  "channel_id": "123456789012345678",
  "user_id": "123456789012345678"
}
EOF
chmod 600 ~/.hermes/voice-vapi-autostart.json
```

For a custom Hermes home, do not rely on the installer's optional autostart step. Set an explicit file path and create the JSON there manually:

```bash
export HERMES_HOME=/srv/hermes-custom
export DISCORD_VAPI_AUTOSTART_FILE="$HERMES_HOME/voice-vapi-autostart.json"
mkdir -p "$HERMES_HOME"
cat > "$DISCORD_VAPI_AUTOSTART_FILE" <<'EOF'
{
  "guild_id": "123456789012345678",
  "channel_id": "123456789012345678",
  "user_id": "123456789012345678"
}
EOF
chmod 600 "$DISCORD_VAPI_AUTOSTART_FILE"
```

Ensure the gateway service receives `DISCORD_VAPI_AUTOSTART_FILE`; exporting it in an unrelated shell does not modify an already running service environment. The file is deleted after a successful start unless `DISCORD_VAPI_KEEP_AUTOSTART_FILE=1`.

## Transcripts and summaries

The current bridge does not persist call transcripts. `voice_vapi_summary` can read compatible JSONL files if they already exist, but normal calls do not create them in this revision. This gap is tracked in [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).

Treat any manually supplied transcript files as sensitive and store them with restrictive permissions.
