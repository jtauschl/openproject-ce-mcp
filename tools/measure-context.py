#!/usr/bin/env python3
"""Measure the context/token cost this MCP actually produces, right now.

Backs the numbers in README.md's "Context efficiency" section. Two parts:

1. **Tool catalog size** (`tools/list`) — pure code, no live instance needed.
   Builds the app with every write scope enabled (the worst case) and, for
   comparison, with none enabled (read-only), and measures the serialized
   `tools/list` payload both with and without the opt-in metadata tools.

2. **Response-size table** (raw API vs. `list_work_packages` vs. `select`) —
   needs a live OpenProject instance with a few realistic work packages, since
   payload size depends on real content (description length, populated
   fields, custom fields) that a synthetic fixture can't responsibly claim to
   represent. Point it at the local Docker test harness
   (``docker/test/up.sh 17``, never production):

    OPENPROJECT_BASE_URL=http://localhost:8175 \\
    OPENPROJECT_API_TOKEN=... \\
    OPENPROJECT_TEST_PROJECT=TST \\
    python tools/measure-context.py

   If those env vars are unset, part 2 is skipped with a message — part 1
   still runs, since it needs no live data.

   Part 2 creates three representative work packages in the target project
   (realistic subjects/descriptions, not empty seed data) to measure against.
   It does not delete them afterward — the Docker test project is disposable
   by convention; don't point this at a real instance.

Token counts throughout are the same bytes/4 approximation used elsewhere in
this project's docs — a rough but consistent proxy, not an exact tokenizer
count.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openproject_ce_mcp.client import OpenProjectClient  # noqa: E402
from openproject_ce_mcp.config import Settings  # noqa: E402
from openproject_ce_mcp.server import create_app  # noqa: E402
from openproject_ce_mcp.tools import _to_payload  # noqa: E402

WRITE_ENV = {
    "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
    "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "true",
    "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
    "OPENPROJECT_ENABLE_VERSION_WRITE": "true",
    "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
    "OPENPROJECT_ENABLE_ADMIN_WRITE": "true",
}
BASE_ENV = {
    "OPENPROJECT_BASE_URL": "https://op.example.com",
    "OPENPROJECT_API_TOKEN": "token",
}

SAMPLE_WORK_PACKAGES = [
    (
        "Attachment upload fails with 500 when metadata part includes a filename",
        "When uploading an attachment, the request occasionally returns a 500 error. "
        "The multipart 'metadata' part was sent with a filename, so the server parses "
        "it as an uploaded file instead of a JSON field.\n\nSteps to reproduce:\n"
        "1. Call create_work_package_attachment with a small text file.\n"
        "2. Observe the 500 response and the conversion error in the server log.\n\n"
        "Expected: the attachment uploads and metadata parses as JSON.",
    ),
    (
        "list_projects returns zero results when allowed projects fall outside the first page",
        "On instances with more than one page of projects, list_projects can return an "
        "empty result even though the caller's allowed project is genuinely visible, "
        "because the allowlist filter was applied per-page instead of walking further "
        "pages until enough matches are found or the server is exhausted.\n\n"
        "Acceptance criteria: a project matching the allowlist is always returned "
        "regardless of which server page it lives on.",
    ),
    (
        "Add Backlogs sprint read tools and hide-field support",
        "Instances with the Backlogs module enabled expose sprints via a separate "
        "module engine not covered by the main work-package API surface. Adds read "
        "tools for sprints, plus hide-field support so operators can control which "
        "sprint fields are exposed, consistent with every other entity.",
    ),
]


async def measure_tools_list() -> None:
    print("=== Tool catalog (tools/list) ===\n")
    scenarios = [
        ("write-enabled, metadata tools off (default)", {**BASE_ENV, **WRITE_ENV}),
        ("write-enabled, metadata tools on", {**BASE_ENV, **WRITE_ENV, "OPENPROJECT_ENABLE_METADATA_TOOLS": "true"}),
        ("read-only (no write scopes)", BASE_ENV),
    ]
    for label, env in scenarios:
        settings = Settings.from_env(env)
        app = create_app(settings)
        tools = await app.list_tools()
        payload = [t.model_dump(exclude_none=True, mode="json") for t in tools]
        raw = json.dumps({"tools": payload})
        print(f"{label}: {len(tools)} tools, {len(raw)} bytes, ~{len(raw) // 4} tokens")
    print()


async def measure_response_sizes() -> None:
    base_url = os.environ.get("OPENPROJECT_BASE_URL")
    token = os.environ.get("OPENPROJECT_API_TOKEN")
    project = os.environ.get("OPENPROJECT_TEST_PROJECT", "TST")

    print("=== Response sizes (raw API vs. MCP) ===\n")
    if not base_url or not token:
        print(
            "Skipped: set OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN "
            "(docker/test/up.sh 17, never production) to run this part.\n"
        )
        return

    import httpx

    settings = Settings.from_env({"OPENPROJECT_BASE_URL": base_url, "OPENPROJECT_API_TOKEN": token})
    client = OpenProjectClient(settings)
    auth = httpx.BasicAuth("apikey", token)

    created_ids = []
    async with httpx.AsyncClient(base_url=base_url, auth=auth, verify=settings.verify_ssl) as http:
        for subject, description in SAMPLE_WORK_PACKAGES:
            resp = await http.post(
                f"/api/v3/projects/{project}/work_packages",
                json={
                    "subject": subject,
                    "description": {"format": "markdown", "raw": description},
                    "_links": {"type": {"href": "/api/v3/types/7"}},
                },
            )
            resp.raise_for_status()
            created_ids.append(resp.json()["id"])

        id_filter = json.dumps([{"id": {"operator": "=", "values": [str(i) for i in created_ids]}}])
        resp = await http.get(f"/api/v3/projects/{project}/work_packages", params={"filters": id_filter})
        resp.raise_for_status()
        raw_collection = resp.json()

    raw_bytes = len(json.dumps(raw_collection))

    result = await client.list_work_packages(project=project, limit=50)
    rows = [r for r in result.results if r.id in created_ids]
    if len(rows) != len(created_ids):
        print(f"Warning: expected {len(created_ids)} rows, found {len(rows)} — numbers below are partial.\n")

    full_bytes = len(json.dumps({"results": [_to_payload(r) for r in rows]}))
    select_fields = ["id", "display_id", "subject", "status", "assignee"]
    select_bytes = len(
        json.dumps({"results": [{k: v for k, v in _to_payload(r).items() if k in select_fields} for r in rows]})
    )

    print(f"Raw OpenProject REST API v3 (HAL), {len(rows)} rows: {raw_bytes} bytes, ~{raw_bytes // 4} tokens")
    print(
        f"list_work_packages (MCP), {len(rows)} rows: {full_bytes} bytes, ~{full_bytes // 4} tokens "
        f"(-{round((1 - full_bytes / raw_bytes) * 100)}% vs. raw)"
    )
    print(
        f"list_work_packages with select (5 fields): {select_bytes} bytes, ~{select_bytes // 4} tokens "
        f"(-{round((1 - select_bytes / raw_bytes) * 100)}% vs. raw)"
    )
    print(
        f"\nCreated work packages {created_ids} in project '{project}' for this measurement; "
        "left in place (disposable test project)."
    )

    await client.aclose()


async def main() -> None:
    await measure_tools_list()
    await measure_response_sizes()


if __name__ == "__main__":
    asyncio.run(main())
