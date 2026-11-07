from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Coroutine, Sequence
from typing import Any

import pytest
from _client_test_helpers import _base_settings
from _project_record_helpers import project_record

from openproject_ce_mcp import http_request_counter
from openproject_ce_mcp.app.call_scope import tool_call
from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError, TransportError
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.services.project_directory_service import FRESHNESS_SECONDS, ProjectDirectoryService
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary

ORIGIN = "https://op.example.com"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _no_detail() -> ProjectDetail:
    raise AssertionError("the directory never reads a project's detail")


def _record(project_id: int, identifier: str, name: str, active: bool = True) -> ProjectRecord:
    summary = ProjectSummary(id=project_id, name=name, identifier=identifier, active=active, description=None)
    return project_record(summary)


class _FakeProjectApi:
    """The server's project index and single-project endpoint.

    `gate`, when set, holds every call until the test releases it, so
    concurrent callers can be lined up behind one in-flight request."""

    def __init__(self, projects: Sequence[tuple] = ()) -> None:
        self.projects = list(projects)
        self.list_calls: list[int] = []
        self.listed_ids: list[list[int]] = []
        self.get_calls: list[str] = []
        self.list_error: Exception | None = None
        self.get_errors: dict[str, Exception] = {}
        self.gate: asyncio.Event | None = None
        self.held_pages: set[int] = set()
        self.ancestor_calls: list[int | None] = []
        # project id -> ids of the projects below it, as OpenProject's ancestor filter would answer
        self.below: dict[int, set[int]] = {}
        self.in_flight = 0
        self.max_in_flight = 0

    async def _hold(self, page: int | None = None) -> None:
        if self.gate is not None and (page is None or not self.held_pages or page in self.held_pages):
            await self.gate.wait()

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        ids: Sequence[int] | None = None,
        ancestor_id: int | None = None,
    ) -> ProjectPage:
        self.list_calls.append(server_offset)
        if ids is not None:
            self.listed_ids.append(list(ids))
        self.ancestor_calls.append(ancestor_id)
        await self._hold(server_offset)
        if self.list_error is not None:
            raise self.list_error
        matching = [
            project
            for project in self.projects
            if (ids is None or project[0] in ids)
            and (ancestor_id is None or project[0] in self.below.get(ancestor_id, ()))
        ]
        start = (server_offset - 1) * server_page_size
        chunk = matching[start : start + server_page_size]
        return ProjectPage(
            records=[_record(*project) for project in chunk],
            server_total=len(matching),
            exhausted=start + server_page_size >= len(matching),
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
    base_url: str = ORIGIN,
) -> ProjectDirectoryService:
    return ProjectDirectoryService(
        api=api,
        settings=dataclasses.replace(
            settings or _base_settings(read_projects=("demo*",), write_projects=("demo*",)), base_url=base_url
        ),
        clock=clock or _Clock(),
    )


def _learn(directory: ProjectDirectoryService, payload: Any) -> Coroutine[Any, Any, None]:
    """Learn `payload` as the answer to a request sent just now."""
    return directory.learn(payload, sent=directory.request_sent())


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

    await _learn(directory, _representation(7, "demo-new", "Demo new"))

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

    await _learn(directory, form)

    assert directory.positives == {}
    assert api.get_calls == []


@pytest.mark.asyncio
async def test_a_representation_whose_self_link_names_another_project_is_not_recorded() -> None:
    api = _FakeProjectApi([(8, "other", "Other")])
    directory = _directory(api)
    spoofed = _representation(7, "demo-spoof", "Demo spoof")
    spoofed["_links"]["self"]["href"] = "/api/v3/projects/8"

    await _learn(directory, spoofed)

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

    await _learn(directory, payload)

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

    await _learn(directory, grid)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_an_embedded_project_representation_is_recorded() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)
    work_package = _work_package_in(7)
    work_package["_embedded"] = {"project": _representation(7, "demo-new", "Demo new")}

    await _learn(directory, {"_type": "Collection", "_embedded": {"elements": [work_package]}})

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

    await _learn(directory, payload)

    assert directory.positives == {7: "demo-copy"}
    assert api.get_calls == ["7"]


