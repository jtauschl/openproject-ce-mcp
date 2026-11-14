from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings
from _project_record_helpers import project_record

from openproject_ce_mcp.app.adapters.httpx_project_api import (
    HttpxProjectApi,
    normalize_project_detail,
    normalize_project_field_schema,
)
from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.form_result import ValidationFailure
from openproject_ce_mcp.app.ports.project_api import (
    ProjectCopyFormResult,
    ProjectFormResult,
    ProjectPage,
    ProjectPhaseDefinition,
    ProjectPhaseRecord,
    ProjectRecord,
    ProjectRef,
    ProjectSchemaResult,
)
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference, VisibleReferences
from openproject_ce_mcp.app.resolvers.project_resolver import ProjectResolver
from openproject_ce_mcp.app.services.project_service import ProjectAdminService, ProjectService
from openproject_ce_mcp.models import ProjectPhase, ProjectSummary, SortCriterion
from openproject_ce_mcp.presentation import _to_payload


def _payload(project_id: int = 6, name: str = "Demo Project", identifier: str = "demo", **extra) -> dict:
    payload = {
        "id": project_id,
        "_type": "Project",
        "name": name,
        "identifier": identifier,
        "active": True,
        "description": {"raw": "Some description"},
        "statusExplanation": {"raw": "Some explanation"},
        "_links": {},
    }
    payload.update(extra)
    return payload


def _summary(project_id: int = 6, name: str = "Demo Project", identifier: str = "demo") -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        name=name,
        identifier=identifier,
        active=True,
        description=None,
    )


def _record(project_id: int = 6, name: str = "Demo Project", identifier: str = "demo") -> ProjectRecord:
    summary = _summary(project_id, name, identifier)
    return project_record(summary, payload=_payload(project_id, name, identifier))


def _written_record(payload: dict) -> ProjectRecord:
    detail = normalize_project_detail(payload)
    return project_record(detail, detail=detail, payload=payload)


class _FakeProjectApi:
    def __init__(self, records: list[ProjectRecord] | None = None) -> None:
        self._records = records or [_record()]
        self.get_calls: list[str] = []
        self.list_calls: list[dict] = []
        self.list_raises: Exception | None = None
        self.copy_schema: dict | None = None
        self.copy_form_calls: list[dict] = []
        self.update_form_calls: list[dict] = []
        self.configuration: dict = {"maximumAttachmentFileSize": 100}
        self.schema: dict = {"status": {"name": "Status", "writable": True, "_embedded": {"allowedValues": []}}}
        # None (default) means get_schema() derives fields from self.schema, as
        # the real adapter does. Set explicitly to a value that deliberately
        # does NOT match self.schema to prove a consumer uses the ProjectSchemaResult
        # it was handed rather than re-normalizing self.schema itself.
        self.fields: tuple | None = None
        self.parent_projects: list[ProjectRef] = []
        self.phase_definitions: list[ProjectPhaseDefinition] = []
        self.phase_record: ProjectPhaseRecord | None = None
        self.validation_errors: dict[str, ValidationFailure] = {}
        self.copy_validation_errors: dict[str, ValidationFailure] = {}
        # What the real forms add to the echoed payload: the whole project, attributes included.
        self.form_echo: dict = {}
        self.schema_reads: list[dict] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.favorite_calls: list[tuple[int, bool]] = []
        self.commit_copy_calls: list[tuple[int, dict]] = []
        self.job_status_url: str | None = "https://op.example.com/api/v3/projects/6/copy/status/1"

    async def list(
        self, *, server_offset: int, server_page_size: int, search: str | None, text_limit=None, **query
    ) -> ProjectPage:
        self.list_calls.append(query)
        if self.list_raises is not None:
            raise self.list_raises
        return ProjectPage(records=self._records, server_total=len(self._records), exhausted=True)

    async def get(self, project_ref: str, *, text_limit=None) -> ProjectRecord:
        self.get_calls.append(project_ref)
        for record in self._records:
            if str(record.summary.id) == project_ref or record.summary.identifier == project_ref:
                return record
        raise AssertionError(f"no fake record for ref {project_ref}")

    async def create_form(self, payload) -> ProjectFormResult:
        return ProjectFormResult(payload={**self.form_echo, **payload}, validation_errors=self.validation_errors)

    async def update_form(self, project_id, payload) -> ProjectFormResult:
        self.update_form_calls.append(payload)
        return ProjectFormResult(payload={**self.form_echo, **payload}, validation_errors=self.validation_errors)

    async def commit_create(self, payload) -> ProjectRecord:
        self.commit_create_calls.append(payload)
        return _written_record(_payload(name=payload.get("name", "Demo Project")))

    async def commit_update(self, project_id, payload) -> ProjectRecord:
        self.commit_update_calls.append((project_id, payload))
        return _written_record(_payload(project_id=project_id, name=payload.get("name", "Demo Project")))

    async def delete(self, project_id) -> None:
        self.delete_calls.append(project_id)

    async def get_schema(self, *, project_id, draft_payload, **kwargs) -> ProjectSchemaResult:
        self.schema_reads.append(kwargs)
        if self.fields is not None:
            fields = self.fields
        else:
            fields = tuple(
                normalize_project_field_schema(key, entry)
                for key, entry in self.schema.items()
                if isinstance(entry, dict)
            )
        return ProjectSchemaResult(schema=self.schema, fields=fields)

    async def list_available_parent_projects(self, project_id, *, schema):
        return self.parent_projects

    async def get_configuration(self, project_id) -> dict:
        return self.configuration

    async def list_phase_definitions(self):
        return self.phase_definitions

    async def get_phase_definition(self, phase_definition_id) -> ProjectPhaseDefinition:
        return self.phase_definitions[0]

    async def get_phase(self, phase_id) -> ProjectPhaseRecord:
        assert self.phase_record is not None
        return self.phase_record

    async def set_favorite(self, project_id, *, favorite) -> None:
        self.favorite_calls.append((project_id, favorite))

    async def get_copy_schema(self, project_id, *, draft_payload, **kwargs) -> ProjectSchemaResult:
        assert self.copy_schema is not None, "the copy schema was not expected to be read"
        fields = tuple(
            normalize_project_field_schema(key, entry)
            for key, entry in self.copy_schema.items()
            if isinstance(entry, dict)
        )
        return ProjectSchemaResult(schema=self.copy_schema, fields=fields)

    async def copy_form(self, project_id, payload) -> ProjectCopyFormResult:
        self.copy_form_calls.append(payload)
        return ProjectCopyFormResult(
            payload={**self.form_echo, **payload}, validation_errors=self.copy_validation_errors
        )

    async def commit_copy(self, project_id, payload) -> str | None:
        self.commit_copy_calls.append((project_id, payload))
        return self.job_status_url


def _resolver(api: _FakeProjectApi, *, settings=None) -> ProjectResolver:
    return ProjectResolver(api=api, settings=settings or make_settings())


async def _all_references_allowed(references):
    return dict.fromkeys(references, True)


