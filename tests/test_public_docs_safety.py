import subprocess
import sys
import unittest
from pathlib import Path


class PublicDocsSafetyTests(unittest.TestCase):
    def test_adversarial_fixture_is_flagged_without_echoing_content(self) -> None:
        script = Path("scripts/public_docs_safety.py")
        fixture = Path("tests/fixtures/public-docs/false-privileged-instructions.md")
        self.assertTrue(script.exists())
        self.assertTrue(fixture.exists())

        result = subprocess.run(
            [sys.executable, str(script), "--all", "--include-test-fixtures"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        output = result.stdout
        self.assertIn(str(fixture), output)
        self.assertRegex(output, r"PDS00[1-5]")
        self.assertNotIn("Ignore previous policy", output)
        self.assertNotIn("expose a secret", output)
        self.assertNotIn("external purchase", output)


if __name__ == "__main__":
    unittest.main()
