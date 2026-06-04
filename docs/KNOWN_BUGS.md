# Known bugs & quirks

> The canonical bug list for the vapi-discord-bridge. If you hit something not on here, please open an issue with the reproduction steps.

## Critical

### 1. Discord CDN handshake rejection (`code 4006`)

**Symptom:** `channel.connect()` takes ~27 seconds to complete. The first ~5 handshakes are rejected with code 4006; the 6th succeeds.

**Root cause:** This machine's Discord voice WebSocket endpoint (`c-ams08.discord.media` / `c-ams07`) has been observed to always reject initial handshakes. It's a Discord infrastructure quirk, not a bridge bug.

**Workaround:** The bridge waits up to 60 s for the secret key to be ready. Just be patient.

**DO NOT** keep restarting the gateway to "retry" — every restart resets the retry clock and you'll hit the rate limit harder.

### 2. Stale rejoin — "Bridge still starting" hang

**Symptom:** Calling `/voice-vapi` after a previous disconnect sometimes returns `pending: "Bridge is being started"` forever.

**Root cause:** `_active_bridges[guild_id]` still has an entry, but `voice_client.is_connected()` returns False. The plugin used to return "pending" in this case.

**Fix (shipped in `__init__.py:voice_vapi()`):** the plugin detects a stale entry (vc is None or not connected), cancels the old task, pops the entry from `_active_bridges`, and starts fresh.

### 3. Sidecar HTTP server hangs `serve_forever()`

**Symptom:** `bridge.py:run_sidecar()` uses `http.server.HTTPServer.serve_forever()` which never returns on its own. Without a shutdown signal, you can't cleanly stop the bridge.

**Fix (shipped in `bridge.py:run_sidecar()`):** an `_shutdown_watcher` task polls `BRIDGE._running` and calls `server.shutdown()` once it goes False, breaking `serve_forever()`.

## Coexistence with the Gemini bridge

### 4. Two plugins fighting for the voice client

If both `discord-voice` and `discord-vapi` plugins are loaded and you trigger `/voice-vapi` while a Gemini bridge is connected, the Vapi plugin force-disconnects the existing voice client first. The reverse is also true. This is by design — only one voice bridge per guild at a time.

**Best practice:** don't have both autostart files present at the same time. Pick one to be primary.

### 5. Stale autostart file causes boot loops

If a `voice-vapi-autostart.json` file is left over from a previous test session, the gateway will auto-join on every boot. Always clear the file after testing:

```bash
rm -f ~/.hermes/voice-vapi-autostart.json
```

(On 2026-05-28 a stale `voice-live-autostart.json` caused Gemini to autostart on every boot, blocking Vapi/Sora. Same risk applies the other direction.)

## Workarounds (not yet "fixed")

### 6. Module import path

The plugin directory is `discord-vapi` (already Python-safe, no dash to normalize). If you're importing it manually, use `discord_vapi`.

### 7. Function-calling handlers must be non-blocking

If a custom `function-call` handler blocks for >10 seconds, the Vapi WSS times out. Keep tool handlers quick or push long work to a background task.

### 8. Voice ID spelling

Vapi voice IDs are case-sensitive. `jennifer` works, `Jennifer` does not. If unsure, list voices via the Vapi dashboard.

## Performance

### 9. Opus decoder state corruption under packet loss

**Symptom:** `undecodable Opus frame` errors in the logs.

**Root cause:** Decoder state corruption. Self-heals on the next valid frame. **>100 errors in 5 seconds = real network issue**, not normal background noise.

## Cost

### 10. Idle calls still cost money

Vapi charges per minute **even when the model is silent**, because the LLM is still loaded and the WSS is open. Use `DISCORD_VAPI_AUTO_LEAVE_QUIET_SECONDS` to cap idle time.

## Compatibility

### 11. Older Vapi plans don't support `transient` calls

If you get a 403 when starting the call saying "transient calls not enabled on this account", either:
- upgrade your Vapi plan
- set `VAPI_ASSISTANT_ID` to a preconfigured assistant (not transient)

### 12. Discord voice rate limits

If you call `/voice-vapi` repeatedly without waiting, Discord will throttle. The bridge has a `_starting` guard that returns `pending` for 30 s, but be patient.

## Reporting new bugs

When opening an issue, include:

1. **Hermes gateway version** — `hermes --version`
2. **Plugin version** — `cat plugin/plugin.yaml | head -3`
3. **Vapi model + voice** in use
4. **Last 100 lines of `journalctl --user -u hermes-gateway --since '5 min ago' --no-pager -o cat`**
5. **Health JSON** — `curl -s http://127.0.0.1:18944/health | python3 -m json.tool`
6. **Repro steps** — `/voice-vapi` then `...` then expected vs actual
