from __future__ import annotations

import sys
import unittest
from pathlib import Path

scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts_dir))

import public_community_docs_safety
import public_docs_safety


class CommunityDocumentTests(unittest.TestCase):
    def test_document_case_variants_are_in_scope(self) -> None:
        paths = (
            "SUPPORT.md",
            "SuPpOrT.md",
            "support.MD",
            "GOVERNANCE.md",
            "GoVeRnAnCe.md",
            "governance.MD",
            ".github/SuPpOrT.md",
            ".github/GoVeRnAnCe.MD",
            "docs/sUpPoRt.Md",
            "docs/gOvErNaNcE.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(public_docs_safety.is_public_doc(path))

    def test_workflow_uses_broad_enforceable_push_patterns(self) -> None:
        workflow = Path(".github/workflows/public-docs-safety.yml").read_text(
            encoding="utf-8"
        )
        for pattern in ("- '*'", "- .github/**", "- docs/**"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, workflow)

    def test_codeowners_uses_broad_enforceable_patterns(self) -> None:
        codeowners = Path(".github/CODEOWNERS").read_text(encoding="utf-8")
        for pattern in (
            "/* @Capslockb",
            "/.github/** @Capslockb",
            "/docs/** @Capslockb",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, codeowners)


if __name__ == "__main__":
    unittest.main()
