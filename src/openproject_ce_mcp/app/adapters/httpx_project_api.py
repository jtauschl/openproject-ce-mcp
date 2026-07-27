"""HTTP-backed ProjectApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). Owns the pure
normalize_* HAL->model translation functions (matching the Versions domain's
convention: normalize_* live in the adapter, not the port). ProjectService no
longer calls these directly -- it consumes the ProjectRecord that
ProjectResolver.resolve_record() forwards from this adapter's own get()/list()
calls, so no second normalization-without-a-second-HTTP-call concern applies.

`_trim_text`/`_link_title`/`_id_from_href`/`_delimit_user_content`/
`_origin_from_url`/`SUBJECT_LIMIT` are shared via `app/adapters/_text.py`.
Still has its own `_normalize_text`/`_trim_text_with_meta`/
`_extract_formattable_text_with_meta`/`_normalize_validation_errors`
(+ `FORMATTABLE_LIMIT`/`PROJECT_ANCESTORS_LIMIT`) -- these differ
behaviorally from the other adapters' equivalents (see `_text.py`'s module
docstring) and are not shared. A local `_slug_from_href` definition existed
here with zero call sites in this file (found dead during a later
migration's step-6 self-audit, alongside the discovery that this same
helper was byte-identically duplicated in two other adapters) -- removed
rather than imported from `_text.py`, since nothing here actually needs it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from ...models import (
    OptionValue,
    ProjectDetail,
    ProjectFieldSchema,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectRef,
    ProjectSummary,
)
from ..errors import OpenProjectServerError
from ..ports.project_api import (
    ProjectCopyFormResult,
    ProjectFormResult,
    ProjectPage,
    ProjectPhaseRecord,
    ProjectRecord,
    ProjectSchemaResult,
)
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _shared_link_to_web_url
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text

FORMATTABLE_LIMIT = 1_200
PROJECT_ANCESTORS_LIMIT = 20


def _normalize_text(value: Any, *, preserve_newlines: bool) -> str:
    if not preserve_newlines:
        return " ".join(str(value).split())
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = " ".join(line.split())
        if stripped:
            blank_run = 0
            normalized.append(stripped)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def _trim_text_with_meta(
    value: Any, *, limit: int | None, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    if value is None:
        return None, False, None
    text = _normalize_text(value, preserve_newlines=preserve_newlines)
    if not text:
        return None, False, None
    full_length = len(text)
    if limit is None or full_length <= limit:
        return text, False, full_length
    return text[: limit - 1].rstrip() + "…", True, full_length


def _extract_formattable_text_with_meta(
    value: Any, *, limit: int | None = FORMATTABLE_LIMIT, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text_with_meta(raw, limit=limit, preserve_newlines=preserve_newlines)


def normalize_project(
    payload: dict[str, Any], *, base_url: str, text_limit: int | None = FORMATTABLE_LIMIT
) -> ProjectSummary:
    """Pure HAL->model translation. Verbatim port of client.py's normalize_project,
    minus the _apply_hidden_fields call and the hidden-field-aware text extraction --
    hidden-field masking is a Policy/Service decision applied after this returns.

    ``text_limit`` defaults to FORMATTABLE_LIMIT (list-row cap) but callers that
    already resolved a single project (get_configuration, get_admin_context) pass
    a smaller/settings-driven cap explicitly, matching client.py's list_projects
    passing settings.text_limit into normalize_project's underlying calls.
    """
    links = payload.get("_links", {})
    identifier = payload.get("identifier")
    description, description_truncated, description_length = _extract_formattable_text_with_meta(
        payload.get("description"), limit=text_limit
    )
    status_explanation, status_explanation_truncated, status_explanation_length = _extract_formattable_text_with_meta(
        payload.get("statusExplanation"), limit=text_limit
    )
    project_path = f"projects/{identifier or payload['id']}"
    return ProjectSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Project {payload['id']}",
        identifier=identifier,
        active=payload.get("active"),
        description=_delimit_user_content(description),
        description_truncated=description_truncated,
        description_length=description_length,
        url=urljoin(f"{base_url.rstrip('/')}/", project_path),
        public=payload.get("public"),
        status=_link_title(links.get("status")),
        status_explanation=_delimit_user_content(status_explanation),
        status_explanation_truncated=status_explanation_truncated,
        status_explanation_length=status_explanation_length,
        parent_id=_id_from_href(links.get("parent", {}).get("href")),
        parent_name=_link_title(links.get("parent")),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        can_update="update" in links or "updateImmediately" in links,
        can_delete="delete" in links,
        favorited=payload.get("favorited"),
    )


def normalize_project_detail(
    payload: dict[str, Any],
    *,
    base_url: str,
    text_limit: int | None = FORMATTABLE_LIMIT,
    summary: ProjectSummary | None = None,
) -> ProjectDetail:
    """Single-project read. ``text_limit=None`` (used by get_project) returns the
    full description/status_explanation uncapped; the FORMATTABLE_LIMIT default
    keeps write-preview callers capped. Verbatim port of client.py's
    normalize_project_detail, minus hidden-field masking (Service concern).

    `summary` lets a caller that already built a `ProjectSummary` for the
    same payload (see `_record()`) pass it in directly instead of paying for
    a second `normalize_project()` call -- callers with only the raw payload
    omit it and get the summary computed here. Only `description`/
    `status_explanation` are independently re-extracted regardless (with
    `preserve_newlines=True`, a genuinely different extraction than the
    summary's, not just a different truncation limit); every other field is
    a cheap copy off `summary`.
    """
    if summary is None:
        summary = normalize_project(payload, base_url=base_url)
    links = payload.get("_links", {})
    description, description_truncated, description_length = _extract_formattable_text_with_meta(
        payload.get("description"), limit=text_limit, preserve_newlines=True
    )
    status_explanation, status_explanation_truncated, status_explanation_length = _extract_formattable_text_with_meta(
        payload.get("statusExplanation"), limit=text_limit, preserve_newlines=True
    )
    ancestors_raw = links.get("ancestors", [])
    ancestors = None
    ancestors_truncated = False
    if ancestors_raw:
        ancestors = [
            {"href": a.get("href"), "title": a.get("title"), "display_id": a.get("displayId")}
            for a in ancestors_raw[:PROJECT_ANCESTORS_LIMIT]
        ]
        ancestors_truncated = len(ancestors_raw) > PROJECT_ANCESTORS_LIMIT
    return ProjectDetail(
        id=summary.id,
        name=summary.name,
        identifier=summary.identifier,
        active=summary.active,
        description=_delimit_user_content(description),
        description_truncated=description_truncated,
        description_length=description_length,
        url=summary.url,
        public=summary.public,
        status=summary.status,
        status_explanation=_delimit_user_content(status_explanation),
        status_explanation_truncated=status_explanation_truncated,
        status_explanation_length=status_explanation_length,
        parent_id=summary.parent_id,
        parent_name=summary.parent_name,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        favorited=summary.favorited,
        ancestors=ancestors,
        ancestors_truncated=ancestors_truncated,
    )


def normalize_option_value(payload: dict[str, Any]) -> OptionValue:
    href = payload.get("_links", {}).get("self", {}).get("href")
    title = (
        _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
        or _trim_text(payload.get("title"), limit=SUBJECT_LIMIT)
        or _trim_text(payload.get("_links", {}).get("self", {}).get("title"), limit=SUBJECT_LIMIT)
        or "Unnamed"
    )
    raw_id = payload.get("id")
    option_id = int(raw_id) if isinstance(raw_id, int | str) and str(raw_id).isdigit() else _id_from_href(href)
    return OptionValue(id=option_id, title=title, href=href)


def normalize_project_field_schema(key: str, payload: dict[str, Any]) -> ProjectFieldSchema:
    normalized_allowed_values: list[OptionValue] = []
    embedded_allowed = payload.get("_embedded", {}).get("allowedValues", [])
    if isinstance(embedded_allowed, list):
        normalized_allowed_values.extend(
            normalize_option_value(item) for item in embedded_allowed if isinstance(item, dict)
        )
    link_allowed = payload.get("_links", {}).get("allowedValues", [])
    if isinstance(link_allowed, list):
        normalized_allowed_values.extend(
            OptionValue(
                id=_id_from_href(item.get("href")),
                title=_trim_text(item.get("title"), limit=SUBJECT_LIMIT) or "Unnamed",
                href=item.get("href"),
            )
            for item in link_allowed
            if isinstance(item, dict)
        )
    elif isinstance(embedded_allowed, list) and embedded_allowed and isinstance(embedded_allowed[0], str):
        normalized_allowed_values.extend(
            OptionValue(id=None, title=_trim_text(item, limit=SUBJECT_LIMIT) or "Unnamed", href=None)
            for item in embedded_allowed
            if isinstance(item, str)
        )
    return ProjectFieldSchema(
        key=key,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or key,
        type=_trim_text(payload.get("type"), limit=SUBJECT_LIMIT),
        required=bool(payload.get("required")),
        writable=bool(payload.get("writable")),
        has_default=bool(payload.get("hasDefault")),
        location=_trim_text(payload.get("location"), limit=SUBJECT_LIMIT),
        allowed_values=normalized_allowed_values,
    )


def normalize_project_phase_definition(payload: dict[str, Any], *, base_url: str) -> ProjectPhaseDefinition:
    phase_id = int(payload["id"])
    return ProjectPhaseDefinition(
        id=phase_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Phase {phase_id}",
        start_gate=_trim_text(payload.get("startGateName"), limit=SUBJECT_LIMIT),
        finish_gate=_trim_text(payload.get("finishGateName"), limit=SUBJECT_LIMIT),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        url=urljoin(f"{base_url.rstrip('/')}/", f"api/v3/project_phase_definitions/{phase_id}"),
    )


def normalize_project_phase(payload: dict[str, Any], *, base_url: str) -> ProjectPhase:
    phase_id = int(payload["id"])
    links = payload.get("_links", {})
    phase_definition_link = links.get("projectPhaseDefinition")
    return ProjectPhase(
        id=phase_id,
        name=(
            _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
            or _link_title(phase_definition_link)
            or f"Project phase {phase_id}"
        ),
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        phase_definition_id=_id_from_href(phase_definition_link.get("href"))
        if isinstance(phase_definition_link, dict)
        else None,
        phase_definition=_link_title(phase_definition_link),
        start_date=payload.get("startDate"),
        finish_date=payload.get("finishDate"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        url=urljoin(f"{base_url.rstrip('/')}/", f"api/v3/project_phases/{phase_id}"),
    )


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

        Unlike _link_to_api_path, a foreign-origin absolute href is not an
        error here -- it silently yields None (job_status_url becomes None)
        rather than raising, matching copy_project's existing behavior for a
        copy-job redirect Location. Delegates to the shared free function in
        _text.py, which every other adapter's own copy of this helper does
        too -- only the bound-method call shape (closing over self._base_url/
        self._origin instead of taking them as params) is Project-specific.
        """
        return _shared_link_to_web_url(href, base_url=self._base_url, origin=self._origin)

    def _record(self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> ProjectRecord:
        base_url = self._base_url
        summary = normalize_project(payload, base_url=base_url, text_limit=text_limit)
        return ProjectRecord(
            summary=summary,
            # Lazy: most callers (ProjectResolver.resolve()/resolve_id(), used
            # by every domain's project-reference resolution; ProjectService.
            # list()) never read this. The closure captures only
            # `payload`/`base_url`/`text_limit`/`summary` (small, per-record),
            # not `self` -- it does not keep a whole adapter/transport alive.
            # Passing `summary` through avoids re-deriving every OTHER field
            # (id, name, identifier, url, status, parent, ...) a second time;
            # description/status_explanation are still re-extracted
            # independently inside normalize_project_detail regardless
            # (preserve_newlines=True there is a genuinely different
            # extraction, not just a truncation-limit divergence).
            to_detail=lambda: normalize_project_detail(
                payload, base_url=base_url, text_limit=text_limit, summary=summary
            ),
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
        schema = form.get("_embedded", {}).get("schema", {})
        fields = tuple(
            normalize_project_field_schema(key, entry) for key, entry in schema.items() if isinstance(entry, dict)
        )
        return ProjectSchemaResult(schema=schema, fields=fields)

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
