"""Integration tests for Backlogs backlog bucket reads.

Backlog Buckets has no create/update/delete endpoint in the OpenProject v3
API (list x2 + single-item GET only, global-only for the single-item route)
-- confirmed by source (op-sources/17.7/modules/backlogs/lib/api/v3/
backlog_buckets/{backlog_buckets_api,backlog_buckets_by_project_api}.rb):
both route files mount only Index (and Show, global-only) endpoints, no
Create/Update/Delete anywhere in the directory.

Requires OpenProject 17.6+: the `backlog_buckets` API directory does not
exist in 16.6/17.4/17.5 (verified against op-sources). get_backlog_bucket is
exercised against a pre-existing bucket sourced via list_backlog_buckets --
if the test project/instance has none (or the endpoint 404s on an
older/Backlogs-disabled instance), the tests skip rather than fail, since
there is no API to seed a backlog bucket.

NOTE on `update_work_package`: unlike Sprints (whose `sprint` field on
`update_work_package` landed separately, after the read-only
Sprints domain landed first), OpenProject 17.6 *does* expose
`backlogBucket` as a writable work-package HAL link (confirmed against
op-sources/full-17.6's `work_package_representer.rb`/
`work_package_schema_representer.rb`, plus an XOR-with-`sprint_id` DB
constraint) -- but wiring a `backlog_bucket` field onto `update_work_package`
is out of scope for this read-only pass, mirroring the
Sprints precedent exactly. No work-package
cross-reference test exists here for that reason -- it is deferred to a
follow-up piece of work, not because the API lacks the
capability.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_backlog_buckets(client: OpenProjectClient) -> None:
    try:
        result = await client.backlog_bucket.list()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled, or OpenProject < 17.6, on this instance")
    assert result is not None
    assert result.count >= 0


async def test_list_project_backlog_buckets(client: OpenProjectClient, test_project: str) -> None:
    try:
        result = await client.backlog_bucket.list_for_project(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled, or OpenProject < 17.6, on this instance")
    assert result is not None
    assert result.count >= 0


async def test_get_backlog_bucket(client: OpenProjectClient) -> None:
    try:
        existing = await client.backlog_bucket.list()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled, or OpenProject < 17.6, on this instance")
    if existing.count == 0:
        pytest.skip("no existing backlog bucket on this instance to read (no create API to seed one)")

    backlog_bucket_id = existing.results[0].id

    bucket = await client.backlog_bucket.get(backlog_bucket_id)
    assert bucket.id == backlog_bucket_id
