"""The shape of a summary or detail whose entity carries custom fields (work package, project)."""

from __future__ import annotations

from typing import Any, Protocol


class CustomFieldCarrier(Protocol):
    custom_fields: dict[str, Any] | None
    custom_fields_truncated: bool
    custom_comments: dict[str, str] | None
    custom_comments_truncated: bool
