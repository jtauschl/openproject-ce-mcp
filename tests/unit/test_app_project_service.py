from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.adapters.httpx_project_api import normalize_project_detail, normalize_project_field_schema
from openproject_ce_mcp.app.errors import PermissionDeniedError
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
from openproject_ce_mcp.app.resolvers.project_resolver import ProjectResolver
from openproject_ce_mcp.app.services.project_service import ProjectAdminService, ProjectService
from openproject_ce_mcp.models import ProjectDetail, ProjectPhase, ProjectSummary

BASE_URL = "https://op.example.com"


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
        url=f"{BASE_URL}/projects/{project_id}",
    )


def _record(project_id: int = 6, name: str = "Demo Project", identifier: str = "demo") -> ProjectRecord:
    summary = _summary(project_id, name, identifier)
    return ProjectRecord(
        summary=summary,
        to_detail=lambda: ProjectDetail(**vars(summary)),
        payload=_payload(project_id, name, identifier),
    )


class _FakeProjectApi:
    def __init__(self, records: list[ProjectRecord] | None = None) -> None:
        self._records = records or [_record()]
        self.get_calls: list[str] = []
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
        self.validation_errors: dict[str, str] = {}
        self.copy_validation_errors: dict[str, str] = {}
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.favorite_calls: list[tuple[int, bool]] = []
        self.commit_copy_calls: list[tuple[int, dict]] = []
        self.job_status_url: str | None = "https://op.example.com/api/v3/projects/6/copy/status/1"

    async def list(
        self, *, server_offset: int, server_page_size: int, search: str | None, text_limit=None
    ) -> ProjectPage:
        return ProjectPage(records=self._records, server_total=len(self._records), exhausted=True)

    async def get(self, project_ref: str, *, text_limit=None) -> ProjectRecord:
        self.get_calls.append(project_ref)
        for record in self._records:
            if str(record.summary.id) == project_ref or record.summary.identifier == project_ref:
                return record
        raise AssertionError(f"no fake record for ref {project_ref}")

    async def create_form(self, payload) -> ProjectFormResult:
        return ProjectFormResult(payload=payload, validation_errors=self.validation_errors)

    async def update_form(self, project_id, payload) -> ProjectFormResult:
        return ProjectFormResult(payload=payload, validation_errors=self.validation_errors)

    async def commit_create(self, payload) -> ProjectDetail:
        self.commit_create_calls.append(payload)
        return normalize_project_detail(_payload(name=payload.get("name", "Demo Project")), base_url=BASE_URL)

    async def commit_update(self, project_id, payload) -> ProjectDetail:
        self.commit_update_calls.append((project_id, payload))
        return normalize_project_detail(
            _payload(project_id=project_id, name=payload.get("name", "Demo Project")), base_url=BASE_URL
        )

    async def delete(self, project_id) -> None:
        self.delete_calls.append(project_id)

    async def get_schema(self, *, project_id, draft_payload) -> ProjectSchemaResult:
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

    async def copy_form(self, project_id, payload) -> ProjectCopyFormResult:
        return ProjectCopyFormResult(payload=payload, validation_errors=self.copy_validation_errors)

    async def commit_copy(self, project_id, payload) -> str | None:
        self.commit_copy_calls.append((project_id, payload))
        return self.job_status_url


def _resolver(api: _FakeProjectApi, *, settings=None) -> ProjectResolver:
    return ProjectResolver(api=api, settings=settings or make_settings(), project_id_to_identifier={})


