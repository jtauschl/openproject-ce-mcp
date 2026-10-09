from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError, TransportError
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.services.project_directory_service import FRESHNESS_SECONDS, ProjectDirectoryService
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary

ORIGIN = "https://op.example.com"
PREFIX = "/api/v3/"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _no_detail() -> ProjectDetail:
    raise AssertionError("the directory never reads a project's detail")


def _record(project_id: int, identifier: str, name: str, active: bool = True) -> ProjectRecord:
    summary = ProjectSummary(id=project_id, name=name, identifier=identifier, active=active, description=None)
    return ProjectRecord(summary=summary, to_detail=_no_detail, payload={})


class _FakeProjectApi:
    """The server's project index and single-project endpoint.

    `gate`, when set, holds every call until the test releases it, so
    concurrent callers can be lined up behind one in-flight request."""

    def __init__(self, projects: Sequence[tuple] = ()) -> None:
        self.projects = list(projects)
        self.list_calls: list[int] = []
        self.get_calls: list[str] = []
        self.list_error: Exception | None = None
        self.get_errors: dict[str, Exception] = {}
        self.gate: asyncio.Event | None = None
        self.held_pages: set[int] = set()
        self.in_flight = 0
        self.max_in_flight = 0

    async def _hold(self, page: int | None = None) -> None:
        if self.gate is not None and (page is None or not self.held_pages or page in self.held_pages):
            await self.gate.wait()

    async def list(self, *, server_offset: int, server_page_size: int, search: str | None) -> ProjectPage:
        self.list_calls.append(server_offset)
        await self._hold(server_offset)
        if self.list_error is not None:
            raise self.list_error
        start = (server_offset - 1) * server_page_size
        chunk = self.projects[start : start + server_page_size]
        return ProjectPage(
            records=[_record(*project) for project in chunk],
            server_total=len(self.projects),
            exhausted=start + server_page_size >= len(self.projects),
        )

    async def get(self, project_ref: str) -> ProjectRecord:
        self.get_calls.append(project_ref)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self._hold()
        finally:
            self.in_flight -= 1
        if project_ref in self.get_errors:
            raise self.get_errors[project_ref]
        for project in self.projects:
            if str(project[0]) == project_ref:
                return _record(*project)
        raise NotFoundError("not found")


def _directory(
    api: _FakeProjectApi,
    *,
    settings: Settings | None = None,
    clock: _Clock | None = None,
    api_prefix: str = PREFIX,
) -> ProjectDirectoryService:
    return ProjectDirectoryService(
        api=api,
        settings=settings or _base_settings(read_projects=("demo*",), write_projects=("demo*",)),
        origin=ORIGIN,
        api_prefix=api_prefix,
        clock=clock or _Clock(),
    )


def _representation(project_id: int, identifier: str, name: str) -> dict:
    return {
        "_type": "Project",
        "id": project_id,
        "identifier": identifier,
        "name": name,
        "_links": {"self": {"href": f"/api/v3/projects/{project_id}", "title": name}},
    }


def _work_package_in(project_id: int) -> dict:
    return {
        "_type": "WorkPackage",
        "id": 1,
        "_links": {"project": {"href": f"/api/v3/projects/{project_id}", "title": "Some project"}},
    }


@pytest.mark.asyncio
async def test_a_project_representation_is_recorded_without_a_fetch() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)

    await directory.learn(_representation(7, "demo-new", "Demo new"))

    assert directory.positives == {7: "demo-new"}
    assert directory.readable_project_ids() == {7}
    assert api.get_calls == []


@pytest.mark.asyncio
async def test_a_form_payload_is_never_recorded() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)
    form = {
        "_type": "Form",
        "_embedded": {"payload": {"_type": "Project", "identifier": "demo-proposed", "name": "Demo proposed"}},
    }

    await directory.learn(form)

    assert directory.positives == {}
    assert api.get_calls == []


@pytest.mark.asyncio
async def test_a_representation_whose_self_link_names_another_project_is_not_recorded() -> None:
    api = _FakeProjectApi([(8, "other", "Other")])
    directory = _directory(api)
    spoofed = _representation(7, "demo-spoof", "Demo spoof")
    spoofed["_links"]["self"]["href"] = "/api/v3/projects/8"

    await directory.learn(spoofed)

    assert 7 not in directory.positives
    assert api.get_calls == ["8"]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"_type": "Grid", "id": 4, "options": {"forged": _representation(2, "demo-forged", "Demo forged")}},
            id="grid options",
        ),
        pytest.param(
            {
                "_type": "Grid",
                "_embedded": {
                    "widgets": [
                        {"options": {"queryProps": {"_embedded": {"project": _representation(2, "demo-x", "X")}}}}
                    ]
                },
            },
            id="widget options below an embedded resource",
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_representation_inside_user_written_content_is_not_recorded(payload: dict) -> None:
    # Grid and widget options are free-form hashes any editor of the grid
    # writes and OpenProject renders unchanged.
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "secret", "Secret")])
    directory = _directory(api)
    await directory.refresh()

    await directory.learn(payload)

    assert directory.positives == {1: "demo"}
    assert directory.readable_project_ids() == {1}


