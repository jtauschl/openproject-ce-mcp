"""Edits of a stored long text, computed against the stored text.

A read returns a cut and whitespace-normalised copy of a stored long text, so a caller that builds a
full replacement from a read rewrites the stored Markdown. These edits run on the stored text instead
and leave everything outside the edit byte-identical. `field` is the name of the parameter family
(`description`, `comment`, `status_explanation`): it names the `<field>_append` and `<field>_replace`
parameters in every message.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ...config import Settings
from ..errors import InvalidInputError
from ..policies import hidden_fields

_ELLIPSIS = "…"
_SHRINK_MIN_CHARS = 200


def _noun(field: str) -> str:
    return field.replace("_", " ")


def ensure_one_text_input(
    field: str,
    full: str | None,
    append: str | None,
    replace: Mapping[str, str] | None,
    *,
    required: bool = False,
) -> None:
    given = [
        name
        for name, value in ((field, full), (f"{field}_append", append), (f"{field}_replace", replace))
        if value is not None
    ]
    if len(given) > 1:
        raise InvalidInputError(f"{' and '.join(given)} cannot be combined in one call; pass only one.")
    if required and not given:
        raise InvalidInputError(f"Give one of {field}, {field}_append and {field}_replace.")
    if append is not None and not append.strip():
        raise InvalidInputError(f"{field}_append must not be blank.")
    if replace is not None and (
        set(replace) != {"old", "new"} or not all(isinstance(v, str) for v in replace.values())
    ):
        raise InvalidInputError(f"{field}_replace takes exactly the string keys 'old' and 'new'.")


def append_paragraph(stored: str, text: str) -> str:
    if not stored.strip():
        return text
    trimmed = stored.rstrip("\r\n")
    return f"{trimmed}\n\n{text}"


def replace_passage(field: str, stored: str, old: str, new: str) -> str:
    """Replace the one passage of `stored` that `old` names, ignoring differences between whitespace runs.

    A read normalises whitespace, so `old` copied from one has to match indented, CRLF or
    multi-blank-line source. Tokens join with `\\s+` and cannot be skipped or reordered; the match
    is counted with a lookahead so overlapping matches make it ambiguous.
    """
    tokens = old.split()
    if not tokens:
        raise InvalidInputError(f"{field}_replace.old must not be blank.")
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    count = len(re.findall(f"(?={pattern})", stored))
    if count == 0:
        raise InvalidInputError(
            f"{field}_replace.old was not found in the stored {_noun(field)}. Copy it from a read without a "
            "trailing … or the escapes of a read (a stored < that looks like a tag reads back as &lt;)."
        )
    if count > 1:
        raise InvalidInputError(
            f"{field}_replace.old matches {count} passages of the stored {_noun(field)}; make it longer "
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


def change_sentence(field: str, before: int, after: int) -> str:
    """The length of the stored text before and after, raw characters (a read reports the normalised length)."""
    sentence = f"The {_noun(field)} changes from {before} to {after} characters."
    if after * 2 <= before and before - after >= _SHRINK_MIN_CHARS:
        sentence += f" It shrinks by {before - after} characters."
    return sentence


def edited_text(
    field: str, stored: str, full: str | None, append: str | None, replace: Mapping[str, str] | None
) -> tuple[str, str]:
    """The text to write and the sentence on its length; exactly one of `full`, `append`, `replace` is given."""
    if append is not None:
        final = append_paragraph(stored, append)
    elif replace is not None:
        final = replace_passage(field, stored, replace["old"], replace["new"])
    else:
        assert full is not None
        if contains_truncated_copy(full, stored):
            raise InvalidInputError(
                f"{field} looks like a truncated read of the stored {_noun(field)} (it contains a cut copy "
                f"ending in …). Writing it would drop the rest of the text. Use {field}_append to add "
                f"text or {field}_replace to change a passage; to write this text as it is, change the …."
            )
        final = full
    return final, change_sentence(field, len(stored), len(final))


def edit_stored_field(
    entity: str,
    field: str,
    stored: str | None,
    full: str | None,
    append: str | None,
    replace: Mapping[str, str] | None,
    *,
    settings: Settings,
) -> tuple[str | None, str | None]:
    """The text to write for one field of `entity` and the sentence on its length; `(None, None)` when untouched.

    The hidden-field check comes first: a match error, a cut-copy refusal or a length would otherwise tell
    a caller about a text the operator hid.
    """
    if full is None and append is None and replace is None:
        return None, None
    hidden_fields.ensure_field_writable(entity, field, settings=settings)
    ensure_one_text_input(field, full, append, replace)
    return edited_text(field, stored or "", full, append, replace)


def joined_sentences(*sentences: str | None) -> str | None:
    present = [sentence for sentence in sentences if sentence is not None]
    return " ".join(present) if present else None


def with_sentence(message: str, sentence: str | None) -> str:
    return message if sentence is None else f"{message} {sentence}"