def _service(api: _FakeProjectApi | None = None, *, settings=None, references_allowed=None) -> ProjectService:
    api = api or _FakeProjectApi()
    settings = settings or make_settings()
    return ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier={},
        resolver=_resolver(api, settings=settings),
        references_allowed=references_allowed or _all_references_allowed,
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_get_description_hidden_by_project_scope_not_project_configuration_scope() -> None:
    """Regression test for the entity-scope class of bug found via News'
    hotfix and Documents' equivalent: a field must only be masked by
    its OWN domain's OPENPROJECT_HIDE_<ENTITY>_FIELDS scope, never by a
    same-named field under a different, similarly-named scope (here
    "project_configuration", the nearest same-prefixed sibling entity).
    """
    settings_configuration_hidden = dataclasses.replace(
        make_settings(), hidden_fields={"project_configuration": ("description",)}
    )
    service_configuration_hidden = _service(settings=settings_configuration_hidden)
    result_configuration_hidden = await service_configuration_hidden.get("demo")
    assert getattr(result_configuration_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_project_hidden = dataclasses.replace(make_settings(), hidden_fields={"project": ("description",)})
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get("demo")
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == {"description"}


def _admin_service(
    api: _FakeProjectApi | None = None, *, settings=None, references_allowed=None
) -> ProjectAdminService:
    api = api or _FakeProjectApi()
    settings = settings or make_settings()
    return ProjectAdminService(
        api=api,
        settings=settings,
        project_id_to_identifier={},
        resolver=_resolver(api, settings=settings),
        references_allowed=references_allowed or _all_references_allowed,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    service = _service()

    result = await service.list()

    assert result.total == 1
    assert result.results[0].id == 6


@pytest.mark.asyncio
async def test_get_returns_detail_with_full_text_uncapped() -> None:
    service = _service()

    detail = await service.get("demo")

    assert detail.identifier == "demo"


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get("demo")

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_get_configuration_returns_normalized_configuration() -> None:
    service = _service()

    config = await service.get_configuration("demo")

    assert config.project_id == 6
    assert config.maximum_attachment_file_size_bytes == 100


@pytest.mark.asyncio
async def test_get_configuration_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"project_configuration": ("duration_format",)})
    service = _service(settings=settings)

    config = await service.get_configuration("demo")

    assert getattr(config, "_hidden_keys", frozenset()) == {"duration_format"}


@pytest.mark.asyncio
async def test_list_phase_definitions_applies_hidden_field_masking() -> None:
    api = _FakeProjectApi()
    api.phase_definitions = [
        ProjectPhaseDefinition(id=1, name="Init", start_gate=None, finish_gate=None, created_at=None, updated_at=None)
    ]
    settings = dataclasses.replace(make_settings(), hidden_fields={"project_phase_definition": ("start_gate",)})
    service = _service(api, settings=settings)

    result = await service.list_phase_definitions()

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"start_gate"}


@pytest.mark.asyncio
async def test_get_phase_applies_hidden_field_masking() -> None:
    api = _FakeProjectApi()
    api.phase_record = _phase_record(project_link={"href": "/api/v3/projects/6", "title": "Demo"})
    settings = dataclasses.replace(
        make_settings(), read_projects=("*",), hidden_fields={"project_phase": ("phase_definition",)}
    )
    service = _service(api, settings=settings)

    phase = await service.get_phase(3)

    assert getattr(phase, "_hidden_keys", frozenset()) == {"phase_definition"}


@pytest.mark.asyncio
async def test_list_phase_definitions_returns_wrapped_result() -> None:
    api = _FakeProjectApi()
    api.phase_definitions = [
        ProjectPhaseDefinition(id=1, name="Init", start_gate=None, finish_gate=None, created_at=None, updated_at=None)
    ]
    service = _service(api)

    result = await service.list_phase_definitions()

    assert result.count == 1
    assert result.results[0].id == 1


def _phase_record(*, project_link: dict | None) -> ProjectPhaseRecord:
    return ProjectPhaseRecord(
        phase=ProjectPhase(
            id=3,
            name="Build",
            project_id=6,
            project="Demo",
            phase_definition_id=None,
            phase_definition=None,
            active=True,
            start_date=None,
            finish_date=None,
            created_at=None,
            updated_at=None,
        ),
        project_link=project_link,
    )


@pytest.mark.asyncio
async def test_get_phase_checks_project_read_allowlist() -> None:
    api = _FakeProjectApi()
    api.phase_record = _phase_record(project_link={"href": "/api/v3/projects/6", "title": "Demo"})
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get_phase(3)


@pytest.mark.asyncio
async def test_get_phase_fails_closed_when_project_link_is_missing() -> None:
    api = _FakeProjectApi()
    api.phase_record = _phase_record(project_link=None)
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get_phase(3)


@pytest.mark.asyncio
async def test_get_phase_returns_stamped_phase_when_allowed() -> None:
    api = _FakeProjectApi()
    api.phase_record = _phase_record(project_link={"href": "/api/v3/projects/6", "title": "Demo"})
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api, settings=settings)

    phase = await service.get_phase(3)

    assert phase.id == 3


@pytest.mark.asyncio
async def test_stamp_zeroes_hidden_description_metadata() -> None:
    settings = dataclasses.replace(make_settings(), hide_project_fields=("description",))
    service = _service(settings=settings)

    detail = await service.get("demo")

    assert detail.description_truncated is False
    assert detail.description_length is None


@pytest.mark.asyncio
async def test_stamp_zeroes_hidden_status_explanation_metadata() -> None:
    settings = dataclasses.replace(make_settings(), hide_project_fields=("status_explanation",))
    service = _service(settings=settings)

    detail = await service.get("demo")

    assert detail.status_explanation_truncated is False
    assert detail.status_explanation_length is None


@pytest.mark.asyncio
async def test_get_admin_context_includes_writable_fields_and_parent_projects() -> None:
    api = _FakeProjectApi()
    api.parent_projects = [ProjectRef(id=1, identifier="root", name="Root")]
    service = _admin_service(api)

    context = await service.get_admin_context("demo")

    assert context.project is not None
    assert context.project.id == 6
    assert len(context.available_parent_projects) == 1
    assert any(field.key == "status" for field in context.fields)


@pytest.mark.asyncio
async def test_get_admin_context_filters_parent_projects_by_read_allowlist() -> None:
    """Regression: a parent-project candidate outside OPENPROJECT_READ_PROJECTS
    must not leak its name/identifier through this picklist just because it's
    a valid value for the parent field -- same allowlist every other
    project-returning path already applies. Fail closed: a disallowed
    candidate is dropped entirely, not just its full detail."""
    api = _FakeProjectApi()
    api.parent_projects = [
        ProjectRef(id=1, identifier="root", name="Root"),
        ProjectRef(id=2, identifier="secret", name="Secret"),
    ]
    settings = dataclasses.replace(make_settings(), read_projects=("demo", "root"))
    service = _admin_service(api, settings=settings)

    context = await service.get_admin_context("demo")

    assert [ref.identifier for ref in context.available_parent_projects] == ["root"]


