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
API::Decorators::FormattableProperty's setter). Every update_document call
therefore corrupts the stored description into a literal Ruby-hash-shaped
string, independent of the client, encoding, or web server in front of it.
test_get_and_update_document below therefore cannot assert a clean
round-trip until this is fixed upstream -- it documents the actual
(broken) behavior instead of asserting an untrue contract.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_documents(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_documents(project=test_project)
    assert result is not None
    # docker/test/seed.rb always seeds two documents (no create_document API
    # exists to seed one through a test-time call instead).
    assert result.count > 0
    assert result.results[0].title


async def test_get_and_update_document(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.list_documents(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id

    document = await client.get_document(document_id)
    assert document.id == document_id

    # See module docstring: this MCP server sends a well-formed request
    # (title-only, no description) here specifically to avoid triggering
    # the known upstream description-corruption bug -- this still proves
    # update_document's title path works end to end.
    new_title = f"{document.title} (updated)"
    update_result = await client.update_document(
        document_id=document_id,
        title=new_title,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
    assert update_result.result is not None
    assert update_result.result.title == new_title


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
    existing = await client.list_documents(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id
    new_description = "A plain, unmangled description"

    update_result = await client.update_document(
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
    unfiltered = await client.list_documents(project=test_project, limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough documents in the test project to prove pagination (seed.rb should provide 2)")

    first_page = await client.list_documents(project=test_project, limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.list_documents(project=test_project, limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
