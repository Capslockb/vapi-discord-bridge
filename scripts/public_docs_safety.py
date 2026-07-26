#!/usr/bin/env python3
"""Fail closed on suspicious additions to public documentation.

Diagnostics intentionally contain only a path, line number, stable rule ID, and
category. Matched repository text is never copied into CI output.
"""
from __future__ import annotations

import argparse
import bisect
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


def push_base_sha() -> str | None:
    value = os.environ.get("GITHUB_EVENT_BEFORE", "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return None
    if set(value) == {"0"}:
        return None
    return value.lower()


def diff_range() -> str:
    before = push_base_sha()
    if before:
        return f"{before}..HEAD"
    return f"origin/{default_branch()}...HEAD"


def ensure_push_base_available() -> bool:
    before = push_base_sha()
    if not before:
        return True
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{before}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode == 0:
        return True
    fetch = subprocess.run(
        ["git", "fetch", "--no-tags", "origin", before],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if fetch.returncode != 0:
        return False
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{before}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return check.returncode == 0


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
    if not ensure_push_base_available():
        return [str(path) for path in Path(".").rglob("*") if path.is_file()]

    proc = subprocess.run(
        ["git", "diff", "--name-only", diff_range()],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode == 0:
        return [line for line in proc.stdout.splitlines() if line]

    if not os.environ.get("GITHUB_ACTIONS"):
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
    if not ensure_push_base_available():
        return None

    proc = subprocess.run(
        ["git", "diff", "--unified=0", diff_range(), "--", *files],
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


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def scan_file(path: str, line_numbers: list[int] | range) -> list[Finding]:
    try:
        raw_text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [(path, 1, "PDS900", "read-failure")]

    lines = raw_text.splitlines()
    targets = {line for line in line_numbers if 1 <= line <= len(lines)}
    if not targets:
        return []

    normalized = raw_text.replace("\n", " ")
    starts = _line_starts(raw_text)
    findings: set[Finding] = set()

    def record_matches(pattern: re.Pattern[str], rule_id: str, category: str) -> None:
        for match in pattern.finditer(normalized):
            start_line = _line_for_offset(starts, match.start())
            end_offset = max(match.start(), match.end() - 1)
            end_line = _line_for_offset(starts, end_offset)
            changed_lines = sorted(
                line for line in targets if start_line <= line <= end_line
            )
            if changed_lines:
                findings.add((path, changed_lines[0], rule_id, category))

    for rule_id, category, pattern in PATTERNS:
        record_matches(pattern, rule_id, category)

    for match in UNCERTAIN.finditer(normalized):
        start_line = _line_for_offset(starts, match.start())
        end_offset = max(match.start(), match.end() - 1)
        end_line = _line_for_offset(starts, end_offset)
        changed_lines = sorted(
            line for line in targets if start_line <= line <= end_line
        )
        if not changed_lines:
            continue
        context_start = starts[start_line - 1]
        context_end = starts[end_line] if end_line < len(starts) else len(normalized)
        if not BENIGN_UNCERTAIN.search(normalized[context_start:context_end]):
            findings.add(
                (path, changed_lines[0], "PDS005", "possible-model-directed-instruction")
            )

    return sorted(findings, key=lambda finding: (finding[1], finding[2], finding[3]))


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
