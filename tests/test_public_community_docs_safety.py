from __future__ import annotations

import sys
import unittest
from pathlib import Path

scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts_dir))

import public_community_docs_safety
import public_docs_safety


class CommunityDocumentTests(unittest.TestCase):
    def test_enforced_document_case_variants_are_in_scope(self) -> None:
        names = (
            "SUPPORT.md",
            "Support.md",
            "support.md",
            "GOVERNANCE.md",
            "Governance.md",
            "governance.md",
        )
        roots = ("", ".github/", "docs/")
        for root in roots:
            for name in names:
                path = f"{root}{name}"
                with self.subTest(path=path):
                    self.assertTrue(public_docs_safety.is_public_doc(path))

    def test_unenforceable_mixed_case_variants_are_out_of_scope(self) -> None:
        for path in ("SuPpOrT.md", ".github/GoVeRnAnCe.md"):
            with self.subTest(path=path):
                self.assertFalse(public_docs_safety.is_public_doc(path))

    def test_workflow_and_codeowners_cover_enforced_case_variants(self) -> None:
        workflow = Path(".github/workflows/public-docs-safety.yml").read_text(
            encoding="utf-8"
        )
        codeowners = Path(".github/CODEOWNERS").read_text(encoding="utf-8")
        names = (
            "SUPPORT.md",
            "Support.md",
            "support.md",
            "GOVERNANCE.md",
            "Governance.md",
            "governance.md",
        )
        roots = ("", "docs/", ".github/")
        for root in roots:
            for name in names:
                path = f"{root}{name}"
                with self.subTest(path=path):
                    self.assertIn(path, workflow)
                    self.assertIn(f"/{path}", codeowners)


if __name__ == "__main__":
    unittest.main()