@pytest.mark.asyncio
async def test_each_unknown_id_is_fetched_once_per_response() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Demo a"), (9, "demo-b", "Demo b")])
    directory = _directory(api)
    payload = {"_embedded": {"elements": [_work_package_in(7), _work_package_in(7), _work_package_in(9)]}}

    await _learn(directory, payload)

    assert sorted(api.get_calls) == ["7", "9"]
    assert directory.positives == {7: "demo-a", 9: "demo-b"}


@pytest.mark.asyncio
async def test_lookups_for_many_unseen_projects_run_a_bounded_number_at_a_time() -> None:
    api = _FakeProjectApi([(project_id, f"demo-{project_id}", "Demo") for project_id in range(1, 26)])
    api.gate = asyncio.Event()
    directory = _directory(api)
    payload = {"_embedded": {"elements": [_work_package_in(project_id) for project_id in range(1, 26)]}}

    learner = asyncio.create_task(_learn(directory, payload))
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

    learners = [asyncio.create_task(_learn(directory, _work_package_in(7))) for _ in range(3)]
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

    cancelled = asyncio.create_task(_learn(directory, _work_package_in(7)))
    survivor = asyncio.create_task(_learn(directory, _work_package_in(7)))
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

    await _learn(directory, _work_package_in(2))

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

    await _learn(directory, _work_package_in(2))

    assert api.get_calls == []
    assert api.list_calls == [1, 1]
    assert directory.positives == {1: "demo", 2: "demo-renamed"}


@pytest.mark.asyncio
async def test_a_404_marks_the_id_negative_until_it_expires() -> None:
    clock = _Clock()
    api = _FakeProjectApi()
    directory = _directory(api, clock=clock)

    await _learn(directory, _work_package_in(7))
    await _learn(directory, _work_package_in(7))
    assert api.get_calls == ["7"]

    clock.now += FRESHNESS_SECONDS + 1
    api.projects.append((7, "demo-late", "Demo late"))
    await _learn(directory, _work_package_in(7))

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

    await _learn(directory, _work_package_in(7))
    del api.get_errors["7"]
    await _learn(directory, _work_package_in(7))

    assert api.get_calls == ["7", "7"]
    assert directory.positives == {7: "demo-a"}


