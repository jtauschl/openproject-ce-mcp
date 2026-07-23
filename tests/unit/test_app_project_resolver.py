from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.resolvers.project_resolver import ProjectResolver
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary


def _summary(project_id: int, name: str, *, identifier: str | None = None) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        name=name,
        identifier=identifier,
        active=True,
        description=None,
        url=f"https://op.example.com/projects/{project_id}",
    )


def _record(project_id: int, name: str, *, identifier: str | None = None) -> ProjectRecord:
    summary = _summary(project_id, name, identifier=identifier)
    return ProjectRecord(
        summary=summary,
        detail=ProjectDetail(**vars(summary)),
        payload={"id": project_id, "name": name, "identifier": identifier, "_type": "Project"},
    )


class _FakeProjectApi:
    """No I/O -- an in-memory ProjectApi double. `get` resolves by numeric id or
    identifier via a direct lookup (like the real GET /projects/{ref}); `list`
    backs the name-search fallback."""

    def __init__(self, records: list[ProjectRecord]) -> None:
        self._records = records
        self.get_calls: list[tuple[str, object]] = []

    async def get(self, project_ref: str, *, text_limit=None) -> ProjectRecord:
        self.get_calls.append((project_ref, text_limit))
        for record in self._records:
            if str(record.summary.id) == project_ref or record.summary.identifier == project_ref:
                return record
        raise NotFoundError(f"no fake record for ref {project_ref}")

    async def list(
        self, *, server_offset: int, server_page_size: int, search: str | None, text_limit=None
    ) -> ProjectPage:
        if server_offset > 1:
            return ProjectPage(records=[], server_total=len(self._records), exhausted=True)
        matches = self._records
        if search:
            search_cf = search.casefold()
            matches = [r for r in matches if search_cf in (r.summary.name or "").casefold()]
        return ProjectPage(records=matches, server_total=len(matches), exhausted=True)

    async def create_form(self, payload): ...
    async def update_form(self, project_id, payload): ...
    async def commit_create(self, payload): ...
    async def commit_update(self, project_id, payload): ...
    async def delete(self, project_id): ...
    async def get_schema(self, *, project_id, draft_payload): ...
    async def list_available_parent_projects(self, project_id, *, schema): ...
    async def get_configuration(self, project_id): ...
    async def list_phase_definitions(self): ...
    async def get_phase_definition(self, phase_definition_id): ...
    async def get_phase(self, phase_id): ...
    async def set_favorite(self, project_id, *, favorite): ...
    async def copy_form(self, project_id, payload): ...
    async def commit_copy(self, project_id, payload): ...


def _resolver(records: list[ProjectRecord], *, settings=None) -> ProjectResolver:
    return ProjectResolver(
        api=_FakeProjectApi(records),
        settings=settings or make_settings(),
        project_id_to_identifier={},
    )


def _resolver_with_api(records: list[ProjectRecord], *, settings=None) -> tuple[ProjectResolver, _FakeProjectApi]:
    api = _FakeProjectApi(records)
    resolver = ProjectResolver(api=api, settings=settings or make_settings(), project_id_to_identifier={})
    return resolver, api


@pytest.mark.asyncio
async def test_resolve_by_numeric_id_direct_get() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    payload = await resolver.resolve("6")

    assert payload["id"] == 6


@pytest.mark.asyncio
async def test_resolve_by_exact_identifier_direct_get() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    payload = await resolver.resolve("demo")

    assert payload["identifier"] == "demo"


@pytest.mark.asyncio
async def test_resolve_id_returns_string_id() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    result = await resolver.resolve_id("demo")

    assert result == "6"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_name_search_on_404() -> None:
    resolver = _resolver([_record(6, "Demo Project", identifier="demo")])

    payload = await resolver.resolve("Demo Project")

    assert payload["id"] == 6


@pytest.mark.asyncio
async def test_resolve_exact_identifier_match_in_search_results_wins_immediately() -> None:
    # "demo" isn't a direct-GET hit (simulated: only in the list, not by ref lookup)
    # but appears as an exact identifier match in the search page.
    records = [_record(6, "Some Name", identifier="demo")]
    resolver = _resolver(records)

    payload = await resolver.resolve("demo")

    assert payload["id"] == 6


@pytest.mark.asyncio
async def test_resolve_ambiguous_exact_name_match_raises() -> None:
    records = [_record(1, "Duplicate"), _record(2, "Duplicate")]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve("Duplicate")


@pytest.mark.asyncio
async def test_resolve_not_found_raises() -> None:
    resolver = _resolver([])

    with pytest.raises(NotFoundError, match="was not found"):
        await resolver.resolve("nope")


@pytest.mark.asyncio
async def test_resolve_read_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver = _resolver([_record(6, "Demo", identifier="demo")], settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await resolver.resolve("demo")


@pytest.mark.asyncio
async def test_resolve_write_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver = _resolver([_record(6, "Demo", identifier="demo")], settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await resolver.resolve("demo", write=True)


@pytest.mark.asyncio
async def test_resolve_record_by_numeric_id_direct_get_returns_project_record() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    record = await resolver.resolve_record("6")

    assert isinstance(record, ProjectRecord)
    assert record.summary.id == 6
    assert record.payload["id"] == 6


@pytest.mark.asyncio
async def test_resolve_record_by_exact_identifier_returns_matching_summary() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    record = await resolver.resolve_record("demo")

    assert record.summary.identifier == "demo"


@pytest.mark.asyncio
async def test_resolve_wraps_resolve_record_and_returns_its_payload() -> None:
    resolver = _resolver([_record(6, "Demo", identifier="demo")])

    record = await resolver.resolve_record("6")
    payload = await resolver.resolve("6")

    assert payload == record.payload


@pytest.mark.asyncio
async def test_resolve_record_falls_back_to_name_search_and_returns_record() -> None:
    resolver = _resolver([_record(6, "Demo Project", identifier="demo")])

    record = await resolver.resolve_record("Demo Project")

    assert record.summary.name == "Demo Project"
    assert record.summary.id == 6


@pytest.mark.asyncio
async def test_resolve_record_ambiguous_exact_name_match_raises() -> None:
    records = [_record(1, "Duplicate"), _record(2, "Duplicate")]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_record("Duplicate")


@pytest.mark.asyncio
async def test_resolve_record_read_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver = _resolver([_record(6, "Demo", identifier="demo")], settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await resolver.resolve_record("demo")


@pytest.mark.asyncio
async def test_resolve_record_write_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver = _resolver([_record(6, "Demo", identifier="demo")], settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await resolver.resolve_record("demo", write=True)


@pytest.mark.asyncio
async def test_resolve_record_text_limit_is_forwarded_to_the_api_on_direct_get() -> None:
    resolver, api = _resolver_with_api([_record(6, "Demo", identifier="demo")])

    await resolver.resolve_record("demo", text_limit=None)

    assert api.get_calls == [("demo", None)]


@pytest.mark.asyncio
async def test_resolve_record_text_limit_is_forwarded_through_the_name_fallback() -> None:
    # "Demo Project" is not a direct-GET hit; resolution falls back to the name
    # search and then recurses into a second api.get() by numeric id -- both the
    # (failed) direct attempt and the final recursive lookup must carry the same
    # text_limit, or a name-resolved project would be capped where an
    # id-resolved one wouldn't.
    resolver, api = _resolver_with_api([_record(6, "Demo Project", identifier="demo")])

    await resolver.resolve_record("Demo Project", text_limit=None)

    assert ("Demo Project", None) in api.get_calls
    assert ("6", None) in api.get_calls
