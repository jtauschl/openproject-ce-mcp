"""Five real adapters against the committed snapshot: every read classified at its location.

The acceptance check of the read model. Each row names the representers that compose a body root and those of its
embedded resources; the expected sets are what the snapshot says about each read the adapters make today. A read that
is `missing` is a phantom (none is left in these five adapters); `partial` exists in some pinned versions only; `open` is a link
whose members the source builds by a helper; `opaque` reaches below what the snapshot holds (the members of a
property value). A change of an adapter, of the snapshot or of the model changes this table on purpose.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import adapter_reads
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "openproject_ce_mcp"
SNAPSHOT = json.loads((ROOT / "tools" / "api-check" / "representer_fields.json").read_text())
ADAPTERS = "app/adapters/"

NOTIFICATION = "lib/api/v3/notifications/notification_representer.rb"
COLLECTION = ("lib/api/decorators/collection.rb", "lib/api/decorators/offset_paginated_collection.rb")
VALUES = (
    "lib/api/v3/values/property_representer.rb",
    "lib/api/v3/values/property_date_representer.rb",
    "lib/api/v3/values/property_generic_representer.rb",
)
WORK_PACKAGE = (
    "lib/api/v3/work_packages/work_package_representer.rb",
    "lib/api/v3/attachments/attachable_representer_mixin.rb",
    "lib/api/v3/work_packages/timestamped_representer.rb",
    *sorted(
        path
        for path in SNAPSHOT["paths"]
        if path.endswith("#extend_api_response:lib/api/v3/work_packages/work_package_representer.rb")
    ),
)
ACTIVITY = (
    "lib/api/v3/activities/activity_representer.rb",
    "lib/api/v3/attachments/attachable_representer_mixin.rb",
    "modules/bim/lib/open_project/bim/engine.rb#extend_api_response:lib/api/v3/activities/activity_representer.rb",
)

ROWS = {
    f"{ADAPTERS}httpx_notification_api.py:normalize_notification": adapter_reads.Row((NOTIFICATION,)),
    f"{ADAPTERS}httpx_notification_api.py:normalize_notification_detail": adapter_reads.Row(
        (NOTIFICATION,), {"details": VALUES}
    ),
    f"{ADAPTERS}httpx_notification_api.py:HttpxNotificationApi.list_all": adapter_reads.Row(
        ("lib/api/v3/notifications/notification_collection_representer.rb", *COLLECTION), {"elements": (NOTIFICATION,)}
    ),
    f"{ADAPTERS}httpx_activity_api.py:normalize_activity": adapter_reads.Row(ACTIVITY),
    f"{ADAPTERS}httpx_relation_api.py:normalize_relation": adapter_reads.Row(
        ("lib/api/v3/relations/relation_representer.rb",)
    ),
    f"{ADAPTERS}httpx_work_package_api.py:normalize_work_package_summary": adapter_reads.Row(WORK_PACKAGE),
    f"{ADAPTERS}httpx_work_package_api.py:normalize_work_package_detail": adapter_reads.Row(WORK_PACKAGE),
    f"{ADAPTERS}httpx_work_package_api.py:HttpxWorkPackageApi.list": adapter_reads.Row(
        ("lib/api/v3/work_packages/work_package_collection_representer.rb", *COLLECTION), {"elements": WORK_PACKAGE}
    ),
}
# The functions whose parameter `payload` a row binds to a body; the other rows start at a transport call.
TERMINALS = {fid: ("payload",) for fid in ROWS if ":normalize_" in fid}

# (path, key, status, first pinned version that renders it): the version is the answer, not only "partial".
EXPECTED_NOT_OK: dict[str, set[tuple[tuple[str, ...], str, str, str]]] = {
    "normalize_notification": set(),
    "normalize_notification_detail": set(),
    "HttpxNotificationApi.list_all": set(),
    "normalize_activity": {(("details", "*"), "raw", "opaque", "")},
    "normalize_relation": set(),
    "normalize_work_package_summary": {
        ((), "displayId", "partial", "17.4"),
        ((), "hasProjectAttributes", "partial", "17.7"),
        (("_links",), "observedInVersions", "partial", "17.9"),
        (("_links",), "projectPhase", "partial", "16.1"),
        (("_links",), "sprint", "partial", "17.3"),
        (("_links",), "targetVersions", "partial", "17.7"),
        (("_links", "assignee"), "title", "open", ""),
        (("_links", "observedInVersions", "*"), "href", "open", ""),
        (("_links", "observedInVersions", "*"), "title", "open", ""),
        (("_links", "parent"), "displayId", "partial", "17.5"),
        (("_links", "projectPhase"), "title", "partial", "16.1"),
        (("_links", "responsible"), "title", "open", ""),
        (("_links", "sprint"), "href", "partial", "17.3"),
        (("_links", "sprint"), "title", "partial", "17.3"),
        (("_links", "targetVersions", "*"), "href", "open", ""),
        (("_links", "targetVersions", "*"), "title", "open", ""),
        (("_links", "version"), "title", "open", ""),
    },
    "normalize_work_package_detail": {
        (("_links", "ancestors", "*"), "displayId", "partial", "17.5"),
        (("_links", "children", "*"), "displayId", "partial", "17.5"),
    },
    "HttpxWorkPackageApi.list": {
        (("groups", "*"), "_links", "opaque", ""),
        (("groups", "*"), "count", "opaque", ""),
        (("groups", "*"), "sums", "opaque", ""),
        (("groups", "*"), "value", "opaque", ""),
        (("groups", "*", "_links"), "valueLink", "opaque", ""),
        (("groups", "*", "_links", "valueLink", "*"), "href", "opaque", ""),
    },
}


# Every (path, key) each row reads today, read against the adapter source: a read that disappears or appears fails.
EXPECTED_READS: dict[str, set[tuple[tuple[str, ...], str]]] = {
    "HttpxNotificationApi.list_all": {
        ((), "_embedded"),
        ((), "pageSize"),
        ((), "total"),
        (("_embedded",), "elements"),
        (("_embedded", "elements", "*"), "_links"),
        (("_embedded", "elements", "*", "_links"), "project"),
        (("_embedded", "elements", "*", "_links"), "resource"),
    },
    "HttpxWorkPackageApi.list": {
        ((), "_embedded"),
        ((), "groups"),
        ((), "total"),
        ((), "totalSums"),
        (("_embedded",), "elements"),
        (("groups", "*"), "_links"),
        (("groups", "*"), "count"),
        (("groups", "*"), "sums"),
        (("groups", "*"), "value"),
        (("groups", "*", "_links"), "valueLink"),
        (("groups", "*", "_links", "valueLink", "*"), "href"),
    },
    "normalize_activity": {
        ((), "_type"),
        ((), "comment"),
        ((), "createdAt"),
        ((), "details"),
        ((), "id"),
        ((), "version"),
        (("comment",), "html"),
        (("comment",), "raw"),
        (("details", "*"), "raw"),
    },
    "normalize_notification": {
        ((), "_links"),
        ((), "createdAt"),
        ((), "id"),
        ((), "readIAN"),
        ((), "reason"),
        (("_links",), "project"),
        (("_links",), "resource"),
        (("_links", "project"), "href"),
        (("_links", "project"), "title"),
        (("_links", "resource"), "href"),
        (("_links", "resource"), "title"),
    },
    "normalize_notification_detail": {
        ((), "_embedded"),
        ((), "_links"),
        (("_embedded",), "details"),
        (("_embedded", "details", "*"), "property"),
        (("_embedded", "details", "*"), "value"),
        (("_links",), "activity"),
        (("_links", "activity"), "href"),
    },
    "normalize_relation": {
        ((), "_links"),
        ((), "description"),
        ((), "id"),
        ((), "type"),
        (("_links",), "from"),
        (("_links",), "to"),
        (("_links", "from"), "href"),
        (("_links", "from"), "title"),
        (("_links", "to"), "href"),
        (("_links", "to"), "title"),
    },
    "normalize_work_package_detail": {
        ((), "_links"),
        ((), "date"),
        ((), "description"),
        ((), "dueDate"),
        ((), "lockVersion"),
        ((), "startDate"),
        (("_links",), "ancestors"),
        (("_links",), "children"),
        (("_links", "ancestors", "*"), "displayId"),
        (("_links", "ancestors", "*"), "href"),
        (("_links", "ancestors", "*"), "title"),
        (("_links", "children", "*"), "displayId"),
        (("_links", "children", "*"), "href"),
        (("_links", "children", "*"), "title"),
        (("description",), "html"),
        (("description",), "raw"),
    },
    "normalize_work_package_summary": {
        ((), "_links"),
        ((), "createdAt"),
        ((), "date"),
        ((), "derivedDueDate"),
        ((), "derivedEstimatedTime"),
        ((), "derivedPercentageDone"),
        ((), "derivedRemainingTime"),
        ((), "derivedStartDate"),
        ((), "description"),
        ((), "displayId"),
        ((), "dueDate"),
        ((), "duration"),
        ((), "estimatedTime"),
        ((), "hasProjectAttributes"),
        ((), "id"),
        ((), "ignoreNonWorkingDays"),
        ((), "percentageDone"),
        ((), "remainingTime"),
        ((), "scheduleManually"),
        ((), "spentTime"),
        ((), "startDate"),
        ((), "subject"),
        ((), "updatedAt"),
        (("_links",), "assignee"),
        (("_links",), "author"),
        (("_links",), "category"),
        (("_links",), "observedInVersions"),
        (("_links",), "parent"),
        (("_links",), "priority"),
        (("_links",), "project"),
        (("_links",), "projectPhase"),
        (("_links",), "responsible"),
        (("_links",), "sprint"),
        (("_links",), "status"),
        (("_links",), "targetVersions"),
        (("_links",), "type"),
        (("_links",), "version"),
        (("_links", "assignee"), "title"),
        (("_links", "author"), "title"),
        (("_links", "category"), "title"),
        (("_links", "observedInVersions", "*"), "href"),
        (("_links", "observedInVersions", "*"), "title"),
        (("_links", "parent"), "displayId"),
        (("_links", "parent"), "href"),
        (("_links", "priority"), "title"),
        (("_links", "project"), "title"),
        (("_links", "projectPhase"), "title"),
        (("_links", "responsible"), "title"),
        (("_links", "sprint"), "href"),
        (("_links", "sprint"), "title"),
        (("_links", "status"), "title"),
        (("_links", "targetVersions", "*"), "href"),
        (("_links", "targetVersions", "*"), "title"),
        (("_links", "type"), "title"),
        (("_links", "version"), "href"),
        (("_links", "version"), "title"),
        (("description",), "html"),
        (("description",), "raw"),
    },
}


@pytest.fixture(scope="module")
def analysis() -> adapter_reads.Analysis:
    return adapter_reads.analyse(PACKAGE, terminals=TERMINALS)


@pytest.mark.parametrize("fid", sorted(ROWS))
def test_every_read_of_the_adapter_is_the_one_its_source_makes(fid: str, analysis: adapter_reads.Analysis) -> None:
    assert {(tuple(r.path), r.key) for r in analysis.reads[fid]} == EXPECTED_READS[fid.split(":", 1)[1]]


def first_present(check: adapter_reads.Check) -> str:
    if check.status != "partial":
        return ""
    pins = list(SNAPSHOT["pinned"])
    missing = check.versions.split(",")
    assert missing == pins[: len(missing)], "a partial read is absent in a prefix of the pins and present from then on"
    return pins[len(missing)]


@pytest.mark.parametrize("fid", sorted(ROWS))
def test_every_read_of_the_adapter_is_classified_at_the_right_location(
    fid: str, analysis: adapter_reads.Analysis
) -> None:
    reads = analysis.reads.get(fid, [])
    checks = [adapter_reads.check(read, ROWS[fid], SNAPSHOT) for read in reads]
    not_ok = {(tuple(c.read.path), c.read.key, c.status, first_present(c)) for c in checks if c.status != "ok"}

    assert reads, fid
    assert not_ok == EXPECTED_NOT_OK[fid.split(":", 1)[1]]


def test_the_notification_reads_the_read_ian_key_alone(analysis: adapter_reads.Analysis) -> None:
    fid = f"{ADAPTERS}httpx_notification_api.py:normalize_notification"
    checks = {
        c.read.key: c.status
        for c in (adapter_reads.check(r, ROWS[fid], SNAPSHOT) for r in analysis.reads[fid])
        if not c.read.path
    }

    assert "read" not in checks
    assert checks["readIAN"] == "ok"


def test_what_the_model_cannot_follow_in_these_adapters_is_reported_not_skipped(
    analysis: adapter_reads.Analysis,
) -> None:
    reported = {(f.kind, f.context.split(":", 1)[1], f.reason) for f in analysis.findings}

    assert ("unresolved", "custom_field_raw_entries", ".items() iteration over a body") in reported
    assert ("unresolved", "without_hidden_custom_fields", ".items() iteration over a body") in reported


def test_the_findings_inside_the_five_adapters_are_exactly_these(analysis: adapter_reads.Analysis) -> None:
    """A new finding in a row's own functions fails here; an exemption (WP2b) names each one of these."""
    own = collections.Counter((f.context.split(":", 1)[1], f.kind) for f in analysis.findings if f.context in ROWS)

    assert own == {
        ("HttpxWorkPackageApi.list", "unresolved"): 1,
        ("normalize_activity", "unresolved"): 3,
        ("normalize_work_package_detail", "unresolved"): 4,
        ("normalize_work_package_summary", "unresolved"): 2,
    }
