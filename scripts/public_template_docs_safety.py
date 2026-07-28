#!/usr/bin/env python3
"""Scan public pull-request templates that live outside the core .github paths."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import public_docs_safety as core

_TEMPLATE_DIR = "pull_request_template"
_ALLOWED_ROOTS: tuple[tuple[str, ...], ...] = ((), ("docs",), (".github",))


def is_public_pr_template(path: str) -> bool:
    """Return whether path is a supported public pull-request template."""
    candidate = Path(path)
    parts = tuple(part.lower() for part in candidate.parts)
    if not parts or set(parts) & core.EXCLUDE_PARTS:
        return False
    if candidate.suffix.lower() not in core.DOC_EXTS:
        return False

    parent = parts[:-1]
    if Path(parts[-1]).stem == _TEMPLATE_DIR and parent in _ALLOWED_ROOTS:
        return True

    for root in _ALLOWED_ROOTS:
        prefix = root + (_TEMPLATE_DIR,)
        if len(parts) > len(prefix) and parts[: len(prefix)] == prefix:
            return True
    return False


def _all_templates() -> list[str]:
    return sorted(
        str(path)
        for path in Path(".").rglob("*")
        if path.is_file() and is_public_pr_template(str(path))
    )


def changed_selection() -> tuple[list[str], set[str]]:
    """Return changed templates and templates requiring a complete scan."""
    status_lines = core._diff_name_status()
    if status_lines is None:
        templates = _all_templates()
        return templates, set(templates)

    selected: set[str] = set()
    precedence_changed = False
    for row in status_lines:
        fields = row.split("\t")
        status = fields[0]
        code = status[:1]
        old_path: str | None = None
        new_path: str | None = None

        if code in {"R", "C"} and len(fields) >= 3:
            old_path, new_path = fields[1], fields[2]
        elif len(fields) >= 2:
            new_path = fields[1]
            if code == "D":
                old_path, new_path = new_path, None

        if new_path and Path(new_path).is_file() and is_public_pr_template(new_path):
            selected.add(new_path)
        if code in {"D", "R"} and old_path and is_public_pr_template(old_path):
            precedence_changed = True

    full_scan: set[str] = set()
    if precedence_changed:
        remaining = _all_templates()
        selected.update(remaining)
        full_scan.update(remaining)
    return sorted(selected), full_scan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        files = _all_templates()
        full_scan = set(files)
    else:
        files, full_scan = changed_selection()

    added_lines = None if args.all else core.changed_added_lines(files)
    findings: list[core.Finding] = []
    for path in files:
        line_numbers = (
            None
            if added_lines is None or path in full_scan
            else sorted(added_lines.get(path, set()))
        )
        findings.extend(core.scan_file(path, line_numbers))

    if findings:
        print("public-docs-safety: FAIL")
        for path, line_number, rule_id, category in findings:
            print(f"{path}:{line_number}: {rule_id} {category}")
        return 1

    print("public-docs-safety: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
