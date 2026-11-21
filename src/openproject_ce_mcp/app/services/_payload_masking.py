"""A result's `payload` and its identity members as shown to the caller.

The form echo and the delete previews carry values of fields the operator hides. The payload sent for the
commit is never touched: this module only builds the copy that the result shows.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import is_dataclass
from typing import Any, TypeVar, cast

from ...config import Settings
from ..policies import hidden_fields
from ..policies.identity_fields import ROW_KEYS
from ..policies.scope import id_from_href
from ._custom_field_masking import is_custom_field_key, without_hidden_custom_fields


def shown_payload(payload: dict[str, Any], *, entity: str, settings: Settings) -> dict[str, Any]:
    """Static keys of hidden fields removed (top level and under `_links`), then the custom field keys
    the settings hide. `_links` itself is structural: its members are judged one by one."""

    def keep(key: str, *, prefix: str = "") -> bool:
        if is_custom_field_key(key):
            return True
        return not hidden_fields.payload_key_hidden(entity, f"{prefix}{key}", settings=settings)

    shown: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "_links" and isinstance(value, dict):
            shown[key] = {rel: link for rel, link in value.items() if keep(rel, prefix="_links.")}
        elif keep(key):
            shown[key] = value
    return without_hidden_custom_fields(shown, entity=entity, settings=settings)


def record_payload(record: Any, **keys: str) -> dict[str, Any]:
    """The payload of a delete preview: `key=attribute` pairs read from a record the service stamped.
    The stamp lists the hidden fields in `_hidden_keys` (absent when nothing is hidden) and edits no
    value of the record, so a value the settings hide is left out here, not copied into the dict."""
    hidden: frozenset[str] = getattr(record, "_hidden_keys", frozenset())
    return {key: getattr(record, attribute) for key, attribute in keys.items() if attribute not in hidden}


_ServiceT = TypeVar("_ServiceT", bound=type)


def _without_copies(payload: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    shown = {key: value for key, value in payload.items() if key not in keys}
    links = shown.get("_links")
    if isinstance(links, dict):
        shown["_links"] = {rel: link for rel, link in links.items() if f"_links.{rel}" not in keys}
    return shown


_ROW_MEMBERS: dict[str, tuple[str, ...]] = {}
for _class_name, _member in ROW_KEYS:
    _ROW_MEMBERS[_class_name] = (*_ROW_MEMBERS.get(_class_name, ()), _member)


def _is_parent_row(row: Any, parent_id: Any) -> bool:
    href = row.get("href") if isinstance(row, dict) else None
    return parent_id is not None and isinstance(href, str) and id_from_href(href) == parent_id


def _stamp_rows(result: Any, *, settings: Settings) -> None:
    class_name = type(result).__name__
    for member in _ROW_MEMBERS.get(class_name, ()):
        rows = getattr(result, member, None)
        if not rows:
            continue
        parent_id = getattr(result, "parent_id", None)
        plain = hidden_fields.hidden_row_keys(class_name, member, parent_row=False, settings=settings)
        of_parent = hidden_fields.hidden_row_keys(class_name, member, parent_row=True, settings=settings)
        hidden = tuple(of_parent if _is_parent_row(row, parent_id) else plain for row in rows)
        if any(hidden):
            result._hidden_row_keys = {**getattr(result, "_hidden_row_keys", {}), member: hidden}


def stamp_result(result: Any, *, settings: Settings) -> Any:
    """List the members of a result that repeat a hidden field's value in `_hidden_keys`, and the keys of its
    dict rows in `_hidden_row_keys`, so the serializer leaves them out: no member or row is edited. The copies in a
    hand-built `payload` are removed from it. The stamp descends into nested dataclasses and lists of them (batch
    items, rows, images, the record of a write result). Idempotent."""
    if not is_dataclass(result) or isinstance(result, type):
        return result
    result = cast(Any, result)
    name = type(result).__name__
    hidden = hidden_fields.hidden_identity_keys(name, action=getattr(result, "action", None), settings=settings)
    if hidden:
        result._hidden_keys = getattr(result, "_hidden_keys", frozenset()) | hidden
    copies = hidden_fields.hidden_payload_copies(name, settings=settings)
    payload = getattr(result, "payload", None)
    if copies and isinstance(payload, dict):
        result.payload = _without_copies(payload, copies)
    _stamp_rows(result, settings=settings)
    for child in list(vars(result).values()):
        for member in child if isinstance(child, list) else (child,):
            stamp_result(member, settings=settings)
    return result


def stamped_results(cls: _ServiceT) -> _ServiceT:
    """Class decorator: every public async method of the service hands its result to `stamp_result` with the
    service's own settings, so a method written later is covered too."""

    def wrap(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(method)
        async def stamped(self: Any, *args: Any, **kwargs: Any) -> Any:
            return stamp_result(await method(self, *args, **kwargs), settings=self._settings)

        return stamped

    for name, member in list(vars(cls).items()):
        if not name.startswith("_") and inspect.iscoroutinefunction(member):
            setattr(cls, name, wrap(member))
    return cls
