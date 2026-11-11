"""The mcp-publisher binary runs next to the OIDC token of the registry job, so it is pinned and verified before use."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "install-mcp-publisher.sh"


def _code(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _problems(text: str) -> list[str]:
    code = "\n".join(_code(text))
    problems = []
    if "set -euo pipefail" not in code:
        problems.append("no set -euo pipefail")
    versions = re.findall(r'^version="(\d+\.\d+\.\d+)"$', code, re.MULTILINE)
    hashes = re.findall(r'^sha256="([0-9a-f]{64})"$', code, re.MULTILINE)
    if len(versions) != 1:
        problems.append("not exactly one pinned version")
    if len(hashes) != 1:
        problems.append("not exactly one 64-hex sha256")
    archive = re.search(r'^archive="([^"]+)"$', code, re.MULTILINE)
    download = re.search(r'curl [^\n]*-o "\$archive"', code)
    check = re.search(r"sha256sum -c", code)
    extract = re.search(r'tar -xzf "\$archive"', code)
    if not (archive and download and check and extract):
        return [*problems, "the download, the check or the extraction does not use the one archive variable"]
    if 'echo "${sha256}  ${archive}" | sha256sum -c -' not in code:
        problems.append("the checksum check does not name the downloaded archive")
    if not download.start() < check.start() < extract.start():
        problems.append("the archive is not checked between the download and the extraction")
    if "/download/v${version}/" not in code:
        problems.append("the download URL does not use the pinned version")
    if "latest" in code:
        problems.append("a floating latest URL")
    return problems


def test_the_publisher_is_pinned_and_checked_before_it_is_extracted() -> None:
    assert _problems(SCRIPT.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('echo "${sha256}  ${archive}" | sha256sum -c -\n', "", "the download, the check or the extraction"),
        (
            'echo "${sha256}  ${archive}" | sha256sum -c -',
            'echo "${sha256}  other.tar.gz" | sha256sum -c -',
            "does not name the downloaded archive",
        ),
        ('sha256="00b21004', 'sha256="0b21004', "not exactly one 64-hex sha256"),
        ("/download/v${version}/", "/download/latest/", "does not use the pinned version"),
        ("set -euo pipefail\n", "set -eu\n", "no set -euo pipefail"),
        ('version="1.8.7"', 'version="latest"', "not exactly one pinned version"),
    ],
)
def test_the_install_check_sees_a_removed_a_foreign_and_a_floating_pin(old: str, new: str, expected: str) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert old in text, old

    assert any(expected in problem for problem in _problems(text.replace(old, new, 1))), _problems(
        text.replace(old, new, 1)
    )


def test_the_check_must_come_before_the_extraction() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    check = 'echo "${sha256}  ${archive}" | sha256sum -c -\n'
    extract = 'tar -xzf "$archive" -C "$target_dir" mcp-publisher\n'
    swapped = text.replace(check + extract, extract + check, 1)

    assert swapped != text
    assert any("not checked between" in problem for problem in _problems(swapped))
