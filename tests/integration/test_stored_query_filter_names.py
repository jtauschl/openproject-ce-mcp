"""The filter names a running server lists are the names the stored query policy knows.

A saved query stores a filter by the API name of its key, and `tools/api-check/query_filter_keys.json` is read from
the server sources. This compares the two on the instance under test: the comparison is not an equality, because the
server leaves a filter out of its schema when its module is off or it is not available in the project, so every name
the instance lists must be in the snapshot (or be a custom field), and the names of the snapshot it does not list are
only counted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openproject_ce_mcp.app.policies.stored_query_policy import NOT_HIDEABLE_FILTERS, STORED_FILTER_OWNERS
from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration

SNAPSHOT = json.loads(
    (Path(__file__).resolve().parents[2] / "tools" / "api-check" / "query_filter_keys.json").read_text()
)


def _is_custom_field(name: str) -> bool:
    return re.fullmatch(r"customField\d+", name) is not None


async def test_every_filter_the_instance_lists_is_in_the_snapshot_and_known_to_the_policy(
    client: OpenProjectClient,
) -> None:
    listed = await client.query_metadata.list_filter_instance_schemas()
    names = {row.id for row in listed.results}

    missing_from_snapshot = {n for n in names if n not in SNAPSHOT["filters"] and not _is_custom_field(n)}
    unknown_to_policy = {
        n for n in names if n not in STORED_FILTER_OWNERS and n not in NOT_HIDEABLE_FILTERS and not _is_custom_field(n)
    }
    assert names
    assert missing_from_snapshot == set(), "a listed filter the extractor does not know"
    assert unknown_to_policy == set(), "a listed filter the policy neither owns nor lists as not hideable"
