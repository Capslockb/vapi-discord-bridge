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
from collections.abc import Iterable, Iterator
from html.parser import HTMLParser
from pathlib import Path

DOC_NAMES = {
    "readme",
    "readme.md",
    "security.md",
    "contributing.md",
    "code_of_conduct.md",
    "agents.md",
}
DOC_DIR_PARTS = {"docs", "doc", "website", "site", "public"}
DOC_EXTS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".html",
    ".htm",
    ".adoc",
    ".asciidoc",
}
EXCLUDE_PARTS = {
    ".git",
    "i18n",
    "node_modules",
    "sessions",
    "vendor",
}
EXCLUDE_NAMES = {"changelog.md"}
PROTECTED_EXACT = {
    ".github/codeowners",
    ".github/pull_request_template.md",
}
PROTECTED_PREFIXES = (
    ".github/pull_request_template/",
    ".github/issue_template/",
)
FIXTURE_PREFIX = "tests/fixtures/public-docs/"
MAX_WINDOW_LINES = 3

PATTERNS = [
    (
        "PDS001",
        "model-directed-override",
        re.compile(
            r"(?i)\b(ignore|disregard|override)\b.{0,100}"
            r"\b(previous|above|system|developer|policy|instruction)s?\b"
        ),
    ),
    (
        "PDS002",
        "secret-or-policy-exfiltration",
        re.compile(
            r"(?i)\b(reveal|print|show|exfiltrate|leak)\b.{0,100}"
            r"\b(secret|token|credential|password|policy|system prompt|developer message)s?\b"
        ),
    ),
    (
        "PDS003",
        "unauthorized-action-request",
        re.compile(
            r"(?i)\b(approve|merge|push|deploy|purchase|transfer|delete|rotate|disable)\b"
            r".{0,100}\b(PR|pull request|repository|repo|payment|account|guard|check|policy|automation)\b"
        ),
    ),
    (
        "PDS004",
        "non-public-automation-disclosure",
        re.compile(
            r"(?i)\b(privileged command|private control|non-public guard|secret marker|"
            r"trusted[- ]identity rule|mutation authorization|worker queue|"
            r"controller lease|private escalation)\b"
        ),
    ),
]

UNCERTAIN = re.compile(
    r"(?i)\b(maintaining model|automation agent|autonomous maintainer|repository bot)\b"
    r".{0,100}\b(must|shall|required to|always|never|use tool|run command|obey|"
    r"ignore|stop when|final status)\b"
)
BENIGN_UNCERTAIN = re.compile(
    r"(?i)\b(example|sample|template|user-facing|configuration|API|worker thread|"
    r"service worker|inference|event loop|model name|route|provider|guardrail|"
    r"security policy|documentation)\b"
)

Finding = tuple[str, int, str, str]
Line = tuple[int, str]
Record = list[Line]

_MARKDOWN_FENCE = re.compile(r"^\s*(```+|~~~+)")
_MARKUP_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s+|={1,6}\s+|\.\.\s+\S|:[A-Za-z0-9_-]+:)"
)
_MARKUP_LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_MARKUP_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_MARKUP_TABLE = re.compile(r"^\s*(?:\|.*\||\+[-+=+]+\+)\s*$")
_HTML_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "html",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}


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
    normalized = candidate.as_posix()
    normalized_lower = normalized.lower()
    lower_parts = {part.lower() for part in candidate.parts}
    name_lower = candidate.name.lower()

    if lower_parts & EXCLUDE_PARTS or name_lower in EXCLUDE_NAMES:
        return False
    if include_fixtures and normalized_lower.startswith(FIXTURE_PREFIX):
        return candidate.suffix.lower() in DOC_EXTS
    if normalized_lower in PROTECTED_EXACT:
        return True
    if any(normalized_lower.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return candidate.suffix.lower() in DOC_EXTS
    return name_lower in DOC_NAMES or (
        candidate.suffix.lower() in DOC_EXTS
        and bool(lower_parts & DOC_DIR_PARTS)
    )


def changed_files() -> list[str]:
    if not ensure_push_base_available():
        return [str(path) for path in Path(".").rglob("*") if path.is_file()]

    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", diff_range()],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode == 0:
        return [line for line in proc.stdout.splitlines() if line]

    if not os.environ.get("GITHUB_ACTIONS"):
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "--cached"],
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
    if proc.returncode != 0:
        return None
    if not proc.stdout.strip():
        return {}

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


def _flush_record(records: list[Record], current: Record) -> Record:
    if current:
        records.append(current)
    return []


def _paragraph_records(lines: list[str]) -> list[Record]:
    records: list[Record] = []
    current: Record = []
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            current = _flush_record(records, current)
            continue
        current.append((number, text))
    _flush_record(records, current)
    return records


def _line_records(lines: list[str]) -> list[Record]:
    return [[(number, text)] for number, text in enumerate(lines, start=1) if text.strip()]


