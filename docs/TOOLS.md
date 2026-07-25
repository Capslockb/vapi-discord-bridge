# Hermes tools

The plugin registers six Hermes tools. Tool arguments are JSON-compatible values even when examples are shown in compact Hermes chat form.

## `voice_vapi`

Start a Vapi bridge for a Discord guild.

```text
voice_vapi guild_id=1234567890 channel_id=0987654321
```

Arguments:

- `guild_id` — Discord guild ID.
- `channel_id` — voice channel ID to join.
- `user_id` — optional Discord user ID whose current voice channel should be used when `channel_id` is omitted.

## `voice_vapi_leave`

Stop the bridge for one guild.

```text
voice_vapi_leave guild_id=1234567890
```

`guild_id` is required. This is the recommended normal shutdown path because it removes the guild registry entry and cancels the owning sidecar task before disconnecting the Discord voice client.

## `voice_vapi_status`

Return bridge health and runtime metrics. It takes no arguments.

```text
voice_vapi_status
```

## `voice_vapi_say`

Send text into an active Vapi call so the assistant speaks it.

```text
voice_vapi_say guild_id=1234567890 text="Reminder: standup in 5 minutes"
```

Both `guild_id` and `text` are required.

## `voice_vapi_stop`

Stop one bridge or all active bridges.

```text
voice_vapi_stop guild_id=1234567890
```

Omit `guild_id` to stop all active bridges:

```text
voice_vapi_stop
```

> Current limitation: this tool calls the bridge media stop routine but does not consistently terminate the owning sidecar task, close the loopback listener, or remove the registry entry immediately. Prefer `voice_vapi_leave` for normal per-guild shutdown until [Issue #4](https://github.com/Capslockb/vapi-discord-bridge/issues/4) is resolved.

## `voice_vapi_summary`

Generate a report from an existing compatible JSONL transcript.

> Current limitation: the active bridge does not create transcript files after a normal call. Supply a compatible file manually until [Issue #2](https://github.com/Capslockb/vapi-discord-bridge/issues/2) is resolved.

Use the newest compatible file in the default directory:

```text
voice_vapi_summary
```

Select report sections:

```text
voice_vapi_summary sections="summary,tasks,decisions,followups"
```

Target a specific transcript:

```text
voice_vapi_summary file="/home/user/.hermes/voice-vapi-notes/voice-vapi-20260725-120000.jsonl"
```

Return JSON instead of Markdown:

```text
voice_vapi_summary json_only=true
```

Arguments:

- `notes_dir` — override the transcript directory.
- `file` — explicit transcript path; otherwise the newest compatible file is used.
- `json_only` — return structured JSON instead of Markdown.
- `sections` — comma-separated subset of `summary`, `transcript`, `tasks`, `decisions`, `questions`, and `followups`.

The summary tool returns an error object when no transcript is available, the helper script fails, the JSONL shape is incompatible, or processing exceeds its 30-second timeout.

Treat transcript inputs and generated reports as sensitive data. Do not commit them or paste unredacted contents into public issues.