def _service(api: _FakeProjectApi | None = None, *, settings=None) -> ProjectService:
    api = api or _FakeProjectApi()
    settings = settings or make_settings()
    return ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier={},
        resolver=_resolver(api, settings=settings),
        base_url=BASE_URL,
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_get_description_hidden_by_project_scope_not_project_configuration_scope() -> None:
    """Regression test for the entity-scope class of bug found via News'
    OPM-266 hotfix and Documents' equivalent: a field must only be masked by
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


def _admin_service(api: _FakeProjectApi | None = None, *, settings=None) -> ProjectAdminService:
    api = api or _FakeProjectApi()
    settings = settings or make_settings()
    return ProjectAdminService(
        api=api,
        settings=settings,
        project_id_to_identifier={},
        resolver=_resolver(api, settings=settings),
        base_url=BASE_URL,
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
    assert config.maximum_attachment_file_size == 100


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
        ProjectPhaseDefinition(
            id=1, name="Init", start_gate=None, finish_gate=None, created_at=None, updated_at=None, url=""
        )
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
        ProjectPhaseDefinition(
            id=1, name="Init", start_gate=None, finish_gate=None, created_at=None, updated_at=None, url=""
        )
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
            start_date=None,
            finish_date=None,
            created_at=None,
            updated_at=None,
            url="",
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
    api.parent_projects = [ProjectRef(id=1, identifier="root", name="Root", url="")]
    service = _admin_service(api)

    context = await service.get_admin_context("demo")

    assert context.project is not None
    assert context.project.id == 6
    assert len(context.available_parent_projects) == 1
    assert any(field.key == "status" for field in context.fields)


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
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.create(name="New Project", identifier="new-project", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert len(api.commit_create_calls) == 1


@pytest.mark.asyncio
async def test_create_rejects_when_validation_errors_present() -> None:
    api = _FakeProjectApi()
    api.validation_errors = {"name": "too short"}
    service = _service(api)

    result = await service.create(name="x", identifier="x", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert result.validation_errors == {"name": "too short"}
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="New Project", identifier="new-project", confirm=False)


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.update(project_ref="demo", name="Renamed", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert len(api.commit_update_calls) == 1
    assert api.commit_update_calls[0][0] == 6


@pytest.mark.asyncio
async def test_update_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(project_ref="demo", name="Renamed", confirm=False)


@pytest.mark.asyncio
async def test_create_remembers_new_project_identifier_in_the_shared_cache() -> None:
    """Regression test for the bug where a project created through this server
    was invisible to every link-shaped allowlist check (ensure_project_link_allowed,
    used by get_work_package/update_work_package/every already-migrated Service)
    until the process restarted -- project_id_to_identifier was otherwise only
    ever populated once, by client.py's initialize() at startup.
    """
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    project_id_to_identifier: dict[int, str] = {}
    service = ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier=project_id_to_identifier,
        resolver=_resolver(api, settings=settings),
        base_url=BASE_URL,
        api_prefix="/api/v3/",
    )

    result = await service.create(name="New Project", identifier="new-project", confirm=True)

    assert result.result is not None
    assert project_id_to_identifier == {result.result.id: result.result.identifier}


@pytest.mark.asyncio
async def test_create_preview_does_not_write_to_the_cache() -> None:
    api = _FakeProjectApi()
    project_id_to_identifier: dict[int, str] = {}
    service = ProjectService(
        api=api,
        settings=make_settings(),
        project_id_to_identifier=project_id_to_identifier,
        resolver=_resolver(api),
        base_url=BASE_URL,
        api_prefix="/api/v3/",
    )

    await service.create(name="New Project", identifier="new-project", confirm=False)

    assert project_id_to_identifier == {}


@pytest.mark.asyncio
async def test_update_remembers_project_identifier_in_the_shared_cache() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    project_id_to_identifier: dict[int, str] = {}
    service = ProjectService(
        api=api,
        settings=settings,
        project_id_to_identifier=project_id_to_identifier,
        resolver=_resolver(api, settings=settings),
        base_url=BASE_URL,
        api_prefix="/api/v3/",
    )

    result = await service.update(project_ref="demo", name="Renamed", confirm=True)

    assert result.result is not None
    assert project_id_to_identifier == {result.result.id: result.result.identifier}


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
        base_url=BASE_URL,
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
    assert preview.requires_confirmation is True
    assert preview.confirmed is False
    assert api.delete_calls == []

    committed = await service.delete(project_ref="demo", confirm=True)
    assert committed.confirmed is True
    assert committed.result is not None
    assert api.delete_calls == [6]


@pytest.mark.asyncio
async def test_delete_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(project_ref="demo", confirm=False)


@pytest.mark.asyncio
async def test_set_favorite_returns_preview_then_commits() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    preview = await service.set_favorite("demo", favorite=True, confirm=False)
    assert preview.requires_confirmation is True
    assert api.favorite_calls == []

    committed = await service.set_favorite("demo", favorite=True, confirm=True)
    assert committed.confirmed is True
    assert api.favorite_calls == [(6, True)]


@pytest.mark.asyncio
async def test_set_favorite_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.set_favorite("demo", favorite=True, confirm=False)


@pytest.mark.asyncio
async def test_copy_returns_preview_without_committing() -> None:
    api = _FakeProjectApi()
    service = _service(api)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_copy_calls == []


@pytest.mark.asyncio
async def test_copy_commits_and_returns_job_status_url() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    api = _FakeProjectApi()
    service = _service(api, settings=settings)

    result = await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=True)

    assert result.confirmed is True
    assert result.job_status_url == api.job_status_url
    assert len(api.commit_copy_calls) == 1


@pytest.mark.asyncio
async def test_copy_denies_target_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.copy(source_project="demo", name="Copy", identifier="copy-project", confirm=False)


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