@pytest.mark.asyncio
async def test_get_admin_context_masks_hidden_fields_on_parent_project_candidates() -> None:
    """Regression: OPENPROJECT_HIDE_PROJECT_FIELDS must apply to each
    available_parent_projects candidate the same way it applies to
    get_project/list_projects -- this picklist must not be a side channel
    that bypasses field-level masking just because it returns ProjectRef
    instead of ProjectSummary. The allowlist filter (previous test) and
    field-level masking (this test) are independent controls."""
    api = _FakeProjectApi()
    api.parent_projects = [ProjectRef(id=1, identifier="root", name="Root")]
    settings = dataclasses.replace(make_settings(), hidden_fields={"project": ("name",)})
    service = _admin_service(api, settings=settings)

    context = await service.get_admin_context("demo")

    assert len(context.available_parent_projects) == 1
    payload = _to_payload(context.available_parent_projects[0])
    assert "name" not in payload
    assert payload["identifier"] == "root"


@pytest.mark.asyncio
async def test_get_admin_context_zeroes_hidden_description_metadata_on_embedded_project() -> None:
    settings = dataclasses.replace(make_settings(), hide_project_fields=("description",))
    service = _admin_service(settings=settings)

    context = await service.get_admin_context("demo")

    assert context.project is not None
    assert context.project.description_truncated is False
    assert context.project.description_length is None


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    api = _FakeProjectApi()
    service = _service(api)

    result = await service.create(name="New Project", identifier="new-project", confirm=False)

    assert result.ready is True
    assert result.state == "preview"
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.create(name="New Project", identifier="new-project", confirm=True)

    assert result.state == "confirmed"
    assert result.result is not None
    assert len(api.commit_create_calls) == 1


@pytest.mark.asyncio
async def test_create_rejects_when_validation_errors_present() -> None:
    api = _FakeProjectApi()
    api.validation_errors = {"name": ValidationFailure("too short")}
    service = _service(api)

    result = await service.create(name="x", identifier="x", confirm=True)

    assert result.ready is False
    assert result.state == "invalid"
    assert result.validation_errors == {"name": ValidationFailure("too short")}
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="New Project", identifier="new-project", confirm=False)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True, hidden_fields={"project": ("name",)})
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_identifier_field_is_hidden() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_project_write=True, hidden_fields={"project": ("identifier",)}
    )
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_description_field_is_hidden() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_project_write=True, hidden_fields={"project": ("description",)}
    )
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", description="notes", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_public_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True, hidden_fields={"project": ("public",)})
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", public=True, confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_active_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True, hidden_fields={"project": ("active",)})
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", active=True, confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_status_explanation_field_is_hidden() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_project_write=True, hidden_fields={"project": ("status_explanation",)}
    )
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", status_explanation="on track", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_status_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True, hidden_fields={"project": ("status",)})
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New Project", identifier="new-project", status="on_track", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_a_written_field_is_hidden() -> None:
    # _build_write_payload is shared between create()/update() -- one
    # representative field is enough here since create()'s tests above
    # already exercise every field through the same shared helper.
    settings = dataclasses.replace(make_settings(), enable_project_write=True, hidden_fields={"project": ("name",)})
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(project_ref="demo", name="Renamed", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.update(project_ref="demo", name="Renamed", confirm=True)

    assert result.state == "confirmed"
    assert result.result is not None
    assert len(api.commit_update_calls) == 1
    assert api.commit_update_calls[0][0] == 6


@pytest.mark.asyncio
async def test_update_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(project_ref="demo", name="Renamed", confirm=False)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_denies_reparent_into_a_project_outside_write_allowlist() -> None:
    """Regression test: reparenting must be write-authorized on the NEW
    parent too, not just on the project being updated. A caller with write
    access to "demo" must not be able to attach it under "root" when they
    only have read access there -- the same gap update_board's reparent-
    target fix already closed for boards.
    """
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    api = _FakeProjectApi(records=[_record(project_id=6, identifier="demo"), _record(project_id=1, identifier="root")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(project_ref="demo", parent="root", confirm=False)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_allows_reparent_into_a_project_inside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo", "root"))
    api = _FakeProjectApi(records=[_record(project_id=6, identifier="demo"), _record(project_id=1, identifier="root")])
    service = _service(api, settings=settings)

    result = await service.update(project_ref="demo", parent="root", confirm=False)

    assert result.ready


@pytest.mark.asyncio
async def test_update_builds_parent_href_from_this_service_s_own_api_prefix() -> None:
    """Regression test for the _api_href unification: the parent
    link's href must use THIS service's own api_prefix, not a hardcoded
    "/api/v3/" -- a non-default prefix here would silently pass if the
    prefix argument were ever dropped.
    """
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo", "root"))
    api = _FakeProjectApi(records=[_record(project_id=6, identifier="demo"), _record(project_id=1, identifier="root")])
    resolver = _resolver(api, settings=settings)
    service = ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier={},
        resolver=resolver,
        references_allowed=_all_references_allowed,
        api_prefix="/custom/v9/",
    )

    result = await service.update(project_ref="demo", parent="root", confirm=False)

    assert result.payload["_links"]["parent"]["href"] == "/custom/v9/projects/1"


@pytest.mark.asyncio
async def test_create_preview_does_not_write_to_the_cache() -> None:
    api = _FakeProjectApi()
    project_id_to_identifier: dict[int, str] = {}
    service = ProjectService(
        api=api,
        settings=make_settings(),
        project_id_to_identifier=project_id_to_identifier,
        resolver=_resolver(api),
        references_allowed=_all_references_allowed,
        api_prefix="/api/v3/",
    )

    await service.create(name="New Project", identifier="new-project", confirm=False)

    assert project_id_to_identifier == {}


@pytest.mark.asyncio
async def test_update_preview_does_not_write_to_the_cache() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    project_id_to_identifier: dict[int, str] = {}
    service = ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier=project_id_to_identifier,
        resolver=_resolver(api, settings=settings),
        references_allowed=_all_references_allowed,
        api_prefix="/api/v3/",
    )

    await service.update(project_ref="demo", name="Renamed", confirm=False)

    assert project_id_to_identifier == {}


@pytest.mark.asyncio
async def test_delete_returns_preview_then_commits() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    preview = await service.delete(project_ref="demo", confirm=False)
    assert preview.ready is True
    assert preview.state == "preview"
    assert api.delete_calls == []

    committed = await service.delete(project_ref="demo", confirm=True)
    assert committed.state == "confirmed"
    assert committed.result is None
    assert api.delete_calls == [6]


@pytest.mark.asyncio
async def test_delete_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(project_ref="demo", confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_set_favorite_returns_preview_then_commits() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    preview = await service.set_favorite("demo", favorite=True, confirm=False)
    assert preview.state == "preview"
    assert api.favorite_calls == []

    committed = await service.set_favorite("demo", favorite=True, confirm=True)
    assert committed.state == "confirmed"
    assert api.favorite_calls == [(6, True)]


@pytest.mark.asyncio
async def test_set_favorite_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.set_favorite("demo", favorite=True, confirm=False)

    assert api.favorite_calls == []


@pytest.mark.asyncio
async def test_copy_returns_preview_without_committing() -> None:
    api = _FakeProjectApi()
    service = _service(api)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=False)

    assert result.state == "preview"
    assert api.commit_copy_calls == []


@pytest.mark.asyncio
async def test_copy_commits_and_derives_job_status_id_without_exposing_the_url() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=True)

    assert result.state == "confirmed"
    # job_status_id is derived from the job_status_url internally (get_job_status
    # is the intended follow-up call), but the redundant url itself is no
    # longer part of the response -- a deliberate token-reduction bugfix.
    assert result.job_status_id == "1"
    assert not hasattr(result, "job_status_url")
    assert len(api.commit_copy_calls) == 1


