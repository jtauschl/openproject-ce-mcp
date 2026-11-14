from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.version_api import VersionPage, VersionRecord
from openproject_ce_mcp.app.resolvers.version_resolver import VersionResolver
from openproject_ce_mcp.models import VersionSummary


def _summary(version_id: int, name: str) -> VersionSummary:
    return VersionSummary(
        id=version_id,
        name=name,
        status="open",
        sharing=None,
        start_date=None,
        end_date=None,
        defining_project="Demo",
        description=None,
    )


def _record(
    version_id: int, name: str, *, defining_project_link: dict | None = None, lookup_name: str | None = None
) -> VersionRecord:
    return VersionRecord(
        summary=_summary(version_id, name),
        defining_project_link=defining_project_link or {"href": "/api/v3/projects/6"},
        lookup_name=name if lookup_name is None else lookup_name,
        payload={},
    )


class _FakeVersionApi:
    def __init__(self, records: list[VersionRecord]) -> None:
        self._records = records

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> VersionPage:
        return VersionPage(records=self._records, server_total=len(self._records))

    async def list_global(self, *, offset: int, page_size: int, text_limit: int | None = None) -> VersionPage:
        return VersionPage(records=self._records, server_total=None)

    async def get(self, version_id: int, *, text_limit: int | None = None) -> VersionRecord:
        for record in self._records:
            if record.summary.id == version_id:
                return record
        raise AssertionError(f"no fake record for id {version_id}")

    async def create_form(self, payload): ...
    async def update_form(self, version_id, payload): ...
    async def commit_create(self, payload): ...
    async def commit_update(self, version_id, payload): ...
    async def delete(self, version_id: int) -> None: ...


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": "demo", "name": "Demo"}


def _resolver(records: list[VersionRecord]) -> VersionResolver:
    return VersionResolver(
        api=_FakeVersionApi(records),
        resolve_project_ref=_resolve_project_ref,
        settings=make_settings(),
        project_id_to_identifier={6: "demo"},
    )


@pytest.mark.asyncio
async def test_resolve_by_numeric_id_within_project() -> None:
    records = [_record(8, "v1.0")]
    resolver = _resolver(records)

    result = await resolver.resolve_id("8", project="demo")

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_within_project() -> None:
    records = [_record(8, "v1.0")]
    resolver = _resolver(records)

    result = await resolver.resolve_id("v1.0", project="demo")

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_numeric_id_not_available_in_project_raises() -> None:
    records = [_record(8, "v1.0")]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="is not available in project"):
        await resolver.resolve_id("999", project="demo")


@pytest.mark.asyncio
async def test_resolve_ambiguous_name_within_project_raises() -> None:
    records = [_record(1, "v1.0"), _record(2, "v1.0")]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("v1.0", project="demo")


