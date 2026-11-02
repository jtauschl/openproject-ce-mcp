"""Shared fixtures of the tests that pin the `target` a work package write names.

Sibling tests import from this module as `from _work_package_target_helpers import ...`, like the other
`_*_test_helpers` modules. The bare number `436` and the display reference `PROJ-436` resolve to two different
work packages, so a result that only echoed the reference could not tell them apart.
"""

from __future__ import annotations

import json

import httpx

from openproject_ce_mcp.app.ports.work_package_ref import ResolvedRecord


def work_package_record(wp_id: int, display_id: str, subject: str, status: str, project_id: int, project: str) -> dict:
    return {
        "id": wp_id,
        "displayId": display_id,
        "subject": subject,
        "lockVersion": 3,
        "_links": {
            "self": {"href": f"/api/v3/work_packages/{wp_id}"},
            "project": {"href": f"/api/v3/projects/{project_id}", "title": project},
            "status": {"href": "/api/v3/statuses/1", "title": status},
            "type": {"href": "/api/v3/types/8", "title": "Task"},
        },
    }


R1 = work_package_record(436, "A-1", "Subject of the bare number", "New", 1, "Project A")
R2 = work_package_record(9001, "PROJ-436", "Subject of the display reference", "In progress", 2, "Project B")
RECORDS_BY_REFERENCE = {"436": R1, "PROJ-436": R2}

EXPECTED_R1 = {
    "id": 436,
    "display_id": "A-1",
    "project": "Project A",
    "subject": "Subject of the bare number",
    "status": "New",
}
EXPECTED_R2 = {
    "id": 9001,
    "display_id": "PROJ-436",
    "project": "Project B",
    "subject": "Subject of the display reference",
    "status": "In progress",
}
REFERENCES = [("436", EXPECTED_R1), ("PROJ-436", EXPECTED_R2)]


def expectation_for(reference: str) -> str | None:
    """A bare number on a record with a display id needs the ticket named: here the one the number resolves to."""
    return EXPECTED_R1["display_id"] if reference == "436" else None


def form_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
    )


def project_response(request: httpx.Request, project_id: int, identifier: str, name: str) -> httpx.Response:
    body = {"_type": "Project", "id": project_id, "name": name, "identifier": identifier, "_links": {}}
    return httpx.Response(200, json=body, request=request)


def resolved_record(wp_id: int) -> ResolvedRecord:
    """What a work package resolver hands a service for `wp_id`, for service tests with a fake resolver."""
    payload = {"id": wp_id, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}}
    return ResolvedRecord(id=wp_id, payload=payload)
