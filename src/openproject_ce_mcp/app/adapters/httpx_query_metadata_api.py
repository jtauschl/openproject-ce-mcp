"""HTTP-backed QueryMetadataApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`link_title`/`link_to_web_url`/`slug_from_href` are shared via
`app/adapters/_text.py`.

`_query_ref_identity` is local: the shared self-link/href/id triple repeated
across all 5 normalize_query_* functions in this module, matching client.py's
original private helper of the same name and shape.

Every single-item GET path segment is `quote(<id>, safe="")`-encoded, matching
client.py's original (verbatim) -- these ids can contain characters like `:`
or `=` (e.g. operator id `"=""`) that would otherwise corrupt the URL path if
passed through unescaped. `filters`/`columns`/`operators`/
`filter_instance_schemas` quote the raw id directly.

`sort_bys` is the one exception, not just an encoding detail: the
route is `queries/sort_bys/:id-:direction` (hyphen-joined, verified against
OpenProject's own API implementation), not a bare id segment like the other
four resources. `get_sort_by` therefore transforms the caller's
colon-separated id (`"subject:asc"`) into the hyphen-joined path (`"subject-asc"`) before
quoting, and passes the original colon-form id through to
`normalize_query_sort_by` as `requested_id` so the public `id` field stays
stable regardless of the server's own hyphen-form self-link.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import (
    QueryColumnSummary,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
)
from ..ports.query_metadata_api import (
    QueryColumnRecord,
    QueryFilterInstanceSchemaRecord,
    QueryFilterRecord,
    QueryOperatorRecord,
    QuerySortByRecord,
)
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import link_title as _link_title
from ._text import link_to_web_url as _link_to_web_url
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments
from ._text import slug_from_href as _slug_from_href
from ._text import trim_text as _trim_text


def _query_ref_identity(links: dict[str, Any], payload: dict[str, Any]) -> tuple[Any, str | None, str]:
    self_link = links.get("self", {})
    href = self_link.get("href") if isinstance(self_link, dict) else None
    ref_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
    return self_link, href, ref_id


def normalize_query_filter(payload: dict[str, Any], *, base_url: str, origin: str) -> QueryFilterSummary:
    links = payload.get("_links", {})
    self_link, href, filter_id = _query_ref_identity(links, payload)
    return QueryFilterSummary(
        id=filter_id,
        name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


def normalize_query_column(payload: dict[str, Any], *, base_url: str, origin: str) -> QueryColumnSummary:
    links = payload.get("_links", {})
    self_link, href, column_id = _query_ref_identity(links, payload)
    return QueryColumnSummary(
        id=column_id,
        name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
        type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
        relation_type=_trim_text(payload.get("relationType"), limit=SUBJECT_LIMIT),
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


def normalize_query_operator(payload: dict[str, Any], *, base_url: str, origin: str) -> QueryOperatorSummary:
    links = payload.get("_links", {})
    self_link, href, operator_id = _query_ref_identity(links, payload)
    return QueryOperatorSummary(
        id=operator_id,
        name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


def normalize_query_sort_by(
    payload: dict[str, Any], *, base_url: str, origin: str, requested_id: str | None = None
) -> QuerySortBySummary:
    links = payload.get("_links", {})
    self_link, href, derived_id = _query_ref_identity(links, payload)
    sort_by_id = requested_id if requested_id is not None else derived_id
    column_link = links.get("column")
    direction_link = links.get("direction")
    direction = _trim_text(payload.get("direction"), limit=SUBJECT_LIMIT)
    if direction is None and isinstance(direction_link, dict):
        direction = _trim_text(direction_link.get("title"), limit=SUBJECT_LIMIT)
    return QuerySortBySummary(
        id=sort_by_id,
        name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
        column=_link_title(column_link) if isinstance(column_link, dict) else None,
        direction=direction,
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


def normalize_query_filter_instance_schema(
    payload: dict[str, Any], *, base_url: str, origin: str
) -> QueryFilterInstanceSchemaSummary:
    links = payload.get("_links", {})
    self_link, href, schema_id = _query_ref_identity(links, payload)
    dependencies = payload.get("_dependencies", [])
    operator_count = 0
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if isinstance(dependency, dict):
                values = dependency.get("dependencies")
                if isinstance(values, dict):
                    operator_count += len(values)
    name_field = payload.get("name")
    return QueryFilterInstanceSchemaSummary(
        id=schema_id,
        name=_trim_text(
            name_field.get("name") if isinstance(name_field, dict) else name_field,
            limit=SUBJECT_LIMIT,
        ),
        filter=_link_title(links.get("filter")),
        operator_count=operator_count,
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


class HttpxQueryMetadataApi:
    def __init__(self, transport: Transport, *, base_url: str, origin: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = origin

    async def get_filter(self, filter_id: str) -> QueryFilterRecord:
        safe_id = _reject_path_traversal_segments(filter_id, field_name="filter_id")
        payload = await self._transport.get_json(f"queries/filters/{quote(safe_id, safe='')}")
        return QueryFilterRecord(summary=normalize_query_filter(payload, base_url=self._base_url, origin=self._origin))

    async def get_column(self, column_id: str) -> QueryColumnRecord:
        safe_id = _reject_path_traversal_segments(column_id, field_name="column_id")
        payload = await self._transport.get_json(f"queries/columns/{quote(safe_id, safe='')}")
        return QueryColumnRecord(summary=normalize_query_column(payload, base_url=self._base_url, origin=self._origin))

    async def get_operator(self, operator_id: str) -> QueryOperatorRecord:
        safe_id = _reject_path_traversal_segments(operator_id, field_name="operator_id")
        payload = await self._transport.get_json(f"queries/operators/{quote(safe_id, safe='')}")
        return QueryOperatorRecord(
            summary=normalize_query_operator(payload, base_url=self._base_url, origin=self._origin)
        )

    async def get_sort_by(self, sort_by_id: str) -> QuerySortByRecord:
        column, _, direction = sort_by_id.partition(":")
        path_id = f"{column}-{direction}" if direction else sort_by_id
        safe_path_id = _reject_path_traversal_segments(path_id, field_name="sort_by_id")
        payload = await self._transport.get_json(f"queries/sort_bys/{quote(safe_path_id, safe='')}")
        return QuerySortByRecord(
            summary=normalize_query_sort_by(
                payload, base_url=self._base_url, origin=self._origin, requested_id=sort_by_id
            )
        )

    async def list_filter_instance_schemas(self, *, project_id: int | None) -> list[QueryFilterInstanceSchemaRecord]:
        path = (
            f"projects/{project_id}/queries/filter_instance_schemas"
            if project_id is not None
            else "queries/filter_instance_schemas"
        )
        payload = await self._transport.get_json(path)
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            QueryFilterInstanceSchemaRecord(
                summary=normalize_query_filter_instance_schema(item, base_url=self._base_url, origin=self._origin)
            )
            for item in elements
            if isinstance(item, dict)
        ]

    async def get_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaRecord:
        safe_id = _reject_path_traversal_segments(schema_id, field_name="schema_id")
        payload = await self._transport.get_json(f"queries/filter_instance_schemas/{quote(safe_id, safe='')}")
        return QueryFilterInstanceSchemaRecord(
            summary=normalize_query_filter_instance_schema(payload, base_url=self._base_url, origin=self._origin)
        )
