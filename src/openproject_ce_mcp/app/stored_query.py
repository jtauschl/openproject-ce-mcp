"""The selection and the order a saved query stores, in a module of its own so that no layer imports another to share them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFilter:
    """A filter of the stored query: the API name of the filter (`assignee`, `dueDate`, `customField5`) and the
    slug of its operator (`=`, `o`). What a filter selects by is its key and operator, so values and titles stay out."""

    key: str
    operator: str


@dataclass(frozen=True)
class StoredSort:
    column: str
    direction: str


@dataclass(frozen=True)
class StoredQuery:
    """The selection and the order the server applies when it runs the saved query."""

    filters: tuple[StoredFilter, ...]
    sort_by: tuple[StoredSort, ...]
    group_by: str | None
    include_subprojects: bool
    project_scoped: bool
