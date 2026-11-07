"""A hidden work package field cannot be used to query either.

The field is left out of every result and refused in every write. A filter, an ordering or a
grouping by it would still show its values, one query at a time, so each of them is refused too.
Pure, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from ...config import Settings
from ...work_package_columns import COLUMN_RESULT_FIELDS, FILTER_RESULT_FIELDS
from ..errors import InvalidInputError
from . import hidden_fields


def _hidden(fields: Iterable[str], *, settings: Settings) -> str | None:
    return next((f for f in fields if hidden_fields.field_hidden("work_package", f, settings=settings)), None)


def ensure_query_allowed(
    *, settings: Settings, filters: Iterable[str], sort_fields: Sequence[str], group_by: str | None
) -> None:
    """Raises when a requested filter parameter, sort column or group column is a hidden field.
    A column or parameter that stands for several result fields (`version` and `target_versions`)
    is closed when any of them is hidden."""
    uses = (
        [("filter", name, FILTER_RESULT_FIELDS.get(name, ())) for name in filters]
        + [("sort", name, COLUMN_RESULT_FIELDS.get(name, ())) for name in sort_fields]
        + ([("group", group_by, COLUMN_RESULT_FIELDS.get(group_by, ()))] if group_by else [])
    )
    for use, name, fields in uses:
        hidden = _hidden(fields, settings=settings)
        if hidden is not None:
            raise InvalidInputError(
                f"OpenProject work package field '{hidden}' is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS "
                f"and cannot be used to {use} ('{name}')."
            )
    for use, column in [("sort", name) for name in sort_fields] + ([("group", group_by)] if group_by else []):
        hidden_fields.ensure_custom_field_column_usable(column, use, entity="work_package", settings=settings)


# The summable fields OpenProject aggregates, by the result field that shows the same value. The
# costs, story points and similar sums have no result field, so no setting can hide them.
SUM_RESULT_FIELDS = {
    "estimatedTime": "estimated_time",
    "remainingTime": "remaining_time",
    "percentageDone": "percentage_done",
}


def sums_without_hidden_fields(sums: dict[str, Any] | None, *, settings: Settings) -> dict[str, Any] | None:
    """The aggregates (`totalSums` or a group's sums) without the ones of a hidden field: a sum of
    a field shows the field's values in aggregate."""
    if sums is None:
        return None

    def shown(key: str) -> bool:
        field = SUM_RESULT_FIELDS.get(key)
        if field is not None:
            return not hidden_fields.field_hidden("work_package", field, settings=settings)
        if key.startswith("customField"):
            return not (
                hidden_fields.field_hidden("work_package", "custom_fields", settings=settings)
                or hidden_fields.custom_field_hidden(key, key, settings=settings)
            )
        return True

    return {key: value for key, value in sums.items() if shown(key)}
