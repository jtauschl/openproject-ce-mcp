"""Integration tests for the Extended Metadata domain:
render_text, Help Texts, Working Days, Non-Working Days, Custom Options.

render_text and list_working_days are also covered in test_meta.py, which
covers unrelated still-flat endpoints like get_current_user; duplicated here
to give this domain a complete, self-contained test file per the project's
usual per-domain integration test convention.

get_custom_option has no list/collection endpoint in the OpenProject v3 API
to source a live id from -- unlike Query Metadata's get-only methods (which
use well-known, stable constant ids like "assignee"/"subject"), a custom
option's id is instance-specific and depends on which custom fields exist.
No stable, universally-present custom option id could be identified, so live
coverage for get_custom_option is explicitly skipped rather than silently
omitted.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_render_text(start_scoped_client) -> None:
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=())
    markdown = await everywhere.extended_metadata.render_text(text="**hello**", format="markdown")
    assert "<strong>hello</strong>" in markdown.html
    plain = await everywhere.extended_metadata.render_text(text="hello", format="plain")
    assert plain.html.startswith("<p") and "hello" in plain.html


async def test_render_text_names_a_work_package_by_macro_only_where_it_is_allowed(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], start_scoped_client
) -> None:
    created = await client.work_package.create(
        project=test_project, type="Task", subject="[integration-test] render macro", confirm=True
    )
    assert created.ready, created.validation_errors
    wp_ids.append(created.work_package_id)
    macro = f"see #{created.work_package_id}"

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.extended_metadata.render_text(text=macro, format="plain")

    everywhere = await start_scoped_client(read_projects=("*",), write_projects=())
    rendered = await everywhere.extended_metadata.render_text(text=macro, format="plain")
    assert "/work_packages/" in rendered.html


async def test_list_help_texts(client: OpenProjectClient) -> None:
    result = await client.extended_metadata.list_help_texts()
    # Help texts are opt-in, per-attribute annotations -- a fresh instance
    # can genuinely have none configured, so this can't assert non-empty.
    if result.count == 0:
        pytest.skip("no help texts configured on this instance")
    assert result.results[0].attribute_name


async def test_list_working_days(client: OpenProjectClient) -> None:
    result = await client.extended_metadata.list_working_days()
    assert result.count > 0


async def test_list_non_working_days(client: OpenProjectClient) -> None:
    result = await client.extended_metadata.list_non_working_days()
    # A default OpenProject instance may genuinely have zero configured
    # non-working days (holidays are opt-in, instance-specific config).
    if result.count == 0:
        pytest.skip("no non-working days configured on this instance")
    assert result.results[0].date


@pytest.mark.skip(reason="custom option ids are instance-specific; no stable, discoverable id exists to test against")
async def test_get_custom_option(client: OpenProjectClient) -> None: ...
