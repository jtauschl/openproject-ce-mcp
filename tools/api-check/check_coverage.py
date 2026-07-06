#!/usr/bin/env python3
"""Report how much of the OpenProject Community Edition API v3 this MCP covers.

Combines three sources of truth into one matrix:

1. **Source inventory** — every ``lib/api/v3/<resource>/`` directory in the
   pinned 17.5 clone (the full set of API resources).
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
SOURCE_VERSION = "17.5"  # inventory reference

# Curated classification of resources that are NOT plain top-level CRUD the
# client should cover. Anything not listed and not client-used and present in
# CE is reported as a genuine gap. Keep this in sync with the live probe.
#   internal    — framework/util endpoints, not user-facing resources
#   subresource — exists only under a parent path; covered via that parent
#   enterprise  — Enterprise-only / feature-flagged; not in plain CE
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
    # enterprise / feature-flagged (confirmed via live CE probe + source guards)
    "portfolios": "enterprise",
    "programs": "enterprise",
    "backups": "enterprise",
    "repositories": "enterprise",
}


def _source_resources() -> list[str]:
    base = SOURCES / SOURCE_VERSION / "lib" / "api" / "v3"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


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
        is_used = r in used
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="(re)write tools/api-check/COVERAGE.md")
    args = parser.parse_args()

    if not (SOURCES / SOURCE_VERSION).exists():
        print(f"error: missing source clone {SOURCE_VERSION}. Run tools/api-check/fetch-sources.sh", file=sys.stderr)
        return 2

    live_enabled = bool(os.environ.get("OPENPROJECT_BASE_URL") and os.environ.get("OPENPROJECT_API_TOKEN"))
    rows, tally = build_matrix()
    report = render(rows, tally, live_enabled=live_enabled)
    print(report)

    if args.write:
        gaps = [r for r, _, _, cls in rows if cls == "GAP (CE)"]
        body = (
            f"# OpenProject CE API coverage\n\n"
            f"Generated by `tools/api-check/check_coverage.py` against source "
            f"{SOURCE_VERSION}"
            + (" with a live CE probe.\n\n" if live_enabled else " (no live probe).\n\n")
            + "Classifications: **covered** (client uses it), **GAP (CE)** "
            "(top-level CE resource not yet used), **subresource** (reached via "
            "a parent path), **enterprise** (not in plain CE), **internal** "
            "(framework/util, not a user resource).\n\n"
            + "```\n"
            + report
            + "\n```\n\n"
            + (
                "## Genuine CE gaps\n\n"
                + (
                    "\n".join(f"- `{g}`" for g in gaps)
                    if gaps
                    else "_None — every plain top-level CE resource is covered._"
                )
                + "\n"
            )
        )
        COVERAGE_MD.write_text(body)
        print(f"\nwrote {COVERAGE_MD.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