@pytest.mark.asyncio
async def test_a_known_project_is_read_again_when_only_its_recorded_identifier_admits_a_link() -> None:
    api = _FakeProjectApi([(7, "renamed", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-old", archived=False)

    await _learn(directory, _work_package_in(7))

    assert api.listed_ids == [[7]]
    assert api.get_calls == []
    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()


@pytest.mark.parametrize(
    ("read_projects", "write_projects"),
    [(("7",), ()), (("7",), ("7",))],
    ids=["id", "id-for-both"],
)
@pytest.mark.asyncio
async def test_a_known_project_is_not_read_again_when_the_link_matches_by_itself(
    read_projects: tuple, write_projects: tuple
) -> None:
    api = _FakeProjectApi([(7, "renamed", "Some project")])
    directory = _directory(api, settings=_base_settings(read_projects=read_projects, write_projects=write_projects))
    directory.record(7, "x7", archived=False)

    await _learn(directory, _work_package_in(7))

    assert api.get_calls == []
    assert directory.positives == {7: "x7"}


@pytest.mark.asyncio
async def test_a_known_project_is_read_again_when_its_identifier_alone_admits_a_write() -> None:
    api = _FakeProjectApi([(7, "renamed", "Some project")])
    settings = _base_settings(read_projects=("7",), write_projects=("demo-old",))
    directory = _directory(api, settings=settings)
    directory.record(7, "demo-old", archived=False)

    await _learn(directory, _work_package_in(7))

    assert api.listed_ids == [[7]]
    assert directory.positives == {7: "renamed"}


@pytest.mark.asyncio
async def test_a_project_shown_in_the_same_response_is_not_read_again() -> None:
    api = _FakeProjectApi()
    directory = _directory(api)
    directory.record(7, "demo-old", archived=False)
    payload = _work_package_in(7)
    payload["_embedded"] = {"project": _representation(7, "demo-new", "Some project")}

    await _learn(directory, payload)

    assert api.get_calls == []
    assert directory.positives == {7: "demo-new"}


@pytest.mark.asyncio
async def test_a_failed_re_read_forgets_the_project_and_the_next_link_looks_it_up() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Some project")])
    directory = _directory(api)
    await directory.refresh()
    api.list_error = TransportError("Could not reach OpenProject")

    await _learn(directory, _work_package_in(7))
    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()

    api.list_error = None
    await _learn(directory, _work_package_in(7))

    assert api.get_calls == ["7"]
    assert api.list_calls == [1, 1]
    assert directory.positives == {7: "demo-a"}


class _HeldReads(_FakeProjectApi):
    """Each id-filtered read takes the projects as they are when it is called, then waits until
    the test releases that call, as a server answer still in transit would."""

    def __init__(self, projects: Sequence[tuple] = ()) -> None:
        super().__init__(projects)
        self.arrived: asyncio.Queue[list[int]] = asyncio.Queue()
        self._releases: list[asyncio.Event] = []

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        ids: Sequence[int] | None = None,
        ancestor_id: int | None = None,
    ) -> ProjectPage:
        if ids is None:
            return await super().list(
                server_offset=server_offset,
                server_page_size=server_page_size,
                search=search,
                ids=ids,
                ancestor_id=ancestor_id,
            )
        self.listed_ids.append(list(ids))
        answer = [project for project in self.projects if project[0] in ids]
        release = asyncio.Event()
        self._releases.append(release)
        self.arrived.put_nowait(list(ids))
        await release.wait()
        if self.list_error is not None:
            raise self.list_error
        return ProjectPage(records=[_record(*project) for project in answer], server_total=len(answer), exhausted=True)

    def release(self, call: int) -> None:
        self._releases[call].set()


@pytest.mark.asyncio
async def test_a_response_relies_only_on_a_read_that_started_after_it_arrived() -> None:
    api = _HeldReads([(7, "demo-old", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-old", archived=False)
    first = asyncio.create_task(_learn(directory, _work_package_in(7)))
    await api.arrived.get()
    api.projects[0] = (7, "renamed", "Some project")

    second = asyncio.create_task(_learn(directory, _work_package_in(7)))
    # Bounds a failure only: the response must start a read of its own.
    await asyncio.wait_for(api.arrived.get(), timeout=5)
    api.release(1)
    await second
    assert directory.positives == {}

    api.release(0)
    await first
    assert directory.positives == {}
    assert api.listed_ids == [[7], [7]]


@pytest.mark.parametrize(
    ("error", "answered"),
    [
        (None, None),
        (TransportError("Could not reach OpenProject"), (7, "demo-old", "Some project")),
        (None, (7, "", "Some project")),
    ],
    ids=["gone", "failure", "no-identifier"],
)
@pytest.mark.asyncio
async def test_a_read_that_ends_without_a_project_keeps_what_a_later_read_recorded(
    error: Exception | None, answered: tuple | None
) -> None:
    api = _HeldReads([answered] if answered else [])
    api.list_error = error
    directory = _directory(api)
    directory.record(7, "demo-old", archived=False)
    earlier = asyncio.create_task(_learn(directory, _work_package_in(7)))
    await api.arrived.get()

    await _learn(directory, _representation(7, "demo-new", "Some project"))
    api.release(0)
    await earlier

    assert directory.positives == {7: "demo-new"}
    assert directory.readable_project_ids() == {7}
    assert api.listed_ids == [[7]]


class _HeldConfirmation(_FakeProjectApi):
    """An id-filtered index answers with the projects as they were when it
    was called and holds that answer until the test releases it."""

    def __init__(self, projects: Sequence[tuple] = ()) -> None:
        super().__init__(projects)
        self.confirmation_arrived: asyncio.Queue[list[int]] = asyncio.Queue()
        self.release_confirmation = asyncio.Event()
        self._held = False

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        ids: Sequence[int] | None = None,
        ancestor_id: int | None = None,
    ) -> ProjectPage:
        page = await super().list(
            server_offset=server_offset,
            server_page_size=server_page_size,
            search=search,
            ids=ids,
            ancestor_id=ancestor_id,
        )
        if ids is not None and not self._held:
            self._held = True
            self.confirmation_arrived.put_nowait(list(ids))
            await self.release_confirmation.wait()
        return page


@pytest.mark.asyncio
async def test_current_readable_projects_answers_from_what_was_recorded_after_its_request_began() -> None:
    api = _HeldConfirmation([(1, "demo-a", "Some project")])
    directory = _directory(api)
    await directory.refresh()
    confirming = asyncio.create_task(directory.current_readable_project_ids())
    assert await api.confirmation_arrived.get() == [1]

    api.projects[0] = (1, "other", "Some project")
    await _learn(directory, _work_package_in(1))
    api.release_confirmation.set()

    assert await confirming == frozenset()
    assert directory.positives == {}
    assert api.listed_ids == [[1], [1]]


@pytest.mark.asyncio
async def test_current_readable_projects_keeps_a_project_its_answer_missed_but_a_later_read_recorded() -> None:
    api = _HeldConfirmation([(1, "demo-a", "Some project")])
    directory = _directory(api)
    await directory.refresh()
    api.projects = []
    confirming = asyncio.create_task(directory.current_readable_project_ids())
    assert await api.confirmation_arrived.get() == [1]

    await _learn(directory, _representation(1, "demo-a", "Some project"))
    api.release_confirmation.set()

    assert await confirming == {1}
    assert directory.positives == {1: "demo-a"}


class _HeldScan(_FakeProjectApi):
    def __init__(self, projects: Sequence[tuple] = ()) -> None:
        super().__init__(projects)
        self.scan_gate: asyncio.Event | None = None
        self.scan_arrived: asyncio.Queue[int] = asyncio.Queue()

    async def list(
        self,
        *,
        server_offset: int,
        server_page_size: int,
        search: str | None,
        ids: Sequence[int] | None = None,
        ancestor_id: int | None = None,
    ) -> ProjectPage:
        page = await super().list(
            server_offset=server_offset,
            server_page_size=server_page_size,
            search=search,
            ids=ids,
            ancestor_id=ancestor_id,
        )
        if ids is None:
            self.scan_arrived.put_nowait(server_offset)
            if self.scan_gate is not None:
                await self.scan_gate.wait()
        return page


@pytest.mark.asyncio
async def test_a_scan_does_not_undo_forgetting_a_project_whose_re_read_failed_while_it_ran() -> None:
    api = _HeldScan([(7, "demo-a", "Some project")])
    directory = _directory(api)
    await directory.refresh()
    await api.scan_arrived.get()
    api.scan_gate = asyncio.Event()
    scan = asyncio.create_task(directory.refresh())
    await api.scan_arrived.get()
    api.list_error = TransportError("Could not reach OpenProject")
    await _learn(directory, _work_package_in(7))
    api.scan_gate.set()
    await scan

    api.list_error = None
    await _learn(directory, _work_package_in(7))

    assert api.get_calls == ["7"]
    assert directory.positives == {7: "demo-a"}


@pytest.mark.asyncio
async def test_a_lookup_answered_without_an_identifier_forgets_the_project() -> None:
    api = _FakeProjectApi([(7, "", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-old", archived=False)

    await _learn(directory, _work_package_in(7))

    assert api.listed_ids == [[7]]
    assert api.get_calls == []
    assert directory.positives == {}


@pytest.mark.asyncio
async def test_current_readable_projects_re_reads_in_one_request_what_the_id_alone_does_not_admit() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-b", "Demo b"), (3, "x3", "Three")])
    directory = _directory(api, settings=_base_settings(read_projects=("demo*", "3")))
    await directory.refresh()
    api.projects[1] = (2, "other", "Other")

    readable = await directory.current_readable_project_ids()

    assert readable == {1, 3}
    assert api.listed_ids == [[1, 2]]
    assert api.get_calls == []
    assert directory.positives == {1: "demo", 3: "x3"}


@pytest.mark.parametrize(
    "server_side",
    [[(1, "demo", "Demo")], [(1, "demo", "Demo"), (2, "demo-b", "Demo b", False)]],
    ids=["gone", "archived"],
)
@pytest.mark.asyncio
async def test_current_readable_projects_leaves_out_a_project_gone_or_archived_since_it_was_recorded(
    server_side: list,
) -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-b", "Demo b")])
    directory = _directory(api)
    await directory.refresh()
    api.projects = server_side

    assert await directory.current_readable_project_ids() == {1}
    assert directory.readable_project_ids() == {1}


@pytest.mark.asyncio
async def test_current_readable_projects_fails_when_the_re_read_fails() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo")])
    directory = _directory(api)
    await directory.refresh()
    api.list_error = TransportError("Could not reach OpenProject")

    with pytest.raises(TransportError):
        await directory.current_readable_project_ids()


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
    directory.record(1, "moved-out", archived=False)
    directory.record(2, "demo-moved-in", archived=False)
    api.gate.set()
    await scan

    assert directory.positives == {2: "demo-moved-in"}
    assert directory.readable_project_ids() == {2}


@pytest.mark.asyncio
async def test_a_project_allowlisted_only_by_name_is_not_readable() -> None:
    directory = _directory(_FakeProjectApi(), settings=_base_settings(read_projects=("Demo Project", "demo-project")))

    directory.record(5, "x5", archived=False)

    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()


@pytest.mark.asyncio
async def test_recording_a_project_that_moved_out_of_scope_drops_it() -> None:
    directory = _directory(_FakeProjectApi())
    directory.record(1, "demo", archived=False)

    directory.record(1, "other", archived=False)

    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()


@pytest.mark.asyncio
async def test_a_write_only_project_is_known_but_not_readable() -> None:
    directory = _directory(_FakeProjectApi(), settings=_base_settings(read_projects=("demo",), write_projects=("ops",)))

    directory.record(3, "ops", archived=False)

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
    await _learn(directory, archived)

    assert directory.positives == {1: "demo", 2: "demo-archived", 3: "demo-old"}
    assert directory.readable_project_ids() == {1}


@pytest.mark.parametrize(
    ("href", "looked_up"),
    [
        ("/op/api/v3/projects/7", True),
        ("/op/api/v3/projects/7/", False),
        ("/op/api/v3/workspaces/7", True),
        ("/op/api/v3/programs/7", True),
        ("/op/api/v3/portfolios/7", True),
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
    directory = _directory(api, base_url=f"{ORIGIN}/op")

    await _learn(directory, {"_links": {"project": {"href": href}}})

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
    await _learn(directory, _work_package_in(1))
    directory.record(1, "demo", archived=False)

    assert api.list_calls == []
    assert api.get_calls == []
    assert directory.positives == {}


@pytest.mark.asyncio
async def test_readable_descendants_are_the_ones_below_a_project_that_the_scope_covers() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-b", "Demo b"), (3, "secret", "Secret"), (4, "demo-c", "C")])
    api.below = {1: {2, 3, 4}}
    directory = _directory(api, settings=_base_settings(read_projects=("demo*",)))

    descendants = await directory.readable_descendant_ids(1)

    assert descendants == {2, 4}
    assert api.ancestor_calls == [1]
    assert directory.positives == {2: "demo-b", 4: "demo-c"}


@pytest.mark.asyncio
async def test_readable_descendants_leave_out_an_archived_project() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-b", "Demo b", False)])
    api.below = {1: {2}}
    directory = _directory(api, settings=_base_settings(read_projects=("demo*",)))

    assert await directory.readable_descendant_ids(1) == frozenset()


@pytest.mark.asyncio
async def test_readable_descendants_are_judged_on_the_answer_not_on_an_earlier_name() -> None:
    api = _FakeProjectApi([(1, "demo", "Demo"), (2, "demo-b", "Demo b")])
    api.below = {1: {2}}
    directory = _directory(api, settings=_base_settings(read_projects=("demo*",)))
    await directory.refresh()
    api.projects[1] = (2, "renamed", "Renamed")

    assert await directory.readable_descendant_ids(1) == frozenset()


@pytest.mark.asyncio
async def test_a_recorded_identifier_is_read_again_once_per_tool_call() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-a", archived=False)

    with tool_call():
        for _ in range(3):
            await _learn(directory, _work_package_in(7))

    assert api.listed_ids == [[7]]
    assert api.get_calls == []


@pytest.mark.asyncio
async def test_a_rename_is_noticed_by_the_next_tool_call() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-a", archived=False)
    with tool_call():
        await _learn(directory, _work_package_in(7))
    assert directory.positives == {7: "demo-a"}

    api.projects[0] = (7, "renamed", "Some project")
    with tool_call():
        await _learn(directory, _work_package_in(7))

    assert directory.positives == {}
    assert api.listed_ids == [[7], [7]]


@pytest.mark.asyncio
async def test_outside_a_tool_call_every_response_reads_again() -> None:
    api = _FakeProjectApi([(7, "demo-a", "Some project")])
    directory = _directory(api)
    directory.record(7, "demo-a", archived=False)

    for _ in range(3):
        await _learn(directory, _work_package_in(7))

    assert api.listed_ids == [[7], [7], [7]]


@pytest.mark.asyncio
async def test_a_response_linking_several_known_projects_reads_them_in_one_request() -> None:
    api = _FakeProjectApi([(7, "demo-a", "A"), (8, "demo-b", "B"), (9, "demo-c", "C")])
    directory = _directory(api)
    for project_id, identifier in ((7, "demo-a"), (8, "demo-b"), (9, "demo-c")):
        directory.record(project_id, identifier, archived=False)
    payload = {
        "_type": "Collection",
        "_embedded": {"elements": [_work_package_in(7), _work_package_in(8), _work_package_in(9)]},
    }

    with tool_call():
        await _learn(directory, payload)
        await _learn(directory, payload)

    assert api.listed_ids == [[7, 8, 9]]
    assert api.get_calls == []
    assert directory.positives == {7: "demo-a", 8: "demo-b", 9: "demo-c"}


class _CountingProjectApi(_FakeProjectApi):
    """Counts a request per call like the counting transport does for a real one."""

    async def list(self, **kwargs: Any) -> ProjectPage:
        http_request_counter.increment()
        return await super().list(**kwargs)

    async def get(self, project_ref: str) -> ProjectRecord:
        http_request_counter.increment()
        return await super().get(project_ref)


@pytest.mark.asyncio
async def test_the_call_that_starts_a_scan_counts_its_requests() -> None:
    api = _CountingProjectApi([(project_id, f"demo-{project_id}", "Demo") for project_id in range(1, 5)])
    directory = _directory(api, settings=_base_settings(read_projects=("demo*",), max_page_size=2))
    http_request_counter.reset()

    await directory.refresh()

    assert api.list_calls == [1, 2]
    assert http_request_counter.current() == 2


@pytest.mark.asyncio
async def test_a_call_that_waits_for_a_scan_it_did_not_start_counts_nothing() -> None:
    api = _CountingProjectApi([(1, "demo", "Demo")])
    api.gate = asyncio.Event()
    directory = _directory(api)
    waiter_counts: list[int] = []

    async def starter() -> int:
        http_request_counter.reset()
        await directory.refresh()
        return http_request_counter.current()

    async def waiter() -> None:
        http_request_counter.reset()
        await directory.refresh()
        waiter_counts.append(http_request_counter.current())

    starting = asyncio.create_task(starter())
    await asyncio.sleep(0)
    waiting = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    api.gate.set()

    assert await starting == 1
    await waiting
    assert waiter_counts == [0]


@pytest.mark.asyncio
async def test_the_call_that_starts_a_lookup_counts_its_request() -> None:
    api = _CountingProjectApi([(7, "demo-a", "Demo a")])
    directory = _directory(api)
    http_request_counter.reset()

    await _learn(directory, _work_package_in(7))

    assert api.get_calls == ["7"]
    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_concurrent_calls_count_only_the_lookups_they_started() -> None:
    api = _CountingProjectApi([(project_id, f"demo-{project_id}", "Demo") for project_id in (7, 8, 9)])
    api.gate = asyncio.Event()
    directory = _directory(api)

    async def call(*project_ids: int) -> int:
        http_request_counter.reset()
        for project_id in project_ids:
            await _learn(directory, _work_package_in(project_id))
        return http_request_counter.current()

    calls = [asyncio.create_task(call(7)), asyncio.create_task(call(8, 9)), asyncio.create_task(call())]
    while len(api.get_calls) < 1:
        await asyncio.sleep(0)
    api.gate.set()

    assert await asyncio.gather(*calls) == [1, 2, 0]
