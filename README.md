# Vapi Discord Bridge

> Discord voice channel ↔ Vapi.ai WebSocket transport, packaged as a [Hermes Agent](https://hermes-agent.nousresearch.com) plugin.

Drop a Vapi-powered voice agent into any Discord voice channel. Low-latency full-duplex audio, text-to-speech, speech-to-text, configurable assistant, and a 3-minute oneshot installer.

```
  Discord user ──► Discord UDP ──► [NaCl] ──► Opus ──► Vapi WSS
  Discord user ◄── Discord UDP ◄── [NaCl] ◄── Opus ◄── Vapi WSS
                                    │
                                    └──► JSONL transcript at ~/.hermes/voice-vapi-notes/
```

---

## ⚡ Quick install (3 min)

```bash
git clone https://github.com/Capslockb/vapi-discord-bridge.git
cd vapi-discord-bridge
python3 installer/install.py
```

The installer walks you through every step interactively:

| Step | What happens |
|------|--------------|
| 1    | System preflight — detects Python, Hermes home, venv, git, gh |
| 2    | API key collection — Discord bot token + Vapi private key (with **live network validation**) |
| 3    | Install mode — copy into `~/.hermes/plugins/`, symlink, or local |
| 4    | Plugin deployment — copies files, fixes perms, runs `pip install` |
| 5    | `.env` merge — writes keys to `~/.hermes/.env` (chmod 600) |
| 6    | Optional autostart — drops `voice-vapi-autostart.json` so the bridge joins on gateway boot |

**Scripted / CI mode:** add `--yes` (or `-y`) to auto-answer all prompts with defaults:
```bash
python3 installer/install.py --yes
```

No external CLI deps. Only requires `rich` (already in the Hermes venv). Pure stdlib otherwise.

---

## 🧰 What you need

| Item | Where | Cost |
|------|-------|------|
| Discord bot token | [discord.com/developers](https://discord.com/developers/applications) → Bot → Reset Token | free |
| Vapi private API key | [dashboard.vapi.ai](https://dashboard.vapi.ai) → Account Settings → API Keys | pay-per-minute |
| Python 3.10+ | system | free |
| Hermes Agent (optional, but recommended) | `pip install hermes-agent` | free / self-hosted |

Discord bot must have these intents enabled: **Server Members**, **Message Content**, and **Voice States** under the Bot tab. Invite URL needs `bot` scope + `connect`, `speak`, `use_voice_activity` permissions.

Vapi costs: outbound voice minutes + LLM tokens + TTS characters. Use `gpt-4o-mini` as the model to keep the per-minute cost low; switch to `gpt-4o` or `claude-3-5-sonnet` for higher quality.

---

## 🎯 Usage

### Slash command (in Discord)

```
/voice-vapi
```

The bot joins **your current voice channel** and starts the Vapi call.

### Hermes chat

```
voice_vapi guild_id=1234567890 channel_id=0987654321
```

### Health check

```bash
curl -s http://127.0.0.1:18944/health | python3 -m json.tool
```

### Send text into the active call

```bash
voice_vapi_say guild_id=1234567890 text="Reminder: standup in 5 minutes"
```

### Leave the channel

```
/voice-vapi-leave
# or
voice_vapi_leave guild_id=1234567890
```

---

## 🏗️ Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown.

```
┌─────────────────┐                    ┌──────────────────────┐
│  Discord Voice  │  ◄──Opus 48kHz──►  │   LiveAudioSource    │
│  (UDP + NaCl)   │                    │   (thread-safe queue)│
└────────┬────────┘                    └──────────┬───────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────┐                    ┌──────────────────────┐
│  VoiceListener  │  ──PCM 16kHz───►   │  VapiClient          │
│  (rx thread)    │                    │  (WSS + JSON ctrl)   │
└─────────────────┘                    └──────────┬───────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │   Vapi.ai            │
                                         │  (STT → LLM → TTS    │
                                         │   + tool calls)      │
                                         └──────────────────────┘
```

The bridge is **in-process** — it lives inside the Hermes gateway's asyncio loop. No external services to run.

---

## 🔧 Configuration

All config goes in `~/.hermes/.env`:

```env
# Required
DISCORD_BOT_TOKEN=...
VAPI_API_KEY=...

# Optional — Vapi assistant
VAPI_ASSISTANT_ID=               # leave blank to auto-provision
VAPI_VOICE=                       # e.g. jennifer, ryan, deepbrian
VAPI_MODEL=gpt-4o-mini            # any Vapi-supported LLM
VAPI_FIRST_MESSAGE=               # what Vapi says on join

# Optional — networking
DISCORD_VAPI_PORT=18944           # localhost HTTP control

# Optional — auto-leave
DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS=900

# Optional — provider override (only if you set VAPI_MODEL=gemini-...)
GEMINI_API_KEY=...
```

Get your Vapi keys at: https://dashboard.vapi.ai

---

## 🎙️ Voice + model choices

The installer accepts a `VAPI_VOICE` and `VAPI_MODEL`. Common picks:

| Voice | Provider | Notes |
|-------|----------|-------|
| `jennifer` | 11labs | warm, female, default |
| `ryan` | 11labs | calm, male |
| `deepbrian` | deepgram | lower latency |
| `alloy` / `echo` / `shimmer` | OpenAI | if you use OpenAI TTS |

| Model | Use case | Cost |
|-------|----------|------|
| `gpt-4o-mini` | default, fast, cheap | $ |
| `gpt-4o` | higher quality, more context | $$ |
| `claude-3-5-sonnet` | longer reasoning, coding | $$$ |
| `gemini-1.5-pro` | long context window | $$ |

---

## 💸 Cost notes

Vapi charges per minute **on top of** the underlying LLM and TTS costs. With `gpt-4o-mini` + 11labs `jennifer`, expect ~$0.10–$0.15 per minute of real conversation. Auto-leave on silence (default 15 min) caps idle time.

---

## 📝 Call transcripts

Every call writes a JSONL transcript to `~/.hermes/voice-vapi-notes/voice-vapi-YYYYMMDD-HHMMSS.jsonl` containing:

- Per-turn events (user / assistant)
- Tool call invocations
- Hangup events
- Final compiled transcript at the bottom

---

## 🐛 Known bugs / quirks

> Full list in [`docs/KNOWN_BUGS.md`](docs/KNOWN_BUGS.md). Summary:

1. **Discord CDN handshake rejection** — `c-ams08.discord.media` rejects the first ~5 handshakes with code 4006. A single `channel.connect()` takes ~27 s of internal retries. **Do not restart the gateway repeatedly** — each restart resets the retry clock.
2. **Stale rejoin fix** — if a guild entry remains in `_active_bridges` but `vc.is_connected()` returns False, a new `/voice-vapi` hangs with "Bridge still starting". The plugin detects this and starts fresh instead of returning pending.
3. **Coexistence with gemini-live-discord-bridge** — each plugin uses its own autostart file (`voice-live-autostart.json` vs `voice-vapi-autostart.json`) and force-disconnects the other plugin's voice client before starting. Don't run both at once in the same channel.
4. **Module import path** — the plugin dir is `discord-vapi` (Python-safe already, no dash to normalize).

---

## 🛠️ Development

```bash
git clone https://github.com/Capslockb/vapi-discord-bridge.git
cd vapi-discord-bridge
pip install -r plugin/requirements.txt

# Symlink install (good for development)
python3 installer/install.py   # pick "symlink" mode

# Compile check after editing
python3 -m py_compile plugin/bridge.py plugin/__init__.py
```

### Project layout

```
vapi-discord-bridge/
├── README.md
├── LICENSE
├── plugin/                    # the actual Hermes plugin
│   ├── __init__.py            #   tool registration + slash commands
│   ├── bridge.py              #   core audio pipeline + Vapi WSS client
│   ├── plugin.yaml            #   Hermes plugin metadata
│   └── requirements.txt
├── installer/
│   └── install.py             # oneshot TUI installer
├── scripts/
│   └── post_call_summary.py   # extract tasks/decisions from .jsonl
├── docs/
│   ├── ARCHITECTURE.md        # deep dive on the audio pipeline
│   ├── CONFIGURATION.md       # every env var explained
│   ├── KNOWN_BUGS.md          # full bug list with repro steps
│   └── diagrams/
│       ├── dataflow.txt       # ASCII dataflow diagram
│       ├── audio-pipeline.txt
│       ├── vapi-wss-protocol.txt
│       └── lifecycle.txt
└── .github/
    └── workflows/
        └── lint.yml
```

---

## 📜 License

MIT.

---

## 🙏 Credits

- Discord voice protocol — [`discord.py`](https://github.com/Rapptz/discord.py) + [`discord-ext-voice-recv`](https://github.com/imayhaveborkedit/discord-ext-voice-recv).
- Opus decoding — bundled with `discord.py`.
- Vapi.ai — [vapi.ai](https://vapi.ai).
- Hermes Agent — [Nous Research](https://nousresearch.com).
- Built and battle-tested at [capslock.nl](https://capslock.nl).
