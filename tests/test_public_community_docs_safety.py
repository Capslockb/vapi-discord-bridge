from __future__ import annotations

import sys
import unittest
from pathlib import Path

scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts_dir))

import public_community_docs_safety
import public_docs_safety


class CommunityDocumentTests(unittest.TestCase):
    def test_named_documents_are_in_scope(self) -> None:
        paths = (
            "SUPPORT.md",
            "GOVERNANCE.md",
            ".github/SUPPORT.md",
            ".github/GOVERNANCE.md",
            "docs/SUPPORT.md",
            "docs/GOVERNANCE.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(public_docs_safety.is_public_doc(path))


if __name__ == "__main__":
    unittest.main()
