"""One way to build a `ProjectRecord` in a test: the summary, and by default a detail made from it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openproject_ce_mcp.app.ports.project_api import ProjectRecord
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary


def project_record(
    summary: ProjectSummary,
    *,
    detail: ProjectDetail | None = None,
    payload: dict[str, Any] | None = None,
    references: Mapping[str, frozenset[ScopedReference]] | None = None,
) -> ProjectRecord:
    shown = detail if detail is not None else ProjectDetail(**vars(summary))
    return ProjectRecord(
        summary=summary,
        references=references or {},
        payload=payload if payload is not None else {},
        summary_factory=lambda visible: summary,
        detail_factory=lambda visible: shown,
    )
