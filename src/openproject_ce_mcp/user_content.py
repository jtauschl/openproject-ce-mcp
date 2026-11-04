"""Marks user-authored text for the reading agent and keeps that text from imitating the mark.

OpenProject stores any text verbatim, so a description, comment or attachment can carry the
delimiter tags and place its own words outside the boundary. The reader is an LLM, which also
takes look-alikes (other case, zero-width characters, full-width brackets) for the tag, so
a tag is detected after folding, not byte for byte. The tags are a convention for the reader,
not a parser boundary: a homoglyph letter or a `<` outside the set below is not caught.

Stdlib only: the tool layer and `app/` both import this module and neither may import the other.
"""

from __future__ import annotations

import re
import unicodedata
from typing import overload

_OPEN = "<user-content>"
_CLOSE = "</user-content>"
_ESCAPED_LESS_THAN = "&lt;"

# Characters read as "<" that NFKC does not map to it: the `003C` sources of Unicode
# confusables.txt 18.0.0 minus the two NFKC maps (U+FF1C, U+FE64), plus the angle-bracket
# family. A literal, because the data file cannot be read at runtime.
_LESS_THAN_LOOKALIKES = frozenset(
    "\u2039\u276e\u02c2\U0001d236\u2d66\u1438\u16b2\U00016aec\U0001032d\u2329\u27e8\u3008\u276c\u2770"
)

# The folded text holds only "<", "/" and letters or digits, so the tag name needs no separators.
_FOLDED_TAG = re.compile(r"</*usercontent")


def _fold(text: str) -> tuple[str, list[int]]:
    """The text reduced to what a reader sees as tag structure, and each kept character's index in `text`.

    Folds per character: whole-string NFKC would compose a letter with a following combining mark
    and break the mapping back to the original positions.
    """
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        pieces = "<" if char in _LESS_THAN_LOOKALIKES else unicodedata.normalize("NFKC", char).casefold()
        for piece in pieces:
            if piece in "</" or piece.isalnum():
                folded.append(piece)
                origin.append(index)
    return "".join(folded), origin


def _neutralize_delimiter_lookalikes(text: str) -> str:
    folded, origin = _fold(text)
    starts = sorted({origin[match.start()] for match in _FOLDED_TAG.finditer(folded)})
    if not starts:
        return text
    parts: list[str] = []
    last = 0
    for start in starts:
        parts.append(text[last:start])
        parts.append(_ESCAPED_LESS_THAN)
        last = start + 1
    parts.append(text[last:])
    return "".join(parts)


@overload
def delimit_user_content(text: str) -> str: ...


@overload
def delimit_user_content(text: None) -> None: ...


def delimit_user_content(text: str | None) -> str | None:
    """Wrap text in the delimiter. Lengths and truncation flags describe the stored text, so callers
    cut the text to its limit first; the escape can make the result longer than that limit."""
    if text is None or not text.strip():
        return text
    return f"{_OPEN}{_neutralize_delimiter_lookalikes(text)}{_CLOSE}"