@pytest.mark.asyncio
async def test_copy_confirmed_with_validation_errors_never_commits() -> None:
    """`copy()` is hand-rolled (no shared `_finalize_write`,
    since it launches an async job rather than returning a detail record),
    so this invariant -- OpenProject's own form validation errors must never
    reach the mutating call, even with confirm=true -- needs its own direct
    test rather than being proven generically."""
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    api.copy_validation_errors = {"identifier": ValidationFailure("has already been taken")}
    service = _service(api, settings=settings)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=True)

    assert result.state == "invalid"
    assert result.ready is False
    assert api.commit_copy_calls == []


@pytest.mark.asyncio
async def test_copy_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=False)

    assert api.commit_copy_calls == []


@pytest.mark.asyncio
async def test_build_write_payload_rejects_hidden_field() -> None:
    from openproject_ce_mcp.app.errors import InvalidInputError

    settings = dataclasses.replace(make_settings(), enable_project_write=True, hide_project_fields=("description",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="New", identifier="new", description="secret", confirm=False)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_get_resolves_project_exactly_once() -> None:
    api = _FakeProjectApi()
    service = _service(api)

    await service.get("demo")

    assert api.get_calls == ["demo"]


@pytest.mark.asyncio
async def test_update_resolves_project_exactly_once() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    await service.update(project_ref="demo", name="Renamed", confirm=True)

    assert api.get_calls == ["demo"]
    assert len(api.commit_update_calls) == 1


@pytest.mark.asyncio
async def test_delete_resolves_project_exactly_once() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    await service.delete(project_ref="demo", confirm=True)

    assert api.get_calls == ["demo"]
    assert api.delete_calls == [6]


@pytest.mark.asyncio
async def test_copy_resolves_source_project_exactly_once() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=True)

    assert api.get_calls == ["demo"]
    assert len(api.commit_copy_calls) == 1


@pytest.mark.asyncio
async def test_get_admin_context_resolves_project_exactly_once() -> None:
    api = _FakeProjectApi()
    service = _admin_service(api)

    await service.get_admin_context("demo")

    assert api.get_calls == ["demo"]


@pytest.mark.asyncio
async def test_get_schema_fields_matches_embedded_linked_and_string_allowed_values() -> None:
    api = _FakeProjectApi()
    api.schema = {
        "status": {
            "name": "Status",
            "writable": True,
            "_embedded": {"allowedValues": [{"id": 1, "name": "Open"}]},
        },
        "priority": {
            "name": "Priority",
            "writable": True,
            "_links": {"allowedValues": [{"href": "/api/v3/priorities/2", "title": "High"}]},
        },
        # normalize_project_field_schema's string-shaped-allowedValues branch is
        # unreachable in practice: payload.get("_links", {}) always defaults to
        # {}, so `_links.allowedValues` is always present as [] and the plain
        # `if isinstance(link_allowed, list)` branch always wins over the
        # `elif`. This field documents that pre-existing (unchanged by this
        # migration) behavior rather than asserting a string-normalization
        # outcome that never actually occurs.
        "category": {
            "name": "Category",
            "writable": True,
            "_embedded": {"allowedValues": ["Bug", "Feature"]},
        },
        # A non-dict schema entry must be skipped, not raise.
        "_type": "Schema",
    }
    service = _admin_service(api)

    context = await service.get_admin_context("demo")

    fields_by_key = {field.key: field for field in context.fields}
    assert set(fields_by_key) == {"status", "priority", "category"}
    assert [v.title for v in fields_by_key["status"].allowed_values] == ["Open"]
    assert [v.title for v in fields_by_key["priority"].allowed_values] == ["High"]
    assert fields_by_key["category"].allowed_values == []


@pytest.mark.asyncio
async def test_get_admin_context_consumes_schema_result_fields_without_renormalizing() -> None:
    api = _FakeProjectApi()
    # `schema` and `fields` are deliberately inconsistent: schema describes a
    # "status" field, but the pre-normalized `fields` the fake API hands back
    # describes an unrelated "sentinel" field instead. If get_admin_context()
    # re-normalized `schema_result.schema` itself instead of consuming
    # `schema_result.fields` as-is, the assertion below would see "status",
    # not "sentinel", and fail -- a re-normalizing regression can't pass this
    # test by coincidence, unlike a version where schema and fields matched.
    api.schema = {"status": {"name": "Status", "writable": True, "_embedded": {"allowedValues": []}}}
    sentinel_field = normalize_project_field_schema("sentinel", {"name": "Sentinel", "writable": True})
    api.fields = (sentinel_field,)
    service = _admin_service(api)

    context = await service.get_admin_context("demo")

    assert context.fields == [sentinel_field]


def test_project_service_module_does_not_define_normalizer_names() -> None:
    from openproject_ce_mcp.app.services import project_service

    normalizer_names = {
        "normalize_project",
        "normalize_project_detail",
        "normalize_option_value",
        "normalize_project_field_schema",
        "normalize_project_phase_definition",
        "normalize_project_phase",
    }
    assert not normalizer_names & set(dir(project_service))


def _record_below(parent: tuple[int, str] | None, ancestors: list[tuple[int, str]]) -> ProjectRecord:
    links: dict = {}
    if parent is not None:
        links["parent"] = {"href": f"/api/v3/projects/{parent[0]}", "title": parent[1]}
    if ancestors:
        links["ancestors"] = [{"href": f"/api/v3/projects/{pid}", "title": title} for pid, title in ancestors]
    payload = _payload(_links=links)
    detail = normalize_project_detail(payload)
    return project_record(detail, detail=detail, payload=payload)


def _scoped_service(record: ProjectRecord, *, read, known=None) -> ProjectService:
    api = _FakeProjectApi([record])
    settings = dataclasses.replace(make_settings(), read_projects=read)
    return ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier={6: "demo", **(known or {})},
        resolver=_resolver(api, settings=settings),
        references_allowed=_all_references_allowed,
        api_prefix="/api/v3/",
    )


_BELOW_SECRET = [(1, "Secret Root"), (2, "Open Middle"), (3, "Secret Branch")]


