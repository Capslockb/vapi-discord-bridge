#!/usr/bin/env python3
"""Compatibility launcher for the plugin-owned post-call summary helper."""

from __future__ import annotations

import runpy
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / "plugin" / "post_call_summary.py"


if __name__ == "__main__":
    runpy.run_path(str(HELPER), run_name="__main__")
