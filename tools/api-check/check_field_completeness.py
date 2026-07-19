#!/usr/bin/env python3
"""Find OpenProject CE representer fields this client has never modeled.

The reverse direction from ``check_api.py``: that tool verifies fields the
client already depends on still exist upstream (drift = "did OpenProject
remove something we rely on"). This tool enumerates every data-bearing field
a CE representer declares for a checked resource and reports which ones have
no corresponding field on the matching ``models.py`` dataclass(es) — drift in
the other direction ("did we silently miss exposing something").

Scope and limits
-----------------
Checks six resources (work_package, user, category, project, version,
membership) against a single pinned source version. Does NOT catch:
behaviour/semantics changes, dynamically-injected custom fields (never
statically declared in source), module-``prepend`` conditional fields (e.g.
Backlogs' sprint/story-point patches), or Enterprise gating (not reliably
derivable from source — see EXCLUSIONS below). Runtime field-hiding
(``app/policies/hidden_fields.py``, ``OPENPROJECT_HIDE_*``) is an orthogonal
axis: a field this tool finds unmodeled is a different category from a field
that's modeled but redacted at runtime for a specific deployment.

A field is either:
  COVERED   — modeled on the resource's Summary/Detail dataclass(es).
  EXCLUDED  — deliberately not modeled, per a curated, reason-bearing
              FieldExclusion entry (Enterprise-only, large embedded object,
              custom-field-pending, or other internal/write-only field).
  UNTRIAGED — neither of the above. Real drift requiring a decision: add a
              model field, or add a FieldExclusion with a reason.

Exit code reflects only UNTRIAGED drift, not "not exposed" per se — a green
run is a claim that every upstream field has been consciously triaged, not
that everything is exposed:
    0  every checked field is COVERED or EXCLUDED
    1  one or more fields are UNTRIAGED
    2  .op-sources/<version> missing (run fetch-sources.sh first)

Usage:
    python tools/api-check/check_field_completeness.py             # report
    python tools/api-check/check_field_completeness.py --verbose   # full table
    python tools/api-check/check_field_completeness.py --write     # (re)write FIELD_COMPLETENESS.md
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / ".op-sources"
FIELD_COMPLETENESS_MD = Path(__file__).resolve().parent / "FIELD_COMPLETENESS.md"
SOURCE_VERSION = "17.6"

sys.path.insert(0, str(ROOT / "src"))
from openproject_ce_mcp import models  # noqa: E402


class ExclusionCategory(str, Enum):
    ENTERPRISE = "enterprise"  # EE-gated per this server's CE-only policy
    LARGE_EMBEDDED = "large_embedded"  # token-heavy embed; exposed via a separate tool/URL instead
    CUSTOM_FIELD_PENDING = "custom_field_pending"
    INTERNAL_OTHER = "internal_other"  # write-only / framework / deliberately not surfaced


@dataclass(frozen=True)
class ResourceCheck:
    name: str
    # ALL representer files contributing fields -- a resource's own
    # *_representer.rb plus any base class/mixin that itself declares
    # macros (a module only providing the macro DSL, e.g.
    # API::Decorators::DateProperty, is not a field source and is not
    # listed). Hand-curated, not auto-resolved from Ruby class/include
    # statements -- see tools/api-check/README.md.
    source_files: tuple[str, ...]
    model_types: tuple[str, ...]  # names looked up on openproject_ce_mcp.models


@dataclass(frozen=True)
class FieldExclusion:
    resource: str
    wire_name: str
    category: ExclusionCategory
    reason: str  # required, non-empty -- enforced by a test


class Finding(NamedTuple):
    resource: str
    wire_name: str
    ruby_symbol: str
    macro: str
    status: str  # "COVERED" | "EXCLUDED" | "UNTRIAGED"
    category: str | None
    reason: str | None


class RawField(NamedTuple):
    macro: str
    ruby_symbol: str
    wire_name: str


RESOURCE_CHECKS: list[ResourceCheck] = [
    ResourceCheck(
        name="work_package",
        source_files=(
            "lib/api/v3/work_packages/work_package_representer.rb",
            # AttachableRepresenterMixin declares `property :attachments`.
            "lib/api/v3/attachments/attachable_representer_mixin.rb",
            # TimestampedRepresenter declares `property :_meta` (+ conditional
            # attributes_by_timestamp).
            "lib/api/v3/work_packages/timestamped_representer.rb",
        ),
        model_types=("WorkPackageSummary", "WorkPackageDetail"),
    ),
    ResourceCheck(
        name="user",
        source_files=(
            "lib/api/v3/users/user_representer.rb",
            # UserRepresenter < PrincipalRepresenter -- the base class
            # declares id/name/created_at/updated_at.
            "lib/api/v3/principals/principal_representer.rb",
        ),
        model_types=("UserSummary", "UserDetail"),
    ),
    ResourceCheck(
        name="category",
        source_files=("lib/api/v3/categories/category_representer.rb",),
        model_types=("CategorySummary",),  # no separate Detail; get_category returns CategorySummary
    ),
    ResourceCheck(
        name="project",
        source_files=("lib/api/v3/projects/project_representer.rb",),
        model_types=("ProjectSummary", "ProjectDetail"),
    ),
    ResourceCheck(
        name="version",
        source_files=("lib/api/v3/versions/version_representer.rb",),
        model_types=("VersionSummary", "VersionDetail"),
    ),
    ResourceCheck(
        name="membership",
        source_files=("lib/api/v3/memberships/membership_representer.rb",),
        model_types=("MembershipSummary",),  # no separate Detail; get_membership returns MembershipSummary
    ),
]

# Python model field -> representer wire name, for cases the default
# camelize(field_name) rule gets wrong: composite id+display pairs that both
# derive from one representer field (parent_id/parent_display_id -> parent),
# and Ruby-side names that don't round-trip through simple camelCase
# (firstname -> firstName since Ruby's own `as:` override doesn't
# camelize-derive from "firstname").
RENAME_MAP: dict[tuple[str, str], str] = {
    ("work_package", "parent_id"): "parent",
    ("work_package", "parent_display_id"): "parent",
    ("category", "default_assignee_id"): "defaultAssignee",
    ("category", "default_assignee"): "defaultAssignee",
    ("category", "project_id"): "project",
    ("user", "firstname"): "firstName",
    ("user", "lastname"): "lastName",
    ("user", "avatar_url"): "avatar",
    ("membership", "role_ids"): "roles",
    ("membership", "role_names"): "roles",
    ("membership", "project_id"): "project",
    ("membership", "project_name"): "project",
    ("membership", "principal_id"): "principal",
    ("membership", "principal_name"): "principal",
    ("project", "parent_id"): "parent",
    ("project", "parent_name"): "parent",
}

# Link names confirmed pure navigation/action affordances by direct
# inspection of all six target representers (plus their source_files) -- a
# link NOT in this set is treated as a candidate data field and reconciled
# against the model like any other macro, not silently ignored. This
# direction is deliberate: an allow-list that defaulted unknown links to
# "ignored" would silently recreate exactly the blind spot this tool exists
# to catch (a new data-only link added upstream staying invisible forever).
# An unclassified link instead surfaces as an UNTRIAGED finding -- loud,
# visible, one triage entry away from being added here with a reason.
NAVIGATION_LINKS: frozenset[str] = frozenset(
    {
        "self",
        "schema",
        "update",
        "updateImmediately",
        "delete",
        "lock",
        "unlock",
        "move",
        "copy",
        "favor",
        "disfavor",
        "watch",
        "unwatch",
        "addWatcher",
        "removeWatcher",
        "addRelation",
        "addChild",
        "changeParent",
        "addComment",
        "previewMarkup",
        "configureForm",
        "availableRelationCandidates",
        "availableWatchers",
        "revisions",
        "pdf",
        "generate_pdf",
        "atom",
        "logTime",
        "timeEntries",
        "createWorkPackage",
        "createWorkPackageImmediately",
        # Confirmed navigation/action links via the first real run against
        # 17.6, triaged one by one rather than left as noise:
        "customFields",  # schema-discovery link to the WP type's available custom fields, not a value
        "activities",  # collection href; check_coverage.py's own CLASSIFICATION already lists this as "subresource"
        "watchers",  # collection href; check_coverage.py's own CLASSIFICATION already lists this as "subresource"
        "prepareAttachment",  # write action affordance (upload prep), not data
        "addAttachment",  # write action affordance, not data
        "memberships",  # collection href (on both user and project) to the memberships sub-resource
        "workPackages",  # collection href to the project's work packages
        "storages",  # collection href to enabled storage integrations
        "categories",  # collection href; check_coverage.py's own CLASSIFICATION already lists this as "subresource"
        "versions",  # collection href to the project's versions
        "types",  # collection href to the project's enabled work-package types
        "projectStorages",  # collection href, same kind as storages
        "availableInProjects",  # action-like lookup link (find projects a version could share into), not the version's own data
        "showUser",  # web-UI navigation href to view the user's profile page, already modeled as UserSummary/UserDetail.url
    }
)

EXCLUSIONS: list[FieldExclusion] = [
    FieldExclusion(
        "work_package",
        "budget",
        ExclusionCategory.ENTERPRISE,
        "Budgets is Enterprise-only per this server's CE-only policy; "
        "associated_resource :budget (work_package_representer.rb:613) has no "
        "representer-level EnterpriseToken guard, so this can't be auto-derived.",
    ),
    FieldExclusion(
        "work_package",
        "customActions",
        ExclusionCategory.ENTERPRISE,
        "Custom Actions is Enterprise-only per the CE-only policy "
        "(resources :customActions, work_package_representer.rb:625).",
    ),
    FieldExclusion(
        "work_package",
        "relations",
        ExclusionCategory.LARGE_EMBEDDED,
        "Embedded relation collection (property :relations, line 478); exposed "
        "instead via relations_url + the get_work_package_relations tool.",
    ),
    FieldExclusion(
        "work_package",
        "attachments",
        ExclusionCategory.LARGE_EMBEDDED,
        "Embedded attachment collection (property :attachments, from the "
        "AttachableRepresenterMixin source pulled in via source_files); exposed "
        "instead via the list_work_package_attachments tool, same precedent as relations.",
    ),
    FieldExclusion(
        "user",
        "password",
        ExclusionCategory.INTERNAL_OTHER,
        "Write-only property (getter: ->(*) {}, render_nil: false) -- never "
        "appears in a read response, per user_representer.rb's own "
        "'# Write-only properties' comment.",
    ),
    FieldExclusion(
        "user",
        "currentPassword",
        ExclusionCategory.INTERNAL_OTHER,
        "Write-only property (getter: ->(*) {}, render_nil: false), same as password.",
    ),
    FieldExclusion(
        "work_package",
        "date",
        ExclusionCategory.INTERNAL_OTHER,
        "Milestone-only date_property (work_package_representer.rb:380, getter: "
        "default_date_getter(:due_date)); OPM-223 normalizes it into start_date/"
        "due_date at runtime (both get the same value for a milestone) rather than "
        "modeling a separate field -- a deliberate composite/semantic mapping, not "
        "an unmodeled field.",
    ),
    FieldExclusion(
        "work_package",
        "projectPhaseDefinition",
        ExclusionCategory.INTERNAL_OTHER,
        "Secondary link to the phase *definition* record (link :projectPhaseDefinition), "
        "distinct from the already-modeled project_phase value/name. "
        "list_project_phase_definitions/get_project_phase_definition already provide "
        "independent definition lookups; not worth a second WorkPackageDetail field.",
    ),
    FieldExclusion(
        "work_package",
        "_meta",
        ExclusionCategory.ENTERPRISE,
        "Backs the Enterprise-only Baseline Comparisons feature (TimestampedRepresenter, "
        "gated by timestamps_active?); never appears in any response this server "
        "produces, since nothing here requests historic timestamps.",
    ),
    FieldExclusion(
        "work_package",
        "attributesByTimestamp",
        ExclusionCategory.ENTERPRISE,
        "Same Enterprise-only Baseline Comparisons feature as _meta above "
        "(TimestampedRepresenter, property :attributes_by_timestamp, "
        "timestamps_active? gated).",
    ),
]
_EXCLUSION_INDEX: dict[tuple[str, str], FieldExclusion] = {(e.resource, e.wire_name): e for e in EXCLUSIONS}

# Macro names this tool treats as data-bearing. `associated_resources` and
# `resources` (plural) are listed distinctly from their singular forms --
# easy to miss, and a real, current field (membership's `associated_resources
# :roles`) depends on the plural being matched. `link`/`links` are handled
# separately (see NAVIGATION_LINKS above): every link is extracted too, then
# filtered, rather than being blanket-excluded from the macro family.
_DATA_MACROS = (
    "formattable_property",
    "date_time_property",
    "date_property",
    "associated_visible_resource",
    "associated_resources",
    "associated_resource",
    "associated_project",
    "resources",
    "resource",
    "property",
)
_LINK_MACROS = ("links", "link")
_MACRO_RE = re.compile(r"^[ \t]*(?P<macro>" + "|".join(_DATA_MACROS + _LINK_MACROS) + r")\b(?P<rest>.*)$")
_POSITIONAL_SYMBOL_RE = re.compile(r"^\s*:(\w+)")
_AS_RE = re.compile(r"\bas:\s*[:\"']?(\w+)")
_MAX_CONTINUATION_LINES = 15


def _camelize(name: str) -> str:
    """Ruby snake_case -> lowerCamelCase, matching Representable's default `as:` derivation.

    Leading-underscore names (e.g. `_meta`, from TimestampedRepresenter) are
    left unchanged -- a generic camelCase converter would otherwise mangle
    `_meta` into `Meta`/`meta`, fabricating a wrong wire name.
    """
    if name.startswith("_"):
        return name
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _positional_symbol(rest: str) -> str | None:
    """The macro's own positional `:symbol` argument, if the very first token after the macro name is one.

    Anchored (not searched) deliberately: an `as: :word` clause later on the
    same line must never be mistaken for a positional symbol -- this is
    exactly the bug a free `.search()` would have for a bare
    `associated_project as: :definingProject` line, which has no positional
    symbol at all.
    """
    m = _POSITIONAL_SYMBOL_RE.match(rest)
    return m.group(1) if m else None


def _resolve_as(first_line_rest: str, following_lines: list[str], indent: int) -> str | None:
    """The `as:` wire-name override, inline on the macro line or on a deeper-indented continuation line."""
    m = _AS_RE.search(first_line_rest)
    if m:
        return m.group(1)
    for line in following_lines[:_MAX_CONTINUATION_LINES]:
        if not line.strip():
            break
        if (len(line) - len(line.lstrip())) <= indent:
            break
        m = _AS_RE.search(line)
        if m:
            return m.group(1)
    return None


def _extract_macro_fields(text: str) -> list[RawField]:
    """Extract every data-bearing field (and link) declaration from one representer source file."""
    lines = text.splitlines()
    out: list[RawField] = []
    for i, line in enumerate(lines):
        m = _MACRO_RE.match(line)
        if not m:
            continue
        macro = m.group("macro")
        rest = m.group("rest")
        indent = len(line) - len(line.lstrip())

        symbol = _positional_symbol(rest)
        if symbol is None:
            if macro == "associated_project":
                # No positional symbol (the common case: a bare
                # `associated_project` meaning "the resource's own project"),
                # or an `as:`-only override with no positional symbol at all
                # (`associated_project as: :definingProject`) -- either way
                # the Ruby symbol defaults to "project".
                symbol = "project"
            else:
                # No macro other than associated_project has been observed
                # without a positional symbol across the six checked
                # resources; skip defensively rather than fabricate one.
                continue

        wire = _resolve_as(rest, lines[i + 1 :], indent) or _camelize(symbol)
        out.append(RawField(macro=macro, ruby_symbol=symbol, wire_name=wire))

    return [f for f in out if not (f.macro in _LINK_MACROS and f.ruby_symbol in NAVIGATION_LINKS)]


def _dedup(records: list[RawField]) -> list[RawField]:
    """Collapse same-wire-name collisions to one record, preferring a data macro over a bare link.

    Real case: work_package_representer.rb declares both `link :relations do
    ... end` and `property :relations, ...` for the same wire name -- without
    this, that inflates tallies and leaves "which macro/symbol is correct"
    ambiguous.
    """
    by_wire: dict[str, RawField] = {}
    for rec in records:
        existing = by_wire.get(rec.wire_name)
        if existing is None or (existing.macro in _LINK_MACROS and rec.macro not in _LINK_MACROS):
            by_wire[rec.wire_name] = rec
    return list(by_wire.values())


def _covered_wire_names(rc: ResourceCheck, model_module: Any = None) -> set[str]:
    mod = model_module if model_module is not None else models
    covered: set[str] = set()
    for type_name in rc.model_types:
        model_cls = getattr(mod, type_name)
        for f in dataclasses.fields(model_cls):
            covered.add(RENAME_MAP.get((rc.name, f.name), _camelize(f.name)))
    return covered


def _findings_for_resource(rc: ResourceCheck, texts: list[str], model_module: Any = None) -> list[Finding]:
    """The pure classification core: takes already-read source texts, no filesystem access.

    This is the monkeypatch-free test seam -- feed fixture Ruby snippets and
    a fixture model namespace directly, no `.op-sources/` or real `models.py`
    dependency required.
    """
    raw: list[RawField] = []
    for text in texts:
        raw.extend(_extract_macro_fields(text))
    deduped = _dedup(raw)
    covered = _covered_wire_names(rc, model_module)

    findings: list[Finding] = []
    for rec in deduped:
        if rec.wire_name in covered:
            findings.append(Finding(rc.name, rec.wire_name, rec.ruby_symbol, rec.macro, "COVERED", None, None))
            continue
        excl = _EXCLUSION_INDEX.get((rc.name, rec.wire_name))
        if excl is not None:
            findings.append(
                Finding(
                    rc.name, rec.wire_name, rec.ruby_symbol, rec.macro, "EXCLUDED", excl.category.value, excl.reason
                )
            )
            continue
        findings.append(Finding(rc.name, rec.wire_name, rec.ruby_symbol, rec.macro, "UNTRIAGED", None, None))
    return findings


class MissingSourceError(RuntimeError):
    """A curated ResourceCheck.source_files entry doesn't exist under the pinned version.

    Distinct from a plain RuntimeError so `main()` can catch exactly this
    case (an incomplete sparse checkout or a stale source_files entry) and
    report it as the same kind of "sources aren't usable" condition as a
    missing .op-sources/<version>/ directory entirely -- exit 2, not an
    uncaught traceback defaulting to exit 1, which would be indistinguishable
    from the documented "real UNTRIAGED findings" exit 1.
    """


def build_findings() -> list[Finding]:
    findings: list[Finding] = []
    for rc in RESOURCE_CHECKS:
        texts: list[str] = []
        for sf in rc.source_files:
            path = SOURCES / SOURCE_VERSION / sf
            if not path.exists():
                raise MissingSourceError(
                    f"check_field_completeness: curated source_files entry missing for "
                    f"resource {rc.name!r}: {sf} (checked {path}). Either "
                    f".op-sources/{SOURCE_VERSION}/ needs tools/api-check/fetch-sources.sh, "
                    "or this ResourceCheck's source_files needs re-verifying against "
                    "upstream (see tools/api-check/README.md)."
                )
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        findings.extend(_findings_for_resource(rc, texts))
    return findings


def render(findings: list[Finding], *, verbose: bool) -> str:
    rows = findings if verbose else [f for f in findings if f.status == "UNTRIAGED"]
    lines = [f"{'resource':<14} {'field':<26} {'macro':<24} {'status':<10} category", "-" * 90]
    for f in rows:
        lines.append(f"{f.resource:<14} {f.wire_name:<26} {f.macro:<24} {f.status:<10} {f.category or '—'}")
    if not verbose:
        lines.append("(pass --verbose to also list COVERED/EXCLUDED rows)")
    lines.append("")
    tally = {
        "resources": len({f.resource for f in findings}),
        "checked_fields": len(findings),
        "covered": sum(1 for f in findings if f.status == "COVERED"),
        "excluded": sum(1 for f in findings if f.status == "EXCLUDED"),
        "untriaged": sum(1 for f in findings if f.status == "UNTRIAGED"),
    }
    lines.append("Summary: " + ", ".join(f"{k}={v}" for k, v in tally.items()))
    return "\n".join(lines)


def render_untriaged_block(findings: list[Finding]) -> str:
    untriaged = [f for f in findings if f.status == "UNTRIAGED"]
    if not untriaged:
        return ""
    lines = []
    for f in untriaged:
        lines.append(f"\nUNTRIAGED  {f.resource}.{f.wire_name}  ({f.macro} :{f.ruby_symbol})")
        lines.append("  Before modeling: (a) token cost -- does this enlarge every list row?")
        lines.append("  (b) hide-field -- should it ship behind a HIDE_FIELD_* opt-out?")
        lines.append("  Resolve by adding a model field OR a FieldExclusion entry with a reason.")
    return "\n".join(lines)


def render_untriaged_section(findings: list[Finding]) -> str:
    untriaged = [f for f in findings if f.status == "UNTRIAGED"]
    if not untriaged:
        return "## Untriaged drift\n\n_None — every checked field is modeled or has a documented exclusion._\n"
    lines = [
        "## Untriaged drift\n",
        "Every field below is a real CE representer field with no model coverage "
        "and no recorded exclusion. Resolve each by adding a model field or a "
        "`FieldExclusion` entry with a reason.\n",
    ]
    for f in untriaged:
        lines.append(f"- `{f.resource}.{f.wire_name}` ({f.macro} `:{f.ruby_symbol}`)")
    return "\n".join(lines) + "\n"


def render_exclusions_section() -> str:
    lines = ["## Intentional exclusions\n"]
    by_category: dict[str, list[FieldExclusion]] = {}
    for e in EXCLUSIONS:
        by_category.setdefault(e.category.value, []).append(e)
    for cat in sorted(by_category):
        lines.append(f"### {cat}\n")
        for e in by_category[cat]:
            lines.append(f"- `{e.resource}.{e.wire_name}` — {e.reason}")
        lines.append("")
    return "\n".join(lines)


def render_report(findings: list[Finding]) -> str:
    return (
        "# Field completeness\n\n"
        f"Generated by `tools/api-check/check_field_completeness.py` against source {SOURCE_VERSION}.\n\n"
        "Reverse-drift guard: enumerates every data-bearing field OpenProject CE's "
        "representers declare for a checked resource and reports which ones this "
        "client has never modeled in `models.py` — the opposite direction from "
        "`check_api.py`, which verifies fields the client already depends on still "
        "exist upstream.\n\n"
        "```\n"
        + render(findings, verbose=True)
        + "\n```\n\n"
        + render_untriaged_section(findings)
        + "\n"
        + render_exclusions_section()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="(re)write tools/api-check/FIELD_COMPLETENESS.md")
    parser.add_argument("--verbose", action="store_true", help="also list COVERED/EXCLUDED rows")
    args = parser.parse_args()

    if not (SOURCES / SOURCE_VERSION).exists():
        print(f"error: missing source clone {SOURCE_VERSION}. Run tools/api-check/fetch-sources.sh", file=sys.stderr)
        return 2

    try:
        findings = build_findings()
    except MissingSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(render(findings, verbose=args.verbose))
    print(render_untriaged_block(findings))

    if args.write:
        FIELD_COMPLETENESS_MD.write_text(render_report(findings))
        print(f"\nwrote {FIELD_COMPLETENESS_MD.relative_to(ROOT)}")

    return 1 if any(f.status == "UNTRIAGED" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
