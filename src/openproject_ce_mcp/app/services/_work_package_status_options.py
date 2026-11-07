"""The statuses a work package's update form offers, as `OptionValue`s.

Read-side counterpart to `_schema_write_helpers.with_offered_status_values`:
both read `schema.status._embedded.allowedValues` of the same form response.
"""

from __future__ import annotations

from typing import Any

from ...models import OptionValue
from ..errors import OpenProjectServerError
from ._schema_write_helpers import _id_from_href, _option_title


def allowed_status_options(schema: dict[str, Any]) -> list[OptionValue]:
    field = schema.get("status")
    allowed_values = field.get("_embedded", {}).get("allowedValues") if isinstance(field, dict) else None
    if not isinstance(allowed_values, list):
        raise OpenProjectServerError("OpenProject work-package form does not offer allowed values for field 'status'.")
    options = []
    for item in allowed_values:
        href = item.get("_links", {}).get("self", {}).get("href")
        title = _option_title(item)
        if not href or title is None:
            raise OpenProjectServerError("OpenProject work-package form offers a status without a link or a name.")
        options.append(OptionValue(id=_id_from_href(href), title=title, href=str(href)))
    return options