@pytest.mark.asyncio
async def test_get_leaves_out_parents_the_read_scope_does_not_cover() -> None:
    record = _record_below((3, "Secret Branch"), _BELOW_SECRET)
    service = _scoped_service(record, read=("demo", "open-middle"), known={2: "open-middle"})

    project = await service.get("demo")

    assert (project.parent_id, project.parent_name) == (None, None)
    assert project.ancestors == [{"href": "/api/v3/projects/2", "title": "Open Middle", "display_id": None}]


@pytest.mark.asyncio
async def test_get_drops_the_whole_ancestor_chain_when_none_is_covered() -> None:
    project = await _scoped_service(_record_below((3, "Secret Branch"), _BELOW_SECRET), read=("demo",)).get("demo")

    assert project.ancestors is None


@pytest.mark.asyncio
async def test_a_covered_parent_stays_but_only_when_its_identifier_is_known() -> None:
    record = _record_below((2, "Open Middle"), [])

    known = await _scoped_service(record, read=("demo", "om-ident"), known={2: "om-ident"}).get("demo")
    unknown = await _scoped_service(record, read=("demo", "om-ident")).get("demo")

    assert (known.parent_id, known.parent_name) == (2, "Open Middle")
    assert (unknown.parent_id, unknown.parent_name) == (None, None)


@pytest.mark.asyncio
async def test_a_parent_is_never_covered_by_its_name() -> None:
    record = _record_below((2, "Open Middle"), [])

    project = await _scoped_service(record, read=("demo", "Open Middle", "open-middle"), known={2: "om-ident"}).get(
        "demo"
    )

    assert (project.parent_id, project.parent_name) == (None, None)


@pytest.mark.asyncio
async def test_a_parent_named_by_the_scope_pattern_stays_under_every_project_scope() -> None:
    record = _record_below((3, "Secret Branch"), _BELOW_SECRET)

    project = await _scoped_service(record, read=("*",)).get("demo")

    assert (project.parent_id, project.parent_name) == (3, "Secret Branch")
    assert [entry["title"] for entry in project.ancestors] == ["Secret Root", "Open Middle", "Secret Branch"]


@pytest.mark.asyncio
async def test_list_leaves_out_an_uncovered_parent() -> None:
    result = await _scoped_service(_record_below((3, "Secret Branch"), []), read=("demo",)).list()

    assert [(row.parent_id, row.parent_name) for row in result.results] == [(None, None)]


@pytest.mark.asyncio
async def test_admin_context_leaves_out_an_uncovered_parent_of_its_project() -> None:
    record = _record_below((3, "Secret Branch"), [])
    api = _FakeProjectApi([record])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = ProjectAdminService(
        api=api,
        settings=settings,
        project_id_to_identifier={6: "demo"},
        resolver=_resolver(api, settings=settings),
        references_allowed=_all_references_allowed,
    )

    context = await service.get_admin_context("demo")

    assert (context.project.parent_id, context.project.parent_name) == (None, None)


class _CopyFormWithParent(_FakeProjectApi):
    async def copy_form(self, project_id, payload) -> ProjectCopyFormResult:
        links = {
            "parent": {"href": "/api/v3/projects/9", "title": "Secret parent"},
            "status": {"href": "/api/v3/project_statuses/on_track", "title": "On track"},
        }
        return ProjectCopyFormResult(payload={"name": "Copy", "_links": links}, validation_errors={})


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_copy_shows_no_title_of_a_link_into_another_project_and_commits_the_form_payload(confirm) -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _CopyFormWithParent()
    service = _service(api, settings=settings)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=confirm)

    assert result.payload["_links"]["parent"] == {"href": "/api/v3/projects/9"}
    assert result.payload["_links"]["status"]["title"] == "On track"
    if confirm:
        assert api.commit_copy_calls[0][1]["_links"]["parent"]["title"] == "Secret parent"


@pytest.mark.asyncio
async def test_admin_context_leaves_out_versions_defined_in_projects_the_read_scope_does_not_cover() -> None:
    def version(version_id: int, name: str, project_id: int | None) -> dict:
        links: dict = {"self": {"href": f"/api/v3/versions/{version_id}", "title": name}}
        if project_id is not None:
            links["definingProject"] = {"href": f"/api/v3/projects/{project_id}"}
        return {"_type": "Version", "id": version_id, "name": name, "_links": links}

    api = _FakeProjectApi()
    api.schema = {
        "customField3": {
            "name": "Target",
            "type": "Version",
            "writable": True,
            "_embedded": {
                "allowedValues": [version(1, "Own", 6), version(2, "Shared in", 9), version(3, "Unlinked", None)]
            },
        }
    }
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = ProjectAdminService(
        api=api,
        settings=settings,
        project_id_to_identifier={6: "demo"},
        resolver=_resolver(api, settings=settings),
        references_allowed=_all_references_allowed,
    )

    context = await service.get_admin_context("demo")

    (field,) = [f for f in context.fields if f.key == "customField3"]
    assert [value.title for value in field.allowed_values] == ["Own"]


@pytest.mark.asyncio
async def test_a_cut_ancestor_chain_does_not_stay_flagged_truncated_once_entries_are_left_out() -> None:
    record = _record_below((3, "Secret Branch"), _BELOW_SECRET)
    detail = dataclasses.replace(record.scoped_detail(visible=VisibleReferences.everything()), ancestors_truncated=True)
    record = project_record(detail, detail=detail, payload=record.payload)

    kept_nothing_out = await _scoped_service(record, read=("*",)).get("demo")
    left_some_out = await _scoped_service(record, read=("demo", "open-middle"), known={2: "open-middle"}).get("demo")

    assert kept_nothing_out.ancestors_truncated is True
    assert left_some_out.ancestors_truncated is False


@pytest.mark.asyncio
async def test_an_ancestor_without_an_id_stays_under_every_project_scope() -> None:
    links = {"ancestors": [{"href": "urn:openproject-org:api:v3:undisclosed", "title": "Hidden"}]}
    payload = _payload(_links=links)
    detail = normalize_project_detail(payload)
    record = project_record(detail, detail=detail, payload=payload)

    project = await _scoped_service(record, read=("*",)).get("demo")

    assert project.ancestors is not None
    assert len(project.ancestors) == 1


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_PROJECT_READ"):
        await service.list()


# --- project attributes (custom fields): read masking, scope, write, list query -------------------------

_SECRET_VERSION = ScopedReference("version", 7)


def _attribute_record(project_id: int = 6, identifier: str = "demo", **extra) -> ProjectRecord:
    """A record built by the real adapter from a payload that carries project attributes."""
    payload = _payload(project_id=project_id, identifier=identifier, **extra)
    payload["customField1"] = "Alpha"
    payload["customField2"] = "Beta"
    payload["customComment1"] = "why alpha"
    payload["customComment2"] = "why beta"
    payload["_links"] = {
        "self": {"href": f"/api/v3/projects/{project_id}"},
        "customField11": {"href": "/api/v3/versions/7", "title": "Secret release"},
        "customField12": {"href": "/api/v3/versions/8", "title": "Own release"},
    }
    api = HttpxProjectApi(None, base_url="https://op.example.com")  # type: ignore[arg-type]
    return api._record(payload)


