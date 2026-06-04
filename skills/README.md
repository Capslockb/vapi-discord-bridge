# Skills (operator docs)

This directory contains the Hermes Agent skills used to drive this bridge.

| Skill | Purpose |
|-------|---------|
| [`vapi-voice-bridge/`](vapi-voice-bridge/SKILL.md) | Drive the Vapi bridge in chat, configure assistant/voice/model, handle tools. |
| [`voice-bridge-protocols/`](voice-bridge-protocols/SKILL.md) | Shared bridge patterns — audio pipeline, lifecycle, cost control. |

## Install a skill into your Hermes home

```bash
HERMES_HOME=~/.hermes

# Symlink (recommended for development)
ln -sf "$(pwd)/skills/vapi-voice-bridge" "$HERMES_HOME/skills/devops/vapi-voice-bridge"
ln -sf "$(pwd)/skills/voice-bridge-protocols" "$HERMES_HOME/skills/devops/voice-bridge-protocols"
```

Or copy them:

```bash
cp -r skills/vapi-voice-bridge "$HERMES_HOME/skills/devops/"
cp -r skills/voice-bridge-protocols "$HERMES_HOME/skills/devops/"
```

Then restart the gateway:

```bash
systemctl --user restart hermes-gateway
```

## Coexistence with the Gemini bridge

`voice-bridge-protocols` is shared between this repo and the sister project
[`Capslockb/gemini-live-discord-bridge`](https://github.com/Capslockb/gemini-live-discord-bridge).
The two are kept identical; if you change it in one, mirror the change in the other.