@pytest.mark.asyncio
async def test_resolve_numeric_id_without_project_checks_allowlist() -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    records = [_record(8, "v1.0", defining_project_link=link)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("8", project=None)

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_without_project_uses_search() -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    records = [_record(8, "v1.0", defining_project_link=link)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("v1.0", project=None)

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_without_project_not_found_raises() -> None:
    resolver = _resolver([])

    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_id("nope", project=None)


@pytest.mark.asyncio
async def test_resolve_does_not_match_a_blank_name_against_the_synthetic_display_fallback() -> None:
    """Matching uses VersionRecord.lookup_name (the raw, never-synthesized
    name), not summary.name, which falls back to a synthetic display name
    ("Version 9") when the raw name is blank -- see app/ports/version_api.py's
    VersionRecord docstring."""
    records = [_record(9, "Version 9", lookup_name="")]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="was not found in project"):
        await resolver.resolve_id("Version 9", project="demo")


@pytest.mark.asyncio
@pytest.mark.parametrize("project", ["demo", None])
@pytest.mark.parametrize("name", ["²", "٣"])
async def test_resolve_reads_non_ascii_digits_as_a_name(name: str, project: str | None) -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    resolver = _resolver([_record(8, name, defining_project_link=link)])

    assert await resolver.resolve_id(name, project=project) == "8"


def _restricted_resolver(records: list[VersionRecord]) -> VersionResolver:
    return VersionResolver(
        api=_FakeVersionApi(records),
        resolve_project_ref=_resolve_project_ref,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={6: "demo"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["Shared in", "9"])
async def test_a_version_shared_in_from_an_uncovered_project_is_not_offered_and_the_error_says_why(reference) -> None:
    records = [
        _record(8, "Own"),
        _record(9, "Shared in", defining_project_link={"href": "/api/v3/projects/20"}),
    ]

    with pytest.raises(InvalidInputError, match=r"(was not found|is not available) in project 'demo'.*not cover"):
        await _restricted_resolver(records).resolve_id(reference, project="demo")

    assert await _restricted_resolver(records).resolve_id("Own", project="demo") == "8"


@pytest.mark.asyncio
async def test_the_error_names_no_scope_reason_when_every_project_is_readable() -> None:
    with pytest.raises(InvalidInputError) as caught:
        await _resolver([_record(8, "Own")]).resolve_id("Nope", project="demo")

    assert "OPENPROJECT_READ_PROJECTS" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("read_projects", "allowed"), [(("*",), True), (("demo",), False)])
async def test_a_numeric_version_without_a_defining_project_link_follows_the_undisclosed_rule(
    read_projects: tuple[str, ...], allowed: bool
) -> None:
    record = dataclasses.replace(_record(8, "v1.0"), defining_project_link=None)
    resolver = VersionResolver(
        api=_FakeVersionApi([record]),
        resolve_project_ref=_resolve_project_ref,
        settings=dataclasses.replace(make_settings(), read_projects=read_projects),
        project_id_to_identifier={6: "demo"},
    )

    if allowed:
        assert await resolver.resolve_id("8", project=None) == "8"
    else:
        with pytest.raises(PermissionDeniedError):
            await resolver.resolve_id("8", project=None)


@pytest.mark.asyncio
async def test_resolve_by_name_works_with_version_reads_disabled() -> None:
    """A work package write resolves a version name; the version read gate is the version tools'."""
    resolver = VersionResolver(
        api=_FakeVersionApi([_record(8, "v1.0")]),
        resolve_project_ref=_resolve_project_ref,
        settings=dataclasses.replace(make_settings(), enable_version_read=False),
        project_id_to_identifier={6: "demo"},
    )

    assert await resolver.resolve_id("v1.0", project="demo") == "8"


@pytest.mark.asyncio
async def test_an_unknown_version_name_in_a_project_names_the_allowed_versions() -> None:
    resolver = _resolver([_record(2, "v2.0"), _record(1, "V1.0"), _record(3, "Version 3", lookup_name="")])

    with pytest.raises(InvalidInputError) as raised:
        await resolver.resolve_id("Ghost", project="demo")

    assert str(raised.value).startswith(
        "OpenProject version 'Ghost' was not found in project 'demo'. Allowed versions: V1.0, v2.0."
    )


@pytest.mark.asyncio
async def test_a_version_id_that_is_not_available_names_the_allowed_versions() -> None:
    resolver = _resolver([_record(1, "v1.0")])

    with pytest.raises(InvalidInputError) as raised:
        await resolver.resolve_id("999", project="demo")

    assert str(raised.value).startswith(
        "OpenProject version '999' is not available in project 'demo'. Allowed versions: v1.0."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("project", ["demo", None])
async def test_an_ambiguous_version_name_names_its_candidates(project: str | None) -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    resolver = _resolver(
        [
            _record(1, "v1.0", defining_project_link=link),
            _record(2, "v1.0", defining_project_link=link),
            _record(3, "v2.0", defining_project_link=link),
        ]
    )

    with pytest.raises(InvalidInputError) as raised:
        await resolver.resolve_id("v1.0", project=project)

    assert str(raised.value).endswith("Pass a numeric version id. Matches: 1 (v1.0), 2 (v1.0).")


@pytest.mark.asyncio
async def test_an_unknown_version_name_without_a_project_names_the_allowed_versions() -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    resolver = _resolver([_record(8, "v1.0", defining_project_link=link)])

    with pytest.raises(InvalidInputError) as raised:
        await resolver.resolve_id("nope", project=None)

    assert str(raised.value) == "OpenProject version 'nope' was not found. Allowed versions: v1.0."
