"""Integration tests for the Extended Metadata domain (19th migrated domain):
render_text, Help Texts, Working Days, Non-Working Days, Custom Options.

render_text and list_working_days were previously covered in test_meta.py
(pre-migration) -- kept there too (that file also covers unrelated
still-flat endpoints like get_current_user), duplicated here to give this
migration's own domain a complete, self-contained test file per the
project's usual per-domain integration test convention.

get_custom_option has no list/collection endpoint in the OpenProject v3 API
to source a live id from -- unlike Query Metadata's get-only methods (which
use well-known, stable constant ids like "assignee"/"subject"), a custom
option's id is instance-specific and depends on which custom fields exist.
No stable, universally-present custom option id could be identified, so this
migration's live coverage for get_custom_option is explicitly skipped rather
than silently omitted (matching the runbook's carve-out for a domain with
neither a create nor a list endpoint).
"""

from __future__ import annotations

import json

import pytest

from openproject_ce_mcp.client import OpenProjectClient, OpenProjectError

pytestmark = pytest.mark.integration


async def test_render_text(client: OpenProjectClient) -> None:
    try:
        result = await client.render_text(text="**hello**", format="markdown")
    except (OpenProjectError, json.JSONDecodeError):
        pytest.skip("render_text endpoint not available on this instance")
    assert result.html
    assert "hello" in result.html


async def test_list_help_texts(client: OpenProjectClient) -> None:
    result = await client.list_help_texts()
    assert result.count >= 0


async def test_get_help_text(client: OpenProjectClient) -> None:
    listed = await client.list_help_texts()
    if listed.count == 0:
        pytest.skip("no help texts available on this instance")

    help_text_id = listed.results[0].id
    help_text = await client.get_help_text(help_text_id)

    assert help_text.id == help_text_id


async def test_list_working_days(client: OpenProjectClient) -> None:
    result = await client.list_working_days()
    assert result.count > 0


async def test_list_non_working_days(client: OpenProjectClient) -> None:
    result = await client.list_non_working_days()
    assert result.count >= 0


@pytest.mark.skip(reason="custom option ids are instance-specific; no stable, discoverable id exists to test against")
async def test_get_custom_option(client: OpenProjectClient) -> None: ...
