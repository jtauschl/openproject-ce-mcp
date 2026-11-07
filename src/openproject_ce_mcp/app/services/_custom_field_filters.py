"""`custom_field_filters` of a list or search call as the `cf_<N>` filter fragments the server takes.

One rule for every entity whose list endpoint filters by custom field. Synchronous and network-free:
the format of a field is not known here, so an operator or value that does not fit it is refused by
the server with its own clear error. Functions only, in an underscore-prefixed module: every public
class under app/services/ must be named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import re
from typing import Any

from ...config import Settings
from ..errors import InvalidInputError
from ..policies import hidden_fields

# The tool layer checks the same shape; a caller that bypasses it still gets a clean error here
# instead of a malformed filter.
_KEY = re.compile(r"^(cf_|customField)([1-9]\d*)$", re.ASCII)


def append_custom_field_filters(
    filters: list[dict[str, Any]], custom_field_filters: dict[str, dict[str, Any]] | None, *, settings: Settings
) -> None:
    """Appends one fragment per entry. A field hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS is refused under
    either spelling of its key (`cf_<N>`, `customField<N>`): with no schema to read a name from, a hide
    pattern may have been written in either form."""
    if not custom_field_filters:
        return
    for raw_key, spec in custom_field_filters.items():
        match = _KEY.match(str(raw_key))
        if not match:
            raise InvalidInputError(
                f"custom_field_filters key '{raw_key}' must be of the form 'cf_<N>' or 'customField<N>'."
            )
        cf_id = match.group(2)
        cf_key = f"cf_{cf_id}"
        if hidden_fields.custom_field_hidden(cf_key, f"customField{cf_id}", settings=settings):
            raise InvalidInputError(
                f"OpenProject custom field '{cf_key}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS "
                "and cannot be filtered."
            )
        if not isinstance(spec, dict):
            raise InvalidInputError(f"custom_field_filters['{raw_key}'] must be an object.")
        operator = spec.get("operator")
        values = spec.get("values")
        if not isinstance(operator, str) or not operator:
            raise InvalidInputError(f"custom_field_filters['{raw_key}'].operator must be a non-empty string.")
        if not isinstance(values, list):
            raise InvalidInputError(f"custom_field_filters['{raw_key}'].values must be a list.")
        filters.append({cf_key: {"operator": operator, "values": list(values)}})
