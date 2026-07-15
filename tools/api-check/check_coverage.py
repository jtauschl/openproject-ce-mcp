#!/usr/bin/env python3
"""Report how much of the OpenProject Community Edition API v3 this MCP covers.

Combines three sources of truth into one matrix:

1. **Source inventory** — every ``lib/api/v3/<resource>/`` directory in the
   pinned 17.6 clone (the full set of API resources).
2. **Client usage** — resources this MCP actually calls, extracted from the
   request paths and HAL hrefs in ``src/openproject_ce_mcp/client.py``.
3. **Live CE probe** (optional) — ``GET /api/v3/<resource>`` against a running
   Community Edition instance, to see what actually answers (200 / 403 / 404).
   Enabled when ``OPENPROJECT_BASE_URL`` and ``OPENPROJECT_API_TOKEN`` are set.

Why all three: the directory list alone over-counts gaps (many resources are
sub-paths like ``projects/{id}/categories`` or ``work_packages/{id}/watchers``
that the client already covers, yet 404 at the top level), and CE/Enterprise
gating is not cleanly derivable from the source (heterogeneous feature-flag /
EnterpriseToken guards). A curated CLASSIFICATION table reconciles the edge
cases; the live probe is the tie-breaker for "is this in CE at all".

Usage:
    python tools/api-check/check_coverage.py            # matrix to stdout
    python tools/api-check/check_coverage.py --write     # also (re)write COVERAGE.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / ".op-sources"
CLIENT = ROOT / "src" / "openproject_ce_mcp" / "client.py"
COVERAGE_MD = Path(__file__).resolve().parent / "COVERAGE.md"
SOURCE_VERSION = "17.6"  # inventory reference

# Resources the client reaches under a different path segment than the
# source directory name. Without this, check_coverage.py under-reports: the
# client genuinely uses the resource, just addressed via an alias route.
#   "my_preferences"  — the current-user shortcut for the `user_preferences`
#                        resource (get_my_preferences/update_my_preferences).
#   "job_statuses"    — the client's plural request path; the source module
#                        directory is the singular `job_status`.
RESOURCE_ALIASES: dict[str, str] = {
    "user_preferences": "my_preferences",
    "job_status": "job_statuses",
}

# Curated classification of resources that are NOT plain top-level CRUD the
# client should cover. Anything not listed and not client-used and present in
# CE is reported as a genuine gap. Keep this in sync with the live probe.
#   internal    — framework/util endpoints, not user-facing resources
#   subresource — exists only under a parent path; covered via that parent
#   enterprise  — Enterprise-only / feature-flagged; not in plain CE
#   review      — not yet classified; verify via source (beyond the sparse
#                 lib/api/v3 subtree) or a live CE probe before ruling out a
#                 gap. The CE/Enterprise split is not cleanly derivable from
#                 the fetched subtree alone (see the module docstring above).
CLASSIFICATION: dict[str, str] = {
    # internal / framework
    "errors": "internal",
    "formatter": "internal",
    "utilities": "internal",
    "schemas": "internal",
    "values": "internal",
    "string_objects": "internal",
    "render": "internal",
    "help_texts": "internal",
    "configuration": "internal",
    "workspaces": "internal",  # aggregation/utility endpoint, not standalone CRUD
    "providers": "internal",  # representer-only support class, not a mountable API resource
    # sub-resources the client already reaches via a parent path
    "categories": "subresource",  # projects/{id}/categories
    "watchers": "subresource",  # work_packages/{id}/watchers
    "activities": "subresource",  # work_packages/{id}/activities
    "attachments": "subresource",  # <container>/{id}/attachments
    "relations": "subresource",  # work_packages/{id}/relations + /relations
    "shares": "subresource",  # work_packages/{id}/shares etc.
    "custom_fields": "subresource",  # exposed via schemas / project context
    "custom_actions": "subresource",
    "emoji_reactions": "subresource",
    "favorites": "subresource",  # legacy `namespace :favorite` mixin; client uses the newer workspaces/{id}/favorite route instead
    # Confirmed by reading each resource's actual *_api.rb file in the pinned
    # 17.6 clone (not merely a live-probe 404 — see the module docstring's
    # warning that CE/Enterprise and subresource-vs-top-level status aren't
    # reliably inferable from an HTTP status alone across versions): each of
    # these has no bare-collection GET of its own; the only listing action is
    # mounted inside a parent resource's route_param block.
    "user_working_hours": "subresource",  # users/{id}/working_hours (source: user_working_hours/working_hours_by_user_api.rb)
    "user_non_working_times": "subresource",  # users/{id}/non_working_times (source: user_non_working_times/non_working_times_by_user_api.rb)
    "page_links": "subresource",  # wiki_pages/{id}/... (source mounts `wiki_page_links`, a different path segment than this directory name)
    "meeting_agenda_items": "subresource",  # meetings/{id}/agenda_items — meeting_agenda_items_api.rb has no bare collection GET; the list lives in agenda_items_by_meeting_api.rb
    "meeting_outcomes": "subresource",  # meetings/{id}/agenda_items/{id}/outcomes — meeting_outcomes_api.rb has no bare collection GET; the list lives in outcomes_by_agenda_item_api.rb
    "meeting_sections": "subresource",  # meetings/{id}/sections — meeting_sections_api.rb has no bare collection GET; the list lives in sections_by_meeting_api.rb
    "cost_entries": "subresource",  # work_packages/{id}/cost_entries — cost_entries_api.rb (plain) is detail-only (route_param :id, no collection GET); the list lives in cost_entries_by_work_package_api.rb
    "github_pull_requests": "subresource",  # work_packages/{id}/github_pull_requests — github_pull_requests_api.rb (plain) is detail-only; the list lives in github_pull_requests_by_work_package_api.rb
    "gitlab_issues": "subresource",  # work_packages/{id}/gitlab_issues — no plain top-level api file at all, only gitlab_issues_by_work_package_api.rb
    "gitlab_merge_requests": "subresource",  # work_packages/{id}/gitlab_merge_requests — no plain top-level api file at all, only gitlab_merge_requests_by_work_package_api.rb
    "oauth_client": "subresource",  # storages/{storage_id}/... — OAuthClient::OAuthClientCredentialsAPI is mounted inside storages_api.rb's route_param(:storage_id) block (distinct from the root-mounted OAuth::OAuthClientCredentialsAPI under "oauth" below)
    # Admin/config resource: real, CE-available, top-level (root.rb mounts
    # OAuth::OAuthApplicationsAPI and OAuth::OAuthClientCredentialsAPI
    # directly), but registering third-party OAuth applications is an
    # instance-admin concern outside this MCP's project-management scope —
    # not a candidate gap for this client to cover, analogous to "configuration".
    "oauth": "internal",
    # enterprise / feature-flagged (confirmed via live CE probe + source guards)
    "placeholder_users": "enterprise",
    "portfolios": "enterprise",
    "programs": "enterprise",
    "backups": "enterprise",
    "repositories": "enterprise",
    "budgets": "enterprise",  # Enterprise feature; see this project's own documented CE scope
    "storage_files": "enterprise",  # source raises API::Errors::EnterpriseTokenMissing
}

# Confirmed genuine top-level CE gaps — verified by reading each resource's
# actual *_api.rb file in the pinned 17.6 clone (not a live probe against a
# different version; see CLASSIFICATION's subresource entries above for why
# that would be unreliable). Encoded here so `_classify` reports them as
# `GAP (CE)` deterministically, without requiring a live probe on every run —
# the live-probe branch in `_classify` still runs when enabled, as an
# independent cross-check that this set hasn't drifted from a later release.
#   meetings, recurring_meetings, storages, project_storages — genuine
#     `resources :x do get &Index... end` top-level collection GETs.
#   backlog_buckets — same: a real top-level Index + Show in
#     backlog_buckets_api.rb (not the parent-scoped case its directory name
#     might suggest by analogy with the other Backlogs-adjacent resources).
#   posts, cost_types — narrower: no bare-collection GET exists anywhere
#     (checked every referencing file in the pinned tree, not just this
#     resource's own directory), but a top-level detail/show-by-id route does
#     (`route_param :id do get ... end` with no preceding collection `get`).
#     A "list" tool could never be built against either; a "get by id" tool
#     could. Reported as a gap rather than forced into "subresource" (which
#     would incorrectly imply a parent path exists) or "internal" (which
#     would incorrectly imply the endpoint isn't real, user-facing CE data).
CONFIRMED_GAPS: frozenset[str] = frozenset(
    {"meetings", "project_storages", "recurring_meetings", "storages", "backlog_buckets", "posts", "cost_types"}
)


def _source_resources() -> list[str]:
    base = SOURCES / SOURCE_VERSION / "lib" / "api" / "v3"
    if not base.exists():
        return []
    resources = {p.name for p in base.iterdir() if p.is_dir()}
    modules_base = SOURCES / SOURCE_VERSION / "modules"
    if modules_base.exists():
        for module_dir in modules_base.iterdir():
            module_api = module_dir / "lib" / "api" / "v3"
            if module_api.is_dir():
                resources.update(p.name for p in module_api.iterdir() if p.is_dir())
    return sorted(resources)


def _client_resources() -> set[str]:
    """First path segment of every request path / HAL href in the client."""
    text = CLIENT.read_text()
    used: set[str] = set()
    for path in re.findall(r'self\._(?:get|post|patch|delete)\(\s*f?"([^"]+)"', text):
        seg = path.lstrip("/").split("/")[0]
        seg = re.sub(r"\{.*?\}", "", seg)
        if re.fullmatch(r"[a-z_]+", seg):
            used.add(seg)
    used |= set(re.findall(r'_api_href\(f?"([a-z_]+)', text))
    return used


def _live_probe(resources: list[str]) -> dict[str, int | None]:
    base = os.environ.get("OPENPROJECT_BASE_URL")
    token = os.environ.get("OPENPROJECT_API_TOKEN")
    if not base or not token:
        return {}
    auth = b64encode(f"apikey:{token}".encode()).decode()
    out: dict[str, int | None] = {}
    for r in resources:
        url = f"{base.rstrip('/')}/api/v3/{r}"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                out[r] = resp.status
        except urllib.error.HTTPError as e:
            out[r] = e.code
        except (urllib.error.URLError, TimeoutError):
            out[r] = None
    return out


def _classify(resource: str, used: bool, live: dict[str, int | None]) -> str:
    if used:
        return "covered"
    kind = CLASSIFICATION.get(resource)
    if kind:
        return kind
    if resource in CONFIRMED_GAPS:
        return "GAP (CE)"
    # Unlisted and unused: decide by live probe if available.
    status = live.get(resource)
    if status == 200:
        return "GAP (CE)"
    if status in (403,):
        return "enterprise"
    if status in (404, None) and live:
        return "subresource?"  # not top-level in CE; likely under a parent
    return "review"


def build_matrix() -> tuple[list[tuple[str, bool, object, str]], dict[str, int]]:
    resources = _source_resources()
    used = _client_resources()
    live = _live_probe(resources)
    rows: list[tuple[str, bool, object, str]] = []
    tally: dict[str, int] = {}
    for r in resources:
        is_used = r in used or RESOURCE_ALIASES.get(r) in used
        cls = _classify(r, is_used, live)
        status = live.get(r, "—") if live else "—"
        rows.append((r, is_used, status, cls))
        tally[cls] = tally.get(cls, 0) + 1
    return rows, tally


def render(rows, tally, *, live_enabled: bool) -> str:
    lines = []
    lines.append(f"{'resource':<26} {'client':<7} {'live':<6} classification")
    lines.append("-" * 60)
    for r, used, status, cls in rows:
        lines.append(f"{r:<26} {'yes' if used else '—':<7} {str(status):<6} {cls}")
    lines.append("")
    lines.append("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    if not live_enabled:
        lines.append("(live probe skipped — set OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN for CE availability)")
    return "\n".join(lines)


def render_gaps_section(rows: list[tuple[str, bool, object, str]]) -> str:
    """The '## Genuine CE gaps' (+ '## Unclassified resources' when needed) markdown.

    Split out from ``render_coverage_body`` so the "no false all-clear while
    resources remain unclassified" behavior is independently testable.
    """
    gaps = [r for r, _, _, cls in rows if cls == "GAP (CE)"]
    unclassified = [r for r, _, _, cls in rows if cls == "review"]
    if unclassified:
        return (
            "## Genuine CE gaps\n\n"
            "**Coverage is not fully verified — see 'Unclassified resources' below.** "
            "Confirmed gaps among the resources that _are_ classified:\n\n"
            + ("\n".join(f"- `{g}`" for g in gaps) if gaps else "_None among the classified resources._")
            + "\n\n## Unclassified resources\n\n"
            + f"{len(unclassified)} resource(s) could not be classified from the fetched "
            "source subtree alone and have not been checked against a live CE instance. "
            "Their CE-gap status is unknown — do not read their absence from the gap list "
            "above as a clean bill of health:\n\n" + "\n".join(f"- `{r}`" for r in unclassified) + "\n"
        )
    return (
        "## Genuine CE gaps\n\n"
        + ("\n".join(f"- `{g}`" for g in gaps) if gaps else "_None — every plain top-level CE resource is covered._")
        + "\n"
    )


def render_coverage_body(
    rows: list[tuple[str, bool, object, str]], tally: dict[str, int], *, live_enabled: bool
) -> str:
    """The full COVERAGE.md markdown document text."""
    report = render(rows, tally, live_enabled=live_enabled)
    return (
        f"# OpenProject CE API coverage\n\n"
        f"Generated by `tools/api-check/check_coverage.py` against source "
        f"{SOURCE_VERSION}"
        + (" with a live CE probe.\n\n" if live_enabled else " (no live probe).\n\n")
        + "Classifications: **covered** (client uses it), **GAP (CE)** "
        "(top-level CE resource not yet used), **subresource** (reached via "
        "a parent path), **enterprise** (not in plain CE), **internal** "
        "(framework/util, not a user resource), **review** (not yet classified — "
        "see 'Unclassified resources' below when present).\n\n"
        + "```\n"
        + report
        + "\n```\n\n"
        + render_gaps_section(rows)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="(re)write tools/api-check/COVERAGE.md")
    args = parser.parse_args()

    if not (SOURCES / SOURCE_VERSION).exists():
        print(f"error: missing source clone {SOURCE_VERSION}. Run tools/api-check/fetch-sources.sh", file=sys.stderr)
        return 2

    live_enabled = bool(os.environ.get("OPENPROJECT_BASE_URL") and os.environ.get("OPENPROJECT_API_TOKEN"))
    rows, tally = build_matrix()
    print(render(rows, tally, live_enabled=live_enabled))

    if args.write:
        COVERAGE_MD.write_text(render_coverage_body(rows, tally, live_enabled=live_enabled))
        print(f"\nwrote {COVERAGE_MD.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
