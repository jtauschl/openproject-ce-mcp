"""Check that every installed dependency is under a license this project has reviewed and allows.

The input is the JSON from `pip-licenses --from=mixed --format=json`. A license string can name several
licenses (`MIT; BSD License`, `Apache-2.0 OR BSD-3-Clause`, `(MIT OR GPL-2.0) AND BSD-3-Clause`). Every license it
names must be on the allow-list: no alternative is chosen on the licensee's behalf, so a dual-licensed package that
offers a copyleft option needs a review before it joins the set. A name the list does not know, an empty license
and `UNKNOWN` fail the same way.

A package that declares no license expression can carry its whole license text in the field. Such a multi-line value
passes only as the canonical MIT text, optionally preceded by an `MIT` title and a block of copyright lines. Nothing
else is read as a prefix or searched for names: any other text needs a review and a canonical text added here. A
copyright line must be one sentence without the word `license`. It may still name its holder in free words; the gate
guards against accidental copyleft, not against a package that hides terms there.

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
        # MIT without the condition to keep the copyright and permission notice: strictly more permissive than MIT and
        # OSI-approved. cffi 2.1.1 (a dependency of cryptography) moved to it from MIT.
        "MIT-0",
        # The Python 1.6b1 license: permissive and OSI-approved. The FSF lists it as GPL-incompatible (a choice-of-law
        # clause), which does not matter for an MIT-licensed project. Appears as `Apache-2.0 AND CNRI-Python`.
        "CNRI-Python",
        # File-level copyleft: it binds only the licensed files themselves. Allowed for a dependency that is installed
        # unmodified and not bundled into this project's artifacts; vendoring or patching one needs a new review.
        "MPL-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
    )
)

# SPDX matching guidelines ignore the title, the copyright notice, whitespace and case, so a text is compared on those
# terms. The compared text is the canonical MIT license from the grant to the last warranty sentence.
_MIT_TITLES = frozenset({"mit", "mit license"})


def _squeezed(text: str) -> str:
    return " ".join(text.split()).casefold()


_MIT_TERMS = _squeezed(
    """
    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
    rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial portions of
    the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
    THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
    """
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


# A holder list has commas, not sentences; a second sentence on a notice line is a term in disguise.
_SENTENCE_BREAK = re.compile(r"[.;:!?]\s+\S")


def _is_notice_line(line: str) -> bool:
    folded = _squeezed(line)
    if not folded:
        return True
    return folded.startswith("copyright") and "licen" not in folded and not _SENTENCE_BREAK.search(folded)


def _is_mit_text(license_text: str) -> bool:
    lines = license_text.strip().splitlines()
    if lines and _squeezed(lines[0]) in _MIT_TITLES:
        lines = lines[1:]
    while lines and _is_notice_line(lines[0]):
        lines = lines[1:]
    return _squeezed(" ".join(lines)) == _MIT_TERMS


def problems(packages: Iterable[Mapping[str, Any]]) -> list[str]:
    """What is wrong with the installed licenses, one line per package, led by the package name."""
    found: list[str] = []
    for package in packages:
        license_text = str(package.get("License") or "")
        lines = license_text.strip().splitlines()
        if len(lines) > 1:
            if not _is_mit_text(license_text):
                found.append(
                    f"{package.get('Name')} {package.get('Version')}: license text of {len(lines)} lines starting "
                    f"{lines[0][:60]!r} is not a recognised license text"
                )
            continue
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
