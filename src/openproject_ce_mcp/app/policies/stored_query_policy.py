"""A saved query cannot select or order by a hidden field either.

`execute_query` runs the filters, the sort and the group-by the query stores, so the server selects and orders the
rows by values the caller never typed and the hide settings still hide. The rule is the one the typed parameters
follow (`work_package_query_policy`), applied to the stored definition: a filter, a sort column or a group column is
refused when a field that shows its value is hidden, whether the work package field (`COLUMN_RESULT_FIELDS`) or the
field of another entity (`OTHER_ENTITY_OWNERS_OF_COLUMN`, `STORED_FILTER_OWNERS`).

The server names a filter by the API name of its key, and may add filters, sort columns and group columns. A name this
table does not know is refused while any hide setting is active (fail closed), like a definition the adapter could
not read; with nothing hidden nothing is refused. The names come from the server sources of every pinned release
(`tools/api-check/query_filter_keys.py`). Pure, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ...config import HIDE_FIELD_ENV_BY_ENTITY, Settings
from ...work_package_columns import (
    COLUMN_RESULT_FIELDS,
    COLUMNS_WITHOUT_RESULT_FIELD,
    OTHER_ENTITY_OWNERS_OF_COLUMN,
    PROJECT_HIERARCHY_OWNERS,
)
from ..errors import InvalidInputError
from ..stored_query import StoredQuery
from . import hidden_fields

Owners = tuple[tuple[str, str], ...]


def _wp(*fields: str) -> Owners:
    return tuple(("work_package", field) for field in fields)


_RELATION: Owners = (("relation", "type"), ("relation", "from_id"), ("relation", "to_id"))
_HIERARCHY: Owners = _wp("parent_id", "ancestors", "children")
_VERSION_STATES: Owners = (("version", "status"),)

# Stored filter (API name of its key) -> the (entity, field) pairs whose value it selects by. The rule of
# `OTHER_ENTITY_OWNERS_OF_FILTER`: the work package field when the row shows the value, a field of another entity when
# the row does not and that entity shows it.
STORED_FILTER_OWNERS: dict[str, Owners] = {
    "ancestor": _HIERARCHY,
    "assignedToRole": _wp("assignee")
    + (("membership", "principal_id"), ("membership", "role_ids"), ("membership", "role_names")),
    "assignee": _wp("assignee"),
    "assigneeOrGroup": _wp("assignee") + (("group", "members"),),
    "attachmentFileName": (("attachment", "file_name"), ("attachment", "title")),
    "author": _wp("author"),
    "backlogBucket": (("backlog_bucket", "name"),),
    "backlogInbox": _wp("sprint") + (("backlog_bucket", "name"),),
    "backlogsWorkPackageType": _wp("type") + _HIERARCHY + _RELATION,
    "blocked": _RELATION,
    "blocks": _RELATION,
    "category": _wp("category"),
    "comment": (("activity", "comment"),),
    "createdAt": _wp("created_at"),
    "datesInterval": _wp("start_date", "due_date"),
    "description": _wp("description"),
    "dueDate": _wp("due_date"),
    "duplicated": _RELATION,
    "duplicates": _RELATION,
    "duration": _wp("duration", "type") + (("type", "is_milestone"),),
    "estimatedTime": _wp("estimated_time"),
    "follows": _RELATION,
    "id": _wp("id"),
    "includes": _RELATION,
    "isMilestone": _wp("type") + (("type", "is_milestone"),),
    "linkableToStorage": (("project_storage", "storage_id"), ("project_storage", "storage_name")),
    "linkableToStorageUrl": (("storage", "host"),),
    "memberOfGroup": _wp("assignee") + (("group", "members"),),
    "observedInVersion": _wp("observed_in_versions"),
    "onlySubproject": _wp("project") + PROJECT_HIERARCHY_OWNERS,
    "parent": _wp("parent_id", "children"),
    "partof": _RELATION,
    "percentageDone": _wp("percentage_done"),
    "precedes": _RELATION,
    "priority": _wp("priority"),
    "project": _wp("project"),
    "projectPhaseDefinition": _wp("project_phase"),
    "relatable": _RELATION + _HIERARCHY,
    "relates": _RELATION,
    "required": _RELATION,
    "requires": _RELATION,
    "responsible": _wp("responsible"),
    "search": _wp("subject", "description", "custom_fields")
    + (("activity", "comment"), ("attachment", "file_name"), ("attachment", "title")),
    "sprint": _wp("sprint"),
    "startDate": _wp("start_date"),
    "status": _wp("status"),
    "storage": (("file_link", "storage_id"), ("file_link", "storage_name")),
    "storageUrl": (("storage", "host"),),
    "subject": _wp("subject"),
    "subjectOr": _wp("subject", "id"),
    "subprojectId": _wp("project") + PROJECT_HIERARCHY_OWNERS,
    "targetVersion": _wp("version", "target_versions"),
    "type": _wp("type"),
    "typeahead": _wp("subject", "id", "display_id", "project", "type", "status") + (("status", "is_closed"),),
    "updatedAt": _wp("updated_at"),
    "version": _wp("version", "target_versions"),
    "watcher": (("watcher", "id"), ("watcher", "name"), ("watcher", "login")),
}

# The operators of a filter that name a state of a record the row does not show (an open status, a locked version).
STATE_OPERATOR_OWNERS: dict[tuple[str, str], Owners] = {
    **{("status", operator): (("status", "is_closed"),) for operator in ("o", "c")},
    **{
        (key, operator): _VERSION_STATES
        for key in ("version", "targetVersion", "observedInVersion")
        for operator in ("o", "c", "l")
    },
}

# An operator after which a filter selects by no hidden value: `!*` on the subproject filter keeps the bound project alone,
# whatever its descendants are.
OPERATORS_WITHOUT_OWNERS: frozenset[tuple[str, str]] = frozenset({("subprojectId", "!*")})

# The filters no entity shows a value of, with the reason: they select by something no tool returns.
NOT_HIDEABLE_FILTERS: dict[str, str] = {
    "attachmentContent": "the extracted text of an attachment is returned only by get_attachment_content, which no hide setting names",
    "bcfIssueAssociated": "whether a work package has a BCF issue is shown by no field",
    "fileLinkOrigin": "the id of a file in its storage is shown by no field",
    "budget": "the budget of a work package is shown by no field",
    "manualSort": "the position in the manual order is shown by no field",
    "sharedWithMe": "the sharing of a work package with a user is shown by no field",
    "sharedWithUser": "the sharing of a work package with a user is shown by no field",
}

# Sort and group columns of the server that the work package row does not carry and no entity shows, with the reason.
STORED_ONLY_COLUMNS: dict[str, str] = {
    "manual_sorting": "the order the user dragged the rows into is a stored position, shown by no field",
    "exact_match": "it ranks by the term of a typeahead filter and is a constant without one, and that filter is judged on its own",
}

# Columns of the server that the work package row does not carry, ordered by a value a field shows: the typeahead sort
# is `updated_at`.
STORED_COLUMN_OWNERS: dict[str, Owners] = {
    "typeahead": _wp("updated_at"),
}

_CUSTOM_FIELD_FILTER = re.compile(r"customField(\d+)\Z")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def column_name(api_name: str) -> str:
    """The snake_case name `COLUMN_RESULT_FIELDS` uses for a column the server names in camelCase; a custom field
    (`customField5`) is the `cf_5` of the typed parameters."""
    custom_field = _CUSTOM_FIELD_FILTER.match(api_name)
    if custom_field:
        return f"cf_{custom_field.group(1)}"
    return _CAMEL_BOUNDARY.sub("_", api_name).lower()


def _hidden(owners: Iterable[tuple[str, str]], *, settings: Settings) -> tuple[str, str] | None:
    return next(
        ((entity, field) for entity, field in owners if hidden_fields.field_hidden(entity, field, settings=settings)),
        None,
    )


def _refuse_owner(entity: str, field: str, subject: str) -> InvalidInputError:
    return InvalidInputError(
        f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by {HIDE_FIELD_ENV_BY_ENTITY[entity]} "
        f"and cannot be used by the saved query ({subject})."
    )


def _ensure_owners(owners: Owners, subject: str, *, settings: Settings) -> None:
    hidden = _hidden(owners, settings=settings)
    if hidden is not None:
        raise _refuse_owner(*hidden, subject)


def _ensure_custom_field(column: str, subject: str, *, settings: Settings) -> None:
    if hidden_fields.custom_field_column_hidden(column, entity="work_package", settings=settings):
        raise InvalidInputError(
            f"OpenProject custom field '{column}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS or by the custom_fields "
            f"field of the work package hide setting and cannot be used by the saved query ({subject})."
        )


def _unknown(subject: str) -> InvalidInputError:
    return InvalidInputError(
        f"The saved query uses a part this MCP does not know ({subject}). It is refused while a field is hidden, "
        "because it could select or order by a hidden value."
    )


def _ensure_filter(key: str, operator: str, *, settings: Settings) -> None:
    subject = f"filter '{key}'"
    custom_field = _CUSTOM_FIELD_FILTER.match(key)
    if custom_field:
        _ensure_custom_field(f"cf_{custom_field.group(1)}", subject, settings=settings)
    elif key in STORED_FILTER_OWNERS:
        if (key, operator) in OPERATORS_WITHOUT_OWNERS:
            return
        if key == "search" and settings.hide_custom_fields:
            raise InvalidInputError(
                f"OpenProject custom fields are hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and the saved query's text "
                f"search ({subject}) matches their values."
            )
        _ensure_owners(
            STORED_FILTER_OWNERS[key] + STATE_OPERATOR_OWNERS.get((key, operator), ()), subject, settings=settings
        )
    elif key not in NOT_HIDEABLE_FILTERS:
        raise _unknown(subject)


def _ensure_column(use: str, api_name: str, *, settings: Settings) -> None:
    subject = f"{use} '{api_name}'"
    column = column_name(api_name)
    if column.startswith("cf_"):
        _ensure_custom_field(column, subject, settings=settings)
        return
    known = (
        COLUMN_RESULT_FIELDS.keys()
        | COLUMNS_WITHOUT_RESULT_FIELD
        | STORED_ONLY_COLUMNS.keys()
        | STORED_COLUMN_OWNERS.keys()
    )
    if column not in known:
        raise _unknown(subject)
    owners = (
        _wp(*COLUMN_RESULT_FIELDS.get(column, ()))
        + OTHER_ENTITY_OWNERS_OF_COLUMN.get(column, ())
        + STORED_COLUMN_OWNERS.get(column, ())
    )
    _ensure_owners(owners, subject, settings=settings)


def ensure_stored_query_allowed(definition: StoredQuery | None, *, settings: Settings) -> None:
    """Raises when the stored definition selects, orders or groups by a field a hide setting hides. `None` is a
    definition the adapter could not read: nothing is known about it, so it is refused while any setting is active."""
    if not hidden_fields.any_hide_active(settings):
        return
    if definition is None:
        raise _unknown("the definition could not be read")
    for stored in definition.filters:
        _ensure_filter(stored.key, stored.operator, settings=settings)
    for sort in definition.sort_by:
        _ensure_column("sort", sort.column, settings=settings)
    if definition.group_by is not None:
        _ensure_column("group", definition.group_by, settings=settings)
    if definition.project_scoped:
        _ensure_owners(_wp("project"), "it is bound to a project", settings=settings)
    keys = {stored.key for stored in definition.filters}
    # The flag adds the descendants of a project filter always, and those of the bound project unless an explicit
    # subproject filter takes its place (that filter is judged above); a global query without a project filter ignores it.
    if definition.include_subprojects and (
        "project" in keys or (definition.project_scoped and "subprojectId" not in keys)
    ):
        _ensure_owners(PROJECT_HIERARCHY_OWNERS, "it includes subprojects", settings=settings)
