"""Check that every installed dependency is under a license this project has reviewed and allows.

The input is the JSON from `pip-licenses --from=mixed --format=json`. A license string can name several
licenses (`MIT; BSD License`, `Apache-2.0 OR BSD-3-Clause`, `(MIT OR GPL-2.0) AND BSD-3-Clause`). Every license it
names must be on the allow-list: no alternative is chosen on the licensee's behalf, so a dual-licensed package that
offers a copyleft option needs a review before it joins the set. A name the list does not know, an empty license
and `UNKNOWN` fail the same way.

Usage: pip-licenses --from=mixed --format=json --output-file licenses.json && python tools/check_licenses.py licenses.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# pip-licenses prints either the SPDX identifier or the trove classifier text, depending on what a package
# declares, so both spellings of a license are listed.
ALLOWED = frozenset(
    name.casefold()
    for name in (
        "MIT",
        "MIT License",
        "BSD License",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "Apache Software License",
        "PSF-2.0",
        # File-level copyleft: it binds only the licensed files themselves. Allowed for a dependency that is installed
        # unmodified and not bundled into this project's artifacts; vendoring or patching one needs a new review.
        "MPL-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
    )
)

# A trove classifier such as "Mozilla Public License 2.0 (MPL 2.0)" carries its own parentheses, so a part that is a
# listed name as a whole is taken as it is before the grouping parentheses of an expression are dropped.
_OPERATOR = re.compile(r"\s+(?:AND|OR)\s+", re.IGNORECASE)


def _named(license_text: str) -> list[str]:
    names: list[str] = []
    for part in re.split(r"\s*;\s*", license_text.strip()):
        if " ".join(part.split()).casefold() in ALLOWED:
            names.append(" ".join(part.split()))
            continue
        for token in _OPERATOR.split(re.sub(r"[()]", " ", part).strip()):
            names.append(" ".join(token.split()))
    return names


def problems(packages: Iterable[Mapping[str, Any]]) -> list[str]:
    """What is wrong with the installed licenses, one line per package, led by the package name."""
    found: list[str] = []
    for package in packages:
        license_text = str(package.get("License") or "")
        refused = [token for token in _named(license_text) if token.casefold() not in ALLOWED]
        if refused:
            shown = ", ".join(repr(token) for token in refused)
            found.append(f"{package.get('Name')} {package.get('Version')}: license {license_text!r} names {shown}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("licenses", type=Path)
    args = parser.parse_args(argv)
    found = problems(json.loads(args.licenses.read_text(encoding="utf-8")))
    for line in found:
        print(f"{line} (add it to ALLOWED in tools/check_licenses.py only after a license review)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
