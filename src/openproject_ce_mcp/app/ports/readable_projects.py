"""The projects whose work packages the read allowlist covers: matched by
OPENPROJECT_READ_PROJECTS."""

from __future__ import annotations

from typing import Protocol


class ReadableProjects(Protocol):
    async def ensure_fresh(self) -> None:
        """Rescan when the last scan is old enough that a new project could be missing."""
        ...

    def readable_project_ids(self) -> frozenset[int]: ...
