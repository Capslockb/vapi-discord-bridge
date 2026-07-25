# Known bugs and limitations

> Canonical operator-facing limitation list for `vapi-discord-bridge`. Open a focused issue when a reproducible problem is not covered here.

## High-priority gaps

### 1. Installer and runtime configuration drift

**Symptom:** installer selections for voice, first message, or a non-OpenAI model appear to succeed but do not change the running transient assistant.

**Cause:** the installer writes `VAPI_VOICE`, `VAPI_FIRST_MESSAGE`, and optionally `GEMINI_API_KEY`, while the runtime reads `VAPI_VOICE_PROVIDER`, `VAPI_VOICE_ID`, `VAPI_MODEL_NAME`/`VAPI_MODEL`, and `VAPI_SYSTEM_PROMPT`. The inline runtime path also hard-codes the model provider to OpenAI.

**Workaround:** use a saved `VAPI_ASSISTANT_ID`, or set the verified runtime keys manually.

**Tracking:** [Issue #1](https://github.com/Capslockb/vapi-discord-bridge/issues/1).

### 2. Calls do not create summary-compatible transcript files

**Symptom:** `voice_vapi_summary` reports that no transcript is available after a normal call.

**Cause:** the current bridge processes incoming transcript messages in memory but does not persist JSONL files under `~/.hermes/voice-vapi-notes/`.

**Workaround:** pass an externally created compatible JSONL file to the summary tool.

**Tracking:** [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2).

### 3. Vapi function-call dispatch is not implemented

The active WebSocket receive loop handles assistant status, conversation updates, transcript text, and binary audio. It does not currently route Vapi function/tool calls to Hermes handlers.

Do not configure a production assistant on the assumption that this bridge will execute Vapi tool calls until Issue #2 is resolved and tested.

### 4. Mutating HTTP routes are unauthenticated

The control listener binds to `127.0.0.1`, but `/stop` and `/say?text=...` do not require a secret.

**Risk:** any local process able to reach the port can stop the bridge or inject speech into an active call.

**Workaround:** keep the listener loopback-only. Do not expose it through a reverse proxy, tunnel, LAN bind, or container port mapping.

**Tracking:** [Issue #3](https://github.com/Capslockb/vapi-discord-bridge/issues/3).

## Discord voice behavior

### 5. Voice connection retries can look like a hang

Some Discord voice endpoints have been observed rejecting several initial handshakes before a later retry succeeds.

**Symptom:** `channel.connect()` takes tens of seconds and logs repeated voice handshake failures.

**Workaround:** allow the configured 60-second connection timeout to finish. Repeated gateway restarts reset the retry sequence and can make rate limiting worse.

This is environment-dependent; do not treat one observed Amsterdam CDN hostname or an exact retry count as universal behavior.

### 6. Stale rejoin entries

A previously disconnected guild may remain in `_active_bridges` while its voice client is no longer connected.

The current `voice_vapi()` path detects this state, cancels the old task, removes the stale entry, and starts again. Report a bug if the command still remains permanently in `pending` state.

### 7. Only one voice bridge per guild

`discord-vapi` and another Discord voice bridge share the guild voice-client slot. Starting one may force-disconnect the other.

**Best practice:** select one active bridge per guild and avoid enabling competing autostart configurations simultaneously.

## Autostart

### 8. Autostart file lifecycle

A successful autostart deletes `~/.hermes/voice-vapi-autostart.json` by default. Set `DISCORD_VAPI_KEEP_AUTOSTART_FILE=1` only when persistent rejoin-on-boot behavior is intentional.

If startup never succeeds, the file remains available for the retry window and can trigger again on the next gateway start. Remove it to stop retries:

```bash
rm -f ~/.hermes/voice-vapi-autostart.json
```

### 9. Repository-specific default user ID

The plugin contains a default `DISCORD_VAPI_USER_ID`. Set your own deployment value explicitly instead of relying on the repository default when autostart infers a voice channel from a user.

## Configuration and tuning

### 10. Voice display names are not voice IDs

The inline assistant sends a provider-specific `voiceId`. Human-readable names such as `jennifer` may not be valid IDs for the selected provider.

Use the exact provider and voice ID from Vapi, or configure them on a saved Vapi assistant.

### 11. Some defined tuning variables are ineffective

- `DISCORD_VAPI_KEEPALIVE_SECONDS` is read, but the active keepalive loop sends silence every 20 ms and does not use the configured interval.
- `DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS` appears in health output but is not used as a separate watchdog threshold.
- `DISCORD_VAPI_OUTPUT_TAIL_PAD_MS` is defined but should not be relied on until its runtime use is verified.

### 12. Module import path

The installed plugin directory is named `discord-vapi`. A hyphen is not valid in a normal Python import identifier, so this is invalid:

```python
import discord-vapi
```

Hermes loads the plugin from its filesystem path. Custom Python code should not import the directory name directly.

## Cost and privacy

### 13. Idle calls may continue consuming paid services

An open Vapi call can continue incurring charges even when conversation is quiet. Configure `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS`, verify current provider pricing, and monitor unattended sessions.

### 14. Transcript inputs are sensitive

Although the current bridge does not persist transcripts itself, any JSONL files supplied to the summary tool may contain private voice content, tool arguments, and identifiers. Store them with restrictive permissions and do not commit them.

## Reporting a new bug

Include:

1. Hermes gateway version: `hermes --version`.
2. Plugin version: `cat plugin/plugin.yaml | head -3`.
3. Whether `VAPI_ASSISTANT_ID` is set.
4. Effective model provider/model and voice provider/ID, with secrets removed.
5. Last 100 gateway log lines:

   ```bash
   journalctl --user -u hermes-gateway --since '5 min ago' --no-pager -o cat | tail -100
   ```

6. Health output:

   ```bash
   curl -s http://127.0.0.1:18944/health | python3 -m json.tool
   ```

7. Exact reproduction steps and expected versus actual behavior.

Never include Discord tokens, Vapi keys, transcript contents, or private user/channel identifiers in a public issue.
