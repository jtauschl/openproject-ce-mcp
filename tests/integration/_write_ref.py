"""The reference a live test passes to a work package write.

A confirmed write that names a record by its bare integer id is refused when the record has a semantic display id,
so a test names such a record by that display id and any other record by its integer id.
"""

from __future__ import annotations

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.work_package_reference import has_semantic_display_id


async def write_ref(client: OpenProjectClient, work_package_id: int) -> int | str:
    record = await client.work_package.get(work_package_id)
    return record.display_id if has_semantic_display_id(record.display_id) else work_package_id
