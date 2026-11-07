"""A hidden project field cannot be used to query either.

The field is left out of every result and refused in every write. A filter or an ordering by it would
still show its values, one query at a time, so each of them is refused too. Pure, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...config import Settings
from ...project_columns import COLUMN_RESULT_FIELDS, FILTER_RESULT_FIELDS
from ..errors import InvalidInputError
from . import hidden_fields


def ensure_query_allowed(*, settings: Settings, filters: Iterable[str], sort_fields: Iterable[str]) -> None:
    """Raises when a requested filter parameter or sort column is a hidden field."""
    for name in filters:
        for field in FILTER_RESULT_FIELDS.get(name, ()):
            _refuse_hidden(field, "filter", name, settings=settings)
    for name in sort_fields:
        for field in COLUMN_RESULT_FIELDS.get(name, ()):
            _refuse_hidden(field, "sort", name, settings=settings)
        hidden_fields.ensure_custom_field_column_usable(name, "sort", entity="project", settings=settings)


def _refuse_hidden(field: str, use: str, name: str, *, settings: Settings) -> None:
    if hidden_fields.field_hidden("project", field, settings=settings):
        raise InvalidInputError(
            f"OpenProject project field '{field}' is hidden by OPENPROJECT_HIDE_PROJECT_FIELDS "
            f"and cannot be used to {use} ('{name}')."
        )