async def _only_visible_versions(references):
    return {reference: reference != _SECRET_VERSION for reference in references}


def _calls(counter: list[list]):
    async def check(references):
        references = list(references)
        counter.append(references)
        return {reference: reference != _SECRET_VERSION for reference in references}

    return check


def _hiding(**hidden) -> object:
    """Settings under a restricted read scope: a version link is only judged when the scope can exclude it."""
    return dataclasses.replace(make_settings(), **{"read_projects": ("demo",), **hidden})


@pytest.mark.asyncio
async def test_get_shows_the_attributes_with_a_version_outside_the_scope_as_null() -> None:
    service = _service(
        _FakeProjectApi([_attribute_record()]), settings=_hiding(), references_allowed=_only_visible_versions
    )

    detail = await service.get("demo")

    assert detail.custom_fields is not None
    assert detail.custom_fields["customField11"] is None
    assert detail.custom_fields["customField12"] == "Own release"
    assert "Secret release" not in repr(detail)


@pytest.mark.asyncio
async def test_a_hidden_custom_field_takes_its_comment_with_it_on_get_and_list() -> None:
    settings = _hiding(hide_custom_fields=("customField1",))
    service = _service(_FakeProjectApi([_attribute_record()]), settings=settings)

    detail = await service.get("demo")
    listed = (await service.list()).results[0]

    for shown in (detail, listed):
        assert shown.custom_fields is not None and "customField1" not in shown.custom_fields
        assert "customField2" in shown.custom_fields
        assert shown.custom_comments == {"customComment2": "<user-content>why beta</user-content>"}


@pytest.mark.asyncio
async def test_a_hide_pattern_written_as_a_name_has_no_effect_on_a_read() -> None:
    settings = _hiding(hide_custom_fields=("Alpha",))
    service = _service(_FakeProjectApi([_attribute_record()]), settings=settings)

    detail = await service.get("demo")

    assert detail.custom_fields is not None and "customField1" in detail.custom_fields


@pytest.mark.asyncio
async def test_hiding_custom_fields_as_a_whole_removes_both_dicts_and_the_flags() -> None:
    settings = _hiding(hidden_fields={"project": ("custom_fields", "custom_comments")})
    service = _service(_FakeProjectApi([_attribute_record()]), settings=settings)

    for shown in (await service.get("demo"), (await service.list()).results[0]):
        assert shown.custom_fields_truncated is False and shown.custom_comments_truncated is False
        assert shown.custom_comments is None
        assert {"custom_fields", "custom_comments"} <= set(getattr(shown, "_hidden_keys", ()))
        assert not {"custom_fields", "custom_comments"} & set(_to_payload(shown))


@pytest.mark.asyncio
async def test_a_page_of_projects_asks_for_the_scope_of_its_versions_once() -> None:
    calls: list[list] = []
    records = [_attribute_record(project_id=n, identifier=f"p{n}") for n in (6, 7, 8)]
    service = _service(
        _FakeProjectApi(records), settings=_hiding(read_projects=("demo", "p*")), references_allowed=_calls(calls)
    )

    result = await service.list()

    assert len(calls) == 1
    assert set(calls[0]) == {_SECRET_VERSION, ScopedReference("version", 8)}
    assert all(row.custom_fields["customField11"] is None for row in result.results)


@pytest.mark.asyncio
async def test_a_hidden_field_costs_no_scope_lookup() -> None:
    calls: list[list] = []
    settings = _hiding(hide_custom_fields=("customField11",))
    service = _service(_FakeProjectApi([_attribute_record()]), settings=settings, references_allowed=_calls(calls))

    await service.get("demo")

    assert [reference for batch in calls for reference in batch] == [ScopedReference("version", 8)]


@pytest.mark.asyncio
async def test_the_admin_context_names_no_out_of_scope_version_in_its_project_and_hides_hidden_definitions() -> None:
    api = _FakeProjectApi([_attribute_record()])
    api.schema = {
        "customField1": {"name": "Alpha", "type": "String", "writable": True, "location": "customField1"},
        "customField2": {"name": "Beta", "type": "String", "writable": True, "location": "customField2"},
        "status": {"name": "Status", "writable": True, "_embedded": {"allowedValues": []}},
    }
    settings = _hiding(hide_custom_fields=("Alpha",))
    service = _admin_service(api, settings=settings, references_allowed=_only_visible_versions)

    context = await service.get_admin_context("demo")

    assert context.project.custom_fields is not None
    assert context.project.custom_fields["customField11"] is None
    assert [field.key for field in context.fields if field.key.startswith("customField")] == ["customField2"]


@pytest.mark.asyncio
async def test_the_admin_context_offers_no_custom_field_definition_when_custom_fields_are_hidden() -> None:
    api = _FakeProjectApi([_attribute_record()])
    api.schema = {"customField1": {"name": "Alpha", "type": "String", "writable": True}}
    service = _admin_service(api, settings=_hiding(hidden_fields={"project": ("custom_fields",)}))

    context = await service.get_admin_context("demo")

    assert [field.key for field in context.fields] == []


def _enabled_settings(**extra):
    return dataclasses.replace(
        make_settings(), enable_project_write=True, read_projects=("demo*",), write_projects=("*",), **extra
    )


_ATTRIBUTE_SCHEMA = {
    "customField1": {"name": "Alpha", "type": "String", "writable": True, "location": "customField1"},
    "customField11": {
        "name": "Release",
        "type": "Version",
        "writable": True,
        "location": "_links",
        "_embedded": {
            "allowedValues": [
                {"name": "Secret release", "_links": {"self": {"href": "/api/v3/versions/7"}}},
                {"name": "Own release", "_links": {"self": {"href": "/api/v3/versions/8"}}},
            ]
        },
    },
}


@pytest.mark.asyncio
async def test_create_sends_the_attributes_the_form_will_validate() -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings(), references_allowed=_only_visible_versions)

    result = await service.create(
        name="Demo N", identifier="demo-n", custom_fields={"alpha": "x", "Release": "Own release"}, confirm=True
    )

    assert api.commit_create_calls == [
        {
            "name": "Demo N",
            "identifier": "demo-n",
            "customField1": "x",
            "_links": {"customField11": {"href": "/api/v3/versions/8"}},
        }
    ]
    assert result.state == "confirmed"


@pytest.mark.asyncio
async def test_create_cannot_name_a_version_outside_the_scope() -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings(), references_allowed=_only_visible_versions)

    with pytest.raises(InvalidInputError, match="'Secret release' is not allowed"):
        await service.create(
            name="Demo N", identifier="demo-n", custom_fields={"Release": "Secret release"}, confirm=True
        )

    assert api.commit_create_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hidden, given",
    [
        ({"hide_custom_fields": ("customField1",)}, {"customField1": "x"}),
        ({"hide_custom_fields": ("customField1",)}, {"Alpha": "x"}),
        ({"hide_custom_fields": ("Alpha",)}, {"customField1": "x"}),
        ({"hidden_fields": {"project": ("custom_fields",)}}, {"customField1": "x"}),
    ],
)
async def test_a_hidden_attribute_is_refused_by_key_or_by_name_before_any_form(hidden, given) -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings(**hidden))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE"):
        await service.create(name="Demo N", identifier="demo-n", custom_fields=given, confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_update_with_only_custom_fields_validates_and_writes_them() -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings())

    await service.update(project_ref="demo", custom_fields={"customField1": None}, confirm=True)

    assert api.commit_update_calls == [(6, {"customField1": None})]