@pytest.mark.asyncio
async def test_links_inside_user_written_content_cause_no_lookups() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)
    forged_links = {str(n): {"href": f"/api/v3/projects/{n}"} for n in range(100, 125)}
    grid = {
        "_type": "Grid",
        "options": {"_links": forged_links},
        "_embedded": {"widgets": [{"_type": "GridWidget", "options": {"queryProps": {"_links": forged_links}}}]},
    }

    await directory.learn(grid)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_an_embedded_project_representation_is_recorded() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)
    work_package = _work_package_in(7)
    work_package["_embedded"] = {"project": _representation(7, "demo-new", "Demo new")}

    await directory.learn({"_type": "Collection", "_embedded": {"elements": [work_package]}})

    assert directory.positives == {7: "demo-new"}
    assert api.get_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_work_package_in(7), id="work package project"),
        pytest.param(
            {
                "_type": "Collection",
                "_embedded": {
                    "elements": [
                        {"_type": "Version", "_links": {"definingProject": {"href": "/api/v3/projects/7"}}},
                    ]
                },
            },
            id="version definingProject in a collection",
        ),
        pytest.param(
            {"_type": "JobStatus", "payload": {"_links": {"project": {"href": "/api/v3/projects/7"}}}},
            id="job status payload project",
        ),
        pytest.param(
            {"_type": "WorkPackage", "_links": {"project": {"href": "/api/v3/workspaces/7"}}},
            id="17.x workspace link",
        ),
        pytest.param(
            {"_type": "Query", "_links": {"projects": [{"href": "/api/v3/projects/7"}]}},
            id="link array",
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_linked_unknown_project_is_looked_up_and_recorded(payload: dict) -> None:
    api = _FakeProjectApi([(7, "demo-copy", "Demo copy")])
    directory = _directory(api)

    await directory.learn(payload)

    assert directory.positives == {7: "demo-copy"}
    assert api.get_calls == ["7"]


@pytest.mark.asyncio
async def test_each_unknown_id_is_fetched_once_per_response() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a"), (9, "demo-b", "Demo b")])
    directory = _directory(api)
    payload = {"_embedded": {"elements": [_work_package_in(7), _work_package_in(7), _work_package_in(9)]}}

    await directory.learn(payload)

    assert sorted(api.get_calls) == ["7", "9"]
    assert directory.positives == {7: "demo-a", 9: "demo-b"}


@pytest.mark.asyncio
async def test_lookups_for_many_unseen_projects_run_a_bounded_number_at_a_time() -> None:
    api = _FakeProjectApi([(project_id, f"demo-{project_id}", "Demo") for project_id in range(1, 26)])
    api.gate = asyncio.Event()
    directory = _directory(api)
    payload = {"_embedded": {"elements": [_work_package_in(project_id) for project_id in range(1, 26)]}}

    learner = asyncio.create_task(directory.learn(payload))
    while not api.get_calls:
        await asyncio.sleep(0)
    for _ in range(10):
        await asyncio.sleep(0)
    in_flight_while_held = api.in_flight
    api.gate.set()
    await learner

    assert in_flight_while_held == 10
    assert api.max_in_flight == 10
    assert len(directory.positives) == 25


@pytest.mark.asyncio
async def test_concurrent_responses_share_one_lookup_per_id() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a")])
    api.gate = asyncio.Event()
    directory = _directory(api)

    learners = [asyncio.create_task(directory.learn(_work_package_in(7))) for _ in range(3)]
    await asyncio.sleep(0)
    api.gate.set()
    await asyncio.gather(*learners)

    assert api.get_calls == ["7"]
    assert directory.positives == {7: "demo-a"}


@pytest.mark.asyncio
async def test_cancelling_one_waiter_neither_cancels_the_lookup_nor_fails_the_others() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a")])
    api.gate = asyncio.Event()
    directory = _directory(api)

    cancelled = asyncio.create_task(directory.learn(_work_package_in(7)))
    survivor = asyncio.create_task(directory.learn(_work_package_in(7)))
    while not api.get_calls:
        await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    api.gate.set()
    await survivor

    assert api.get_calls == ["7"]
    assert directory.positives == {7: "demo-a"}


@pytest.mark.asyncio
async def test_out_of_scope_projects_seen_by_the_scan_cause_no_fetch() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "other", "Other")])
    directory = _directory(api)
    await directory.refresh()

    await directory.learn(_work_package_in(2))

    assert api.get_calls == []
    assert api.list_calls == [1]
    assert directory.positives == {1: "demo"}


