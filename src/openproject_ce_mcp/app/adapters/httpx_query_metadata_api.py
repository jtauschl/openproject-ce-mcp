"""HTTP-backed QueryMetadataApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`link_title`/`link_to_web_url`/`slug_from_href` are shared via
`app/adapters/_text.py`.

`_query_ref_identity` is local: the shared self-link/href/id triple of four
of the five normalize_query_* functions in this module. The filter instance
schema renders no `id`, so it takes the slug of its own self link.

`filters`/`columns`/`operators`/`filter_instance_schemas` take a raw id and
`quote(<id>, safe="")`-encode it as the path segment: these ids can contain
characters like `:` or `=` (e.g. operator id `"=""`) that would otherwise
corrupt the URL path if passed through unescaped.

`sort_bys` routes on `:id-:direction`; `get_sort_by` builds that path from a
parsed criterion and reports the id as the caller gave it.
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
    SortCriterion,
)
from ..api_href import sort_by_path
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
        name=_trim_text(self_link.get("title"), limit=SUBJECT_LIMIT),
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
    # QuerySortByRepresenter has no top-level `direction` property, only the
    # `_links.direction` link's title.
    direction = (
        _trim_text(direction_link.get("title"), limit=SUBJECT_LIMIT) if isinstance(direction_link, dict) else None
    )
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
    # A QueryFilterInstanceSchema renders `self` as its only top-level link, no `id` and, outside a form, no filter
    # link: its `name` attribute is the constant "Name", not the filter's name. The id is the slug of `self`.
    self_link = payload.get("_links", {}).get("self", {})
    href = self_link.get("href") if isinstance(self_link, dict) else None
    dependencies = payload.get("_dependencies", [])
    operator_count = 0
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if isinstance(dependency, dict):
                values = dependency.get("dependencies")
                if isinstance(values, dict):
                    operator_count += len(values)
    return QueryFilterInstanceSchemaSummary(
        id=_slug_from_href(href) or "",
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

    async def get_sort_by(self, criterion: SortCriterion, *, requested_id: str) -> QuerySortByRecord:
        payload = await self._transport.get_json(sort_by_path(criterion))
        return QuerySortByRecord(
            summary=normalize_query_sort_by(
                payload, base_url=self._base_url, origin=self._origin, requested_id=requested_id
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