@pytest.mark.asyncio
async def test_update_clears_a_link_attribute_with_a_null_link() -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings())

    await service.update(project_ref="demo", custom_fields={"Release": None}, confirm=True)

    assert api.commit_update_calls == [(6, {"_links": {"customField11": {"href": None}}})]


@pytest.mark.asyncio
async def test_update_refuses_to_replace_a_version_the_result_cannot_name() -> None:
    api = _FakeProjectApi([_attribute_record()])
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings(), references_allowed=_only_visible_versions)

    with pytest.raises(InvalidInputError, match="1 version custom field value"):
        await service.update(project_ref="demo", custom_fields={"Release": "Own release"}, confirm=True)
    with pytest.raises(InvalidInputError, match="1 version custom field value"):
        await service.update(project_ref="demo", custom_fields={"Release": None}, confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_may_change_an_attribute_next_to_a_version_it_does_not_touch() -> None:
    api = _FakeProjectApi([_attribute_record()])
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings(), references_allowed=_only_visible_versions)

    await service.update(project_ref="demo", custom_fields={"Alpha": "new"}, confirm=True)

    assert api.commit_update_calls == [(6, {"customField1": "new"})]


@pytest.mark.asyncio
async def test_copy_resolves_the_attributes_against_the_schema_of_the_copy_form() -> None:
    api = _FakeProjectApi()
    api.copy_schema = {"customField1": _ATTRIBUTE_SCHEMA["customField1"]}
    service = _service(api, settings=_enabled_settings())

    await service.copy(
        source_project="demo", name="Demo N", identifier="demo-n", custom_fields={"Alpha": "x"}, confirm=False
    )

    assert api.copy_form_calls == [{"name": "Demo N", "identifier": "demo-n", "customField1": "x"}]


@pytest.mark.asyncio
async def test_copy_reads_the_attribute_options_only_from_the_copy_form() -> None:
    api = _FakeProjectApi()
    api.copy_schema = {"customField1": _ATTRIBUTE_SCHEMA["customField1"]}
    service = _service(api, settings=_enabled_settings())

    await service.copy(
        source_project="demo", name="Demo N", identifier="demo-n", custom_fields={"Alpha": "x"}, confirm=False
    )

    assert [bool(read.get("custom_field_options")) for read in api.schema_reads] == [False]


@pytest.mark.asyncio
async def test_copy_without_attributes_reads_no_copy_schema() -> None:
    api = _FakeProjectApi()
    service = _service(api, settings=_enabled_settings())

    await service.copy(source_project="demo", name="Demo N", identifier="demo-n", confirm=False)

    assert api.copy_form_calls == [{"name": "Demo N", "identifier": "demo-n"}]


@pytest.mark.asyncio
async def test_a_write_result_shows_the_attributes_of_the_committed_project_scoped_like_a_read() -> None:
    settings = _enabled_settings(hide_custom_fields=("customField2",))
    api = _FakeProjectApi([_attribute_record()])
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}

    async def commit_update(project_id, payload):
        return _attribute_record()

    api.commit_update = commit_update  # type: ignore[method-assign]
    service = _service(api, settings=settings, references_allowed=_only_visible_versions)

    result = await service.update(project_ref="demo", custom_fields={"Alpha": "new"}, confirm=True)

    assert result.result is not None and result.result.custom_fields is not None
    assert "customField2" not in result.result.custom_fields
    assert result.result.custom_fields["customField11"] is None


