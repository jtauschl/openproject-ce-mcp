#!/usr/bin/env python3
"""Measure the context/token cost this MCP actually produces, right now.

Backs the numbers in docs/context-efficiency.md (and the short summary table
in README.md's "How it works" section). Three parts:

1. **Tool catalog size** (`tools/list`) — pure code, no live instance needed.
   Builds the app with every write scope enabled (the worst case) and, for
   comparison, with none enabled (read-only), and measures the serialized
   `tools/list` payload both with and without the opt-in metadata tools.

2. **Response-size table** (raw API vs. list/get/search/update/bulk, each with
   and without MCP trimming) — needs a live OpenProject instance with a few
   realistic work packages, since payload size depends on real content
   (description length, populated fields, custom fields) that a synthetic
   fixture can't responsibly claim to represent. Point it at the local
   Docker test harness (``docker/test/up.sh 17``, never production):

    OPENPROJECT_BASE_URL=http://localhost:8175 \\
    OPENPROJECT_API_TOKEN=... \\
    OPENPROJECT_TEST_PROJECT=TST \\
    python tools/measure-context.py

   If those env vars are unset, parts 2 and 3 are skipped with a message —
   part 1 still runs, since it needs no live data.

   Part 2 creates three representative work packages in the target project
   (realistic subjects/descriptions, not empty seed data) for the list/read/
   search/update measurements, plus 5 more for the bulk-create/bulk-update
   measurements. It does not delete any of them afterward — the Docker test
   project is disposable by convention; don't point this at a real instance.

3. **Cost of null-vs-absent distinguishability** (OPM-373 trade-off) — reuses
   the live rows from part 2 (real, uneven None-field population, not an
   invented distribution) to measure the token cost of keeping `None` fields
   explicit instead of eliding them: `elide_none`, derived per-tool from
   whether it accepts `select`, plus `next_offset` always being present, make
   some responses slightly *larger* than pure elision would, in exchange for
   callers being able to tell "unset" apart from "not returned". This is a
   deliberate, measured trade-off, not a regression — see part 2's savings
   numbers for what it sits alongside.

Token counts use tiktoken's `cl100k_base` encoding (the GPT-4-family
tokenizer) as a real-tokenizer stand-in — no public tokenizer for Claude
models exists, so this is a consistent, reproducible approximation, not an
exact Claude token count. Requires the `measure` extra (`uv sync --extra
measure`, or `pip install openproject-ce-mcp[measure]`).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tiktoken  # noqa: E402

from openproject_ce_mcp.client import OpenProjectClient  # noqa: E402
from openproject_ce_mcp.config import Settings  # noqa: E402
from openproject_ce_mcp.models import SortCriterion  # noqa: E402
from openproject_ce_mcp.presentation import _to_payload  # noqa: E402
from openproject_ce_mcp.server import CE_INSTRUCTIONS, create_app  # noqa: E402

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _tokens(raw: str) -> int:
    return len(_ENCODING.encode(raw))


# A substring of CE_INSTRUCTIONS distinctive enough that a false-positive match
# elsewhere is implausible -- used by measure_tools_list's duplication check below.
_CE_INSTRUCTIONS_NEEDLE = "Community Edition (CE)"

WRITE_ENV = {
    "OPENPROJECT_READ_PROJECTS": "*",
    "OPENPROJECT_WRITE_PROJECTS": "*",
    "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
    "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": "true",
    "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
    "OPENPROJECT_ENABLE_VERSION_WRITE": "true",
    "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
    "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
    "OPENPROJECT_ENABLE_PERSONAL_WRITE": "true",
    "OPENPROJECT_ENABLE_ADMIN_READ": "true",
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
        ("every write scope enabled, extended tools off (worst case)", {**BASE_ENV, **WRITE_ENV}),
        (
            "every write scope enabled, extended tools on",
            {
                **BASE_ENV,
                **WRITE_ENV,
                "OPENPROJECT_ENABLE_EXTENDED_READ": "true",
            },
        ),
        ("fresh install (compatible defaults, no project scope granted)", BASE_ENV),
    ]
    for label, env in scenarios:
        settings = Settings.from_env(env)
        app = create_app(settings)
        tools = await app.list_tools()
        payload = [t.model_dump(exclude_none=True, mode="json") for t in tools]
        raw = json.dumps({"tools": payload})
        print(f"{label}: {len(tools)} tools, {len(raw)} bytes, ~{_tokens(raw)} tokens")
    print()

    # Live Codex tool discovery reportedly saw the server-level CE
    # instructions repeated in every tool's own metadata/description. Verify
    # server.instructions is carried exactly once (the spec-standard `initialize`
    # field) and never duplicated into any individual tool's `description` --
    # confirming the duplication, if real, is not introduced by this server or
    # by FastMCP's Tool.description construction (which is built from each
    # function's own docstring, never referencing `instructions`).
    print("=== server instructions vs. per-tool descriptions ===\n")
    settings = Settings.from_env({**BASE_ENV, **WRITE_ENV, "OPENPROJECT_ENABLE_EXTENDED_READ": "true"})
    app = create_app(settings)
    tools = await app.list_tools()
    payload = [t.model_dump(exclude_none=True, mode="json") for t in tools]
    server_instructions = app._mcp_server.instructions  # type: ignore[attr-defined]
    duplicated_into = [t["name"] for t in payload if _CE_INSTRUCTIONS_NEEDLE in (t.get("description") or "")]
    raw = json.dumps({"tools": payload})
    raw_tokens = _tokens(raw)
    hypothetical_tokens = raw_tokens + len(tools) * _tokens(CE_INSTRUCTIONS)
    print(f"server.instructions is CE_INSTRUCTIONS: {server_instructions == CE_INSTRUCTIONS}")
    print(f"tools whose description duplicates it: {duplicated_into or 'none'}")
    print(
        f"tools/list as sent by this server: {len(raw)} bytes, ~{raw_tokens} tokens "
        f"(if a client duplicated instructions into every one of {len(tools)} tool descriptions "
        f"instead, that would be ~{hypothetical_tokens} tokens, {round(hypothetical_tokens / raw_tokens, 1)}x)"
    )
    print()


def _report(label: str, raw_json: str, mcp_json: str) -> None:
    raw_tokens, mcp_tokens = _tokens(raw_json), _tokens(mcp_json)
    pct = round((1 - mcp_tokens / raw_tokens) * 100) if raw_tokens else 0
    print(f"{label}:")
    print(f"  Raw: {len(raw_json)} bytes, ~{raw_tokens} tokens")
    print(f"  MCP: {len(mcp_json)} bytes, ~{mcp_tokens} tokens (-{pct}% vs. raw)\n")


async def measure_response_sizes() -> list | None:
    base_url = os.environ.get("OPENPROJECT_BASE_URL")
    token = os.environ.get("OPENPROJECT_API_TOKEN")
    project = os.environ.get("OPENPROJECT_TEST_PROJECT", "TST")

    print("=== Response sizes (raw API vs. MCP) ===\n")
    if not base_url or not token:
        print(
            "Skipped: set OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN "
            "(docker/test/up.sh 17, never production) to run this part.\n"
        )
        return None

    import httpx

    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": base_url,
            "OPENPROJECT_API_TOKEN": token,
            "OPENPROJECT_READ_PROJECTS": project,
            "OPENPROJECT_WRITE_PROJECTS": project,
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
        }
    )
    client = OpenProjectClient(settings)
    await client.initialize()
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

    raw_json = json.dumps(raw_collection)
    raw_tokens = _tokens(raw_json)

    # Sort by id desc so the work packages just created above are always
    # within the first `limit` rows, regardless of how many other work
    # packages already exist in this (disposable, never-cleaned) test
    # project from earlier runs.
    result = await client.list_work_packages(project=project, limit=50, sort_by=[SortCriterion("id", "desc")])
    rows = [r for r in result.results if r.id in created_ids]
    if len(rows) != len(created_ids):
        print(f"Warning: expected {len(created_ids)} rows, found {len(rows)} — numbers below are partial.\n")

    full_json = json.dumps({"results": [_to_payload(r) for r in rows]})
    full_tokens = _tokens(full_json)
    # Use the real _select_fields() path (same as a caller passing `select`
    # would exercise via the registered wrapper) rather than filtering an
    # already-fully-serialized row after the fact -- filtering post-hoc would
    # silently miss any None-valued field among select_fields, since it's
    # already gone from _to_payload(r)'s default (elide_none=True) output
    # before the filter ever runs.
    select_fields = frozenset({"id", "display_id", "subject", "status", "assignee"})
    select_json = json.dumps({"results": [_select_row(r, select_fields) for r in rows]})
    select_tokens = _tokens(select_json)

    print(f"Raw OpenProject REST API v3 (HAL), {len(rows)} rows: {len(raw_json)} bytes, ~{raw_tokens} tokens")
    print(
        f"list_work_packages (MCP), {len(rows)} rows: {len(full_json)} bytes, ~{full_tokens} tokens "
        f"(-{round((1 - full_tokens / raw_tokens) * 100)}% vs. raw)"
    )
    print(
        f"list_work_packages with select (5 fields): {len(select_json)} bytes, ~{select_tokens} tokens "
        f"(-{round((1 - select_tokens / raw_tokens) * 100)}% vs. raw)"
    )
    print(
        f"\nCreated work packages {created_ids} in project '{project}' for this measurement; "
        "left in place (disposable test project)."
    )
    print()

    async with httpx.AsyncClient(base_url=base_url, auth=auth, verify=settings.verify_ssl) as http:
        # --- Single read: get_work_package vs. GET /work_packages/{id} ---
        single_id = created_ids[0]
        resp = await http.get(f"/api/v3/work_packages/{single_id}")
        resp.raise_for_status()
        raw_single_json = json.dumps(resp.json())
        lock_version = resp.json()["lockVersion"]

        detail = await client.get_work_package(single_id)
        _report(
            "get_work_package (single read)",
            raw_single_json,
            json.dumps(_to_payload(detail, elide_none=False)),
        )

        # --- Search: search_work_packages vs. GET /work_packages?filters=subject_or_id ---
        query = SAMPLE_WORK_PACKAGES[0][0].split()[0]  # first word of a known subject, guaranteed to match
        project_href_id = resp.json()["_links"]["project"]["href"].rsplit("/", 1)[-1]
        raw_filters = json.dumps(
            [
                {"subject_or_id": {"operator": "**", "values": [query]}},
                {"project_id": {"operator": "=", "values": [project_href_id]}},
            ]
        )
        resp = await http.get("/api/v3/work_packages", params={"filters": raw_filters})
        resp.raise_for_status()
        raw_search_json = json.dumps(resp.json())

        search_result = await client.search_work_packages(search=query, project=project)
        _report(
            f"search_work_packages ({len(search_result.results)} rows)",
            raw_search_json,
            json.dumps({"results": [_to_payload(r) for r in search_result.results]}),
        )

        # --- Confirmed single update: update_work_package vs. PATCH /work_packages/{id} ---
        resp = await http.patch(
            f"/api/v3/work_packages/{single_id}",
            json={"lockVersion": lock_version, "percentageDone": 40},
        )
        resp.raise_for_status()
        raw_update_json = json.dumps(resp.json())

        update_result = await client.update_work_package(work_package_id=single_id, percentage_done=60, confirm=True)
        _report(
            "update_work_package (confirmed write)",
            raw_update_json,
            # update_work_package has no `select` param, so its real registered
            # wrapper uses elide_none=False -- match that here.
            json.dumps(_to_payload(update_result, elide_none=False)),
        )

        # --- Bulk create ×5: bulk_create_work_packages vs. 5x POST /work_packages ---
        # type "7" matches the numeric type id used for the raw POSTs above and below
        # (same type as SAMPLE_WORK_PACKAGES) — avoids a name/id mismatch between the
        # raw and MCP creation paths.
        bulk_items = [{"project": project, "type": "7", "subject": f"Bulk-created sample {i}"} for i in range(1, 6)]
        raw_bulk_create_parts = []
        for item in bulk_items:
            resp = await http.post(
                f"/api/v3/projects/{project}/work_packages",
                json={"subject": item["subject"], "_links": {"type": {"href": "/api/v3/types/7"}}},
            )
            resp.raise_for_status()
            raw_bulk_create_parts.append(resp.json())

        bulk_create_result = await client.bulk_create_work_packages(items=bulk_items, confirm=True)
        created_ids.extend(
            item.result.result.id
            for item in bulk_create_result.items
            if item.success and item.result and item.result.result
        )
        _report(
            f"bulk_create_work_packages (x{len(bulk_items)}, vs. {len(bulk_items)} individual raw POSTs)",
            json.dumps(raw_bulk_create_parts),
            json.dumps(_to_payload(bulk_create_result)),
        )

        # --- Bulk update ×5: bulk_update_work_packages vs. 5x PATCH /work_packages/{id} ---
        bulk_target_ids = created_ids[-len(bulk_items) :]
        raw_bulk_update_parts = []
        for wp_id in bulk_target_ids:
            resp = await http.get(f"/api/v3/work_packages/{wp_id}")
            resp.raise_for_status()
            wp_lock_version = resp.json()["lockVersion"]
            resp = await http.patch(
                f"/api/v3/work_packages/{wp_id}", json={"lockVersion": wp_lock_version, "percentageDone": 20}
            )
            resp.raise_for_status()
            raw_bulk_update_parts.append(resp.json())

        bulk_update_items = [{"work_package_id": wp_id, "percentage_done": 30} for wp_id in bulk_target_ids]
        bulk_update_result = await client.bulk_update_work_packages(items=bulk_update_items, confirm=True)
        _report(
            f"bulk_update_work_packages (x{len(bulk_target_ids)}, vs. {len(bulk_target_ids)} individual raw PATCHes)",
            json.dumps(raw_bulk_update_parts),
            json.dumps(_to_payload(bulk_update_result)),
        )

    # First page (up to OPENPROJECT_MAX_PAGE_SIZE, 50 by default -- `limit`
    # above is requested but capped server-side) of the project's work
    # packages (seeded + created above), for Part 3 -- a much richer, real
    # None-field distribution than just the handful of rows created earlier
    # in this function. Not the complete project (that would need to page
    # until next_offset is None), but plenty for a representative sample.
    page_result = await client.list_work_packages(project=project, limit=200)

    await client.aclose()
    return list(page_result.results)


# ── Part 3: cost of null-vs-absent distinguishability (OPM-373) ──────────────
#
# elide_none (derived per-tool from whether it accepts `select`) and the
# always-present next_offset are a deliberate trade-off, not a saving: some
# responses get slightly larger so a caller can tell "field is unset" apart
# from "field was never returned". This section measures that cost against
# the first page of real seeded rows fetched by measure_response_sizes (its
# `rows` return value -- NOT the same 3 rows shown in that function's own
# printed table, which only covers the handful of work packages it created;
# see that function's docstring comment for the exact fetch), rather than
# synthetic fixtures with an invented None distribution -- a made-up 50/50
# split would not tell you anything about the actual cost on real data, since
# real field-population patterns are uneven (e.g. `responsible` is unset on
# nearly every seeded work package here, `priority` on very few). Requires
# the same live instance as measure_response_sizes.
#
# Two angles, BOTH counterfactual comparisons against a hypothetical
# always-elide policy that never actually shipped as this diff's behavior
# (not a real before/after of a released version -- see
# docs/context-efficiency.md's framing of these numbers): (a) what
# elide_none=True (maximal elision) would produce vs. elide_none=False (the
# real registered policy for any tool with no `select` parameter, e.g.
# list_statuses -- simulated here on work-package rows since they have a much
# richer None distribution than this instance's 14 fully-populated statuses);
# (b) a `select` that includes a field which is None on some real rows, with
# that field dropped (maximal elision, again hypothetical) vs. kept as
# explicit null (the real, registered `_select_fields` behavior).


def measure_null_distinguishability_cost(rows: list) -> None:
    print("=== Cost of null-vs-absent distinguishability (OPM-373 trade-off) ===\n")
    print(f"Measured on {len(rows)} real seeded work packages (first page, see script docstring).\n")

    # (a) elide_none=True (hypothetical maximal-elision policy) vs. False (the
    # real registered policy for a select-less tool) on the SAME rows, full
    # field set.
    elided_json = json.dumps({"results": [_to_payload(r, elide_none=True) for r in rows]})
    explicit_json = json.dumps({"results": [_to_payload(r, elide_none=False) for r in rows]})
    elided_tokens, explicit_tokens = _tokens(elided_json), _tokens(explicit_json)
    delta_pct = round((explicit_tokens / elided_tokens - 1) * 100) if elided_tokens else 0
    print(f"Full rows, simulating a select-less tool (e.g. list_statuses's Rule 1, {len(rows)} rows):")
    print(f"  Maximal elision (hypothetical, not this tool's real policy): ~{elided_tokens} tokens")
    print(f"  Explicit null (real registered behavior, elide_none=False): ~{explicit_tokens} tokens (+{delta_pct}%)\n")

    # (b) select-capable tool, `select` includes a field that's None on some
    # real rows (responsible is unset on most seeded work packages here).
    select_fields = frozenset({"id", "subject", "responsible"})
    selected = [_select_row(r, select_fields) for r in rows]
    dropped_json = json.dumps({"results": [{k: v for k, v in row.items() if v is not None} for row in selected]})
    kept_json = json.dumps({"results": selected})
    dropped_tokens, kept_tokens = _tokens(dropped_json), _tokens(kept_json)
    delta_pct = round((kept_tokens / dropped_tokens - 1) * 100) if dropped_tokens else 0
    none_count = sum(1 for row in selected if row.get("responsible") is None)
    print(
        f"list_work_packages with select=[id,subject,responsible] ({len(rows)} rows, {none_count} with responsible=None):"
    )
    print(f"  Selected None dropped (hypothetical maximal elision): ~{dropped_tokens} tokens")
    print(f"  Selected None kept as explicit null (real registered behavior): ~{kept_tokens} tokens (+{delta_pct}%)\n")

    print(
        "Both deltas are the accepted cost of a caller being able to tell "
        "'unset' apart from 'not returned' -- see docs/context-efficiency.md "
        "for the accompanying savings this trade-off sits alongside.\n"
    )


def _select_row(row: Any, select_fields: frozenset[str]) -> dict:
    from openproject_ce_mcp.presentation import _select_fields

    # elide_none=True: matches list_work_packages's real registered policy
    # (it has a `select` param, so elide_none is derived as True).
    return _select_fields(row, select_fields, elide_none=True)


async def main() -> None:
    await measure_tools_list()
    rows = await measure_response_sizes()
    if rows is not None:
        measure_null_distinguishability_cost(rows)
    else:
        print("=== Cost of null-vs-absent distinguishability (OPM-373 trade-off) ===\n")
        print("Skipped: needs the same live instance as the response-size table above.\n")


if __name__ == "__main__":
    asyncio.run(main())
