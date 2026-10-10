from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import policy_observation
from openproject_ce_mcp.app.errors import ProjectScopeDeniedError
from openproject_ce_mcp.app.policies.backlog_bucket_policy import ensure_backlog_bucket_workspace_allowed


def test_embedded_payload_branch_permits_when_scope_allows_all() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    ensure_backlog_bucket_workspace_allowed(
        defining_workspace_payload={"id": 6, "identifier": "demo", "_links": {"self": {"href": "/api/v3/projects/6"}}},
        defining_workspace_link=None,
        settings=settings,
        project_id_to_identifier={},
    )


def test_embedded_payload_branch_denies_outside_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload={
                "id": 6,
                "identifier": "demo",
                "_links": {"self": {"href": "/api/v3/projects/6"}},
            },
            defining_workspace_link=None,
            settings=settings,
            project_id_to_identifier={},
        )


def test_link_branch_delegates_to_ensure_project_link_allowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload=None,
            defining_workspace_link={"href": "/api/v3/projects/6", "title": "Demo"},
            settings=settings,
            project_id_to_identifier={},
        )


# ── OPM-2709 regression: policy_observation instrumentation ────────────────
#
# Found during a Codex review of release/0.5.0: the embedded-payload branch
# (payload already resolved, no link to delegate to scope.py's already-
# instrumented ensure_project_link_allowed) raised ProjectScopeDeniedError
# directly without ever recording policy_observation.


def test_embedded_payload_branch_records_denied_decision_and_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    policy_observation.reset()
    with pytest.raises(ProjectScopeDeniedError):
        ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload={
                "id": 6,
                "identifier": "demo",
                "_links": {"self": {"href": "/api/v3/projects/6"}},
            },
            defining_workspace_link=None,
            settings=settings,
            project_id_to_identifier={},
        )
    assert policy_observation.current_policy_decision() == "project_scope_read_denied"
    assert policy_observation.current_project_scope() == "demo"


def test_embedded_payload_branch_records_allowed_decision_and_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    policy_observation.reset()
    ensure_backlog_bucket_workspace_allowed(
        defining_workspace_payload={"id": 6, "identifier": "demo", "_links": {"self": {"href": "/api/v3/projects/6"}}},
        defining_workspace_link=None,
        settings=settings,
        project_id_to_identifier={},
    )
    assert policy_observation.current_policy_decision() == "project_scope_read_allowed"
    assert policy_observation.current_project_scope() == "demo"


@pytest.mark.parametrize(
    ("self_href", "link"),
    [
        ("/api/v3/projects/7", None),
        ("/api/v3/projects/6", {"href": "https://evil.example.com/api/v3/projects/6"}),
    ],
)
def test_embedded_payload_naming_another_project_is_denied_and_recorded(self_href, link) -> None:
    policy_observation.reset()

    with pytest.raises(ProjectScopeDeniedError):
        ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload={"id": 6, "identifier": "demo", "_links": {"self": {"href": self_href}}},
            defining_workspace_link=link,
            settings=dataclasses.replace(make_settings(), read_projects=("*",)),
            project_id_to_identifier={},
        )

    assert policy_observation.current_policy_decision() == "project_scope_read_denied"
    assert policy_observation.current_project_scope() == "demo"
