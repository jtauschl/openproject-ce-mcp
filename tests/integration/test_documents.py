"""Integration tests for document read/update operations.

Documents is PATCH-only in the OpenProject v3 API: no POST create / DELETE
endpoint exists, so unlike news/versions/memberships this file has no
create-then-cleanup fixture. get_document/update_document are exercised
against a pre-existing document in the test project, sourced via
list_documents -- if the test project has none, that test is skipped rather
than failed, since there's no API to seed one.

KNOWN SERVER BUG, WORKED AROUND CLIENT-SIDE (community.openproject.org/wp/
19876, opf/openproject#24769, still open upstream as of this writing):
OpenProject's `PATCH /api/v3/documents/{id}` (modules/documents/lib/api/v3/
documents/documents_api.rb) parses the request body itself (`JSON.parse(
request.body.read)`) and passes `description` straight to
`Documents::UpdateService` unmodified -- when a caller sends description as
the normal HAL `{format, raw, html}` shape every other formattable-
property-backed domain uses (via API::Decorators::FormattableProperty's
setter), the server stores the entire hash, stringified, instead of
extracting `.raw` first. Confirmed via raw curl (no client involved) on a
live 17.8.0 instance, confirmed this is not an encoding issue
(Document#description= and JSON.parse both always yield UTF-8 strings on
their own; a pure-ASCII payload additionally 500s via Commonmarker only as
a downstream consequence of the corrupted hash-shaped string, not a
genuine encoding bug), and confirmed identical against Puma directly
(bypassing the bundled Apache).

This client works around the bug by sending description as a plain string
instead of the HAL shape (see DocumentService.update) -- confirmed
forward-compatible by reading the upstream fix's own diff, which only
transforms description when it arrives as a Hash, leaving a plain string
unchanged either way. test_update_document_description_round_trips below
therefore asserts a real, working round-trip, not documented-broken
behavior.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_documents(client: OpenProjectClient, test_project: str) -> None:
    result = await client.document.list(project=test_project)
    assert result is not None
    # docker/test/seed.rb always seeds two documents (no create_document API
    # exists to seed one through a test-time call instead).
    assert result.count > 0
    assert result.results[0].title


async def test_get_and_update_document(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.document.list(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id

    document = await client.document.get(document_id)
    assert document.id == document_id

    # See module docstring: this MCP server sends a well-formed request
    # (title-only, no description) here specifically to avoid triggering
    # the known upstream description-corruption bug -- this still proves
    # update_document's title path works end to end.
    new_title = f"{document.title} (updated)"
    try:
        update_result = await client.document.update(
            document_id=document_id,
            title=new_title,
            confirm=True,
        )
    except PermissionDeniedError:
        # OpenProject 16.6 gates PATCH /documents/{id} entirely behind the
        # "Block note editor" experimental feature flag, off by default
        # (on by default from 17.x onward, where the gate was removed) --
        # confirmed by reproducing with a bare curl PATCH (no client
        # involved) and toggling Setting.feature_block_note_editor_active.
        pytest.skip(
            "update_document is gated behind the 'Block note editor' feature flag on this "
            "OpenProject version, and it's off by default -- not a client-side permission gap"
        )
    except NotFoundError:
        # No PATCH route at all before 16.6 (verified against source: no
        # `patch do` block in documents_api.rb until then).
        pytest.skip("update_document has no PATCH route on this OpenProject version (added in 16.6)")
    assert update_result.ready, update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.title == new_title


async def test_update_document_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str
) -> None:
    existing = await client.document.list(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to attempt a denied update against")

    document_id = existing.results[0].id
    with pytest.raises(PermissionDeniedError):
        await denied_client.document.update(document_id=document_id, title="denied update", confirm=True)


async def test_update_document_description_round_trips(client: OpenProjectClient, test_project: str) -> None:
    """Documents this MCP server's own workaround for the known upstream
    description-corruption bug: it sends description as a plain string
    (not the HAL {format, raw, html} shape) specifically to route around
    OpenProject's PATCH /documents/{id} bug (see module docstring). Asserts
    both the update response and a freshly fetched read afterward, not just
    the PATCH echo -- a corrupted write could still echo a plausible-looking
    value back without actually persisting correctly, so a separate GET is
    the real proof."""
    existing = await client.document.list(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id
    new_description = "A plain, unmangled description"

    try:
        update_result = await client.document.update(
            document_id=document_id,
            description=new_description,
            confirm=True,
        )
    except PermissionDeniedError:
        # See test_get_and_update_document's identical guard: OpenProject
        # 16.6 gates PATCH /documents/{id} behind the "Block note editor"
        # feature flag, off by default.
        pytest.skip(
            "update_document is gated behind the 'Block note editor' feature flag on this "
            "OpenProject version, and it's off by default -- not a client-side permission gap"
        )
    except NotFoundError:
        # No PATCH route at all before 16.6 -- see test_get_and_update_document.
        pytest.skip("update_document has no PATCH route on this OpenProject version (added in 16.6)")
    assert update_result.ready, update_result.validation_errors
    assert update_result.result is not None
    # This server wraps free text in <user-content> delimiters as its own
    # prompt-injection boundary marker -- expected, not a sign of corruption.
    expected = f"<user-content>{new_description}</user-content>"
    assert update_result.result.description == expected

    refetched = await client.document.get(document_id)
    assert refetched.description == expected


async def test_list_documents_paginates_beyond_a_single_page(client: OpenProjectClient, test_project: str) -> None:
    """Regression: list_documents never sent offset/pageSize to OpenProject
    at all, so a limit smaller than the total available documents silently
    returned everything the server happened to include in that first page
    rather than genuinely paginating. Relies on docker/test/seed.rb's two
    pre-seeded documents (no create_document API exists to seed more here)."""
    unfiltered = await client.document.list(project=test_project, limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough documents in the test project to prove pagination (seed.rb should provide 2)")

    first_page = await client.document.list(project=test_project, limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.document.list(project=test_project, limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
