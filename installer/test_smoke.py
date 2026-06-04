#!/usr/bin/env python3
"""Smoke test the Vapi installer with --yes support."""
import importlib.util, os, shutil, sys, tempfile
from pathlib import Path

sandbox = Path(tempfile.mkdtemp(prefix="vapi-installer-test-"))
hermes_home = sandbox / "hermes"
plugin_dir = hermes_home / "plugins"
(plugin_dir / "discord-vapi").mkdir(parents=True, exist_ok=True)
(hermes_home / "hermes-agent" / "venv" / "bin").mkdir(parents=True, exist_ok=True)
(hermes_home / "config.yaml").write_text("gateway:\n  enabled: false\n")
(hermes_home / "hermes-agent" / "venv" / "bin" / "python").write_text("#!/bin/sh\necho mock\n")
os.chmod(hermes_home / "hermes-agent" / "venv" / "bin" / "python", 0o755)
os.environ["HERMES_HOME"] = str(hermes_home)

repo = Path.home() / "code" / "voice-bridges" / "vapi-discord-bridge"
sys.path.insert(0, str(repo / "installer"))
spec = importlib.util.spec_from_file_location("install", repo / "installer" / "install.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["install"] = mod
spec.loader.exec_module(mod)

# Pre-create .env to avoid interactive confirm
(hermes_home / ".env").write_text("# fresh\n")

print("=== Test: --yes auto-mode ===")
ui = mod.UI(auto_yes=True)
assert ui.auto_yes is True
assert ui.confirm("test?") == True
assert ui.confirm("test?", default=False) == False
assert ui.menu("pick?", [("a","opt A"),("b","opt B")]) == "a"
assert ui.prompt("name?", default="foo") == "foo"
print("  ✓ auto_yes works: all prompts return defaults without blocking")

print("\n=== Test: preflight ===")
pre = mod.step_preflight(mod.UI(auto_yes=True))
assert pre["hermes_home"] == hermes_home
print("  ✓ preflight")

print("\n=== Test: env write (fresh .env) ===")
keys = {"DISCORD_BOT_TOKEN": "bt", "VAPI_API_KEY": "vk", "VAPI_MODEL": "gpt-4o-mini"}
env_info = mod.step_write_env(mod.UI(auto_yes=True), keys, pre)
assert env_info["path"] is not None
content = env_info["path"].read_text()
assert "bt" in content and "vk" in content
print(f"  ✓ env write with --yes (no prompt)")

print("\n=== Test: deploy ===")
target = plugin_dir / "discord-vapi"
info = mod.step_deploy(mod.UI(auto_yes=True), {"mode": "copy", "target": target, "plugins_dir": plugin_dir}, repo)
assert target.exists()
assert (target / "bridge.py").exists()
print(f"  ✓ deploy: {len(list(target.glob('*')))} files")

shutil.rmtree(sandbox)
print(f"\n✅ VAPI WITH --YES: ALL PASSED")
