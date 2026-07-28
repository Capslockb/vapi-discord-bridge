#!/usr/bin/env python3
"""Run the public-document scanner with community-health filenames enabled."""
from __future__ import annotations

import sys
from pathlib import Path

import public_docs_safety


COMMUNITY_DOC_NAMES = {"support.md", "governance.md"}
ENFORCED_COMMUNITY_DOC_NAMES = {
    "SUPPORT.md",
    "Support.md",
    "support.md",
    "GOVERNANCE.md",
    "Governance.md",
    "governance.md",
}
_ORIGINAL_IS_PUBLIC_DOC = public_docs_safety.is_public_doc


def _is_public_doc_with_enforceable_community_case(
    path: str,
    include_fixtures: bool = False,
) -> bool:
    name = Path(path).name
    if name.lower() in COMMUNITY_DOC_NAMES and name not in ENFORCED_COMMUNITY_DOC_NAMES:
        return False
    return _ORIGINAL_IS_PUBLIC_DOC(path, include_fixtures)


public_docs_safety.DOC_NAMES.update(COMMUNITY_DOC_NAMES)
public_docs_safety.is_public_doc = _is_public_doc_with_enforceable_community_case


if __name__ == "__main__":
    sys.exit(public_docs_safety.main())
