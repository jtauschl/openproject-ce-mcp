"""MCP output/context-reduction presentation policy.

Relocated out of tools.py: this is presentation/serialization policy (hides
confirmed payloads, drops derived fields, applies `select`, filters hidden
fields) rather than a model definition, so it does not belong in models.py
either. Package-root module (not under app/) -- tools.py must never import
from app/ directly (see tests/test_architecture_boundaries.py), and this is
needed by tools.py.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any

from .models import BatchWorkPackageReadItemResult, BulkWorkPackageItemResult


def _to_payload(value: Any, *, select: frozenset[str] | None = None, elide_none: bool = True) -> Any:
    """Serialize a tool result to a trimmed plain dict for context reduction.

    Recursively turns dataclass instances into dicts while applying structural
    omissions that would otherwise cost fixed context on every call:

    - **payload**: dropped from a write result once ``state`` is ``"confirmed"``
      (the success case), since the normalized ``result`` already carries the same
      information. It stays on preview/validation-error results, where the agent
      still needs it. Applied recursively, so nested bulk items are trimmed too.
    - **count / truncated**: dropped from list results — both are derivable
      (``count == len(results)``, ``truncated == next_offset is not None``).
    - **next_offset**: never dropped, even when ``None`` — it is the pagination
      control field, and callers page until it comes back ``null``, not until
      it is absent.
    - **hidden keys**: removed entirely (not nulled) when the client tagged
      the instance with ``_hidden_keys``.
    - **None-valued fields**: dropped when ``elide_none`` is true, kept as an
      explicit ``null`` otherwise. An empty list/dict is always kept regardless
      (it means "present but empty", distinct from "not applicable"). ``elide_none``
      reflects the *calling tool's* serialization policy, not the shape of the
      dataclass currently being serialized: it is set once by the ``tools.py``
      registration wrapper — true when the tool accepts a ``select`` parameter
      (so a caller who wants a ``None`` field back can request it explicitly),
      false when it does not (so nothing would otherwise be able to recover an
      elided field). It is threaded unchanged through every recursive call,
      including into nested row lists and nested entities, since a nested
      dataclass never has its own ``select`` — the policy is a property of the
      top-level tool call, not of whichever type happens to be nested inside it.
    - **selected fields**: requesting a field via ``select`` guarantees its
      presence in the response, even when its value is ``None`` — see
      ``_select_fields``. This is how a caller distinguishes "unset" from
      "not requested" for select-capable tools. The one deliberate exception
      in the other direction: a failed batch/bulk item's nested entity is
      still emitted as an explicit ``null`` (see ``_select_fields``'s
      ``_SELECT_NESTED_FIELD`` branch) regardless of ``select`` contents —
      there, ``null`` means "this item failed", not "no value", and eliding
      it would make failed items indistinguishable from a missing key.

    ``select`` is applied to the top-level row list — ``results`` for list reads,
    or ``items`` for bulk write results — keeping just the requested fields per
    row. For a row type registered in ``_SELECT_NESTED_FIELD`` (e.g. a batch-read
    item that wraps a single work package, or a bulk item that wraps a single
    write result, rather than being the entity itself), ``select`` instead trims
    that nested entity — the row's own wrapper fields (id/success/error, or
    index/success/error) are kept regardless of ``select``. When the top-level
    value itself has neither ``results``/``items`` NOR ``payload``/``next_offset``
    (a genuinely bare single-entity result, e.g. ``WorkPackageDetail`` —
    excluding ``payload``/``next_offset`` deliberately keeps a bare
    ``*WriteResult`` like ``WorkPackageWriteResult`` on the normal per-field
    path even though it also lacks ``results``/``items``, so its
    confirmed-payload-drop and next_offset handling stay intact if such a
    type ever gains ``select``), ``select`` instead trims the top-level
    object directly, via the same ``_select_fields`` used for rows — this is
    what lets a single-entity ``get_*`` tool support field selection despite
    not being a list/bulk result.

    Non-dataclass values pass through unchanged, so tools (and test stubs) that
    already return plain dicts are untouched.
    """
    if is_dataclass(value) and not isinstance(value, type):
        # "results" (list reads) and "items" (bulk writes) are the two row-list
        # field names the seam knows about. count/truncated are results-only —
        # BulkWorkPackageWriteResult carries total/succeeded/failed instead.
        row_field_name = "results" if _has_field(value, "results") else "items" if _has_field(value, "items") else None
        # A bare single-entity result -- no results/items for the
        # row_field_name branch below to act on, AND no payload/next_offset
        # of its own -- has nothing the per-field loop's special-cased
        # fields (drop_payload, next_offset) need to apply to. Hand the
        # whole object to _select_fields instead, so single-entity get_*
        # tools can support select too. The payload/next_offset exclusion is
        # deliberate, not incidental: a bare *WriteResult (e.g.
        # WorkPackageWriteResult) also has no results/items but DOES carry
        # payload/state, and bypassing drop_payload for it would leak a
        # confirmed write's payload back into the response if such a tool
        # ever gains select -- none does today, but the condition must not
        # rely on that being permanent.
        is_bare_entity = (
            row_field_name is None and not _has_field(value, "payload") and not _has_field(value, "next_offset")
        )
        if select is not None and is_bare_entity:
            return _select_fields(value, select, elide_none=elide_none)
        drop_payload = getattr(value, "state", None) == "confirmed" and _has_field(value, "payload")
        is_list_result = row_field_name == "results"
        hidden = getattr(value, "_hidden_keys", ())
        out: dict[str, Any] = {}
        for f in dataclass_fields(value):
            name = f.name
            if name in hidden:
                continue
            if name == "payload" and drop_payload:
                continue
            if is_list_result and name in ("count", "truncated"):
                continue
            child = getattr(value, name)
            if name == "next_offset":
                out[name] = child
                continue
            if child is None:
                if not elide_none:
                    out[name] = None
                continue
            if name == row_field_name and select is not None:
                out[name] = [_select_fields(row, select, elide_none=elide_none) for row in child]
            else:
                out[name] = _to_payload(child, elide_none=elide_none)
        return out
    if isinstance(value, list):
        return [_to_payload(item, elide_none=elide_none) for item in value]
    if isinstance(value, tuple):
        return [_to_payload(item, elide_none=elide_none) for item in value]
    if isinstance(value, dict):
        return {k: _to_payload(v, elide_none=elide_none) for k, v in value.items()}
    return value


def _has_field(value: Any, name: str) -> bool:
    return any(f.name == name for f in dataclass_fields(value))


# Rows that wrap a single nested entity instead of being the entity itself.
# `select` trims the nested entity; the row's own non-None wrapper fields
# (id/success/error, or index/success/error) survive regardless of `select`,
# since a batch caller needs them to correlate results regardless of which
# entity fields it asked for — a None-valued wrapper field is still elided,
# same as everywhere else (the wrapper fields are never select-targetable).
_SELECT_NESTED_FIELD: dict[type, str] = {
    BatchWorkPackageReadItemResult: "work_package",
    BulkWorkPackageItemResult: "result",
}


def _select_fields(row: Any, select: frozenset[str], *, elide_none: bool) -> Any:
    """Keep only the selected fields of a result row (dataclass), still trimmed.

    Most rows ARE the selectable entity. A row type in ``_SELECT_NESTED_FIELD``
    instead wraps a single nested entity — for those, ``select`` trims the
    nested entity and the row's own non-None fields are kept in full (a
    None-valued wrapper field is elided, same as elsewhere). The nested
    entity's own key is a deliberate exception: when the entity itself is
    missing (a failed batch/bulk item), that key is still emitted as an
    explicit ``null`` rather than being dropped — it signals failure, not
    absence of a value.

    For the plain (non-nested) case below, a field named in ``select`` is
    always emitted, even when its value is ``None`` — this is what lets a
    caller distinguish "this field is unset" from "this field was never
    requested" for select-capable tools. Fields not in ``select``, or in
    ``hidden``, are omitted entirely regardless of their value.

    ``elide_none`` has no default, deliberately: it is a required, explicit
    parameter (not silently inherited from ``_to_payload``'s own default) so a
    future call site cannot forget to thread the calling tool's policy through
    and reintroduce a coupling on ``_to_payload``'s ``elide_none=True``
    default happening to coincide with the only value select-capable tools
    currently have.
    """
    if not is_dataclass(row) or isinstance(row, type):
        return _to_payload(row, elide_none=elide_none)
    hidden = getattr(row, "_hidden_keys", ())
    nested_field = _SELECT_NESTED_FIELD.get(type(row))
    if nested_field is not None:
        out = {
            f.name: _to_payload(getattr(row, f.name), elide_none=elide_none)
            for f in dataclass_fields(row)
            if f.name != nested_field and f.name not in hidden and getattr(row, f.name) is not None
        }
        # nested_field itself is deliberately exempt from None-elision: a
        # failed batch/bulk item signals that via an explicit null here, not
        # via a missing key (see _to_payload's docstring).
        nested = getattr(row, nested_field)
        out[nested_field] = _select_fields(nested, select, elide_none=elide_none) if nested is not None else None
        return out
    return {
        f.name: _to_payload(getattr(row, f.name), elide_none=elide_none)
        for f in dataclass_fields(row)
        if f.name in select and f.name not in hidden
    }