@pytest.mark.asyncio
async def test_an_expired_negative_seen_by_the_scan_triggers_a_rescan_not_a_fetch() -> None:
    clock = _Clock()
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "other", "Other")])
    directory = _directory(api, clock=clock)
    await directory.refresh()
    api.projects[1] = (2, "demo-renamed", "Demo renamed")
    clock.now += FRESHNESS_SECONDS + 1

    await directory.learn(_work_package_in(2))

    assert api.get_calls == []
    assert api.list_calls == [1, 1]
    assert directory.positives == {1: "demo", 2: "demo-renamed"}


@pytest.mark.asyncio
async def test_a_404_marks_the_id_negative_until_it_expires() -> None:
    clock = _Clock()
    api = _FakeProjectApi()
    directory = _directory(api, clock=clock)

    await directory.learn(_work_package_in(7))
    await directory.learn(_work_package_in(7))
    assert api.get_calls == ["7"]

    clock.now += FRESHNESS_SECONDS + 1
    api.projects.append((7, "demo-late", "Demo late"))
    await directory.learn(_work_package_in(7))

    assert api.get_calls == ["7", "7"]
    assert directory.positives == {7: "demo-late"}


@pytest.mark.parametrize(
    "error",
    [PermissionDeniedError("forbidden"), TransportError("Could not reach OpenProject")],
    ids=["403", "transport"],
)
@pytest.mark.asyncio
async def test_a_failed_lookup_leaves_the_id_unknown_and_does_not_raise(error: Exception) -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a")])
    api.get_errors["7"] = error
    directory = _directory(api)

    await directory.learn(_work_package_in(7))
    del api.get_errors["7"]
    await directory.learn(_work_package_in(7))

    assert api.get_calls == ["7", "7"]
    assert directory.positives == {7: "demo-a"}


@pytest.mark.asyncio
async def test_concurrent_ensure_fresh_calls_share_one_scan() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo")])
    api.gate = asyncio.Event()
    directory = _directory(api)

    callers = [asyncio.create_task(directory.ensure_fresh()) for _ in range(3)]
    await asyncio.sleep(0)
    api.gate.set()
    await asyncio.gather(*callers)

    assert api.list_calls == [1]
    assert directory.positives == {1: "demo"}


@pytest.mark.asyncio
async def test_cancelling_one_caller_does_not_cancel_the_shared_scan() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo")])
    api.gate = asyncio.Event()
    directory = _directory(api)

    cancelled = asyncio.create_task(directory.refresh())
    survivor = asyncio.create_task(directory.refresh())
    while not api.list_calls:
        await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.sleep(0)
    api.gate.set()
    await survivor

    assert api.list_calls == [1]
    assert directory.positives == {1: "demo"}


@pytest.mark.asyncio
async def test_ensure_fresh_rescans_only_after_the_freshness_window() -> None:
    clock = _Clock()
    api = _FakeProjectApi([(1, "demo", "Demo")])
    directory = _directory(api, clock=clock)

    await directory.ensure_fresh()
    clock.now += FRESHNESS_SECONDS - 1
    await directory.ensure_fresh()
    assert api.list_calls == [1]

    clock.now += 2
    await directory.ensure_fresh()
    assert api.list_calls == [1, 1]


@pytest.mark.asyncio
async def test_a_scan_is_applied_in_one_step_after_its_last_page() -> None:
    settings = _base_settings(read_projects=("demo*",), write_projects=("demo*",), max_page_size=1)
    api = _FakeProjectApi([(1, "demo-old", "Demo old")])
    directory = _directory(api, settings=settings)
    await directory.refresh()

    api.projects = [(2, "demo-a", "Demo a"), (3, "demo-b", "Demo b")]
    api.gate = asyncio.Event()
    api.held_pages = {2}
    scan = asyncio.create_task(directory.refresh())
    while api.list_calls != [1, 1, 2]:
        await asyncio.sleep(0)

    assert directory.positives == {1: "demo-old"}
    assert directory.readable_project_ids() == {1}

    api.gate.set()
    await scan
    assert directory.positives == {2: "demo-a", 3: "demo-b"}
    assert directory.readable_project_ids() == {2, 3}


