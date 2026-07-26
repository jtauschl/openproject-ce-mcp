"""Projects Domain API port (ADR 0001) -- narrow, no universal gateway.

Holds only the ProjectApi Protocol and its Result dataclasses (ProjectRecord,
ProjectPage, ProjectFormResult, ProjectSchemaResult, ProjectCopyFormResult,
ProjectPhaseRecord). HAL->model normalize_* translation lives in
HttpxProjectApi (app/adapters/httpx_project_api.py), matching the Versions
domain's convention -- ProjectService no longer normalizes a raw payload
itself; it consumes the already-normalized ProjectRecord that
ProjectResolver.resolve_record() forwards from the adapter (see
project_resolver.py's module docstring for how the former "second
normalization without a second HTTP round-trip" concern is resolved).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import (
    ProjectDetail,
    ProjectFieldSchema,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectRef,
    ProjectSummary,
)
from ..form_result import FormResult

# Duplicated from httpx_version_api.py's constant of the same name (ADR 0001
# deliberate duplication) -- needed here as the Protocol's default text_limit value.
FORMATTABLE_LIMIT = 1_200


@dataclass(frozen=True)
class ProjectRecord:
    """One project as read from the API: the normalized summary, a LAZY
    `to_detail` thunk for the richer single-item shape (detail carries fields
    summary doesn't -- ancestors, an independently text_limit'd
    description/status_explanation -- so it is a real second normalization,
    not derivable from summary alone; see normalize_project_detail's
    ancestors-from-_links.ancestors logic), plus the unmodified raw HAL
    payload (including ``_links``). The raw payload must be carried, not just
    the normalized fields, because several still-flat client.py domains
    (list_project_memberships, get_my_project_access, ...) read arbitrary raw
    ``_links``/fields off a resolved project payload today, a contract
    ProjectResolver.resolve() must keep honoring verbatim.

    `to_detail` is a callable, not a precomputed `ProjectDetail` field,
    because most `ProjectRecord` consumers never read it: `ProjectResolver.
    resolve()`/`resolve_id()` (used by EVERY migrated domain's project-
    reference resolution, plus every still-flat client.py domain via the
    `ProjectRefResolver` seam) only ever read `.payload`, and
    `ProjectService.list()` only ever reads `.summary`. Precomputing detail
    eagerly on every `_record()` build -- as this used to do -- ran a second,
    independent text-extraction pass over every resolved/listed project's
    description AND status_explanation, plus rebuilt its ancestors list, for
    a value almost no caller reads. Only `ProjectService.get()` (the single-
    item read path) calls `to_detail()`.
    """

    summary: ProjectSummary
    to_detail: Callable[[], ProjectDetail]
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProjectPage:
    records: list[ProjectRecord]
    server_total: int | None  # set only by the exact-server-pagination path; None elsewhere
    exhausted: bool  # False if the server page still had more (unscanned) results


ProjectFormResult = FormResult


@dataclass(frozen=True)
class ProjectSchemaResult:
    """The raw schema dict (used by write-payload builders) plus the same schema
    already normalized into ProjectFieldSchema entries (used by
    ProjectAdminService.get_admin_context(), which must not import the
    normalize_* functions living in the adapter -- see module docstring).
    """

    schema: dict[str, Any]
    fields: tuple[ProjectFieldSchema, ...]


ProjectCopyFormResult = FormResult


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
