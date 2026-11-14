"""The values a rejected reference could have been, worded once for every resolver.

A caller that names a status, version, role or other value OpenProject does not know needs the accepted values to
correct the call in the same turn. Every resolver that rejects a name appends `offered_clause` (or, for an ambiguous
name, `candidates_clause`) to its message, from the set it has already read: no extra request, and only the scope
filtered set the resolver itself matched against.

The values land in an error text that the client reads into its context, so the list is capped. The names are short
user-authored strings; whether such strings are delimited is an open decision that applies to these texts as to every
other short string.
"""

from __future__ import annotations

from collections.abc import Iterable

NAME_LIMIT = 255
OFFERED_LIMIT = 20


def trim_text(value: object, *, limit: int = NAME_LIMIT) -> str | None:
    """`value` on one line, cut at `limit` characters; None for nothing or only whitespace."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _capped(items: list[str]) -> str:
    shown = ", ".join(items[:OFFERED_LIMIT])
    if len(items) > OFFERED_LIMIT:
        shown += f", … (+{len(items) - OFFERED_LIMIT} more)"
    return shown


def offered_names(names: Iterable[object], *, sort: bool = True) -> str | None:
    """The distinct, non-empty names joined by commas, capped; None when there is none.

    `sort` orders them case-insensitively; the schema options of a form keep the order the server offers them in
    (a workflow lists its statuses in a meaningful order)."""
    distinct = list(dict.fromkeys(name for name in map(trim_text, names) if name))
    if not distinct:
        return None
    if sort:
        distinct.sort(key=lambda name: (name.casefold(), name))
    return _capped(distinct)


def offered_clause(names: Iterable[object], *, plural: str, sort: bool = True) -> str:
    """` Allowed <plural>: a, b, c.` for the end of a not-found message; empty when no name is known."""
    offered = offered_names(names, sort=sort)
    return f" Allowed {plural}: {offered}." if offered else ""


def candidates_clause(candidates: Iterable[tuple[object, object]]) -> str:
    """` Matches: 12 (Release), 15 (Release).` for the end of an ambiguity message: each candidate's id and name."""
    shown = [
        f"{identifier} ({name})" if (name := trim_text(label)) else str(identifier) for identifier, label in candidates
    ]
    return f" Matches: {_capped(shown)}." if shown else ""
