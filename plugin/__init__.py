"""
Discord Vapi Voice Plugin — Hermes Plugin Registration
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("discord-vapi-plugin")

PLUGIN_DIR = Path(__file__).parent
CONTROL_PORT = int(os.getenv("DISCORD_VAPI_PORT", "18944"))
DEFAULT_USER_ID = os.getenv("DISCORD_VAPI_USER_ID", "1474100257762578597")
DEFAULT_GUILD_ID = os.getenv("DISCORD_VAPI_GUILD_ID", "")
DEFAULT_CHANNEL_ID = os.getenv("DISCORD_VAPI_CHANNEL_ID", "")
AUTOSTART_FILE = Path(os.getenv(
    "DISCORD_VAPI_AUTOSTART_FILE",
    str(Path.home() / ".hermes" / "voice-vapi-autostart.json"),
))

_active_bridges: Dict[int, Dict[str, Any]] = {}
_starting: Dict[int, bool] = {}


def _coerce_tool_args(args: Optional[Dict[str, Any]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(args, dict):
        merged.update(args)
        for key in ("arguments", "args", "input"):
            nested = args.get(key)
            if isinstance(nested, dict):
                merged.update(nested)
    merged.update(kwargs)
    return merged


async def _disconnect_any_existing_vc(adapter, guild_id_int: int) -> None:
    """Force-disconnect any active voice client in the guild, regardless of plugin."""
    guild = adapter._client.get_guild(guild_id_int) if hasattr(adapter, "_client") else None
    if not guild:
        return
    existing_vc = getattr(guild, "voice_client", None)
    if existing_vc and existing_vc.is_connected():
        try:
            logger.info("Vapi: force-disconnecting existing guild voice client before starting")
            await asyncio.wait_for(existing_vc.disconnect(force=True), timeout=10.0)
        except Exception as e:
            logger.warning("Vapi: existing voice disconnect failed: %s", e)
        # Give Discord a moment to propagate the disconnect
        await asyncio.sleep(0.5)


def register(ctx):
    ctx.register_tool(
        name="voice_vapi",
        toolset="hermes",
        schema={
            "name": "voice_vapi",
            "description": "Start a live Discord voice bridge via Vapi.ai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "string", "description": "Discord guild ID"},
                    "channel_id": {"type": "string", "description": "Voice channel ID to join"},
                    "user_id": {"type": "string", "description": "Discord user ID whose current voice channel should be used when channel_id is omitted"},
                },
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    if AUTOSTART_FILE.exists() or os.getenv("DISCORD_VAPI_AUTOSTART", "").lower() in {"1", "true", "yes"}:
        _schedule_autostart_thread()

    ctx.register_tool(
        name="voice_vapi_leave",
        toolset="hermes",
        schema={
            "name": "voice_vapi_leave",
            "description": "Stop the Vapi voice bridge for a guild.",
            "parameters": {
                "type": "object",
                "properties": {"guild_id": {"type": "string", "description": "Discord guild ID"}},
                "required": ["guild_id"],
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_leave_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    ctx.register_tool(
        name="voice_vapi_status",
        toolset="hermes",
        schema={
            "name": "voice_vapi_status",
            "description": "Check the Vapi voice bridge health and metrics. No arguments needed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_status_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    ctx.register_tool(
        name="voice_vapi_say",
        toolset="hermes",
        schema={
            "name": "voice_vapi_say",
            "description": "Send a text message through an active Vapi voice bridge (makes the bot speak through Vapi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "string", "description": "Discord guild ID of the active bridge"},
                    "text": {"type": "string", "description": "Text for Vapi to say"},
                },
                "required": ["guild_id", "text"],
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_say_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    ctx.register_tool(
        name="voice_vapi_stop",
        toolset="hermes",
        schema={
            "name": "voice_vapi_stop",
            "description": "Stop an active Vapi voice bridge. Stops all bridges if guild_id is omitted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "string", "description": "Discord guild ID (omit to stop all)"},
                },
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_stop_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    async def _voice_vapi_summary_handler(*args, **kwargs) -> str:
        """Build a post-call summary from the most recent Vapi voice transcript.

        Args (kwargs):
          notes_dir: override the JSONL notes directory
                     (default: ~/.hermes/voice-vapi-notes/)
          file: explicit transcript path (overrides --latest)
          json_only: return the JSON payload instead of the markdown sections
          sections: comma-separated subset of {summary,transcript,tasks,
                    decisions,questions,followups} (default: all)

        Returns a Discord-friendly markdown (or JSON) string. Falls back to a
        human error message if the script fails or no transcripts exist.
        """
        params = _coerce_tool_args(args, kwargs)
        notes_dir = params.get("notes_dir") or str(
            Path.home() / ".hermes" / "voice-vapi-notes"
        )
        file_arg = params.get("file")
        json_only = bool(params.get("json_only"))
        sections_raw = params.get("sections")
        try:
            script_path = PLUGIN_DIR / "post_call_summary.py"
            if not script_path.exists():
                # Fall back to the upstream repo location.
                script_path = (
                    Path.home() / "vapi-discord-bridge" / "scripts" / "post_call_summary.py"
                )
            cmd: list[str] = [
                sys.executable, str(script_path),
                "--notes-dir", notes_dir,
            ]
            if file_arg:
                cmd.extend(["--file", str(file_arg)])
            else:
                cmd.append("--latest")
            if json_only:
                cmd.append("--json")
            else:
                if sections_raw:
                    for sec in str(sections_raw).split(","):
                        sec = sec.strip()
                        if sec and sec in {
                            "summary", "transcript", "tasks",
                            "decisions", "questions", "followups",
                        }:
                            cmd.append(f"--{sec}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                return json.dumps({
                    "status": "error",
                    "message": "post_call_summary.py timed out after 30s",
                })
            if proc.returncode != 0:
                err = (stderr_b or b"").decode("utf-8", "replace").strip()
                return json.dumps({
                    "status": "error",
                    "message": f"post_call_summary failed (rc={proc.returncode}): {err or 'no stderr'}",
                })
            payload = (stdout_b or b"").decode("utf-8", "replace")
            if not payload.strip():
                return json.dumps({
                    "status": "error",
                    "message": "post_call_summary returned empty output",
                })
            if json_only:
                return json.dumps({
                    "status": "success",
                    "format": "json",
                    "data": json.loads(payload),
                })
            return json.dumps({
                "status": "success",
                "format": "markdown",
                "report": payload,
            })
        except SystemExit as exc:
            return json.dumps({
                "status": "error",
                "message": f"no transcripts available (SystemExit {exc.code})",
            })
        except Exception as exc:
            logger.warning("voice_vapi_summary failed: %s", exc)
            return json.dumps({
                "status": "error",
                "message": f"voice_vapi_summary failed: {exc}",
            })

    ctx.register_tool(
        name="voice_vapi_summary",
        toolset="hermes",
        schema={
            "name": "voice_vapi_summary",
            "description": (
                "Generate a post-call summary from the most recent Vapi voice "
                "transcript (tasks, decisions, questions, follow-ups, transcript). "
                "Reads from ~/.hermes/voice-vapi-notes/ — pass --file to target a "
                "specific transcript, or --latest to use the newest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notes_dir": {
                        "type": "string",
                        "description": "Override the JSONL notes directory.",
                    },
                    "file": {
                        "type": "string",
                        "description": "Explicit transcript JSONL path (overrides --latest).",
                    },
                    "json_only": {
                        "type": "boolean",
                        "description": "Return raw JSON instead of markdown sections.",
                    },
                    "sections": {
                        "type": "string",
                        "description": (
                            "Comma-separated subset of "
                            "{summary,transcript,tasks,decisions,questions,followups}."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
        handler=_voice_vapi_summary_handler,
        check_fn=lambda: True,
        is_async=True,
    )

    # Slash command wrapper: /voice-vapi in Discord starts the Vapi voice bridge.
    # Mirrors what the discord-voice plugin does for /voice-live.
    async def _slash_voice_vapi(raw_args: str) -> str:
        import gateway.run as _gw
        from gateway.platforms.base import Platform
        runner = None
        ref = getattr(_gw, "_gateway_runner_ref", None)
        if callable(ref):
            runner = ref()
        if runner is None:
            runner = getattr(getattr(_gw, "GatewayRunner", object), "_instance", None)
        if not runner:
            return "Gateway not available."
        adapter = runner.adapters.get(Platform("discord"))
        if not adapter:
            return "Discord adapter not found."
        user_id = DEFAULT_USER_ID
        inferred = _infer_user_voice_channel(adapter, str(user_id))
        if not inferred:
            return "Could not infer your current voice channel. Join a voice channel first."
        guild_id_str, channel_id_str = inferred
        result = json.loads(await voice_vapi(adapter, guild_id_str, channel_id_str))
        status = result.get("status", "error")
        msg = result.get("message", "")
        if status == "success":
            return f"✅ voice-vapi: {msg}"
        if status == "pending":
            return f"⏳ voice-vapi: {msg}"
        return f"❌ voice-vapi: {msg or status}"

    ctx.register_command(
        name="voice-vapi",
        handler=_slash_voice_vapi,
        description="Start Vapi voice bridge in your current voice channel",
        args_hint="",
    )

    async def _slash_voice_vapi_leave(raw_args: str) -> str:
        import gateway.run as _gw
        runner = None
        ref = getattr(_gw, "_gateway_runner_ref", None)
        if callable(ref):
            runner = ref()
        if runner is None:
            runner = getattr(getattr(_gw, "GatewayRunner", object), "_instance", None)
        if not runner:
            return "Gateway not available."
        from gateway.platforms.base import Platform
        adapter = runner.adapters.get(Platform("discord"))
        if not adapter:
            return "Discord adapter not found."
        user_id = DEFAULT_USER_ID
        inferred = _infer_user_voice_channel(adapter, str(user_id))
        if not inferred:
            return "No active voice session found."
        guild_id_str = inferred[0]
        result = json.loads(await voice_vapi_leave(guild_id_str))
        status = result.get("status", "error")
        msg = result.get("message", "")
        if status == "success":
            return f"✅ voice-vapi-leave: {msg}"
        return f"❌ voice-vapi-leave: {msg or status}"

    ctx.register_command(
        name="voice-vapi-leave",
        handler=_slash_voice_vapi_leave,
        description="Stop Vapi voice bridge",
        args_hint="",
    )


async def _voice_vapi_handler(args: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    params = _coerce_tool_args(args, kwargs)
    import gateway.run as gateway_run
    from gateway.platforms.base import Platform
    runner = None
    ref = getattr(gateway_run, "_gateway_runner_ref", None)
    if callable(ref):
        runner = ref()
    if runner is None:
        runner = getattr(getattr(gateway_run, "GatewayRunner", object), "_instance", None)
    if not runner:
        return json.dumps({"status": "error", "message": "Gateway not available"})
    adapter = runner.adapters.get(Platform("discord"))
    if not adapter:
        return json.dumps({"status": "error", "message": "Discord adapter not found"})

    guild_id = params.get("guild_id")
    channel_id = params.get("channel_id")
    user_id = str(params.get("user_id") or DEFAULT_USER_ID)
    if not guild_id or not channel_id:
        inferred = _infer_user_voice_channel(adapter, user_id)
        if inferred:
            guild_id, channel_id = inferred
    if not guild_id or not channel_id:
        return json.dumps({"status": "error", "message": "guild_id/channel_id are required"})
    return await _run_on_gateway_loop(runner, voice_vapi(adapter, str(guild_id), str(channel_id)))


async def _voice_vapi_leave_handler(args: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    params = _coerce_tool_args(args, kwargs)
    guild_id = params.get("guild_id")
    if not guild_id:
        return json.dumps({"status": "error", "message": "guild_id is required"})
    import gateway.run as gateway_run
    runner = None
    ref = getattr(gateway_run, "_gateway_runner_ref", None)
    if callable(ref):
        runner = ref()
    if runner is not None:
        return await _run_on_gateway_loop(runner, voice_vapi_leave(str(guild_id)))
    return await voice_vapi_leave(str(guild_id))


async def _voice_vapi_status_handler(args: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    bridges = []
    for gid, info in list(_active_bridges.items()):
        bridge_mod = info.get("bridge_mod")
        br = getattr(bridge_mod, "BRIDGE", None) if bridge_mod else None
        if br and hasattr(br, "health"):
            bridges.append({"guild_id": gid, **br.health()})
        else:
            bridges.append({"guild_id": gid, "status": "starting"})
    if not bridges:
        return json.dumps({"status": "no_bridges", "message": "No active Vapi bridges"})
    return json.dumps({"status": "ok", "bridges": bridges})


async def _voice_vapi_say_handler(args: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    params = _coerce_tool_args(args, kwargs)
    guild_id = int(params.get("guild_id", 0))
    text = str(params.get("text", "")).strip()
    if not text:
        return json.dumps({"status": "error", "message": "text is required"})
    if guild_id not in _active_bridges:
        return json.dumps({"status": "error", "message": f"No active Vapi bridge for guild {guild_id}"})
    bridge_mod = _active_bridges[guild_id].get("bridge_mod")
    br = getattr(bridge_mod, "BRIDGE", None) if bridge_mod else None
    if not (br and getattr(br, "_running", False)):
        return json.dumps({"status": "error", "message": "Bridge not running"})
    vapi = getattr(br, "_vapi", None)
    if not vapi:
        return json.dumps({"status": "error", "message": "Vapi not connected"})
    await vapi.send_text(text)
    return json.dumps({"status": "sent", "text": text})


async def _voice_vapi_stop_handler(args: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    params = _coerce_tool_args(args, kwargs)
    guild_id = int(params.get("guild_id", 0))
    if guild_id:
        if guild_id not in _active_bridges:
            return json.dumps({"status": "error", "message": f"No active Vapi bridge for guild {guild_id}"})
        bridge_mod = _active_bridges[guild_id].get("bridge_mod")
        br = getattr(bridge_mod, "BRIDGE", None) if bridge_mod else None
        if br and hasattr(br, "stop"):
            await br.stop()
        return json.dumps({"status": "stopped", "guild_id": guild_id})
    # Stop all
    for gid in list(_active_bridges.keys()):
        bridge_mod = _active_bridges[gid].get("bridge_mod")
        br = getattr(bridge_mod, "BRIDGE", None) if bridge_mod else None
        if br and hasattr(br, "stop"):
            await br.stop()
    return json.dumps({"status": "stopped", "message": "All Vapi bridges stopped"})


async def _control_get(path: str) -> str:
    """Fallback — reads from _active_bridges directly, no HTTP."""
    return await _voice_vapi_status_handler()


async def _run_on_gateway_loop(runner, coro):
    loop = getattr(runner, "_gateway_loop", None)
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if loop is None or loop is current_loop or not loop.is_running():
        return await coro
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return await asyncio.wrap_future(future)


def _infer_user_voice_channel(adapter, user_id: str) -> Optional[tuple]:
    client = getattr(adapter, "_client", None)
    if not client:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    for guild in getattr(client, "guilds", []) or []:
        member = guild.get_member(uid)
        if member and member.voice and member.voice.channel:
            return str(guild.id), str(member.voice.channel.id)
    return None


async def voice_vapi(adapter, guild_id: str, channel_id: str) -> str:
    guild_id_int = int(guild_id)

    if _starting.get(guild_id_int):
        return json.dumps({"status": "pending", "message": "Bridge is being started"})

    if guild_id_int in _active_bridges:
        bridge_info = _active_bridges[guild_id_int]
        current_vc = bridge_info.get("vc")
        if current_vc and current_vc.is_connected() and current_vc.channel:
            if str(current_vc.channel.id) == channel_id:
                return json.dumps({"status": "success", "message": "Voice bridge is ready"})
            guild = adapter._client.get_guild(guild_id_int) if hasattr(adapter, "_client") else None
            target = guild.get_channel(int(channel_id)) if guild else None
            if target:
                try:
                    await current_vc.move_to(target)
                    return json.dumps({"status": "success", "message": f"Moved to {target.name}"})
                except Exception as e:
                    return json.dumps({"status": "success", "message": f"Active but couldn't move: {e}"})
        else:
            # Stale entry (vc disconnected but entry remains) — clean up and start fresh
            old_task = bridge_info.get("task")
            if old_task and not old_task.done():
                old_task.cancel()
                try:
                    await asyncio.wait_for(old_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
            _active_bridges.pop(guild_id_int, None)
            _starting.pop(guild_id_int, None)

    if not hasattr(adapter, "_client") or not adapter._client:
        return json.dumps({"status": "error", "message": "Discord client not connected"})

    guild = adapter._client.get_guild(guild_id_int)
    if not guild:
        return json.dumps({"status": "error", "message": f"Guild {guild_id} not found"})

    # Force-disconnect any existing voice client in this guild (prevents Gemini↔Vapi conflicts)
    await _disconnect_any_existing_vc(adapter, guild_id_int)

    channel = guild.get_channel(int(channel_id))
    if not channel:
        return json.dumps({"status": "error", "message": f"Channel {channel_id} not found"})

    _starting[guild_id_int] = True
    try:
        import importlib.util
        bridge_path = PLUGIN_DIR / "bridge.py"
        spec = importlib.util.spec_from_file_location("discord_vapi_bridge", bridge_path)
        bridge_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge_mod)

        loop = asyncio.get_running_loop()
        ready_future = loop.create_future()
        bridge_task = asyncio.create_task(bridge_mod.run_sidecar(channel, adapter, ready_future))
        bridge_task.add_done_callback(
            lambda _task, _gid=guild_id_int: _active_bridges.pop(_gid, None)
        )
        _active_bridges[guild_id_int] = {
            "vc": None,
            "adapter": adapter,
            "task": bridge_task,
            "bridge_mod": bridge_mod,
        }

        try:
            ready = await asyncio.wait_for(ready_future, timeout=120.0)
        except asyncio.TimeoutError:
            bridge_task.cancel()
            return json.dumps({"status": "error", "message": "Timed out waiting for bridge"})

        if not ready.get("ok"):
            bridge_task.cancel()
            return json.dumps({"status": "error", "message": ready.get("message", "Bridge failed")})

        _active_bridges[guild_id_int]["vc"] = ready.get("vc")

        return json.dumps({
            "status": "success",
            "message": f"Vapi voice bridge started in {channel.name}",
            "health": ready.get("health", {}),
        })
    except Exception as e:
        logger.error("Failed to start Vapi bridge: %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Failed: {e}"})
    finally:
        _starting.pop(guild_id_int, None)


async def voice_vapi_leave(guild_id: str) -> str:
    guild_id_int = int(guild_id)
    bridge = _active_bridges.pop(guild_id_int, None)
    if not bridge:
        return json.dumps({"status": "error", "message": "No active Vapi voice bridge"})
    try:
        bridge["task"].cancel()
        try:
            await asyncio.wait_for(bridge["task"], timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        vc = bridge["vc"]
        if vc and vc.is_connected():
            try:
                await asyncio.wait_for(vc.disconnect(force=True), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        return json.dumps({"status": "success", "message": "Vapi voice bridge stopped."})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error: {e}"})


# ---------------------------------------------------------------------------
# Autostart support — mirrors the discord-voice plugin pattern so the
# `voice-vapi-autostart.json` file at ~/.hermes/ is honored on gateway boot.
# ---------------------------------------------------------------------------

KEEP_AUTOSTART_FILE = os.getenv("DISCORD_VAPI_KEEP_AUTOSTART_FILE", "0").lower() in {"1", "true", "yes"}


async def _autostart_voice_vapi() -> None:
    deadline = time.monotonic() + 180.0
    last_error = ""
    while time.monotonic() < deadline:
        try:
            params = {}
            if AUTOSTART_FILE.exists():
                try:
                    params = json.loads(AUTOSTART_FILE.read_text())
                except Exception:
                    pass
            import gateway.run as gateway_run
            from gateway.platforms.base import Platform
            runner = None
            ref = getattr(gateway_run, "_gateway_runner_ref", None)
            if callable(ref):
                runner = ref()
            adapter = runner.adapters.get(Platform("discord")) if runner else None
            if not adapter:
                last_error = "Discord adapter not ready"
                await asyncio.sleep(2.0)
                continue
            guild_id = params.get("guild_id") or DEFAULT_GUILD_ID
            channel_id = params.get("channel_id") or DEFAULT_CHANNEL_ID
            user_id = str(params.get("user_id") or DEFAULT_USER_ID)
            if not guild_id or not channel_id:
                inferred = _infer_user_voice_channel(adapter, user_id)
                if inferred:
                    guild_id = str(inferred[0])
                    channel_id = str(inferred[1])
            if not guild_id or not channel_id:
                last_error = "Target voice channel not found"
                await asyncio.sleep(10.0)
                continue

            result = json.loads(await voice_vapi(adapter, str(guild_id), str(channel_id)))
            if result.get("status") == "success":
                if not KEEP_AUTOSTART_FILE:
                    try:
                        AUTOSTART_FILE.unlink(missing_ok=True)
                    except Exception:
                        pass
                return
            if result.get("status") == "pending":
                await asyncio.sleep(5.0)
                continue
            last_error = result.get("message", str(result))
        except Exception as exc:
            last_error = str(exc)
            logger.warning("voice-vapi autostart failed: %s", exc)
        await asyncio.sleep(5.0)
    logger.error("voice-vapi autostart gave up: %s", last_error)


_autostart_thread_started = False


def _schedule_autostart_thread() -> None:
    global _autostart_thread_started
    if _autostart_thread_started:
        return
    _autostart_thread_started = True

    def _thread_main():
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            try:
                import gateway.run as gateway_run
                ref = getattr(gateway_run, "_gateway_runner_ref", None)
                runner = ref() if callable(ref) else None
                loop = getattr(runner, "_gateway_loop", None) if runner else None
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(_autostart_voice_vapi(), loop)
                    future.result(timeout=185.0)
                    return
            except Exception:
                pass
            time.sleep(1.0)

    thread = threading.Thread(target=_thread_main, name="voice-vapi-autostart", daemon=True)
    thread.start()
