"""Integration tests for document read/update operations.

Documents is PATCH-only in the OpenProject v3 API: no POST create / DELETE
endpoint exists, so unlike news/versions/memberships this file has no
create-then-cleanup fixture. get_document/update_document are exercised
against a pre-existing document in the test project, sourced via
list_documents -- if the test project has none, that test is skipped rather
than failed, since there's no API to seed one.

KNOWN SERVER BUG (reported upstream, not a client issue): OpenProject's
`PATCH /api/v3/documents/{id}` (modules/documents/lib/api/v3/documents/
documents_api.rb) parses the request body itself (`JSON.parse(request.body
.read)`) and passes the RAW, still-nested `description` hash straight to
`Documents::UpdateService`, instead of extracting `description.raw` first
the way every other formattable-property-backed domain does (via
API::Decorators::FormattableProperty's setter). Every confirmed
update_document call therefore corrupts the stored description into a
literal Ruby-hash-shaped string -- confirmed via raw curl (no client
involved), confirmed this is not an encoding issue (Document#description=
and JSON.parse both always yield UTF-8 strings on their own; a pure-ASCII
payload additionally 500s via Commonmarker only as a downstream
consequence of the corrupted hash-shaped string, not a genuine encoding
bug), and confirmed identical against Puma directly (bypassing the bundled
Apache). test_get_and_update_document below therefore cannot assert a
clean round-trip until this is fixed upstream -- it documents the actual
(broken) behavior instead of asserting an untrue contract.
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


@pytest.mark.xfail(
    reason="Upstream OpenProject bug: PATCH /documents/{id} corrupts description "
    "into a literal hash-shaped string instead of extracting description.raw "
    "(see module docstring). Reported upstream; un-xfail once fixed.",
    strict=True,
)
async def test_update_document_description_round_trips(client: OpenProjectClient, test_project: str) -> None:
    """Documents this MCP server's own client code is correct -- it sends
    the well-formed {"format": ..., "raw": ...} payload OpenProject's API
    documents -- the round-trip failure is entirely server-side."""
    existing = await client.document.list(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id
    new_description = "A plain, unmangled description"

    update_result = await client.document.update(
        document_id=document_id,
        description=new_description,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.description == new_description


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
