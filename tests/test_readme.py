"""README.md is the package's long description, so it is also the PyPI
project page, where a relative link resolves against pypi.org."""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"

_MARKDOWN_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)")
# Footnote definitions ("[^1]: text") carry no target.
_REFERENCE_TARGET = re.compile(r"^\s*\[(?!\^)[^\]]+\]:\s*<?([^\s>]+)", re.MULTILINE)
_HTML_TARGET = re.compile(r"""\b(href|src|srcset)\s*=\s*(?:["']([^"']+)["']|([^\s>"']+))""")


def _targets(text: str) -> list[str]:
    targets = [*_MARKDOWN_TARGET.findall(text), *_REFERENCE_TARGET.findall(text)]
    for attribute, quoted, unquoted in _HTML_TARGET.findall(text):
        value = quoted or unquoted
        if attribute == "srcset":
            targets.extend(candidate.split()[0] for candidate in value.split(",") if candidate.strip())
        else:
            targets.append(value)
    return targets


def test_every_readme_link_and_image_is_absolute() -> None:
    targets = _targets(README.read_text(encoding="utf-8"))

    relative = [target for target in targets if not target.startswith(("https://", "http://", "#", "mailto:"))]

    assert targets
    assert relative == []


def test_the_link_scan_sees_markdown_reference_and_html_targets() -> None:
    sample = """
[inline](docs/a.md) ![image](img/b.png) [anchor](#c)
[ref]: CONTRIBUTING.md
[titled]: docs/e.md "Title"
[^1]: A footnote, not a link.
<img src="img/d.jpg"> <a href="https://example.com/f"> <img src=img/g.png>
<source srcset="img/h.png 1x, img/i.png 2x">
"""

    assert _targets(sample) == [
        "docs/a.md",
        "img/b.png",
        "#c",
        "CONTRIBUTING.md",
        "docs/e.md",
        "img/d.jpg",
        "https://example.com/f",
        "img/g.png",
        "img/h.png",
        "img/i.png",
    ]