@pytest.mark.asyncio
async def test_a_failed_scan_keeps_the_previous_state_and_waits_before_retrying(caplog) -> None:
    clock = _Clock()
    api = _FakeProjectApi([(1, "demo", "Demo")])
    directory = _directory(api, clock=clock)
    await directory.refresh()

    api.list_error = TransportError("Could not reach OpenProject")
    clock.now += FRESHNESS_SECONDS + 1
    with caplog.at_level(logging.WARNING):
        await directory.ensure_fresh()
        await directory.ensure_fresh()

    assert directory.positives == {1: "demo"}
    assert api.list_calls == [1, 1]
    assert any("allowlist scan failed" in record.message for record in caplog.records)

    clock.now += FRESHNESS_SECONDS + 1
    await directory.ensure_fresh()
    assert api.list_calls == [1, 1, 1]


@pytest.mark.asyncio
async def test_a_scan_never_overwrites_what_was_recorded_after_it_started() -> None:
    api = _FakeProjectApi([(1, "demo-one", "Demo one"), (2, "other", "Other")])
    api.gate = asyncio.Event()
    directory = _directory(api)

    scan = asyncio.create_task(directory.refresh())
    while not api.list_calls:
        await asyncio.sleep(0)
    directory.record(1, "moved-out", "Moved out", archived=False)
    directory.record(2, "demo-moved-in", "Demo moved in", archived=False)
    api.gate.set()
    await scan

    assert directory.positives == {2: "demo-moved-in"}
    assert directory.readable_project_ids() == {2}


@pytest.mark.asyncio
async def test_a_project_allowlisted_only_by_name_is_readable() -> None:
    directory = _directory(_FakeProjectApi(), settings=_base_settings(read_projects=("Demo Project",)))

    directory.record(5, "x5", "Demo Project", archived=False)

    assert directory.positives == {5: "x5"}
    assert directory.readable_project_ids() == {5}


@pytest.mark.asyncio
async def test_recording_a_project_that_moved_out_of_scope_drops_it() -> None:
    directory = _directory(_FakeProjectApi())
    directory.record(1, "demo", "Demo", archived=False)

    directory.record(1, "other", "Other", archived=False)

    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()


@pytest.mark.asyncio
async def test_a_write_only_project_is_known_but_not_readable() -> None:
    directory = _directory(_FakeProjectApi(), settings=_base_settings(read_projects=("demo",), write_projects=("ops",)))

    directory.record(3, "ops", "Ops", archived=False)

    assert directory.positives == {3: "ops"}
    assert directory.readable_project_ids() == frozenset()


@pytest.mark.asyncio
async def test_an_archived_project_stays_known_but_is_not_readable() -> None:
    # OpenProject rejects a work-package project filter naming an archived
    # project, so the global list must not receive one.
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-archived", "Demo archived", False)])
    directory = _directory(api)

    await directory.refresh()
    archived = _representation(3, "demo-old", "Demo old")
    archived["active"] = False
    await directory.learn(archived)

    assert directory.positives == {1: "demo", 2: "demo-archived", 3: "demo-old"}
    assert directory.readable_project_ids() == {1}


@pytest.mark.parametrize(
    ("href", "looked_up"),
    [
        ("/op/api/v3/projects/7", True),
        ("/op/api/v3/projects/7/", True),
        ("/op/api/v3/workspaces/7", True),
        ("https://op.example.com/op/api/v3/projects/7", True),
        ("https://evil.example.com/op/api/v3/projects/7", False),
        ("/api/v3/projects/7", False),
        ("/op/api/v3/projects/7/categories", False),
        ("/op/api/v3/versions/7", False),
        ("/op/api/v3/projects/demo", False),
    ],
)
@pytest.mark.asyncio
async def test_only_project_hrefs_under_the_configured_api_are_project_links(href: str, looked_up: bool) -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a")])
    directory = _directory(api, api_prefix="/op/api/v3/")

    await directory.learn({"_links": {"project": {"href": href}}})

    assert api.get_calls == (["7"] if looked_up else [])


@pytest.mark.parametrize(
    ("read_projects", "write_projects"),
    [(("*",), ("*",)), ((), ())],
    ids=["wildcard", "empty"],
)
@pytest.mark.asyncio
async def test_unrestricted_scopes_need_no_directory(read_projects: tuple, write_projects: tuple) -> None:
    api = _FakeProjectApi([(1, "demo", "Demo")])
    directory = _directory(api, settings=_base_settings(read_projects=read_projects, write_projects=write_projects))

    await directory.refresh()
    await directory.ensure_fresh()
    await directory.learn(_work_package_in(1))
    directory.record(1, "demo", "Demo", archived=False)

    assert api.list_calls == []
    assert api.get_calls == []
    assert directory.positives == {}
