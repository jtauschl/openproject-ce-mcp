"""A create under a parent commits what the form computes without the parent, plus the parent link.

The server copies the span of an automatically scheduled parent into a new child unless the request names the
dates; an explicit `null` wins. Measured on op.nutrilytics.de, OpenProject 16.0 and 17.9: the same copy happens
at commit for a body that carries only the caller's values, so the commit body must hold the null dates itself.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Any

import pytest
from _client_test_helpers import make_settings
from test_app_work_package_service import _FakeWorkPackageApi, _payload, _record, _service

from openproject_ce_mcp.app.errors import NotFoundError, TransportError
from openproject_ce_mcp.app.services.work_package_service import _with_requested_version_links

_SPAN = {"startDate": "2026-11-10", "dueDate": "2026-11-12", "duration": "P3D"}
_DATE_KEYS = ("startDate", "dueDate", "duration")
_VERSION_LINK = {"href": "/api/v3/versions/4"}
_PARENT_LINK = {"href": "/api/v3/work_packages/6"}


class _ParentDerivingApi(_FakeWorkPackageApi):
    """The create logic of a server, as measured: the form payload lists every attribute; a date attribute the
    request leaves out takes the parent's value, an explicit value (null included) wins; the commit runs the
    same logic on its body, so `stored` is what a real `POST` would persist."""

    def __init__(
        self,
        *,
        spans: dict[int, dict[str, Any]] | None = None,
        multi_version: bool = False,
        echo_target_versions: bool = False,
        static_defaults: dict[str, Any] | None = None,
        static_links: dict[str, Any] | None = None,
        echo_ignores_explicit_nulls: bool = False,
        fail_on_form_call: int | None = None,
        failure: Exception | None = None,
    ) -> None:
        super().__init__()
        self.spans = spans if spans is not None else {6: dict(_SPAN)}
        self.multi_version = multi_version
        self.echo_target_versions = echo_target_versions
        self.static_defaults = static_defaults or {}
        self.static_links = static_links or {}
        self.echo_ignores_explicit_nulls = echo_ignores_explicit_nulls
        self.fail_on_form_call = fail_on_form_call
        self.failure = failure or TransportError("OpenProject did not answer.")
        self.stored: list[dict[str, Any]] = []
        if multi_version:
            self.next_schema = {"targetVersions": {"writable": True}}

    def _server_payload(
        self, request: dict[str, Any], *, honour_nulls: bool = True, echo: bool = False
    ) -> dict[str, Any]:
        links = {**self.static_links, **request.get("_links", {})}
        body: dict[str, Any] = {key: value for key, value in request.items() if key != "_links"}
        for key, value in self.static_defaults.items():
            body.setdefault(key, value)
        parent_href = (links.get("parent") or {}).get("href")
        span = self.spans.get(int(parent_href.rsplit("/", 1)[1])) if parent_href else None
        for key in _DATE_KEYS:
            if key not in body or (not honour_nulls and body[key] is None):
                body[key] = span[key] if span else None
        if body.get("startDate") and body.get("duration") and body.get("dueDate") is None and not span:
            days = int(body["duration"].removeprefix("P").removesuffix("D"))
            body["dueDate"] = (date.fromisoformat(body["startDate"]) + timedelta(days=days - 1)).isoformat()
        if self.multi_version:
            if "version" in links:
                links.pop("version")
        if echo and self.echo_target_versions:
            links["targetVersions"] = []
        return {**body, "_links": links}

    async def validate_create(self, project_id: str, payload: dict) -> dict:
        self.validate_create_calls.append((project_id, payload))
        if self.fail_on_form_call == len(self.validate_create_calls):
            raise self.failure
        echo = self._server_payload(payload, honour_nulls=not self.echo_ignores_explicit_nulls, echo=True)
        return {
            "_embedded": {
                "payload": echo,
                "validationErrors": self._next_validation_errors(),
                "schema": self.next_schema,
            }
        }

    async def commit_create(self, payload: dict, *, text_limit: int | None):
        self.stored.append(self._server_payload(payload))
        return await super().commit_create(payload, text_limit=text_limit)


def _dates(body: dict[str, Any]) -> dict[str, Any]:
    return {key: body.get(key) for key in _DATE_KEYS}


async def _create(api: _ParentDerivingApi, **kwargs: Any):
    service, _ = _service(api)
    arguments: dict[str, Any] = {
        "project": "demo",
        "type": "Task",
        "subject": "Child",
        "parent_work_package_id": 6,
        "confirm": True,
    }
    return await service.create(**{**arguments, **kwargs})


@pytest.mark.asyncio
async def test_a_create_under_a_parent_commits_null_dates_and_keeps_the_parent_link() -> None:
    api = _ParentDerivingApi()

    result = await _create(api)

    assert result.state == "confirmed"
    committed = api.commit_create_calls[0]
    assert _dates(committed) == {"startDate": None, "dueDate": None, "duration": None}
    assert committed["_links"]["parent"] == _PARENT_LINK
    assert _dates(api.stored[0]) == {"startDate": None, "dueDate": None, "duration": None}


@pytest.mark.asyncio
async def test_the_parent_free_form_is_validated_first_and_the_request_with_the_parent_second() -> None:
    api = _ParentDerivingApi()

    await _create(api)

    assert len(api.validate_create_calls) == 2
    assert "parent" not in api.validate_create_calls[0][1]["_links"]
    assert api.validate_create_calls[1][1]["_links"]["parent"] == _PARENT_LINK
    assert api.commit_create_calls[0] == api.validate_create_calls[1][1]


@pytest.mark.asyncio
async def test_the_preview_shows_the_validated_answer_and_commits_nothing() -> None:
    api = _ParentDerivingApi()

    result = await _create(api, confirm=False)

    assert result.state == "preview"
    assert api.commit_create_calls == []
    assert _dates(result.payload) == {"startDate": None, "dueDate": None, "duration": None}


@pytest.mark.asyncio
async def test_a_named_start_date_stays_and_the_dates_the_parent_would_add_do_not() -> None:
    api = _ParentDerivingApi()

    await _create(api, start_date="2026-12-01")

    assert _dates(api.commit_create_calls[0]) == {"startDate": "2026-12-01", "dueDate": None, "duration": None}


@pytest.mark.asyncio
async def test_a_due_date_derived_from_the_callers_own_values_is_kept() -> None:
    api = _ParentDerivingApi()

    await _create(api, start_date="2026-12-01", duration="P3D")

    assert _dates(api.commit_create_calls[0]) == {
        "startDate": "2026-12-01",
        "dueDate": "2026-12-03",
        "duration": "P3D",
    }


@pytest.mark.asyncio
async def test_both_dates_named_are_the_callers() -> None:
    api = _ParentDerivingApi()

    await _create(api, start_date="2026-12-01", due_date="2026-12-05")

    assert _dates(api.commit_create_calls[0]) == {"startDate": "2026-12-01", "dueDate": "2026-12-05", "duration": None}


@pytest.mark.asyncio
async def test_a_parent_that_derives_nothing_still_takes_two_calls_and_the_baseline_plus_the_link() -> None:
    api = _ParentDerivingApi(spans={})

    await _create(api)

    assert len(api.validate_create_calls) == 2
    baseline = api._server_payload(api.validate_create_calls[0][1], echo=True)
    assert api.commit_create_calls[0] == {**baseline, "_links": {**baseline["_links"], "parent": _PARENT_LINK}}


@pytest.mark.asyncio
async def test_a_create_without_a_parent_takes_one_form_call_and_commits_the_form_answer() -> None:
    api = _ParentDerivingApi()

    await _create(api, parent_work_package_id=None)

    assert len(api.validate_create_calls) == 1
    assert api.commit_create_calls[0] == api._server_payload(api.validate_create_calls[0][1], echo=True)


@pytest.mark.asyncio
async def test_the_default_links_of_the_project_and_the_type_stay_in_the_commit_body() -> None:
    defaults = {"status": {"href": "/api/v3/statuses/1"}, "priority": {"href": "/api/v3/priorities/8"}}
    api = _ParentDerivingApi(static_links=defaults)

    await _create(api)

    assert {key: api.commit_create_calls[0]["_links"][key] for key in defaults} == defaults


@pytest.mark.asyncio
async def test_a_default_version_of_the_project_stays_when_no_version_is_named() -> None:
    api = _ParentDerivingApi(static_links={"version": _VERSION_LINK})

    await _create(api)

    assert api.commit_create_calls[0]["_links"]["version"] == _VERSION_LINK


@pytest.mark.asyncio
async def test_a_static_default_of_the_project_stays_in_the_commit_body() -> None:
    api = _ParentDerivingApi(static_defaults={"customField3": "project default"})

    await _create(api)

    assert api.commit_create_calls[0]["customField3"] == "project default"


_VERSION_CASES = [
    pytest.param({"version": "1.0"}, False, id="version-single-model"),
    pytest.param({"version": "1.0"}, True, id="version-multi-model"),
    pytest.param({"target_versions": ["1.0"]}, False, id="target-versions-single-model"),
    pytest.param({"target_versions": ["1.0"]}, True, id="target-versions-multi-model"),
    pytest.param({}, False, id="no-version-single-model"),
    pytest.param({}, True, id="no-version-multi-model"),
]


def _expected_links(arguments: dict[str, Any], multi_version: bool) -> dict[str, Any]:
    if "target_versions" in arguments:
        return {"targetVersions": [_VERSION_LINK]}
    if "version" in arguments:
        return {"targetVersions": [_VERSION_LINK]} if multi_version else {"version": _VERSION_LINK}
    return {"targetVersions": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(("arguments", "multi_version"), _VERSION_CASES)
async def test_the_version_links_of_the_commit_are_the_ones_the_commit_carried_before(
    arguments: dict[str, Any], multi_version: bool
) -> None:
    api = _ParentDerivingApi(multi_version=multi_version, echo_target_versions=True)

    await _create(api, **arguments)

    committed = api.commit_create_calls[0]
    links = {key: committed["_links"][key] for key in ("version", "targetVersions") if key in committed["_links"]}
    assert links == _expected_links(arguments, multi_version)
    final_request_links = api.validate_create_calls[-1][1]["_links"]
    assert {key: final_request_links[key] for key in ("version", "targetVersions") if key in final_request_links} == (
        _expected_links(arguments, multi_version)
    )
    validated_draft = api.validate_create_calls[-2][1]
    assert api.validate_create_calls[-1][1]["_links"]["parent"] == _PARENT_LINK
    assert committed == _with_requested_version_links(api.validate_create_calls[-1][1], validated_draft)
    assert committed == api.validate_create_calls[-1][1]
    assert _dates(committed) == {"startDate": None, "dueDate": None, "duration": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(("arguments", "multi_version"), _VERSION_CASES)
async def test_the_commit_body_equals_the_body_committed_before_except_for_the_dates(
    arguments: dict[str, Any], multi_version: bool
) -> None:
    """The oracle is the previous flow on the same server model: the form answer for the draft with the parent,
    repaired with the version links of the validated draft."""
    api = _ParentDerivingApi(multi_version=multi_version, echo_target_versions=True)

    await _create(api, **arguments)

    draft = api.validate_create_calls[-2][1]
    draft_with_parent = {**draft, "_links": {**draft["_links"], "parent": _PARENT_LINK}}
    before = _with_requested_version_links(api._server_payload(draft_with_parent, echo=True), draft)
    assert {k: v for k, v in api.commit_create_calls[0].items() if k not in _DATE_KEYS} == {
        k: v for k, v in before.items() if k not in _DATE_KEYS
    }


@pytest.mark.asyncio
async def test_a_version_on_a_multi_version_form_takes_three_calls_and_the_last_carries_the_parent() -> None:
    api = _ParentDerivingApi(multi_version=True, echo_target_versions=True)

    await _create(api, version="1.0")

    assert [
        ("parent" in call[1]["_links"], call[1]["_links"].get("targetVersions")) for call in api.validate_create_calls
    ] == [
        (False, None),
        (False, [_VERSION_LINK]),
        (True, [_VERSION_LINK]),
    ]


@pytest.mark.asyncio
async def test_a_form_that_derives_the_parent_dates_again_does_not_change_the_committed_request() -> None:
    api = _ParentDerivingApi(echo_ignores_explicit_nulls=True)

    preview = await _create(api, confirm=False)
    result = await _create(api)

    assert _dates(preview.payload) == _SPAN
    assert result.state == "confirmed"
    assert _dates(api.commit_create_calls[0]) == {"startDate": None, "dueDate": None, "duration": None}
    assert api.commit_create_calls[0] == api.validate_create_calls[-1][1]


@pytest.mark.asyncio
async def test_create_subtask_commits_null_dates_too() -> None:
    api = _ParentDerivingApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/1", project_title="Demo"))
    service, _ = _service(api)

    result = await service.create_subtask(parent_work_package_id=6, type="Task", subject="Child task", confirm=True)

    assert result.state == "confirmed"
    assert len(api.validate_create_calls) == 2
    assert _dates(api.commit_create_calls[0]) == {"startDate": None, "dueDate": None, "duration": None}
    assert api.commit_create_calls[0]["_links"]["parent"] == _PARENT_LINK


@pytest.mark.asyncio
async def test_a_bulk_create_item_under_a_parent_commits_null_dates_and_each_item_has_its_own_baseline() -> None:
    api = _ParentDerivingApi()
    service, _ = _service(api)

    result = await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "One", "parent_work_package_id": 6},
            {"project": "demo", "type": "Task", "subject": "Two", "parent_work_package_id": 6},
        ],
        confirm=True,
    )

    assert result.succeeded == 2
    assert len(api.validate_create_calls) == 4
    assert [_dates(body) for body in api.commit_create_calls] == [
        {"startDate": None, "dueDate": None, "duration": None}
    ] * 2


@pytest.mark.asyncio
async def test_a_hidden_start_date_is_committed_as_null_and_absent_from_the_shown_payload() -> None:
    api = _ParentDerivingApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("start_date",)})
    service, _ = _service(api, settings=settings)

    result = await service.create(project="demo", type="Task", subject="Child", parent_work_package_id=6, confirm=True)

    assert api.commit_create_calls[0]["startDate"] is None
    assert "startDate" not in result.payload


@pytest.mark.asyncio
@pytest.mark.parametrize("call_number", [1, 2])
@pytest.mark.parametrize("failure", [TransportError("OpenProject did not answer."), NotFoundError("Not found.")])
async def test_a_form_call_that_fails_raises_and_commits_nothing(call_number: int, failure: Exception) -> None:
    api = _ParentDerivingApi(fail_on_form_call=call_number, failure=failure)

    with pytest.raises(type(failure)):
        await _create(api)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_validation_errors_of_the_parent_free_form_are_ignored() -> None:
    api = _ParentDerivingApi()
    api.validation_errors_queue = [{"subject": "is not valid without the parent."}, {}]

    result = await _create(api)

    assert result.state == "confirmed"
    assert len(api.commit_create_calls) == 1


@pytest.mark.asyncio
async def test_validation_errors_of_the_request_with_the_parent_are_shown_and_nothing_is_committed() -> None:
    api = _ParentDerivingApi()
    api.validation_errors_queue = [{}, {"parent": "is invalid."}]

    result = await _create(api)

    assert result.ready is False
    assert result.validation_errors
    assert api.commit_create_calls == []
