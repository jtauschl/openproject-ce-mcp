"""The two project reads the allowlist directory needs: the paged project index
and a single project by id."""

from __future__ import annotations

from typing import Protocol

from .project_api import ProjectPage, ProjectRecord


class ProjectLookupApi(Protocol):
    async def list(self, *, server_offset: int, server_page_size: int, search: str | None) -> ProjectPage: ...
    async def get(self, project_ref: str) -> ProjectRecord: ...
