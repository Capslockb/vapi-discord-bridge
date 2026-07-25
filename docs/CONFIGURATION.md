# Configuration

> Runtime configuration verified against `plugin/bridge.py` and `plugin/__init__.py`.

All settings live in `~/.hermes/.env` unless you inject them through another process environment. Keep the file mode at `0600`. After changing runtime settings, restart the gateway:

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
| `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS` | `900` | Stop after this many seconds without recorded user activity. The intended disable value is `0`, but the current watchdog still stops after minimum uptime because one decision path lacks the disable guard. See Issue #11. |
| `DISCORD_VAPI_AUTO_LEAVE_MIN_UPTIME_SECONDS` | `120` | Minimum bridge uptime before idle prompting or auto-leave may fire. |
| `DISCORD_VAPI_IDLE_PROMPT_SECONDS` | `120` | Send the idle prompt after this many quiet seconds. `0` disables the prompt. |
| `DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS` | `60` | Reported in health output; the current watchdog does not use it as a separate shutdown threshold. |
| `DISCORD_VAPI_IDLE_PROMPT_TEXT` | `Are you still there?` | Text sent through Vapi when the idle prompt fires. |

Until [Issue #11](https://github.com/Capslockb/vapi-discord-bridge/issues/11) is fixed and tested, do not rely on `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS=0` to keep a bridge open. A deliberately large positive value is only a temporary workaround; unattended calls can continue incurring provider costs.

## Playback tuning

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_OUTPUT_PREROLL_MS` | `320` | Silence inserted before a new output turn. |
| `DISCORD_VAPI_OUTPUT_FADE_IN_MS` | `0` | Fade-in applied to the first output chunk. |
| `DISCORD_VAPI_OUTPUT_READ_WAIT_SECONDS` | `0.005` | Queue wait before returning a silence frame to Discord playback. |
| `DISCORD_VAPI_OUTPUT_TAIL_PAD_MS` | `240` | Defined by the runtime; verify behavior before relying on it for tuning. |
| `DISCORD_VAPI_CLEAR_ON_INTERRUPT` | `true` | Clear queued playback when Vapi reports an interrupted or ended conversation update. |

`DISCORD_VAPI_KEEPALIVE_SECONDS` is currently read but the active keepalive loop sends silence every 20 ms instead of using the configured interval. Treat it as ineffective until the runtime is corrected.

## Autostart and voice-channel inference

The plugin can start from either an autostart file or environment defaults.

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_AUTOSTART` | _(false)_ | Set to `1`, `true`, or `yes` to schedule autostart without requiring the file. |
| `DISCORD_VAPI_AUTOSTART_FILE` | `~/.hermes/voice-vapi-autostart.json` | Override the autostart JSON path. |
| `DISCORD_VAPI_KEEP_AUTOSTART_FILE` | `0` | When false, a successful autostart deletes the JSON file. |
| `DISCORD_VAPI_GUILD_ID` | _(empty)_ | Fallback guild ID when not present in the JSON file. |
| `DISCORD_VAPI_CHANNEL_ID` | _(empty)_ | Fallback voice channel ID. |
| `DISCORD_VAPI_USER_ID` | repository-specific default | User whose current voice channel is inferred when guild/channel are absent. The `/voice-vapi` and `/voice-vapi-leave` command wrappers also use this fixed ID instead of the command invoker. Set it explicitly for your deployment. |

The current slash-command wrappers do not receive or use the invoking member's Discord ID. Until [Issue #8](https://github.com/Capslockb/vapi-discord-bridge/issues/8) is resolved, both commands target the voice state of `DISCORD_VAPI_USER_ID`.

Example:

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

The file is deleted after a successful start unless `DISCORD_VAPI_KEEP_AUTOSTART_FILE=1`.

## Transcripts and summaries

The current bridge does not persist call transcripts. `voice_vapi_summary` can read compatible JSONL files if they already exist, but normal calls do not create them in this revision. This gap is tracked in [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).

Treat any manually supplied transcript files as sensitive and store them with restrictive permissions.