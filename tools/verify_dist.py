"""Check a downloaded distribution against the digests the build job recorded.

The directory must hold exactly the wheel and the sdist of one version, each a regular file, and nothing else (hidden
files included). The digests file is the `sha256sum` output the build job wrote right after its first build: exactly one
well-formed record per expected file, and each file must hash to its record.

What this proves is identity and integrity relative to those digests: the files are the ones the build job recorded.
It does not make the package benign; a compromised build step could record digests that match its own output.

Usage: python tools/verify_dist.py <dist-dir> <version> <digests-file>
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

RECORD = re.compile(r"^([0-9a-f]{64})  (\S+)$")


class DistError(Exception):
    pass


def expected_names(version: str) -> frozenset[str]:
    return frozenset({f"openproject_ce_mcp-{version}-py3-none-any.whl", f"openproject_ce_mcp-{version}.tar.gz"})


def parse_digests(text: str, expected: frozenset[str]) -> dict[str, str]:
    lines = [line for line in text.splitlines() if line]
    if not lines:
        raise DistError("the digests are empty")
    records: dict[str, str] = {}
    for line in lines:
        match = RECORD.fullmatch(line)
        if match is None:
            raise DistError(f"malformed digest record: {line!r}")
        digest, name = match.groups()
        if name in records:
            raise DistError(f"duplicate digest record for {name}")
        records[name] = digest
    if set(records) != expected:
        raise DistError(f"the digest records name {sorted(records)}, expected {sorted(expected)}")
    return records


def verify(dist_dir: Path, version: str, digests_text: str) -> dict[str, str]:
    expected = expected_names(version)
    records = parse_digests(digests_text, expected)
    with os.scandir(dist_dir) as scan:
        entries = {entry.name: entry for entry in scan}
    if set(entries) != expected:
        raise DistError(f"{dist_dir} holds {sorted(entries)}, expected {sorted(expected)}")
    for name in sorted(expected):
        if not entries[name].is_file(follow_symlinks=False):
            raise DistError(f"{name} is not a regular file")
        actual = hashlib.sha256((dist_dir / name).read_bytes()).hexdigest()
        if actual != records[name]:
            raise DistError(f"{name} has digest {actual}, the build job recorded {records[name]}")
    return records


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    _, dist_dir, version, digests_file = argv
    try:
        records = verify(Path(dist_dir), version, Path(digests_file).read_text(encoding="utf-8"))
    except (DistError, OSError) as error:
        print(f"verify_dist: {error}", file=sys.stderr)
        return 1
    for name in sorted(records):
        print(f"{records[name]}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
