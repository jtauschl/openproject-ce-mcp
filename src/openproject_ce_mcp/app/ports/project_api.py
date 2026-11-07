"""Projects Domain API port -- narrow, no universal gateway.

Holds only the ProjectApi Protocol and its Result dataclasses (ProjectRecord,
ProjectPage, ProjectFormResult, ProjectSchemaResult, ProjectCopyFormResult,
ProjectPhaseRecord). HAL->model normalize_* translation lives in
HttpxProjectApi (app/adapters/httpx_project_api.py): ProjectService never
normalizes a raw payload itself; it consumes the already-normalized
ProjectRecord that ProjectResolver.resolve_record() forwards from the
adapter (see project_resolver.py's module docstring for how a second
normalization is avoided without a second HTTP round-trip).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import (
    ProjectDetail,
    ProjectFieldSchema,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectRef,
    ProjectSummary,
    SortCriterion,
)
from ..form_result import FormResult
from .scoped_reference import ScopedReference, VisibleReferences

# Deliberately duplicated from httpx_version_api.py's constant of the same
# name -- needed here as the Protocol's default text_limit value.
FORMATTABLE_LIMIT = 1_200


@dataclass(frozen=True)
class ProjectRecord:
    """One project as read from the API.

    `summary` is the identity-grade summary every reader of a project reference uses (id, identifier,
    name, active, status, parent, descriptions): it never carries custom field values, because their
    link titles are decided per result, once the service has judged `references`. A result that shows
    custom fields is built with `scoped_summary` / `scoped_detail`, like `WorkPackageRecord`; the detail
    is a LAZY factory too (a second, independent text extraction with the ancestor chain), called only
    by `get_project` and the write results.

    `references` maps each `customField<N>` that names a version to the references it names, so a
    field a hide setting removes costs no lookup. The raw HAL `payload` (including ``_links``) is carried
    because several callers (list_project_memberships, get_my_project_access, ...) read arbitrary raw
    ``_links``/fields off a resolved project payload, a contract ProjectResolver.resolve() must keep
    honoring.
    """

    summary: ProjectSummary
    references: Mapping[str, frozenset[ScopedReference]]
    payload: dict[str, Any]
    summary_factory: Callable[[VisibleReferences], ProjectSummary]
    detail_factory: Callable[[VisibleReferences], ProjectDetail]

    def scoped_summary(self, *, visible: VisibleReferences) -> ProjectSummary:
        return self.summary_factory(visible)

    def scoped_detail(self, *, visible: VisibleReferences) -> ProjectDetail:
        return self.detail_factory(visible)


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
        custom_field_filters: Sequence[Mapping[str, Any]] = (),
        sort_by: Sequence[SortCriterion] | None = None,
    ) -> ProjectPage: ...
    async def get(self, project_ref: str, *, text_limit: int | None = FORMATTABLE_LIMIT) -> ProjectRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> ProjectFormResult: ...
    async def update_form(self, project_id: int, payload: dict[str, Any]) -> ProjectFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> ProjectRecord: ...
    async def commit_update(self, project_id: int, payload: dict[str, Any]) -> ProjectRecord: ...
    async def delete(self, project_id: int) -> None: ...
    async def get_schema(
        self, *, project_id: int | None, draft_payload: dict[str, Any], custom_field_options: bool = False
    ) -> ProjectSchemaResult: ...
    async def list_available_parent_projects(
        self, project_id: int, *, schema: dict[str, Any]
    ) -> Sequence[ProjectRef]: ...
    async def get_configuration(self, project_id: int) -> dict[str, Any]: ...
    async def list_phase_definitions(self) -> Sequence[ProjectPhaseDefinition]: ...
    async def get_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition: ...
    async def get_phase(self, phase_id: int) -> ProjectPhaseRecord: ...
    async def set_favorite(self, project_id: int, *, favorite: bool) -> None: ...
    async def get_copy_schema(
        self, project_id: int, *, draft_payload: dict[str, Any], custom_field_options: bool = False
    ) -> ProjectSchemaResult: ...
    async def copy_form(self, project_id: int, payload: dict[str, Any]) -> ProjectCopyFormResult: ...
    async def commit_copy(self, project_id: int, payload: dict[str, Any]) -> str | None: ...
