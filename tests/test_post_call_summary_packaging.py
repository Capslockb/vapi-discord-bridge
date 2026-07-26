from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_HELPER = REPO_ROOT / "plugin" / "post_call_summary.py"
COMPAT_LAUNCHER = REPO_ROOT / "scripts" / "post_call_summary.py"


class PostCallSummaryPackagingTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> Path:
        transcript = root / "voice-vapi-test.jsonl"
        events = [
            {"type": "transcript", "speaker": "user", "text": "Please send the report."},
            {"type": "transcript", "speaker": "assistant", "text": "We agreed to follow up later."},
        ]
        transcript.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        return transcript

    def _run_json(self, helper: Path, transcript: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, str(helper), "--file", str(transcript), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout)

    def test_plugin_helper_runs_from_an_isolated_copy_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed_plugin = root / "discord-vapi"
            installed_plugin.mkdir()
            installed_helper = installed_plugin / "post_call_summary.py"
            shutil.copy2(PLUGIN_HELPER, installed_helper)
            transcript = self._write_fixture(root)

            payload = self._run_json(installed_helper, transcript)

            self.assertEqual(len(payload["turns"]), 2)
            self.assertIn("Please send the report.", payload["tasks"])
            self.assertIn("We agreed to follow up later.", payload["decisions"])
            self.assertIn("We agreed to follow up later.", payload["followups"])

    def test_repository_launcher_delegates_to_plugin_owned_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self._write_fixture(Path(tmp))

            packaged = self._run_json(PLUGIN_HELPER, transcript)
            compatibility = self._run_json(COMPAT_LAUNCHER, transcript)

            self.assertEqual(compatibility, packaged)


if __name__ == "__main__":
    unittest.main()
