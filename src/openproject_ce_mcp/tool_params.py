"""Parameter types whose meaning is the same in every tool that takes them.

The description travels in the tool's input schema, so an agent reads it
next to the parameter instead of in a docstring paragraph. These aliases are
resolved when the tool is registered (``inspect.signature(eval_str=True)``
on the tool's module globals), so modules must import them at runtime,
never under ``TYPE_CHECKING``. They add no constraint beyond their type
(``IdOrName`` keeps its strict integer check); the tool bodies validate the
values and report a rejection as ``[VALIDATION_FAILED]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields as dataclass_fields
from typing import Annotated, Any, Required

from pydantic import ConfigDict, Field, with_config
from pydantic.fields import FieldInfo
from typing_extensions import TypedDict

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
ParentRef = Annotated[
    int | str | None,
    Field(description='Parent work package: id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.'),
]
WorkPackageRefs = Annotated[
    list[int | str],
    Field(
        description='Work package ids (e.g. 952) or display ids (e.g. "PROJ-51"), not the bare number 51. Duplicates are dropped.'
    ),
]

_EXPECT_DISPLAY_ID = 'Display id of the work package you mean, e.g. "PROJ-51"; see the server instructions.'
ExpectDisplayId = Annotated[str | None, Field(description=_EXPECT_DISPLAY_ID)]

_EXPECT_RELATED_DISPLAY_ID = (
    'Display id of the related work package you mean, e.g. "PROJ-51"; see the server instructions.'
)
ExpectRelatedDisplayId = Annotated[str | None, Field(description=_EXPECT_RELATED_DISPLAY_ID)]

_EXPECT_PARENT_DISPLAY_ID = 'Display id of the parent you mean, e.g. "PROJ-51"; see the server instructions.'
ExpectParentDisplayId = Annotated[str | None, Field(description=_EXPECT_PARENT_DISPLAY_ID)]

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
    observed_in_versions: list[IdOrName] | None
    project_phase: IdOrName | None
    assignee: IdOrName | None
    responsible: IdOrName | None
    priority: IdOrName | None
    category: IdOrName | None
    custom_fields: CustomFieldValues
    parent: IdOrName | None
    parent_work_package_id: OptionalWorkPackageRef
    expect_parent_display_id: ExpectParentDisplayId
    start_date: str | None
    due_date: str | None
    estimated_time: str | None
    remaining_time: str | None
    duration: str | None


@with_config(ConfigDict(strict=True, extra="forbid", allow_inf_nan=False))
class TextReplace(TypedDict):
    old: str
    new: str


TextAppend = Annotated[str | None, Field(description="Paragraph added after the stored text.")]
TextReplaceParam = Annotated[
    TextReplace | None, Field(description="Replaces the one passage old names with new (may be empty).")
]


@with_config(ConfigDict(strict=True, extra="forbid", allow_inf_nan=False))
class BulkUpdateWorkPackageItem(TypedDict, total=False):
    """One change of `bulk_update_work_packages`; a key outside this list is rejected, and so is a
    value of the wrong JSON type."""

    work_package_id: Required[WorkPackageRef]
    subject: str | None
    description: str | None
    description_append: TextAppend
    description_replace: TextReplaceParam
    type: IdOrName | None
    version: IdOrName | None
    target_versions: list[IdOrName] | None
    observed_in_versions: list[IdOrName] | None
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
    expect_parent_display_id: ExpectParentDisplayId
    start_date: str | None
    due_date: str | None
    estimated_time: str | None
    remaining_time: str | None
    duration: str | None
    percentage_done: int | None
    expect_display_id: ExpectDisplayId


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


def _top_level_select_fields(
    row_type: type, wrapper_fields: frozenset[str], unfilled: frozenset[str]
) -> frozenset[str]:
    return (frozenset(field.name for field in dataclass_fields(row_type)) - unfilled) | wrapper_fields


def _nested_select_fields(nested: Mapping[str, type] | None, unfilled: frozenset[str]) -> dict[str, frozenset[str]]:
    return {
        prefix: frozenset(field.name for field in dataclass_fields(model) if f"{prefix}.{field.name}" not in unfilled)
        for prefix, model in (nested or {}).items()
    }


def allowed_select_fields(
    row_type: type,
    *,
    wrapper_fields: frozenset[str] = frozenset(),
    nested: Mapping[str, type] | None = None,
    unfilled: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Every name ``select`` accepts for rows of ``row_type``, nested ones as ``<field>.<name>``.

    ``unfilled`` names fields this tool's producer never sets (a nested one as ``<field>.<name>``): offering
    one would hand back ``null`` that reads like "no value" instead of "never read".
    """
    nested_names = {
        f"{prefix}.{name}" for prefix, names in _nested_select_fields(nested, unfilled).items() for name in names
    }
    return _top_level_select_fields(row_type, wrapper_fields, unfilled) | nested_names


def select_field(
    row_type: type,
    *,
    wrapper_fields: frozenset[str] = frozenset(),
    nested: Mapping[str, type] | None = None,
    unfilled: frozenset[str] = frozenset(),
) -> FieldInfo:
    """Schema description for a ``select`` parameter, naming every field it accepts."""
    allowed = ", ".join(sorted(_top_level_select_fields(row_type, wrapper_fields, unfilled)))
    for prefix, names in sorted(_nested_select_fields(nested, unfilled).items()):
        allowed += f"; {prefix}.<field> for {', '.join(sorted(names))}"
    return Field(description=f"Fields to return; a requested unset field comes back as null. Allowed: {allowed}.")
