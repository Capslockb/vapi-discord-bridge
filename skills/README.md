# Skills (operator docs)

This directory contains the Hermes Agent skills used to drive this bridge.

| Skill | Purpose |
|-------|---------|
| [`vapi-voice-bridge/`](vapi-voice-bridge/SKILL.md) | Drive the Vapi bridge in chat, configure assistant/voice/model, handle tools. |
| [`voice-bridge-protocols/`](voice-bridge-protocols/SKILL.md) | Shared bridge patterns — audio pipeline, lifecycle, cost control. |

## Install a skill into your Hermes home

Run these commands from the repository root. An existing `HERMES_HOME` value is preserved; otherwise the default is `~/.hermes`. The destination directory must exist before either install mode is used.

These commands install the Hermes skill directories only. They do not deploy the bridge plugin, install `plugin/requirements.txt`, write credentials, or create autostart state. For a complete bridge installation, follow the root [`README.md`](../README.md) and [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md). With a custom `HERMES_HOME`, keep the dependency and autostart limitations tracked in Issues [#24](https://github.com/Capslockb/vapi-discord-bridge/issues/24) and [#26](https://github.com/Capslockb/vapi-discord-bridge/issues/26) in mind.

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

If either destination already exists as a real directory from an earlier copy install, move or remove that directory deliberately before switching to symlink mode; `ln -sfn` does not replace a real directory atomically.

Or copy them:

```bash
cp -r "$(pwd)/skills/vapi-voice-bridge" "$SKILLS_DIR/"
cp -r "$(pwd)/skills/voice-bridge-protocols" "$SKILLS_DIR/"
```

Copying over an existing skill directory merges files and can leave stale files behind. For a clean replacement, back up or remove the previous destination first.

Then restart the gateway:

```bash
systemctl --user restart hermes-gateway
```

If the gateway service does not already receive the same custom `HERMES_HOME`, configure that value in its service environment before restarting it.

## Coexistence with the Gemini bridge

`voice-bridge-protocols` is shared between this repo and the sister project
[`Capslockb/gemini-live-discord-bridge`](https://github.com/Capslockb/gemini-live-discord-bridge).
The two are kept identical; if you change it in one, mirror the change in the other.
