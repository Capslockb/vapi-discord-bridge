#!/usr/bin/env python3
"""Fail closed on suspicious additions to public documentation.

Diagnostics intentionally contain only a path, line number, stable rule ID, and
category. Matched repository text is never copied into CI output.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DOC_NAMES = {"README.md", "SECURITY.md", "CONTRIBUTING.md", "AGENTS.md"}
DOC_DIR_PARTS = {"docs", "doc", "website", "site", "public"}
FIXTURE_PARTS = {"tests", "fixtures", "public-docs"}
DOC_EXTS = {".md", ".mdx", ".rst", ".txt"}
EXCLUDE_PARTS = {"i18n", "CHANGELOG.md", "sessions", "vendor", "node_modules", ".git"}

PATTERNS = [
    (
        "PDS001",
        "model-directed-override",
        re.compile(r"(?i)\b(ignore|disregard|override)\b.{0,100}\b(previous|above|system|developer|policy|instruction)s?\b"),
    ),
    (
        "PDS002",
        "secret-or-policy-exfiltration",
        re.compile(r"(?i)\b(reveal|print|show|exfiltrate|leak)\b.{0,100}\b(secret|token|credential|password|policy|system prompt|developer message)s?\b"),
    ),
    (
        "PDS003",
        "unauthorized-action-request",
        re.compile(r"(?i)\b(approve|merge|push|deploy|purchase|transfer|delete|rotate|disable)\b.{0,100}\b(PR|pull request|repository|repo|payment|account|guard|check|policy|automation)\b"),
    ),
    (
        "PDS004",
        "non-public-automation-disclosure",
        re.compile(r"(?i)\b(privileged command|private control|non-public guard|secret marker|trusted[- ]identity rule|mutation authorization|worker queue|controller lease|private escalation)\b"),
    ),
]

UNCERTAIN = re.compile(
    r"(?i)\b(maintaining model|automation agent|autonomous maintainer|repository bot)\b.{0,100}\b(must|shall|required to|always|never|use tool|run command|obey|ignore|stop when|final status)\b"
)
BENIGN_UNCERTAIN = re.compile(
    r"(?i)\b(example|sample|template|user-facing|configuration|API|worker thread|service worker|inference|event loop|model name|route|provider|guardrail|security policy|documentation)\b"
)

Finding = tuple[str, int, str, str]


def default_branch() -> str:
    explicit = os.environ.get("GITHUB_BASE_REF") or os.environ.get("DEFAULT_BRANCH")
    if explicit:
        return explicit
    proc = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode == 0 and "/" in proc.stdout:
        return proc.stdout.strip().rsplit("/", 1)[-1]
    return "main"


def is_public_doc(path: str, include_fixtures: bool = False) -> bool:
    candidate = Path(path)
    parts = set(candidate.parts)
    if parts & EXCLUDE_PARTS:
        return False
    if include_fixtures and FIXTURE_PARTS <= parts and candidate.suffix.lower() in DOC_EXTS:
        return True
    return candidate.name in DOC_NAMES or (
        candidate.suffix.lower() in DOC_EXTS and bool(parts & DOC_DIR_PARTS)
    )


def changed_files() -> list[str]:
    base = default_branch()
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base}...HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode == 0:
        return [line for line in proc.stdout.splitlines() if line]

    proc = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode == 0:
        return [line for line in proc.stdout.splitlines() if line]

    return [str(path) for path in Path(".").rglob("*") if path.is_file()]


def changed_added_lines(files: list[str]) -> dict[str, set[int]] | None:
    if not files:
        return {}
    base = default_branch()
    proc = subprocess.run(
        ["git", "diff", "--unified=0", f"origin/{base}...HEAD", "--", *files],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    output: dict[str, set[int]] = {}
    current_path: str | None = None
    new_line: int | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            output.setdefault(current_path, set())
        elif line.startswith("@@") and current_path:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                new_line = int(match.group(1))
        elif current_path and new_line is not None:
            if line.startswith("+") and not line.startswith("+++"):
                output.setdefault(current_path, set()).add(new_line)
                new_line += 1
            elif not line.startswith("-"):
                new_line += 1
    return output


def scan_file(path: str, line_numbers: list[int] | range) -> list[Finding]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return [(path, 1, "PDS900", "read-failure")]

    findings: list[Finding] = []
    for line_number in line_numbers:
        if line_number < 1 or line_number > len(lines):
            continue
        line = lines[line_number - 1]

        for rule_id, category, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((path, line_number, rule_id, category))

        if UNCERTAIN.search(line) and not BENIGN_UNCERTAIN.search(line):
            findings.append((path, line_number, "PDS005", "possible-model-directed-instruction"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--include-test-fixtures", action="store_true")
    args = parser.parse_args()

    include_fixtures = args.include_test_fixtures or args.all
    candidates = (
        [str(path) for path in Path(".").rglob("*") if path.is_file()]
        if args.all
        else changed_files()
    )
    files = [path for path in candidates if is_public_doc(path, include_fixtures)]
    added_lines = None if args.all else changed_added_lines(files)

    findings: list[Finding] = []
    for path in files:
        if added_lines is None:
            total = len(Path(path).read_text(encoding="utf-8", errors="ignore").splitlines())
            line_numbers: list[int] | range = range(1, total + 1)
        else:
            line_numbers = sorted(added_lines.get(path, set()))
        findings.extend(scan_file(path, line_numbers))

    if findings:
        print("public-docs-safety: FAIL")
        for path, line_number, rule_id, category in findings:
            print(f"{path}:{line_number}: {rule_id} {category}")
        return 1

    print("public-docs-safety: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
