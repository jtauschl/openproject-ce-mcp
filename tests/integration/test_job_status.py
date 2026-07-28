"""Integration coverage decision for the Job Status domain (20th migrated
domain, OPM-311).

get_job_status has neither a create endpoint nor a list endpoint to source a
live id from -- job statuses are ephemeral background-job progress records,
only ever created as a side effect of an async operation like
copy_project's 302-redirect-follow (client.py's copy_project itself isn't
exercised against a live instance either, since it would create real
projects on every test run -- too invasive for the routine integration
suite). Unlike Query Metadata's get-only methods (filter/column/operator/
sort_by ids), job status ids are also not well-known, stable OpenProject
constants -- each one is a fresh numeric id generated per background job.

Per the runbook's explicit guidance for this exact shape ("no practical way
to source a live id at all for that specific method"), this is a deliberate,
documented skip of live coverage for get_job_status rather than a silent
omission. Unit coverage (tests/unit/test_app_httpx_job_status_api.py,
tests/unit/test_app_job_status_service.py) and the pre-existing
tests/unit/test_projects.py::test_job_status_documents_news_and_wiki /
::test_get_project_configuration_and_copy_project (mocked HTTP) exercise
the full normalization, allowlist, and hidden-field-masking behavior
instead.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(
    reason=(
        "get_job_status has no create/list endpoint to source a live id from, and job "
        "status ids are not well-known stable constants (unlike Query Metadata's "
        "filter/column/operator/sort_by ids) -- see module docstring for the deliberate "
        "decision to skip live coverage for this one method."
    )
)
def test_get_job_status_has_no_practical_live_id_source() -> None:
    pass
