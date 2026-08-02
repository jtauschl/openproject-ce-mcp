"""News-only policy. Pure, no I/O."""

from __future__ import annotations

from typing import Any

from ...config import Settings
from .scope import project_link_payload_allowed


def news_payload_allowed(
    payload: dict[str, Any], *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> bool:
    return project_link_payload_allowed(
        payload, link_key="project", settings=settings, project_id_to_identifier=project_id_to_identifier
    )
