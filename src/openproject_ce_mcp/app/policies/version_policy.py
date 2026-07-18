"""Versions-only policy (ADR 0001). Pure, no I/O."""

from __future__ import annotations

from typing import Any

from ...config import Settings
from .scope import ensure_project_link_allowed, payload_allowed


def version_payload_allowed(
    payload: dict[str, Any], *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> bool:
    return payload_allowed(
        lambda: ensure_project_link_allowed(
            payload.get("_links", {}).get("definingProject"),
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    )
