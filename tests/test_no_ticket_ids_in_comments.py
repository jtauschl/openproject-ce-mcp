"""Code comments and docstrings carry the reason, not a tracker id: an id
says nothing to a reader without tracker access and goes stale when the
ticket is closed or renumbered. They also name no private source: a review
round, an AI tool as the author of a finding, a dated verification, a local
mirror of the upstream source or a process document the reader cannot open.
String literals are data and stay allowed."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TICKET_ID = re.compile(r"\bOPM-\d+")


def _python_files() -> list[Path]:
    return sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")])


def _comments_and_docstrings(source: str) -> list[tuple[int, str]]:
    found = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            docstring = ast.get_docstring(node, clean=False)
            if docstring is not None:
                found.append((node.body[0].lineno, docstring))
    return found


def test_no_tracker_ids_in_comments_or_docstrings() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in _python_files()
        for line, text in _comments_and_docstrings(path.read_text(encoding="utf-8"))
        if _TICKET_ID.search(text)
    ]
    assert offenders == []


def test_the_check_sees_comments_and_docstrings() -> None:
    sample = '"""Module OPM-1."""\n\n\ndef f():\n    """Doc OPM-2."""\n    return "OPM-3"  # note OPM-4\n'
    texts = [text for _, text in _comments_and_docstrings(sample)]
    assert sum(bool(_TICKET_ID.search(text)) for text in texts) == 3


# Text that points at something a reader of the public tree cannot open or that dates the comment.
_PRIVATE_SOURCES = {
    "a review round or an AI tool as the author of a finding": re.compile(
        r"\b(Codex|Claude|Copilot|ChatGPT|Gemini)\b[^\n]{0,40}\b(review|caught|found|wrote|round)\b"
        r"|\b(review|round)\b[^\n]{0,30}\b(Codex|Claude)\b|\b\d(st|nd|rd|th)[- ]round\b|\bround[- ]\d+\b|\breview rounds?\b|\bstep[- ]\d+(\.\d+)?\b[^\n]{0,10}\breview",
        re.IGNORECASE,
    ),
    "a dated or session-stamped verification": re.compile(
        r"\b(verified|checked|confirmed)\b[^\n]{0,40}\b20\d\d-\d\d-\d\d|\blive[- ]verified\b", re.IGNORECASE
    ),
    "a local mirror of the upstream source as evidence": re.compile(r"\bop-sources\b", re.IGNORECASE),
    "a process document the reader cannot open": re.compile(
        r"\bRELEASE\.md\b|\bsw_dev_handbook\b|\bthe handbook\b|\bhandbook's\b", re.IGNORECASE
    ),
}

# The tooling tests that describe how the local mirror works may name it.
_MAY_NAME_THE_MIRROR = {
    "test_check_api.py",
    "test_check_field_completeness.py",
    "test_fetch_sources.py",
    "test_check_coverage.py",
    "test_error_keys_oracle.py",
    "test_query_filter_keys_oracle.py",
}


def _private_source_offenders(path: Path, source: str) -> list[str]:
    found = []
    for line, text in _comments_and_docstrings(source):
        for reason, pattern in _PRIVATE_SOURCES.items():
            if "mirror" in reason and path.name in _MAY_NAME_THE_MIRROR:
                continue
            if pattern.search(text):
                found.append(f"{path.relative_to(ROOT)}:{line} {reason}")
    return found


def test_no_comment_or_docstring_names_a_private_source() -> None:
    offenders = [
        entry for path in _python_files() for entry in _private_source_offenders(path, path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_the_check_sees_each_kind_of_private_source() -> None:
    sample = (
        "# a 2nd-round Codex review caught this\n"
        "# verified live 2026-09-07 against the image\n"
        "# verified against op-sources 17.7\n"
        "# see RELEASE.md step 12\n"
        "# the Codex client reads its config here\n"
        "# a handbook entry for the client lives in its docs\n"
    )

    found = _private_source_offenders(ROOT / "tests" / "planted.py", sample)

    assert [entry.split(" ", 1)[1] for entry in found] == [
        "a review round or an AI tool as the author of a finding",
        "a dated or session-stamped verification",
        "a local mirror of the upstream source as evidence",
        "a process document the reader cannot open",
    ]
