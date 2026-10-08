"""The allowlists' knowledge of which projects exist, rescanned on demand."""

from __future__ import annotations

from typing import Protocol


class ReadableProjects(Protocol):
    async def ensure_fresh(self) -> None:
        """Rescan when the last scan is old enough that a new project could be missing."""
        ...
