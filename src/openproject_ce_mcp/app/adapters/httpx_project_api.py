"""HTTP-backed ProjectApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). The pure
normalize_* HAL->model translation functions live in `..ports.project_api`
(not here) -- unlike Versions, where they live in the adapter and Services
never need to call them directly, ProjectService itself normalizes an
already-resolved raw payload (from ProjectResolver) without a second port
round-trip, and Services may not import Adapters, only Ports/Policies/
Resolvers. This adapter imports them FROM the port instead.

Contains a small, deliberately duplicated private copy of
`_normalize_validation_errors`'s text-extraction dependency and
`_origin_from_url` (+ `SUBJECT_LIMIT`) -- duplicated rather than imported from
client.py to avoid `app/` importing from `client.py`. Unify only once every
domain has migrated and client.py's copies become truly dead.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from ...models import ProjectDetail, ProjectPhaseDefinition, ProjectRef
from ..errors import OpenProjectServerError
from ..ports.project_api import (
    SUBJECT_LIMIT,
    ProjectCopyFormResult,
    ProjectFormResult,
    ProjectPage,
    ProjectPhaseRecord,
    ProjectRecord,
    ProjectSchemaResult,
    _extract_formattable_text_with_meta,
    _trim_text,
    normalize_project,
    normalize_project_detail,
    normalize_project_phase,
    normalize_project_phase_definition,
)
from ..transport.protocol import Transport

FORMATTABLE_LIMIT = 1_200


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message, _, _ = _extract_formattable_text_with_meta(entry, limit=SUBJECT_LIMIT)
        if message is None and isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class HttpxProjectApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)
        self._api_prefix = api_prefix

    def _link_to_api_path(self, href: str) -> str:
        """Same-origin-checked href -> API-relative path (with the API prefix
        stripped, since the Transport's own base URL already includes it).

        Verbatim port of client.py's _link_to_api_path: an absolute href whose
        origin differs from this instance's configured origin is rejected
        BEFORE any authenticated request is made -- a manipulated/foreign
        `allowedValues.href` in a schema response must never be contacted.
        """
        parsed = urlparse(href)
        if not parsed.scheme:
            path = parsed.path or href
        else:
            if _origin_from_url(href) != self._origin:
                raise OpenProjectServerError("OpenProject returned an unexpected link host.")
            path = parsed.path
        relative_path = path[len(self._api_prefix) :] if path.startswith(self._api_prefix) else path.lstrip("/")
        if parsed.query:
            return f"{relative_path}?{parsed.query}"
        return relative_path

    def _link_to_web_url(self, href: str | None) -> str | None:
        """Same-origin-checked href -> absolute web URL, or None for a foreign origin.

        Verbatim port of client.py's _link_to_web_url: unlike _link_to_api_path,
        a foreign-origin absolute href is not an error here -- it silently
        yields None (job_status_url becomes None) rather than raising, matching
        copy_project's existing behavior for a copy-job redirect Location.
        """
        if not href:
            return None
        parsed = urlparse(href)
        if parsed.scheme:
            if _origin_from_url(href) != self._origin:
                return None
            return href
        if href.startswith("/"):
            return urljoin(f"{self._origin.rstrip('/')}/", href.lstrip("/"))
        return urljoin(f"{self._base_url.rstrip('/')}/", href)

    def _record(self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> ProjectRecord:
        return ProjectRecord(
            summary=normalize_project(payload, base_url=self._base_url, text_limit=text_limit),
            detail=normalize_project_detail(payload, base_url=self._base_url, text_limit=text_limit),
            payload=payload,
        )

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        text_limit: int | None = FORMATTABLE_LIMIT,
    ) -> ProjectPage:
        filters: list[dict[str, Any]] = []
        if search:
            filters.append({"name_and_identifier": {"operator": "~", "values": [search]}})
        payload = await self._transport.get_json(
            "projects",
            params={
                "offset": str(server_offset),
                "pageSize": str(server_page_size),
                "filters": json.dumps(filters, separators=(",", ":")),
            },
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [
            self._record(item, text_limit=text_limit)
            for item in elements
            if isinstance(item, dict) and item.get("_type") == "Project"
        ]
        total = int(payload.get("total", 0))
        exhausted = server_offset * server_page_size >= total
        return ProjectPage(records=records, server_total=total, exhausted=exhausted)

    async def get(self, project_ref: str, *, text_limit: int | None = FORMATTABLE_LIMIT) -> ProjectRecord:
        payload = await self._transport.get_json(f"projects/{quote(project_ref, safe='')}")
        return self._record(payload, text_limit=text_limit)

    async def create_form(self, payload: dict[str, Any]) -> ProjectFormResult:
        return self._form_result(await self._transport.post_json("projects/form", json_body=payload))

    async def update_form(self, project_id: int, payload: dict[str, Any]) -> ProjectFormResult:
        return self._form_result(await self._transport.post_json(f"projects/{project_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> ProjectDetail:
        response = await self._transport.post_json("projects", json_body=payload)
        return normalize_project_detail(response, base_url=self._base_url)

    async def commit_update(self, project_id: int, payload: dict[str, Any]) -> ProjectDetail:
        response = await self._transport.patch_json(f"projects/{project_id}", json_body=payload)
        return normalize_project_detail(response, base_url=self._base_url)

    async def delete(self, project_id: int) -> None:
        await self._transport.delete(f"projects/{project_id}")

    async def get_schema(self, *, project_id: int | None, draft_payload: dict[str, Any]) -> ProjectSchemaResult:
        if project_id is None:
            form = await self._transport.post_json("projects/form", json_body=draft_payload)
        else:
            form = await self._transport.post_json(f"projects/{project_id}/form", json_body=draft_payload)
        return ProjectSchemaResult(schema=form.get("_embedded", {}).get("schema", {}))

    async def list_available_parent_projects(self, project_id: int, *, schema: dict[str, Any]) -> Sequence[ProjectRef]:
        parent_field = schema.get("parent")
        if not isinstance(parent_field, dict):
            return []
        href = parent_field.get("_links", {}).get("allowedValues", {}).get("href")
        if not href:
            href = f"/api/v3/projects/available_parent_projects?of={project_id}"
        path = self._link_to_api_path(href)
        payload = await self._transport.get_json(path)
        elements = payload.get("_embedded", {}).get("elements", [])
        # Note: caller-side allowlist filtering (Fail closed: a parent-project
        # candidate outside READ_PROJECTS must not leak here) happens in the
        # Service, not this adapter -- the adapter is a dumb HTTP translator.
        return [
            ProjectRef(
                id=int(item["id"]),
                identifier=item.get("identifier"),
                name=_trim_text(item.get("name"), limit=SUBJECT_LIMIT) or f"Project {item['id']}",
                url=urljoin(f"{self._base_url.rstrip('/')}/", f"projects/{item.get('identifier') or item['id']}"),
            )
            for item in elements
            if isinstance(item, dict)
        ]

    async def get_configuration(self, project_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"projects/{project_id}/configuration")

    async def list_phase_definitions(self) -> Sequence[ProjectPhaseDefinition]:
        payload = await self._transport.get_json("project_phase_definitions")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            normalize_project_phase_definition(item, base_url=self._base_url)
            for item in elements
            if isinstance(item, dict) and item.get("_type") == "ProjectPhaseDefinition"
        ]

    async def get_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition:
        payload = await self._transport.get_json(f"project_phase_definitions/{phase_definition_id}")
        return normalize_project_phase_definition(payload, base_url=self._base_url)

    async def get_phase(self, phase_id: int) -> ProjectPhaseRecord:
        payload = await self._transport.get_json(f"project_phases/{phase_id}")
        return ProjectPhaseRecord(
            phase=normalize_project_phase(payload, base_url=self._base_url),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def set_favorite(self, project_id: int, *, favorite: bool) -> None:
        # The favorite endpoint returns 204 with no body -- request_raw (not
        # post_json, which would try to parse the empty body as JSON).
        if favorite:
            await self._transport.request_raw("POST", f"workspaces/{project_id}/favorite", json_body={})
        else:
            await self._transport.request_raw("DELETE", f"workspaces/{project_id}/favorite")

    async def copy_form(self, project_id: int, payload: dict[str, Any]) -> ProjectCopyFormResult:
        form = await self._transport.post_json(f"projects/{project_id}/copy/form", json_body=payload)
        form_payload = form.get("_embedded", {}).get("payload", payload)
        validation_errors = _normalize_validation_errors(form.get("_embedded", {}).get("validationErrors"))
        return ProjectCopyFormResult(payload=form_payload, validation_errors=validation_errors)

    async def commit_copy(self, project_id: int, payload: dict[str, Any]) -> str | None:
        result = await self._transport.request_raw("POST", f"projects/{project_id}/copy", json_body=payload)
        source = result.redirect_headers[0] if result.redirect_headers else result.headers
        return self._link_to_web_url(source.get("location"))

    @staticmethod
    def _form_result(form: dict[str, Any]) -> ProjectFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return ProjectFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
