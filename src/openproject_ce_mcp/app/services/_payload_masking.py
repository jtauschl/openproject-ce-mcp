"""A write result's `payload` as shown to the caller.

The form echo and the delete previews carry values of fields the operator hides. The payload sent for the
commit is never touched: this module only builds the copy that the result shows.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ...config import Settings
from ..policies import hidden_fields
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
    The stamp lists the hidden fields in `_hidden_keys` (absent when nothing is hidden) and changes no
    value, so a value the settings hide is left out here, not copied into the dict."""
    hidden: frozenset[str] = getattr(record, "_hidden_keys", frozenset())
    return {key: getattr(record, attribute) for key, attribute in keys.items() if attribute not in hidden}


_ServiceT = TypeVar("_ServiceT", bound=type)


def _without_copies(payload: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    shown = {key: value for key, value in payload.items() if key not in keys}
    links = shown.get("_links")
    if isinstance(links, dict):
        shown["_links"] = {rel: link for rel, link in links.items() if f"_links.{rel}" not in keys}
    return shown


def stamp_write_result(result: Any, *, settings: Settings) -> Any:
    """List the members of a write result that repeat a hidden field's value in `_hidden_keys`, so the
    serializer leaves them out. A batch result stamps the write result of each item. Idempotent."""
    name = type(result).__name__
    hidden = hidden_fields.hidden_identity_keys(name, action=getattr(result, "action", None), settings=settings)
    if hidden:
        result._hidden_keys = getattr(result, "_hidden_keys", frozenset()) | hidden
    copies = hidden_fields.hidden_payload_copies(name, settings=settings)
    payload = getattr(result, "payload", None)
    if copies and isinstance(payload, dict):
        result.payload = _without_copies(payload, copies)
    items = getattr(result, "items", None)
    for item in items if isinstance(items, list) else ():
        inner = getattr(item, "result", None)
        if inner is not None:
            stamp_write_result(inner, settings=settings)
    return result


def stamped_write_results(cls: _ServiceT) -> _ServiceT:
    """Class decorator: every public async method of the service hands its write result to
    `stamp_write_result` with the service's own settings, so a method written later is covered too."""

    def wrap(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(method)
        async def stamped(self: Any, *args: Any, **kwargs: Any) -> Any:
            return stamp_write_result(await method(self, *args, **kwargs), settings=self._settings)

        return stamped

    for name, member in list(vars(cls).items()):
        if not name.startswith("_") and inspect.iscoroutinefunction(member):
            setattr(cls, name, wrap(member))
    return cls
