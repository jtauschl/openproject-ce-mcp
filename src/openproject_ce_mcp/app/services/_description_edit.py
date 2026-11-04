"""Edits of a stored work package description, computed against the stored text.

A read returns a cut and whitespace-normalised copy of the stored description, so a caller that
builds a full replacement from a read rewrites the stored Markdown. These edits run on the stored
text instead and leave everything outside the edit byte-identical.
"""

from __future__ import annotations

import re

from ..errors import InvalidInputError

_ELLIPSIS = "…"
_SHRINK_MIN_CHARS = 200


def append_paragraph(stored: str, text: str) -> str:
    if not stored.strip():
        return text
    trimmed = stored.rstrip("\r\n")
    return f"{trimmed}\n\n{text}"


def replace_passage(stored: str, old: str, new: str) -> str:
    """Replace the one passage of `stored` that `old` names, ignoring differences between whitespace runs.

    A read normalises whitespace, so `old` copied from one has to match indented, CRLF or
    multi-blank-line source. Tokens join with `\\s+` and cannot be skipped or reordered; the match
    is counted with a lookahead so overlapping matches make it ambiguous.
    """
    tokens = old.split()
    if not tokens:
        raise InvalidInputError("description_replace.old must not be blank.")
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    count = len(re.findall(f"(?={pattern})", stored))
    if count == 0:
        raise InvalidInputError(
            "description_replace.old was not found in the stored description. Copy it from a read without a "
            "trailing … or the escapes of a read (a stored < that looks like a tag reads back as &lt;)."
        )
    if count > 1:
        raise InvalidInputError(
            f"description_replace.old matches {count} passages of the stored description; make it longer "
            "until it names exactly one."
        )
    match = re.search(pattern, stored)
    assert match is not None
    return stored[: match.start()] + new + stored[match.end() :]


def _flat(text: str) -> str:
    return " ".join(text.split())


def contains_truncated_copy(text: str, stored: str) -> bool:
    """True when `text` holds a cut read of `stored`: the part before some … is a proper prefix of it.

    A read ends a cut text with … after rstrip, so the signature is exact. Both sides are compared as
    one line (a list read has no line breaks) and the read escape of a delimiter look-alike (&lt;) is
    undone in a second pass.
    """
    stored_flat = _flat(stored)
    flat = _flat(text)
    for candidate in dict.fromkeys((flat, flat.replace("&lt;", "<"))):
        position = candidate.find(_ELLIPSIS)
        while position != -1:
            prefix = candidate[:position]
            if (
                prefix
                and len(prefix) < len(stored_flat)
                and stored_flat.startswith(prefix)
                and not stored_flat[len(prefix) :].lstrip().startswith(_ELLIPSIS)
            ):
                return True
            position = candidate.find(_ELLIPSIS, position + 1)
    return False


def change_sentence(before: int, after: int) -> str:
    """The length of the stored description before and after, raw characters (a read reports the normalised length)."""
    sentence = f"The description changes from {before} to {after} characters."
    if after * 2 <= before and before - after >= _SHRINK_MIN_CHARS:
        sentence += f" It shrinks by {before - after} characters."
    return sentence