@pytest.mark.asyncio
async def test_list_passes_the_custom_field_filters_and_the_order_to_the_api() -> None:
    api = _FakeProjectApi()
    service = _service(api)

    await service.list(
        custom_field_filters={"cf_3": {"operator": "=", "values": ["x"]}},
        sort_by=[SortCriterion(field="cf_3", direction="desc")],
    )

    assert api.list_calls == [
        {
            "custom_field_filters": [{"cf_3": {"operator": "=", "values": ["x"]}}],
            "sort_by": [SortCriterion(field="cf_3", direction="desc")],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings, query",
    [
        (
            {"hide_custom_fields": ("customField3",)},
            {"custom_field_filters": {"cf_3": {"operator": "=", "values": ["x"]}}},
        ),
        ({"hide_custom_fields": ("cf_3",)}, {"sort_by": [SortCriterion("cf_3", "asc")]}),
        ({"hidden_fields": {"project": ("custom_fields",)}}, {"sort_by": [SortCriterion("cf_3", "asc")]}),
        (
            {"hidden_fields": {"project": ("custom_fields",)}},
            {"custom_field_filters": {"cf_3": {"operator": "=", "values": ["x"]}}},
        ),
        ({"hidden_fields": {"project": ("status",)}}, {"sort_by": [SortCriterion("project_status", "asc")]}),
        ({"hidden_fields": {"project": ("name",)}}, {"sort_by": [SortCriterion("name", "asc")]}),
        ({"hidden_fields": {"project": ("name",)}}, {"search": "demo"}),
    ],
)
async def test_a_hidden_field_cannot_be_used_to_filter_or_to_sort(settings, query) -> None:
    api = _FakeProjectApi()
    service = _service(api, settings=_hiding(**settings))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE"):
        await service.list(**query)

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_a_sort_column_a_release_lacks_names_the_release_that_has_it() -> None:
    api = _FakeProjectApi()
    api.list_raises = InvalidInputError("Order updated_at does not exist.")
    service = _service(api)

    with pytest.raises(InvalidInputError, match=r"Order updated_at does not exist\..*updated_at.*16\.5"):
        await service.list(sort_by=[SortCriterion(field="updated_at", direction="asc")])


@pytest.mark.asyncio
async def test_a_sort_column_every_release_has_adds_no_release_hint() -> None:
    api = _FakeProjectApi()
    api.list_raises = InvalidInputError("Bad filter.")
    service = _service(api)

    with pytest.raises(InvalidInputError) as raised:
        await service.list(sort_by=[SortCriterion(field="name", direction="asc")])

    assert str(raised.value) == "Bad filter."


_FORM_ECHO = {
    "customField2": "SECRET VALUE",
    "customComment2": "SECRET NOTE",
    "customField3": "visible",
    "_links": {"customField2": {"href": "/api/v3/users/9", "title": "Secret Person"}},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_a_write_preview_and_result_drop_the_hidden_attributes_the_form_echoes(confirm: bool) -> None:
    api = _FakeProjectApi()
    api.form_echo = _FORM_ECHO
    service = _service(api, settings=dataclasses.replace(_enabled_settings(), hide_custom_fields=("customField2",)))

    update = await service.update(project_ref="demo", name="Renamed", confirm=confirm)
    create = await service.create(name="Demo N", identifier="demo-n", confirm=confirm)

    for result in (update, create):
        assert result.payload["customField3"] == "visible"
        assert "customField2" not in result.payload and "customComment2" not in result.payload
        assert "customField2" not in result.payload.get("_links", {})


@pytest.mark.asyncio
async def test_a_copy_preview_drops_the_hidden_attributes_the_form_echoes() -> None:
    api = _FakeProjectApi()
    api.form_echo = _FORM_ECHO
    service = _service(api, settings=dataclasses.replace(_enabled_settings(), hide_custom_fields=("customField2",)))

    result = await service.copy(source_project="demo", name="Copy", identifier="demo-copy", confirm=False)

    assert result.payload["customField3"] == "visible"
    assert "customField2" not in result.payload and "customComment2" not in result.payload
    assert "customField2" not in result.payload.get("_links", {})


@pytest.mark.asyncio
async def test_a_copy_request_carries_no_custom_field_comment_key() -> None:
    api = _FakeProjectApi()
    api.form_echo = _FORM_ECHO
    service = _service(api, settings=_enabled_settings())

    preview = await service.copy(source_project="demo", name="Copy", identifier="demo-copy", confirm=False)
    await service.copy(source_project="demo", name="Copy", identifier="demo-copy", confirm=True)

    assert "customComment2" not in preview.payload
    assert preview.payload["customField3"] == "visible"
    [(_, committed)] = api.commit_copy_calls
    assert "customComment2" not in committed and committed["customField3"] == "visible"


@pytest.mark.asyncio
async def test_a_copy_refuses_to_set_a_custom_field_comment() -> None:
    api = _FakeProjectApi()
    service = _service(api, settings=_enabled_settings())

    with pytest.raises(InvalidInputError, match="cannot set a custom field comment"):
        await service.copy(
            source_project="demo",
            name="Copy",
            identifier="demo-copy",
            custom_fields={"customComment2": "x"},
            confirm=True,
        )

    assert api.commit_copy_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_a_copy_rejection_does_not_name_a_hidden_attribute(confirm: bool) -> None:
    api = _FakeProjectApi()
    api.copy_validation_errors = {
        "customField2": ValidationFailure("Secret can't be blank"),
        "name": ValidationFailure("too short"),
    }
    service = _service(api, settings=dataclasses.replace(_enabled_settings(), hide_custom_fields=("customField2",)))

    result = await service.copy(source_project="demo", name="Copy", identifier="demo-copy", confirm=confirm)

    assert result.validation_errors["name"] == ValidationFailure("too short")
    assert "Secret" not in repr(result.validation_errors)
    assert set(result.validation_errors) == {"customField2", "name"}


@pytest.mark.asyncio
async def test_the_members_behind_a_user_attribute_are_read_only_to_resolve_a_written_value() -> None:
    api = _FakeProjectApi()
    api.schema = {**api.schema, **_ATTRIBUTE_SCHEMA}
    service = _service(api, settings=_enabled_settings())
    admin = _admin_service(api, settings=_enabled_settings())

    await admin.get_admin_context("demo")
    await service.update(project_ref="demo", name="Renamed", confirm=False)
    await service.update(project_ref="demo", custom_fields={"customField1": None}, confirm=False)

    assert [bool(read.get("custom_field_options")) for read in api.schema_reads] == [False, False, True]


_DEFINING_PROJECT_LINKS = {
    1: {"definingProject": {"href": "/api/v3/projects/1"}},
    2: {"definingProject": {"href": "/api/v3/projects/9"}},
    3: {},
    4: {"definingProject": {"href": "urn:openproject-org:api:v3:undisclosed"}},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("read_projects", [("demo",), ("*",)])
async def test_the_write_path_and_the_admin_context_offer_the_same_versions(read_projects: tuple[str, ...]) -> None:
    from types import SimpleNamespace

    from openproject_ce_mcp.app.resolvers.scoped_reference_resolver import ScopedReferenceResolver
    from openproject_ce_mcp.app.resource_href import ResourceLinks
    from openproject_ce_mcp.app.services._scoped_references import field_with_visible_options

    settings = dataclasses.replace(make_settings(), read_projects=read_projects)
    known = {1: "demo", 9: "secret"}

    class _Versions:
        async def get(self, version_id: int):
            link = _DEFINING_PROJECT_LINKS[version_id].get("definingProject")
            return SimpleNamespace(defining_project_link=link)

    resolver = ScopedReferenceResolver(
        version_api=_Versions(),  # type: ignore[arg-type]
        sprint_api=None,  # type: ignore[arg-type]
        backlog_bucket_api=None,  # type: ignore[arg-type]
        settings=settings,
        project_id_to_identifier=known,
    )
    options = [
        {
            "_type": "Version",
            "name": f"V{number}",
            "_links": {"self": {"href": f"/api/v3/versions/{number}"}, **links},
        }
        for number, links in _DEFINING_PROJECT_LINKS.items()
    ]
    schema_field = {
        "name": "Release",
        "type": "Version",
        "writable": True,
        "location": "_links",
        "_embedded": {"allowedValues": options},
    }
    api = _FakeProjectApi()
    api.schema = {"customField11": schema_field}
    admin = ProjectAdminService(
        api=api,
        settings=settings,
        project_id_to_identifier=known,
        resolver=_resolver(api, settings=settings),
        references_allowed=resolver.references_allowed,
    )

    context = await admin.get_admin_context("demo")
    on_admin_context = {value.href for field in context.fields for value in field.allowed_values}
    written = await field_with_visible_options(
        schema_field,
        links=ResourceLinks("https://op.example.com"),
        settings=settings,
        check=resolver.references_allowed,
    )
    on_write_path = {option["_links"]["self"]["href"] for option in written["_embedded"]["allowedValues"]}

    assert on_admin_context == on_write_path
    assert on_write_path == (
        {"/api/v3/versions/1"}
        if read_projects == ("demo",)
        else {f"/api/v3/versions/{number}" for number in _DEFINING_PROJECT_LINKS}
    )


@pytest.mark.asyncio
async def test_an_unknown_project_status_names_the_allowed_statuses() -> None:
    api = _FakeProjectApi()
    api.schema = {
        "status": {
            "name": "Status",
            "writable": True,
            "_links": {
                "allowedValues": [
                    {"href": "/api/v3/project_statuses/on_track", "title": "On track"},
                    {"href": "/api/v3/project_statuses/off_track", "title": "Off track"},
                ]
            },
        }
    }
    service = _service(api, settings=_enabled_settings())

    with pytest.raises(InvalidInputError) as raised:
        await service.create(name="Demo New", identifier="demo-new", status="ghost", confirm=False)

    assert str(raised.value) == (
        "OpenProject project status 'ghost' is not allowed. Allowed statuses: On track, Off track."
    )
