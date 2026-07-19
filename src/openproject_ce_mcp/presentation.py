"""MCP output/context-reduction presentation policy (OPM-48).

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


def _to_payload(value: Any, *, select: frozenset[str] | None = None) -> Any:
    """Serialize a tool result to a trimmed plain dict for context reduction.

    Recursively turns dataclass instances into dicts while applying structural
    omissions that would otherwise cost fixed context on every call:

    - **payload**: dropped from a write result once ``confirmed`` is true
      (the success case), since the normalized ``result`` already carries the same
      information. It stays on preview/validation-error results, where the agent
      still needs it. Applied recursively, so nested bulk items are trimmed too.
    - **count / truncated**: dropped from list results — both are derivable
      (``count == len(results)``, ``truncated == next_offset is not None``).
    - **hidden keys**: removed entirely (not nulled) when the client tagged
      the instance with ``_hidden_keys``.

    ``select`` is applied to the top-level row list — ``results`` for list reads,
    or ``items`` for bulk write results — keeping just the requested fields per
    row. For a row type registered in ``_SELECT_NESTED_FIELD`` (e.g. a batch-read
    item that wraps a single work package, or a bulk item that wraps a single
    write result, rather than being the entity itself), ``select`` instead trims
    that nested entity — the row's own wrapper fields (id/success/error, or
    index/success/error) are kept regardless of ``select``.

    Non-dataclass values pass through unchanged, so tools (and test stubs) that
    already return plain dicts are untouched.
    """
    if is_dataclass(value) and not isinstance(value, type):
        drop_payload = getattr(value, "confirmed", None) is True and _has_field(value, "payload")
        # "results" (list reads) and "items" (bulk writes) are the two row-list
        # field names the seam knows about. count/truncated are results-only —
        # BulkWorkPackageWriteResult carries total/succeeded/failed instead.
        row_field_name = "results" if _has_field(value, "results") else "items" if _has_field(value, "items") else None
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
            if name == row_field_name and select is not None:
                out[name] = [_select_fields(row, select) for row in child]
            else:
                out[name] = _to_payload(child)
        return out
    if isinstance(value, list):
        return [_to_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_to_payload(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_payload(v) for k, v in value.items()}
    return value


def _has_field(value: Any, name: str) -> bool:
    return any(f.name == name for f in dataclass_fields(value))


# Rows that wrap a single nested entity instead of being the entity itself.
# `select` trims the nested entity; the row's own wrapper fields (id/success/
# error, or index/success/error) always survive, since a batch caller needs
# them to correlate results regardless of which entity fields it asked for.
_SELECT_NESTED_FIELD: dict[type, str] = {
    BatchWorkPackageReadItemResult: "work_package",
    BulkWorkPackageItemResult: "result",
}


def _select_fields(row: Any, select: frozenset[str]) -> Any:
    """Keep only the selected fields of a result row (dataclass), still trimmed.

    Most rows ARE the selectable entity. A row type in ``_SELECT_NESTED_FIELD``
    instead wraps a single nested entity — for those, ``select`` trims the
    nested entity and the row's own fields are always kept in full.
    """
    if not is_dataclass(row) or isinstance(row, type):
        return _to_payload(row)
    hidden = getattr(row, "_hidden_keys", ())
    nested_field = _SELECT_NESTED_FIELD.get(type(row))
    if nested_field is not None:
        out = {
            f.name: _to_payload(getattr(row, f.name))
            for f in dataclass_fields(row)
            if f.name != nested_field and f.name not in hidden
        }
        nested = getattr(row, nested_field)
        out[nested_field] = _select_fields(nested, select) if nested is not None else None
        return out
    return {
        f.name: _to_payload(getattr(row, f.name))
        for f in dataclass_fields(row)
        if f.name in select and f.name not in hidden
    }
