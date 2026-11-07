from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _client_test_helpers import _base_settings
from _project_record_helpers import project_record

from openproject_ce_mcp.app.errors import PermissionDeniedError, TransportError
from openproject_ce_mcp.app.policies.scope import ensure_project_link_allowed
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.services.project_directory_service import ProjectDirectoryService
from openproject_ce_mcp.app.transport.learning_transport import LearningTransport
from openproject_ce_mcp.app.transport.protocol import BinaryContent, TransportResponse
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary


class _Inner:
    """Answers every call with its own fresh body, so identity shows the body
    is passed through untouched."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.events = [] if events is None else events

    def _body(self) -> dict[str, Any]:
        self.events.append("requested")
        body = {"_type": "WorkPackage", "_links": {"project": {"href": "/api/v3/projects/7"}}}
        self.bodies.append(body)
        return body

    async def get_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def post_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def post_text(self, path: str, **_: Any) -> str:
        return "<p>x</p>"

    async def post_multipart(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def patch_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def delete_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def get_binary(self, path: str, **_: Any) -> BinaryContent:
        return BinaryContent(data=b"x", content_type=None, truncated=False)

    async def delete(self, path: str, **_: Any) -> None:
        return None

    async def request_raw(self, method: str, path: str, **_: Any) -> TransportResponse:
        return TransportResponse(status_code=204, headers={}, redirect_headers=())


JSON_CALLS = {
    "get_json": lambda t: t.get_json("x"),
    "post_json": lambda t: t.post_json("x", json_body={}),
    "post_multipart": lambda t: t.post_multipart(
        "x", metadata={}, file_name="a.txt", file_bytes=b"a", content_type="text/plain"
    ),
    "patch_json": lambda t: t.patch_json("x", json_body={}),
    "delete_json": lambda t: t.delete_json("x"),
}

OTHER_CALLS = {
    "post_text": lambda t: t.post_text("x", content=b"x", headers={}),
    "get_binary": lambda t: t.get_binary("x", max_bytes=1),
    "delete": lambda t: t.delete("x"),
    "request_raw": lambda t: t.request_raw("GET", "x"),
}


class _Learner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.learned: list[tuple[Any, int]] = []

    def request_sent(self) -> int:
        self.events.append("sent")
        return 41

    async def learn(self, payload: Any, *, sent: int) -> None:
        self.events.append("learned")
        self.learned.append((payload, sent))


@pytest.mark.parametrize("call", JSON_CALLS.values(), ids=JSON_CALLS.keys())
@pytest.mark.asyncio
async def test_every_json_body_is_learned_with_its_send_time_before_it_is_returned_unchanged(call) -> None:
    events: list[str] = []
    inner = _Inner(events)
    learner = _Learner(events)

    body = await call(LearningTransport(inner, learner=learner))

    assert body is inner.bodies[0]
    assert learner.learned == [(body, 41)]
    assert learner.learned[0][0] is body
    assert events == ["sent", "requested", "learned"]


@pytest.mark.parametrize("call", OTHER_CALLS.values(), ids=OTHER_CALLS.keys())
@pytest.mark.asyncio
async def test_responses_without_a_json_body_are_not_learned(call) -> None:
    learner = _Learner([])

    await call(LearningTransport(_Inner(), learner=learner))

    assert learner.learned == []


@pytest.mark.asyncio
async def test_a_failed_project_lookup_does_not_lose_a_confirmed_write() -> None:
    class _UnreachableProjects:
        async def list(self, *, server_offset: int, server_page_size: int, search: str | None) -> ProjectPage:
            raise AssertionError("learning a link never scans")

        async def get(self, project_ref: str) -> ProjectRecord:
            raise TransportError("Could not reach OpenProject")

    directory = ProjectDirectoryService(
        api=_UnreachableProjects(),
        settings=_base_settings(read_projects=("demo",), write_projects=("demo",)),
    )
    inner = _Inner()

    body = await LearningTransport(inner, learner=directory).patch_json("work_packages/1", json_body={})

    assert body is inner.bodies[0]
    assert directory.positives == {}


class _GatedProjects:
    """Project 42 as the server holds it now; `projects` changes on a rename."""

    def __init__(self) -> None:
        self.projects = {42: ("FIDOLD", "Fid Project")}

    async def list(
        self, *, server_offset: int, server_page_size: int, search: str | None, ids: Any = None, **_: Any
    ) -> ProjectPage:
        records = [_record(project_id, *project) for project_id, project in self.projects.items()]
        return ProjectPage(records=records, server_total=len(records), exhausted=True)

    async def get(self, project_ref: str) -> ProjectRecord:
        return _record(int(project_ref), *self.projects[int(project_ref)])


def _record(project_id: int, identifier: str, name: str) -> ProjectRecord:
    summary = ProjectSummary(id=project_id, name=name, identifier=identifier, active=True, description=None)
    return project_record(summary)


def _no_detail() -> ProjectDetail:
    raise AssertionError("the directory never reads a project's detail")


class _GatedServer(_Inner):
    """`project` answers with the project as it was when the request was
    sent and holds that answer until the test releases it; `work_package`
    answers at once with a work package linking project 42."""

    def __init__(self, projects: _GatedProjects) -> None:
        super().__init__()
        self.projects = projects
        self.project_sent = asyncio.Event()
        self.release_project = asyncio.Event()

    async def get_json(self, path: str, **_: Any) -> dict[str, Any]:
        if path == "projects/42":
            identifier, name = self.projects.projects[42]
            self.project_sent.set()
            await self.release_project.wait()
            return {
                "_type": "Project",
                "id": 42,
                "identifier": identifier,
                "name": name,
                "_links": {"self": {"href": "/api/v3/projects/42", "title": name}},
            }
        return {"_type": "WorkPackage", "id": 7, "_links": {"project": _LINK_42}}


_LINK_42 = {"href": "/api/v3/projects/42", "title": "Fid Project"}


@pytest.mark.asyncio
async def test_a_project_shown_by_a_late_response_does_not_undo_a_rename_read_since() -> None:
    settings = _base_settings(read_projects=("FIDOLD",), write_projects=("FIDNEW",))
    projects = _GatedProjects()
    directory = ProjectDirectoryService(api=projects, settings=settings)
    await directory.refresh()
    server = _GatedServer(projects)
    transport = LearningTransport(server, learner=directory)

    late = asyncio.create_task(transport.get_json("projects/42"))
    await server.project_sent.wait()
    projects.projects[42] = ("FIDNEW", "Fid Project")
    linking = await transport.get_json("work_packages/7")
    server.release_project.set()
    await late

    assert directory.positives[42] == "FIDNEW"
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        ensure_project_link_allowed(
            linking["_links"]["project"], settings=settings, project_id_to_identifier=directory.positives
        )


@pytest.mark.asyncio
async def test_a_project_shown_by_a_response_sent_before_a_scan_that_missed_it_stays_gone() -> None:
    settings = _base_settings(read_projects=("FIDOLD",))
    projects = _GatedProjects()
    directory = ProjectDirectoryService(api=projects, settings=settings)
    await directory.refresh()
    server = _GatedServer(projects)
    transport = LearningTransport(server, learner=directory)

    late = asyncio.create_task(transport.get_json("projects/42"))
    await server.project_sent.wait()
    del projects.projects[42]
    await directory.refresh()
    server.release_project.set()
    await late

    assert directory.positives == {}
    assert directory.readable_project_ids() == frozenset()
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        ensure_project_link_allowed(_LINK_42, settings=settings, project_id_to_identifier=directory.positives)
