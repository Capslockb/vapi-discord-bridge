#!/usr/bin/env python3
"""Run the public-document scanner with community-health filenames enabled."""
from __future__ import annotations

import sys

import public_docs_safety


COMMUNITY_DOC_NAMES = {"support.md", "governance.md"}
public_docs_safety.DOC_NAMES.update(COMMUNITY_DOC_NAMES)


if __name__ == "__main__":
    sys.exit(public_docs_safety.main())
