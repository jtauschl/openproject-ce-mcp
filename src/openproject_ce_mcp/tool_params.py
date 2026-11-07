"""Parameter types whose meaning is the same in every tool that takes them.

The description travels in the tool's input schema, so an agent reads it
next to the parameter instead of in a docstring paragraph. These aliases are
resolved when the tool is registered (``inspect.signature(eval_str=True)``
on the tool's module globals), so modules must import them at runtime,
never under ``TYPE_CHECKING``. They add no constraint beyond their type; the
tool bodies validate the values and report a rejection as ``[validation_error]``.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Annotated, Any

from pydantic import ConfigDict, Field, with_config
from pydantic.fields import FieldInfo
from typing_extensions import Required, TypedDict

from .tool_types import IdOrName

Confirm = Annotated[
    bool,
    Field(
        description="false: preview only, nothing changes. true: applies it; get the user's approval of the preview first."
    ),
]

BulkConfirm = Annotated[
    bool,
    Field(
        description=(
            "false: preview of every item, nothing changes. true: attempts every item; get the user's approval "
            "of the preview first. Failed items are reported per item; items already written are not undone."
        )
    ),
]

_WORK_PACKAGE_REF = 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.'
WorkPackageRef = Annotated[int | str, Field(description=_WORK_PACKAGE_REF)]
OptionalWorkPackageRef = Annotated[int | str | None, Field(description=_WORK_PACKAGE_REF)]

# The resolver falls back to the display name and then to a unique search
# match on name or identifier (app/resolvers/project_resolver.py), for writes
# as well.
_PROJECT_REF = "Project identifier, id, or name; a unique part of a name or identifier also matches."
ProjectRef = Annotated[IdOrName, Field(description=_PROJECT_REF)]
OptionalProjectRef = Annotated[IdOrName | None, Field(description=_PROJECT_REF)]


@with_config(ConfigDict(strict=True, extra="forbid", allow_inf_nan=False))
class BulkCreateWorkPackageItem(TypedDict, total=False):
    """One work package of `bulk_create_work_packages`; a key outside this list is rejected, and so is
    a value of the wrong JSON type (a boolean for a subject, a number for a description)."""

    project: Required[ProjectRef]
    type: Required[IdOrName]
    subject: Required[str]
    description: str | None
    version: IdOrName | None
    target_versions: list[IdOrName] | None
    project_phase: IdOrName | None
    assignee: IdOrName | None
    responsible: IdOrName | None
    priority: IdOrName | None
    category: IdOrName | None
    custom_fields: CustomFieldValues
    parent: IdOrName | None
    parent_work_package_id: OptionalWorkPackageRef
    start_date: str | None
    due_date: str | None
    estimated_time: str | None
    remaining_time: str | None
    duration: str | None


@with_config(ConfigDict(strict=True, extra="forbid", allow_inf_nan=False))
class BulkUpdateWorkPackageItem(TypedDict, total=False):
    """One change of `bulk_update_work_packages`; a key outside this list is rejected, and so is a
    value of the wrong JSON type."""

    work_package_id: Required[WorkPackageRef]
    subject: str | None
    description: str | None
    type: IdOrName | None
    version: IdOrName | None
    target_versions: list[IdOrName] | None
    sprint: IdOrName | None
    project_phase: IdOrName | None
    status: IdOrName | None
    assignee: IdOrName | None
    responsible: IdOrName | None
    priority: IdOrName | None
    category: IdOrName | None
    custom_fields: CustomFieldValues
    parent: IdOrName | None
    parent_work_package_id: OptionalWorkPackageRef
    start_date: str | None
    due_date: str | None
    estimated_time: str | None
    remaining_time: str | None
    duration: str | None
    percentage_done: int | None


CustomFieldValues = Annotated[
    dict[str, Any] | None,
    Field(
        description="Custom field values by customField<N> key or field name, at most 50. Text, number or boolean as "
        "is; list, user and version fields take an option id or title (a list for several values); null clears."
    ),
]

CustomFieldFilters = Annotated[
    dict[str, dict[str, Any]] | None,
    Field(
        description='Filter by custom field values: {"cf_<N>": {"operator": "=", "values": ["x"]}}, N from a '
        "customField<N> key. The operators a field takes depend on its format (docs/filters.md). At most 20 "
        "filters, 100 values each. A project matches only where the token may see the field."
    ),
]

Offset = Annotated[int, Field(description="1-based page number; pass the previous result's next_offset.")]

Limit = Annotated[int | None, Field(description="Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.")]


def allowed_select_fields(row_type: type, *, wrapper_fields: frozenset[str] = frozenset()) -> frozenset[str]:
    """Every name ``select`` accepts for rows of ``row_type``."""
    return frozenset(field.name for field in dataclass_fields(row_type)) | wrapper_fields


def select_field(row_type: type, *, wrapper_fields: frozenset[str] = frozenset()) -> FieldInfo:
    """Schema description for a ``select`` parameter, naming every field it accepts."""
    allowed = ", ".join(sorted(allowed_select_fields(row_type, wrapper_fields=wrapper_fields)))
    return Field(description=f"Fields to return; a requested unset field comes back as null. Allowed: {allowed}.")