def _markup_records(lines: list[str]) -> list[Record]:
    """Split Markdown, RST, and AsciiDoc into structural records."""
    records: list[Record] = []
    current: Record = []
    fence_marker: str | None = None
    current_kind = "paragraph"

    for number, text in enumerate(lines, start=1):
        stripped = text.strip()
        if not stripped:
            current = _flush_record(records, current)
            current_kind = "paragraph"
            continue

        fence = _MARKDOWN_FENCE.match(text)
        if fence_marker:
            current.append((number, text))
            if fence and fence.group(1).startswith(fence_marker):
                current = _flush_record(records, current)
                fence_marker = None
                current_kind = "paragraph"
            continue
        if fence:
            current = _flush_record(records, current)
            fence_marker = fence.group(1)[:3]
            current = [(number, text)]
            current_kind = "fence"
            continue

        is_heading = bool(_MARKUP_HEADING.match(text))
        is_rule = bool(_MARKUP_RULE.match(text))
        is_list = bool(_MARKUP_LIST.match(text))
        is_quote = stripped.startswith(">")
        is_table = bool(_MARKUP_TABLE.match(text))

        if is_heading or is_rule:
            current = _flush_record(records, current)
            records.append([(number, text)])
            current_kind = "paragraph"
            continue

        if is_list:
            current = _flush_record(records, current)
            current = [(number, text)]
            current_kind = "list"
            continue

        if is_quote:
            if current_kind != "quote":
                current = _flush_record(records, current)
                current_kind = "quote"
            current.append((number, text))
            continue

        if is_table:
            if current_kind != "table":
                current = _flush_record(records, current)
                current_kind = "table"
            current.append((number, text))
            continue

        if current_kind in {"quote", "table"}:
            current = _flush_record(records, current)
            current_kind = "paragraph"

        current.append((number, text))

    _flush_record(records, current)
    return records


class _HTMLRecordParser(HTMLParser):
    """Collect text into block-aware records while preserving source line numbers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[Record] = []
        self.current: Record = []

    def _flush(self) -> None:
        if self.current:
            self.records.append(self.current)
            self.current = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _HTML_BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _HTML_BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _HTML_BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        start_line = self.getpos()[0]
        for offset, text in enumerate(data.splitlines()):
            if text.strip():
                self.current.append((start_line + offset, text))

    def close(self) -> None:
        super().close()
        self._flush()


def _html_records(raw_text: str) -> list[Record]:
    parser = _HTMLRecordParser()
    parser.feed(raw_text)
    parser.close()
    return parser.records


def structural_records(path: str, raw_text: str) -> list[Record]:
    candidate = Path(path)
    normalized = candidate.as_posix().lower()
    lines = raw_text.splitlines()

    if normalized == ".github/codeowners":
        return _line_records(lines)
    if candidate.suffix.lower() in {".html", ".htm"}:
        return _html_records(raw_text)
    if candidate.suffix.lower() in {".md", ".mdx", ".rst", ".adoc", ".asciidoc"}:
        return _markup_records(lines)
    if candidate.name.lower() in DOC_NAMES:
        return _markup_records(lines)
    return _paragraph_records(lines)


def _bounded_windows(
    records: list[Record],
    targets: set[int],
) -> Iterator[tuple[int, str]]:
    """Yield one-to-three-line windows within one structural record."""
    for record in records:
        for start_index in range(len(record)):
            max_stop = min(len(record), start_index + MAX_WINDOW_LINES)
            for stop_index in range(start_index + 1, max_stop + 1):
                window_lines = record[start_index:stop_index]
                changed = sorted(
                    line_number
                    for line_number, _ in window_lines
                    if line_number in targets
                )
                if not changed:
                    continue
                yield changed[0], " ".join(text for _, text in window_lines)


def scan_file(
    path: str,
    line_numbers: Iterable[int] | None,
) -> list[Finding]:
    try:
        raw_text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [(path, 1, "PDS900", "read-failure")]

    lines = raw_text.splitlines()
    if line_numbers is None:
        targets = set(range(1, len(lines) + 1))
    else:
        targets = {line for line in line_numbers if 1 <= line <= len(lines)}
    if not targets:
        return []

    findings: set[Finding] = set()
    for report_line, window in _bounded_windows(
        structural_records(path, raw_text),
        targets,
    ):
        for rule_id, category, pattern in PATTERNS:
            if pattern.search(window):
                findings.add((path, report_line, rule_id, category))

        if UNCERTAIN.search(window) and not BENIGN_UNCERTAIN.search(window):
            findings.add(
                (
                    path,
                    report_line,
                    "PDS005",
                    "possible-model-directed-instruction",
                )
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
        line_numbers = (
            None
            if added_lines is None
            else sorted(added_lines.get(path, set()))
        )
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
