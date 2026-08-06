# Skills (operator docs)

This directory contains the Hermes Agent skills used to drive this bridge.

| Skill | Purpose |
|-------|---------|
| [`vapi-voice-bridge/`](vapi-voice-bridge/SKILL.md) | Drive the Vapi bridge in chat, configure assistant/voice/model, handle tools. |
| [`voice-bridge-protocols/`](voice-bridge-protocols/SKILL.md) | Shared bridge patterns — audio pipeline, lifecycle, cost control. |

## Install a skill into your Hermes home

Run these commands from the repository root. An existing `HERMES_HOME` value is preserved; otherwise the default is `~/.hermes`. The destination directory must exist before either install mode is used.

```bash
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILLS_DIR="$HERMES_HOME/skills/devops"
mkdir -p "$SKILLS_DIR"
```

Symlink the skills for development:

```bash
ln -sfn "$(pwd)/skills/vapi-voice-bridge" "$SKILLS_DIR/vapi-voice-bridge"
ln -sfn "$(pwd)/skills/voice-bridge-protocols" "$SKILLS_DIR/voice-bridge-protocols"
```

Or copy them:

```bash
cp -r "$(pwd)/skills/vapi-voice-bridge" "$SKILLS_DIR/"
cp -r "$(pwd)/skills/voice-bridge-protocols" "$SKILLS_DIR/"
```

Then restart the gateway:

```bash
systemctl --user restart hermes-gateway
```

If the gateway service does not already receive the same custom `HERMES_HOME`, configure that value in its service environment before restarting it.

## Coexistence with the Gemini bridge

`voice-bridge-protocols` is shared between this repo and the sister project
[`Capslockb/gemini-live-discord-bridge`](https://github.com/Capslockb/gemini-live-discord-bridge).
The two are kept identical; if you change it in one, mirror the change in the other.
