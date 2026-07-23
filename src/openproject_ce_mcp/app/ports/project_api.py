"""Projects Domain API port (ADR 0001) -- narrow, no universal gateway.

Also holds the pure HAL->model normalize_* translation functions (ADR: "lives in
the Domain API adapter" for Versions, but Ports may not import Adapters and
Services may only import Ports/Policies/Resolvers -- so for Projects, where
ProjectService itself needs to normalize an already-resolved raw payload
without a second port round-trip, these pure functions live here instead,
and HttpxProjectApi imports them FROM this port rather than the reverse).
Contains small, deliberately duplicated private copies of `_trim_text`/
`_normalize_text`/`_trim_text_with_meta`/`_extract_formattable_text_with_meta`/
`_link_title`/`_id_from_href`/`_delimit_user_content` (+ `SUBJECT_LIMIT`) --
duplicated rather than imported from client.py to avoid `app/` importing from
`client.py`. Unify only once every domain has migrated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urljoin

from ...models import (
    OptionValue,
    ProjectDetail,
    ProjectFieldSchema,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectRef,
    ProjectSummary,
)

# Duplicated from httpx_version_api.py's constant of the same name (ADR 0001
# deliberate duplication) -- needed here only as the Protocol's default text_limit.
FORMATTABLE_LIMIT = 1_200
SUBJECT_LIMIT = 255
PROJECT_ANCESTORS_LIMIT = 20


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def _delimit_user_content(text: str | None) -> str | None:
    if text is None or not text.strip():
        return text
    return f"<user-content>{text}</user-content>"


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
    payload: dict[str, Any], *, base_url: str, text_limit: int | None = FORMATTABLE_LIMIT
) -> ProjectDetail:
    """Single-project read. ``text_limit=None`` (used by get_project) returns the
    full description/status_explanation uncapped; the FORMATTABLE_LIMIT default
    keeps write-preview callers capped. Verbatim port of client.py's
    normalize_project_detail, minus hidden-field masking (Service concern).
    """
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


@dataclass(frozen=True)
class ProjectRecord:
    """One project as read from the API: the normalized summary AND detail
    (detail carries fields summary doesn't -- ancestors, an independently
    text_limit'd description/status_explanation -- so it is a real second
    normalization, not derivable from summary alone; see
    normalize_project_detail's ancestors-from-_links.ancestors logic) plus the
    unmodified raw HAL payload (including ``_links``). The raw payload must be
    carried, not just the normalized fields, because several still-flat
    client.py domains (list_project_memberships, get_my_project_access, ...)
    read arbitrary raw ``_links``/fields off a resolved project payload today,
    a contract ProjectResolver.resolve() must keep honoring verbatim.
    """

    summary: ProjectSummary
    detail: ProjectDetail
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProjectPage:
    records: list[ProjectRecord]
    server_total: int | None  # set only by the exact-server-pagination path; None elsewhere
    exhausted: bool  # False if the server page still had more (unscanned) results


@dataclass(frozen=True)
class ProjectFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]


@dataclass(frozen=True)
class ProjectSchemaResult:
    schema: dict[str, Any]


@dataclass(frozen=True)
class ProjectCopyFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]


@dataclass(frozen=True)
class ProjectPhaseRecord:
    """A ProjectPhase plus the raw `_links.project` link it was read with.

    The link must be carried separately (mirrors VersionRecord.defining_project_link)
    because the allowlist check needs the raw link (href/id), which ProjectPhase
    itself (a display-only, already-normalized model) does not carry -- and unlike
    ensure_project_read_allowed's payload-shaped check, this needs
    ensure_project_link_allowed's link-shaped, fail-closed-on-missing-link semantics.
    """

    phase: ProjectPhase
    project_link: dict[str, Any] | None


class ProjectApi(Protocol):
    """Narrow, Projects-only Domain API port. ProjectService/ProjectResolver depend
    on this Protocol, never on HttpxProjectApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        text_limit: int | None = FORMATTABLE_LIMIT,
    ) -> ProjectPage: ...
    async def get(self, project_ref: str, *, text_limit: int | None = FORMATTABLE_LIMIT) -> ProjectRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> ProjectFormResult: ...
    async def update_form(self, project_id: int, payload: dict[str, Any]) -> ProjectFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> ProjectDetail: ...
    async def commit_update(self, project_id: int, payload: dict[str, Any]) -> ProjectDetail: ...
    async def delete(self, project_id: int) -> None: ...
    async def get_schema(self, *, project_id: int | None, draft_payload: dict[str, Any]) -> ProjectSchemaResult: ...
    async def list_available_parent_projects(
        self, project_id: int, *, schema: dict[str, Any]
    ) -> Sequence[ProjectRef]: ...
    async def get_configuration(self, project_id: int) -> dict[str, Any]: ...
    async def list_phase_definitions(self) -> Sequence[ProjectPhaseDefinition]: ...
    async def get_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition: ...
    async def get_phase(self, phase_id: int) -> ProjectPhaseRecord: ...
    async def set_favorite(self, project_id: int, *, favorite: bool) -> None: ...
    async def copy_form(self, project_id: int, payload: dict[str, Any]) -> ProjectCopyFormResult: ...
    async def commit_copy(self, project_id: int, payload: dict[str, Any]) -> str | None: ...
