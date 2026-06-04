# Configuration

> Every env var the vapi-discord-bridge understands.

All settings live in `~/.hermes/.env` (chmod 600). The installer writes/merges them automatically. After changing anything, restart the gateway:

```bash
systemctl --user restart hermes-gateway
```

## Required

| Key | Type | Example | Notes |
|-----|------|---------|-------|
| `DISCORD_BOT_TOKEN` | secret | `MTI0...X.Vw.A...` | Bot token from Discord Developer Portal. Voice States intent must be enabled. |
| `VAPI_API_KEY` | secret | `sk-...` (≥20 chars) | Vapi **private** key from [dashboard.vapi.ai](https://dashboard.vapi.ai) → Account Settings → API Keys. |

## Vapi assistant & model

| Key | Default | Notes |
|-----|---------|-------|
| `VAPI_ASSISTANT_ID` | _(auto)_ | A preconfigured Vapi assistant ID. If blank, the bridge auto-provisions a minimal one on first run. |
| `VAPI_VOICE` | _(Vapi default)_ | Voice ID — see [vapi voices](https://docs.vapi.ai/voices). E.g. `jennifer`, `ryan`, `alloy`, `echo`. |
| `VAPI_MODEL` | `gpt-4o-mini` | Any Vapi-supported LLM: `gpt-4o`, `gpt-4o-mini`, `claude-3-5-sonnet`, `gemini-1.5-pro`, `llama-3.1-70b`. |
| `VAPI_FIRST_MESSAGE` | _(Vapi default)_ | Text the assistant says when joining the call. |

## Provider overrides

| Key | Default | Notes |
|-----|---------|-------|
| `GEMINI_API_KEY` | _(empty)_ | Only required if you set `VAPI_MODEL=gemini-...`. Vapi will use it as the LLM provider. |
| `VAPI_PUBLIC_KEY` | _(empty)_ | Public Web SDK key. Optional for headless server use; only needed if you also embed a Vapi widget. |

## Networking

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_PORT` | `18944` | Localhost HTTP control port. Bind stays on `127.0.0.1`. |

## Auto-leave

| Key | Default | Notes |
|-----|---------|-------|
| `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS` | `900` | Hang up after this many seconds of silence. `0` disables auto-leave. |
| `DISCORD_VAPI_AUTO_LEAVE_MIN_UPTIME_SECONDS` | `120` | Don't auto-leave during the first N seconds. Prevents hangs on long connects. |
| `DISCORD_VAPI_LEAVE_PHRASES` | `goodbye,bye,hang up,end call,stop voice,thanks bye` | Comma-separated. If the assistant outputs any of these, the bridge leaves immediately. |

## Notes / transcripts

| Key | Default | Notes |
|-----|---------|-------|
| `NOTES_DIR` | `~/.hermes/voice-vapi-notes/` | Where the JSONL transcript is written. Created on first call if missing. |

## Autostart

Trigger the bridge to auto-join on gateway boot by writing a small JSON file:

```bash
mkdir -p ~/.hermes
cat > ~/.hermes/voice-vapi-autostart.json <<EOF
{
  "guild_id": "123456789012345678",
  "channel_id": "123456789012345678",
  "user_id": "123456789012345678"
}
EOF
chmod 600 ~/.hermes/voice-vapi-autostart.json
```

The file is **deleted on successful start** — recreate it to re-trigger. The Gemini plugin uses a different file (`voice-live-autostart.json`) and won't conflict.

## Tuning tips

- **Lower cost** — set `VAPI_MODEL=gpt-4o-mini`, `VAPI_VOICE=deepbrian` (Deepgram TTS, faster & cheaper than 11labs).
- **Higher quality** — `VAPI_MODEL=claude-3-5-sonnet`, `VAPI_VOICE=jennifer`. Pays roughly 4× the per-minute cost.
- **Add tool calls** — configure a Vapi assistant with a `serverUrl` in the dashboard. Vapi POSTs to it; the bridge receives the result and resumes the call.
- **Multiple bots** — bind each gateway instance to a different `DISCORD_VAPI_PORT` (e.g. 18944, 18954, 18964) and run them under separate Hermes profiles.
