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

### 6. Some stop paths leave the sidecar task registered

`BRIDGE.stop()` disconnects the Vapi and Discord resources, but the owning `run_sidecar()` task can remain blocked in `server.serve_forever()`. The loopback listener and a stopped `_active_bridges` entry may therefore remain after the HTTP `/stop` route or `voice_vapi_stop` tool is used.

The next `voice_vapi()` start normally detects the disconnected voice client and performs stale-entry recovery, but status and immediate restart behavior should not depend on that fallback.

**Workaround:** prefer `/voice-vapi-leave` or `voice_vapi_leave` when a clean task cancellation and registry removal are required.

**Tracking:** [Issue #4](https://github.com/Capslockb/vapi-discord-bridge/issues/4).

### 7. Only one voice bridge per guild

`discord-vapi` and another Discord voice bridge share the guild voice-client slot. Starting one may force-disconnect the other.

**Best practice:** select one active bridge per guild and avoid enabling competing autostart configurations simultaneously.

## Autostart and command inference

### 8. Autostart file lifecycle

A successful autostart deletes `~/.hermes/voice-vapi-autostart.json` by default. Set `DISCORD_VAPI_KEEP_AUTOSTART_FILE=1` only when persistent rejoin-on-boot behavior is intentional.

If startup never succeeds, the file remains available for the retry window and can trigger again on the next gateway start. Remove it to stop retries:

```bash
rm -f ~/.hermes/voice-vapi-autostart.json
```

### 9. Slash commands use a fixed configured user

The plugin contains a repository-specific default `DISCORD_VAPI_USER_ID`. The current `/voice-vapi` and `/voice-vapi-leave` wrappers use that fixed configured user to infer a voice channel or guild; they do not use the Discord member who invoked the command.

**Symptom:** a command can target another user's channel, select the wrong guild, or report no active voice session even though the invoker is connected.

**Authorization risk:** setting `DISCORD_VAPI_USER_ID` chooses the target account only; it does not authorize the member invoking the command. Any member who can invoke these wrappers may start or stop the configured user's bridge or guild session.

**Workaround:** treat both slash commands as administrator-only and restrict invocation through the surrounding Discord/Hermes command permissions. If untrusted members can invoke them, do not expose or use the slash-command wrappers. Set `DISCORD_VAPI_USER_ID` explicitly only for target selection, not as an access-control mechanism.

**Tracking:** [Issue #8](https://github.com/Capslockb/vapi-discord-bridge/issues/8).

### 10. Malformed tool identifiers can escape controlled errors

The Hermes schemas accept Discord identifiers as strings, while the current start, leave, say, and stop paths convert several values with `int(...)` before entering a controlled validation boundary.

**Symptom:** an empty, whitespace-only, non-decimal, zero, negative, boolean, or otherwise malformed `guild_id` or `channel_id` can raise `TypeError` or `ValueError` instead of returning the plugin's normal JSON error object.

**Workaround:** pass only known positive decimal Discord snowflake strings. Do not map untrusted free-form text directly into identifier fields. For `voice_vapi_stop`, omit `guild_id` only when an intentional stop-all operation is authorized; a malformed supplied value is not a safe substitute for omission.

**Tracking:** [Issue #13](https://github.com/Capslockb/vapi-discord-bridge/issues/13).

## Configuration and tuning

### 11. Voice display names are not voice IDs

The inline assistant sends a provider-specific `voiceId`. Human-readable names such as `jennifer` may not be valid IDs for the selected provider.

Use the exact provider and voice ID from Vapi, or configure them on a saved Vapi assistant.

### 12. Some defined tuning variables are ineffective

- `DISCORD_VAPI_KEEPALIVE_SECONDS` is parsed, but `_keepalive_loop()` sends silence every 20 ms on a hard-coded cadence and never uses the configured interval.
- `KEEPALIVE_MESSAGE` is defined but is not sent by the active WebSocket path.
- `DISCORD_VAPI_IDLE_PROMPT_GRACE_SECONDS` appears in health output but is not used as a grace or shutdown threshold.
- `DISCORD_VAPI_OUTPUT_TAIL_PAD_MS` is parsed but is not consumed by playback or turn-completion logic.

Changing these values currently does not alter the corresponding runtime behavior. Treat them as inactive configuration rather than tuning controls.

**Tracking:** [Issue #14](https://github.com/Capslockb/vapi-discord-bridge/issues/14).

### 13. Zero does not currently disable quiet auto-leave

`DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS=0` is intended to disable the quiet-timeout stop, and the helper method contains that guard. However, the watchdog performs an earlier unconditional `idle >= AUTO_LEAVE_QUIET_SECONDS` comparison. With a value of `0`, the bridge can therefore stop as soon as the minimum-uptime gate is reached.

**Workaround:** do not rely on `0` as a disable value in the current runtime. A deliberately large positive value can postpone the stop, but it is not a safety control and unattended calls may continue incurring provider costs.

**Tracking:** [Issue #11](https://github.com/Capslockb/vapi-discord-bridge/issues/11).

### 14. Quiet activity includes every non-empty PCM frame

The bridge resets `_last_activity_at` whenever it receives a non-empty PCM frame from a non-bot Discord user. It does not currently require detected speech: the existing energy helper and silence counters are not used by the active sink path.

**Impact:** silence, background noise, or other sub-speech PCM can postpone the idle prompt and positive quiet auto-leave threshold. The `quiet_seconds` health value is therefore time since the last qualifying inbound frame, not verified time since the last spoken activity.

**Workaround:** treat the timers as best-effort operational aids. Monitor unattended calls and stop them explicitly; do not use quiet auto-leave as the sole provider-cost cap.

**Tracking:** [Issue #12](https://github.com/Capslockb/vapi-discord-bridge/issues/12).

### 15. Module import path

The installed plugin directory is named `discord-vapi`. A hyphen is not valid in a normal Python import identifier, so this is invalid:

```python
import discord-vapi
```

Hermes loads the plugin from its filesystem path. Custom Python code should not import the directory name directly.

## Cost and privacy

### 16. Idle calls may continue consuming paid services

An open Vapi call can continue incurring charges even when conversation is quiet. Configure a tested positive `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS` value, verify current provider pricing, and monitor unattended sessions. Until Issues [#11](https://github.com/Capslockb/vapi-discord-bridge/issues/11) and [#12](https://github.com/Capslockb/vapi-discord-bridge/issues/12) are resolved, the timer is not a dependable disable control or speech-inactivity cost cap.

### 17. Transcript inputs are sensitive

Although the current bridge does not persist transcripts itself, any JSONL files supplied to the summary tool may contain private voice content, tool arguments, and identifiers. Store them with restrictive permissions and do not commit them.

### 18. Gateway logs can retain spoken content and control payloads

The active receive loop logs complete parsed Vapi message objects at DEBUG. When a transcript containing `disconnect` triggers shutdown, the spoken transcript is also propagated as the leave reason and logged at INFO.

**Impact:** transcripts, tool/control payloads, identifiers, provider metadata, and other call content can persist in journald, terminal captures, monitoring systems, or copied support bundles. Lowering the log level does not remove the INFO-level disconnect-reason exposure.

**Workaround:** treat all gateway logs as sensitive voice-session records. Avoid enabling or retaining verbose logs unless necessary, inspect them locally, and redact transcript text, identifiers, URLs, tokens, and raw provider payloads before sharing. Do not rely on log-level configuration as a complete privacy control.

**Tracking:** [Issue #15](https://github.com/Capslockb/vapi-discord-bridge/issues/15).

### 19. Injected speech is unbounded and echoed in responses

The active `voice_vapi_say` tool and loopback `/say?text=...` route accept caller-controlled text without a shared maximum length. Each path sends the complete value in one provider message and reproduces the submitted speech content in its success result.

**Impact:** oversized or untrusted values can create excessive speech generation, avoidable provider cost, large tool traces, and additional retention of private content in callers, logs, or support captures.

**Workaround:** keep injected text short, operator-authored, and non-sensitive. Do not pass documents, transcripts, secrets, or arbitrary untrusted input. Treat the accepted owner direction as pending runtime work: one conservative shared length contract, controlled handling of empty, control, newline, multi-byte, and oversized input, and metadata-only success responses.

**Tracking:** [Issue #16](https://github.com/Capslockb/vapi-discord-bridge/issues/16).

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

Never include Discord tokens, Vapi keys, transcript contents, raw provider payloads, tool arguments, private URLs, or private user/channel identifiers in a public issue.