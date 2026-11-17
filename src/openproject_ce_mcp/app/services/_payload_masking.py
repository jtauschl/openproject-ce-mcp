"""A write result's `payload` as shown to the caller.

The form echo and the delete previews carry values of fields the operator hides. The payload sent for the
commit is never touched: this module only builds the copy that the result shows.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from typing import Any

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
