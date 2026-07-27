#!/usr/bin/env bash
set -euo pipefail

# Checks a consuming project's conformance to its own declared Project Profile
# (<project>-int/20-requirements/00-handbook-profile.md — see
# ../../02-bootstrap/project-setup.md#project-profile for the 9-axis vocabulary and
# ../../templates/00-handbook-profile.md.example for the exact schema) and its own
# handbook-baseline.yml (<project>-int/30-implementation/handbook-baseline.yml — see
# ../../templates/handbook-baseline.yml.example for that schema, and
# ../../01-foundations/documentation.md#structure for why 30-implementation is the right tier for
# an observed-state file like this one). Both files are read every run, never cached — this
# script is never the source of truth for what a project's profile axes or baseline fields
# currently are, only a checker of whether reality matches what's already declared there.
#
# Every check below maps to exactly one handbook rule; several cross-reference
# ../../03-build/architecture-principles.md#architecture-maturity-tiers (the mobile_only_
# consistency and infra_governance_vs_profile checks, which flag a profile self-contradiction
# rather than resolve one) and ../../01-foundations/documentation.md#structure (companion-repo and
# required-root-files presence).
#
# --- yq dependency: mikefarah/yq v4.x, NOT kislyuk/yq, NOT mikefarah/yq v3 -----------------------
# This script requires the Go-based `mikefarah/yq` (https://github.com/mikefarah/yq) at major
# version 4 specifically. Two different, unrelated tools can satisfy `command -v yq` and still be
# wrong:
#   - kislyuk/yq (https://github.com/kislyuk/yq) is an entirely different, Python-based project
#     that happens to install a same-named `yq` command — its flags and semantics don't match
#     mikefarah/yq's at all (it's a jq wrapper for YAML, not its own query language), so a script
#     written for mikefarah/yq fails against it in confusing, tool-specific ways rather than a
#     clean "wrong tool" message.
#   - mikefarah/yq's OWN v3 releases use a materially different CLI syntax from v4 — notably,
#     `--front-matter=extract` (used below to read the profile file's YAML front matter out of a
#     markdown file) is a v4-only flag; v3 has no equivalent invocation shape.
# require_yq_v4() below inspects `yq --version` output for both the substring "mikefarah/yq" and
# "v4." before trusting whatever `yq` resolves to on PATH — on failure it prints an actionable,
# platform-specific install command and exits 1, rather than letting a mismatched binary produce a
# cryptic parse error partway through the first real check. On macOS: `brew install yq` (Homebrew's
# yq formula tracks mikefarah/yq). On Linux: a distro's own `yq` package can resolve to a different
# implementation entirely (Debian/Ubuntu's `yq` apt package has historically been the Python
# kislyuk/yq instead) — `go install github.com/mikefarah/yq/v4@latest` is the disambiguating pin
# that names the exact module path, sidestepping whatever a distro package manager happens to call
# "yq" this year.
#
# --- Severity/exit-status contract: five outcomes, not a bare pass/fail ---------------------------
# Every check function below reports exactly one of five outcomes: the four-outcome severity
# contract below (FAIL/WARN/INDETERMINATE/SKIPPED) that determines exit-code contribution, PLUS
# PASS, the success terminal state a check reports when none of the other four apply. PASS is not
# part of the severity contract itself (it never contributes to the exit code, has nothing to waive,
# and is never itself a subject of policy) — it exists purely so every check's successful case has
# its own explicit, readable outcome in this script's output, rather than being represented as an
# absence of the other four.
#   - PASS       — the check ran to completion and found no problem: the normative expectation is
#                  met, or (for a WARN/SKIPPED-kind check) nothing worth reporting was found.
#                  Printed, never contributes to the exit code.
#   - FAIL       — a normative mismatch or an unmet enforced expectation. Contributes to this
#                  script's final nonzero exit UNLESS validly waived via handbook-baseline.yml's
#                  exceptions[] list. Every check is waivable by default EXCEPT the fixed 3-item
#                  NON_WAIVABLE_CHECKS array below — there is no separate "waivable list" to
#                  maintain, only that one exclusion.
#   - WARN       — genuinely report-only: the underlying handbook rule doesn't use "must" for this
#                  particular fact. Printed, but NEVER contributes to the exit code, regardless of
#                  waiver state (a WARN-kind check has nothing to waive in the first place).
#   - INDETERMINATE — one of the 5 live/network checks (15-19) could not complete because the
#                  external API itself was unreachable (a transport/auth failure) — NEVER used by a
#                  local/offline check for a local parse/read/config problem, which is a FAIL
#                  instead (see each local check's own logic), and NEVER used for a local
#                  prerequisite a live check needs before it can even attempt its API call (`gh` not
#                  found on PATH, or owner/repo not resolvable) — those are also FAIL (or WARN, for a
#                  WARN-kind check), since the network was never even reached. Likewise, a live
#                  check's API call that DID succeed (a 2xx response) but returned a malformed/
#                  unexpected response body is a data problem, not a transport failure, so that's
#                  FAIL too. INDETERMINATE is reserved specifically for a genuine transport-level
#                  failure while actually contacting the API endpoint (a non-2xx/404-recognized HTTP
#                  status, a curl timeout, a `000` status, or gh_api_get's own "ERR" meaning no HTTP
#                  response was received at all). ALWAYS contributes to this script's
#                  final nonzero exit, for every check capable of going indeterminate, and is NEVER
#                  waivable — even when that same check's own FAIL outcome IS waivable. These are
#                  two independent rules, not one: e.g. dependabot_readonly reporting "disabled" is
#                  a waivable FAIL, but dependabot_readonly reporting "unreachable" is
#                  unconditionally nonzero and cannot be waived by naming dependabot_readonly in
#                  exceptions[] — that waiver only ever applies to the FAIL outcome, never to
#                  INDETERMINATE.
#   - SKIPPED    — an explicitly permitted case where a check genuinely cannot run through no
#                  fault of the project (currently: openproject_project_exists with no
#                  OPENPROJECT_API_TOKEN credential in the environment). Printed, never
#                  contributes to the exit code.
#
# --- The 19 checks -------------------------------------------------------------------------------
# Local/offline (14): tag_pin, int_present (non-waivable), infra_governance_vs_profile,
# required_root_files, agents_md_symlink, commit_msg_hook (non-waivable), dev_subcommands,
# handbook_check_wired, gitignore_baseline, baseline_schema_version, stack_folder_shape,
# mobile_only_consistency, script_self_placement, profile_hash_drift (WARN-only).
# Live/read-only (5), each independently network-guarded so a failure reaching one API never
# aborts the whole run or blocks any other check: github_issues_vs_tracker (non-waivable),
# branch_protection (WARN-only), dependabot_readonly, openproject_project_exists (SKIPPED without
# a credential), latest_release_vs_pinned (WARN-only).
# See each check_<id>() function below for its own specific normative source and outcome logic.
#
# --- Known gaps (not automatically checkable) ------------------------------------------------------
# print_not_checkable_notice() (called unconditionally, every run, regardless of overall pass/
# fail) prints the fixed list of things this script cannot verify no matter how it's extended:
# whether a declared profile axis is actually true in the real world (this script only checks
# INTERNAL CONSISTENCY between axes and between axes and the filesystem, never the axis's
# real-world truth); whether <project>-int's content is actually good (presence-only checked, see
# int_present); whether a documented exception's stated reason in handbook-baseline.yml's
# exceptions[] is still valid (only that the entry exists and names a waivable check, never
# whether its rationale still holds); whether CI is green on the latest commit; ISO/compliance-
# framework substantive conformance (a governance companion repo's mere presence is checked, never
# its content); and whether architecture-principles.md#architecture-maturity-tiers's acceptance
# criteria are satisfied for any specific real decision this project has made.
#
# --- Hard constraints ------------------------------------------------------------------------------
# This script NEVER mutates external state: every GitHub/OpenProject API call anywhere below is a
# GET, never a PUT/POST/PATCH — unlike github-security-settings.sh.example, this is purely a
# checker, not an enforcer. The ONE local write this script ever performs is updating
# handbook-baseline.yml itself, and only when explicitly invoked with --migrate. This script also
# never prints secrets, raw API error response bodies, or command traces that could leak a
# credential — a captured API error is summarized, not echoed verbatim.
#
# Usage: ./handbook-check.sh.example [--migrate]
#   e.g. ./handbook-check.sh.example
#        ./handbook-check.sh.example --migrate
#   Run from anywhere inside the code repo (or any of its sibling companion repos) — this script
#   locates the umbrella directory itself (see locate_umbrella() below) rather than assuming a
#   specific invocation-time working directory. --migrate additionally updates
#   handbook-baseline.yml in place for fields this script can safely re-derive on its own (e.g.
#   profile.source_sha256); it never edits fields that require a human decision (exceptions[],
#   tracker.project_identifier).
#
# NOT wired as a ./dev subcommand by sw_dev_handbook itself — that's a copier-side integration
# step once this template is copied into a project's own scripts/ folder, per
# ../../02-bootstrap/project-setup.md#where-a-copied-automation-script-lives. See the
# handbook_check_wired check below, which verifies that integration step was actually done.

# SW_DEV_HANDBOOK_DOC_REF: set this to the sw_dev_handbook tag YOUR project is actually pinned to
# (see `git -C sw_dev_handbook describe --tags --exact-match` from the umbrella directory, or
# sw_dev_handbook/CHANGELOG.md's latest released version) before relying on the doc links this
# script prints below — either edit the fallback value directly when copying this template, or
# export SW_DEV_HANDBOOK_DOC_REF in the environment before running it (the `${VAR:-default}` form
# below means an already-exported value always wins over the fallback, unlike a plain `VAR=...`
# assignment, which would silently discard an inherited env var of the same name).
#
# The fallback is a DELIBERATELY INVALID placeholder, not `main` or any other value that would
# silently "work" — see github-security-settings.sh.example's own header comment for the full
# reasoning; the short version is that an invalid placeholder makes every resulting doc link 404
# loudly until it's actually set, instead of silently resolving to the wrong policy version.
SW_DEV_HANDBOOK_DOC_REF="${SW_DEV_HANDBOOK_DOC_REF:-v0.9.0}"

# Fixed, non-configurable: no exceptions[] entry in handbook-baseline.yml may waive any of these
# three check IDs, no matter what handbook-baseline.yml itself claims. An exceptions[] entry
# naming one of these is reported as its own ERROR (see apply_waivers() below), not silently
# honored or silently skipped.
NON_WAIVABLE_CHECKS=(int_present commit_msg_hook github_issues_vs_tracker)

# The 5 live/network check IDs — used only by run_check()'s own unexpected-crash fallback below to
# decide whether an unhandled non-zero return is reported as INDETERMINATE (appropriate for a live
# check, whose whole nature is "may not be able to complete due to something outside this script's
# control") or FAIL (appropriate for a local/offline check, where an unhandled crash is at least as
# bad as a normal, deterministic FAIL — see the header comment's "local problem = FAIL" rule).
LIVE_CHECK_IDS=(github_issues_vs_tracker branch_protection dependabot_readonly openproject_project_exists latest_release_vs_pinned)

KNOWN_BASELINE_SCHEMA_VERSION=1

migrate=0
case "${1:-}" in
--migrate)
    migrate=1
    ;;
"") ;;
*)
    echo "handbook-check: unknown argument: $1 (usage: ./handbook-check.sh.example [--migrate])" >&2
    exit 1
    ;;
esac

# --- Preflight: yq v4 (mikefarah), never a look-alike --------------------------------------------
require_yq_v4() {
    if ! command -v yq >/dev/null 2>&1; then
        echo "handbook-check: yq not found. This script requires mikefarah/yq v4.x (NOT the" >&2
        echo "unrelated Python kislyuk/yq package, which shares the same command name)." >&2
        echo "  macOS:  brew install yq" >&2
        echo "  Linux:  go install github.com/mikefarah/yq/v4@latest" >&2
        echo "          (a distro's own 'yq' package can resolve to a different, incompatible" >&2
        echo "          implementation — the go install path above pins the exact one this" >&2
        echo "          script needs)" >&2
        exit 1
    fi
    local version_out
    version_out="$(yq --version 2>&1 || true)"
    if [[ "$version_out" != *"mikefarah/yq"* ]] || [[ "$version_out" != *"v4."* ]]; then
        echo "handbook-check: found a 'yq' on PATH, but it doesn't look like mikefarah/yq v4.x:" >&2
        echo "  $version_out" >&2
        echo "This script requires mikefarah/yq (https://github.com/mikefarah/yq) at major" >&2
        echo "version 4 specifically — v3's CLI syntax differs, and the unrelated Python" >&2
        echo "kislyuk/yq package shares this same command name with entirely different flags." >&2
        echo "  macOS:  brew install yq" >&2
        echo "  Linux:  go install github.com/mikefarah/yq/v4@latest" >&2
        exit 1
    fi
}
require_yq_v4

if ! command -v jq >/dev/null 2>&1; then
    echo "handbook-check: jq not found — https://jqlang.org/download/" >&2
    exit 1
fi

# --- yq wrapper helpers ----------------------------------------------------------------------------
# yq_front_matter <markdown-file> <yq-expression>: reads YAML front matter out of a markdown file
# (the Project Profile's own shape — see templates/00-handbook-profile.md.example) via v4's
# --front-matter=extract, which pulls just the leading `---...---` block and evaluates the
# expression against that. Returns empty (not an error) if the expression resolves to null, so
# callers checking for an absent/false axis don't need to special-case yq's own null formatting.
yq_front_matter() {
    local file="$1" expr="$2" out
    if ! out="$(yq --front-matter=extract "$expr" "$file" 2>&1)"; then
        return 1
    fi
    if [ "$out" = "null" ]; then
        out=""
    fi
    printf '%s' "$out"
}

# yq_baseline <baseline-file> <yq-expression>: reads plain YAML (handbook-baseline.yml's own
# shape, no front matter wrapper) via a plain yq invocation. Same null-to-empty normalization as
# yq_front_matter above.
yq_baseline() {
    local file="$1" expr="$2" out
    if ! out="$(yq "$expr" "$file" 2>&1)"; then
        return 1
    fi
    if [ "$out" = "null" ]; then
        out=""
    fi
    printf '%s' "$out"
}

# --- Self-location: find the umbrella directory, never assume the invocation-time cwd -----------
# Mirrors github-security-settings.sh.example's own script_dir/repo_root resolution style: resolve
# $0 to its real, symlink-free path first (this script is typically invoked as
# ./scripts/handbook-check.sh from inside a project's code repo, but must not assume that literal
# relative form). Per ../../02-bootstrap/project-setup.md#where-a-copied-automation-script-lives,
# a copied automation script always lives at <code-repo>/scripts/, so the code repo itself is
# always exactly two levels up from this script's own resolved directory — CODE_REPO_DIR is
# derived directly from that, never from walking up looking for a sibling <project>-int (a missing
# <project>-int is exactly the FAIL condition int_present itself exists to report — deriving
# CODE_REPO_DIR from its presence would make that check's own FAIL case impossible to observe).
# UMBRELLA_DIR is CODE_REPO_DIR's own parent, additionally confirmed by requiring a sibling
# sw_dev_handbook/ git clone to exist there — that confirmation is what actually distinguishes a
# genuine umbrella directory from an arbitrary parent directory (e.g. this script running
# standalone from inside sw_dev_handbook's own templates/scripts/ during development, which has no
# sibling sw_dev_handbook/ clone one level up from ITS OWN scripts/ analog).
script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
CODE_REPO_DIR="$(cd -- "$script_dir/.." && pwd)"
UMBRELLA_DIR="$(dirname -- "$CODE_REPO_DIR")"

if [ ! -d "$UMBRELLA_DIR/sw_dev_handbook" ] || [ ! -d "$UMBRELLA_DIR/sw_dev_handbook/.git" ]; then
    echo "handbook-check: could not locate the umbrella directory — expected a sibling" >&2
    echo "sw_dev_handbook/ git clone one level above the code repo ($UMBRELLA_DIR), given this" >&2
    echo "script's own resolved location at $script_dir — see" >&2
    echo "../../02-bootstrap/project-setup.md#repo-topology for the expected layout, and" >&2
    echo "#where-a-copied-automation-script-lives for why this script must be copied into the" >&2
    echo "code repo's own scripts/ folder, not run standalone from inside sw_dev_handbook itself." >&2
    exit 1
fi

# INT_DIR may legitimately be empty — see int_present below, whose entire job is reporting that
# fact as a FAIL. PROJECT_NAME falls back to the code repo's own directory basename when no
# <project>-int sibling exists yet, since several other checks below (infra_governance_vs_profile,
# mobile_only_consistency's own <project>-infrastructure/<project>-governance lookups) still need
# a project name even when int_present itself is failing.
INT_DIR="$(find "$UMBRELLA_DIR" -maxdepth 1 -type d -name '*-int' 2>/dev/null | head -n1 || true)"
if [ -n "$INT_DIR" ]; then
    PROJECT_NAME="$(basename "${INT_DIR%-int}")"
else
    PROJECT_NAME="$(basename "$CODE_REPO_DIR")"
fi

PROFILE_FILE="$INT_DIR/20-requirements/00-handbook-profile.md"
BASELINE_FILE="$INT_DIR/30-implementation/handbook-baseline.yml"

fail=0

# CHECK_IDS[] is the fixed, ordered registry of every check ID this run may record an outcome
# for — appended to once per record_outcome() call, in first-seen order, so the final tally and
# apply_waivers() below can enumerate "every check that ran" without needing an associative array.
# Bash 3.2 (macOS's shipped /bin/bash — the same target github-security-settings.sh.example's own
# gh_api_status() comment documents, for the same reason: no `local -n` namerefs, no `declare -A`
# on this version) has no associative-array support at all, so outcome/message storage below uses
# dynamically-named PLAIN variables instead (`outcome_<id>`, `message_<id>`), read back via bash's
# indirect-expansion form `${!varname}` (POSIX-portable, bash-3.2-safe) rather than an associative
# array. Every check ID used anywhere in this script is a fixed, internal, hardcoded bash
# identifier (never derived from external/untrusted input), so the `eval`-based assignment below
# is safe — there is no injection surface, since $id is never anything other than one of this
# script's own literal check_<id> function-name suffixes.
CHECK_IDS=()

# record_outcome <check_id> <FAIL|WARN|INDETERMINATE|SKIPPED|PASS> <message>: the single place
# every check function reports its result through, so the exit-code/waiver logic below (see
# apply_waivers and the final tally) never has to be reimplemented per check.
record_outcome() {
    local id="$1" outcome="$2" message="$3"
    CHECK_IDS+=("$id")
    eval "outcome_${id}=\$outcome"
    eval "message_${id}=\$message"
    case "$outcome" in
    FAIL) echo "FAIL [$id]: $message" ;;
    WARN) echo "WARN [$id]: $message" ;;
    INDETERMINATE) echo "INDETERMINATE [$id]: $message" >&2 ;;
    SKIPPED) echo "SKIPPED [$id]: $message" ;;
    PASS) echo "PASS [$id]: $message" ;;
    esac
}

# get_outcome <check_id>: echoes the recorded outcome for a check ID, or empty if it never ran.
get_outcome() {
    local id="$1"
    local varname="outcome_${id}"
    printf '%s' "${!varname:-}"
}

# set_outcome <check_id> <new_outcome>: used only by apply_waivers() to flip a FAIL to WAIVED.
set_outcome() {
    local id="$1" outcome="$2"
    eval "outcome_${id}=\$outcome"
}

# get_message <check_id>: echoes the recorded message for a check ID, or empty if it never ran.
get_message() {
    local id="$1"
    local varname="message_${id}"
    printf '%s' "${!varname:-}"
}

# ===================================================================================================
# Local/offline checks (1-14)
# ===================================================================================================

# 1. tag_pin — sw_dev_handbook/README.md#using-this-repo-in-another-project and
# ../../02-bootstrap/project-setup.md#repo-topology require the umbrella-level sw_dev_handbook
# clone to sit exactly on a released tag (never track main) — that tag must match what
# handbook-baseline.yml's handbook.pinned_tag last recorded, or the baseline itself is stale.
check_tag_pin() {
    local actual expected
    if ! actual="$(git -C "$UMBRELLA_DIR/sw_dev_handbook" describe --tags --exact-match 2>&1)"; then
        record_outcome tag_pin FAIL "sw_dev_handbook is not checked out exactly on a released tag (git describe --tags --exact-match failed) — see ../../02-bootstrap/project-setup.md#repo-topology"
        return
    fi
    if ! expected="$(yq_baseline "$BASELINE_FILE" '.handbook.pinned_tag')"; then
        record_outcome tag_pin FAIL "could not read handbook.pinned_tag from $BASELINE_FILE"
        return
    fi
    if [ "$actual" = "$expected" ]; then
        record_outcome tag_pin PASS "sw_dev_handbook is on $actual, matching handbook-baseline.yml"
    else
        record_outcome tag_pin FAIL "sw_dev_handbook is on $actual but handbook-baseline.yml records pinned_tag: $expected — update the baseline after reconciling against the new tag"
    fi
}

# 2. int_present — NON-WAIVABLE. ../../02-bootstrap/project-setup.md#documentation-companion-repo
# mandates <project>-int for every project, no size exception.
check_int_present() {
    if [ -n "$INT_DIR" ] && [ -d "$INT_DIR" ]; then
        record_outcome int_present PASS "companion repo present: $INT_DIR"
    else
        record_outcome int_present FAIL "no sibling <project>-int directory found next to the code repo at the umbrella level — see ../../02-bootstrap/project-setup.md#documentation-companion-repo"
    fi
}

# 3. infra_governance_vs_profile — the profile's infrastructure_repo_needed/compliance_obligation
# axes (see ../../02-bootstrap/project-setup.md#project-profile, axes 5/6) gate whether
# <project>-infrastructure/<project>-governance are expected to exist; this check flags a mismatch
# between the declared axis and what's actually on disk, in either direction.
check_infra_governance_vs_profile() {
    local infra_needed compliance
    if ! infra_needed="$(yq_front_matter "$PROFILE_FILE" '.infrastructure_repo_needed')"; then
        record_outcome infra_governance_vs_profile FAIL "could not read infrastructure_repo_needed from $PROFILE_FILE"
        return
    fi
    if ! compliance="$(yq_front_matter "$PROFILE_FILE" '.compliance_obligation | length')"; then
        record_outcome infra_governance_vs_profile FAIL "could not read compliance_obligation from $PROFILE_FILE"
        return
    fi
    local infra_dir_exists=0 gov_dir_exists=0
    [ -d "$UMBRELLA_DIR/${PROJECT_NAME}-infrastructure" ] && infra_dir_exists=1
    [ -d "$UMBRELLA_DIR/${PROJECT_NAME}-governance" ] && gov_dir_exists=1
    local problems=""
    if [ "$infra_needed" = "true" ] && [ "$infra_dir_exists" -eq 0 ]; then
        problems="${problems}profile declares infrastructure_repo_needed: true but ${PROJECT_NAME}-infrastructure is missing; "
    fi
    if [ "$infra_needed" != "true" ] && [ "$infra_dir_exists" -eq 1 ]; then
        problems="${problems}${PROJECT_NAME}-infrastructure exists but the profile declares infrastructure_repo_needed: false; "
    fi
    if [ "${compliance:-0}" != "0" ] && [ -n "$compliance" ] && [ "$gov_dir_exists" -eq 0 ]; then
        problems="${problems}profile declares a non-empty compliance_obligation but ${PROJECT_NAME}-governance is missing; "
    fi
    if [ "${compliance:-0}" = "0" ] && [ "$gov_dir_exists" -eq 1 ]; then
        problems="${problems}${PROJECT_NAME}-governance exists but the profile declares an empty compliance_obligation; "
    fi
    if [ -n "$problems" ]; then
        record_outcome infra_governance_vs_profile FAIL "$problems see ../../02-bootstrap/project-setup.md#infrastructure-companion-repo and #governance-companion-repo"
    else
        record_outcome infra_governance_vs_profile PASS "infrastructure/governance companion-repo presence matches the declared profile axes"
    fi
}

# 4. required_root_files — ../../02-bootstrap/project-setup.md#required-root-files' baseline list,
# plus PRIVACY.md/RUNBOOK.md when the profile declares product_shape: mobile-app (see that same
# section's mobile-specific addition).
check_required_root_files() {
    local required=(README.md LICENSE .gitignore CHANGELOG.md .editorconfig SECURITY.md)
    local product_shape
    if ! product_shape="$(yq_front_matter "$PROFILE_FILE" '.product_shape')"; then
        record_outcome required_root_files FAIL "could not read product_shape from $PROFILE_FILE — cannot determine whether the mobile-app-specific PRIVACY.md/RUNBOOK.md requirement applies"
        return
    fi
    if [ "$product_shape" = "mobile-app" ]; then
        required+=(PRIVACY.md RUNBOOK.md)
    fi
    local missing=()
    local f
    for f in "${required[@]}"; do
        if [ ! -f "$CODE_REPO_DIR/$f" ]; then
            missing+=("$f")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_outcome required_root_files PASS "all required root files present in $CODE_REPO_DIR"
    else
        record_outcome required_root_files FAIL "missing required root file(s): ${missing[*]} — see ../../02-bootstrap/project-setup.md#required-root-files"
    fi
}

# 5. agents_md_symlink — ../../02-bootstrap/project-setup.md#required-root-files: AGENTS.md is a
# plain file at the umbrella level; CLAUDE.md is either a symlink to it, or (Windows exception) a
# regular file whose first line is literally "@AGENTS.md". The import form must still confirm
# AGENTS.md itself exists — a CLAUDE.md whose first line merely looks right, with no real
# AGENTS.md backing it, does not pass.
check_agents_md_symlink() {
    local agents_file="$UMBRELLA_DIR/AGENTS.md"
    local claude_file="$UMBRELLA_DIR/CLAUDE.md"
    if [ -L "$agents_file" ] || [ ! -f "$agents_file" ]; then
        record_outcome agents_md_symlink FAIL "AGENTS.md not found, is not a regular file, or is itself a symlink (it must be the one real plain file — CLAUDE.md is what symlinks to it, never the reverse) at the umbrella level ($UMBRELLA_DIR) — see ../../02-bootstrap/project-setup.md#required-root-files"
        return
    fi
    if [ -L "$claude_file" ]; then
        local resolved
        resolved="$(cd -- "$(dirname -- "$claude_file")" && readlink "$claude_file")"
        # resolved is relative to claude_file's own directory (the umbrella dir); resolve to an
        # absolute path for a robust comparison against agents_file's own absolute path.
        local resolved_abs
        resolved_abs="$(cd -- "$UMBRELLA_DIR" && cd -- "$(dirname -- "$resolved")" 2>/dev/null && pwd)/$(basename -- "$resolved")" || resolved_abs=""
        if [ "$resolved_abs" = "$agents_file" ] || [ "$(cd -- "$UMBRELLA_DIR" && readlink -f "$claude_file" 2>/dev/null)" = "$agents_file" ]; then
            record_outcome agents_md_symlink PASS "CLAUDE.md is a symlink resolving to AGENTS.md"
        else
            record_outcome agents_md_symlink FAIL "CLAUDE.md is a symlink but does not resolve to AGENTS.md — see ../../02-bootstrap/project-setup.md#required-root-files"
        fi
        return
    fi
    if [ -f "$claude_file" ]; then
        local first_line
        first_line="$(head -n1 "$claude_file" 2>/dev/null || true)"
        if [ "$first_line" = "@AGENTS.md" ]; then
            record_outcome agents_md_symlink PASS "CLAUDE.md uses the Windows import form (@AGENTS.md) and AGENTS.md exists"
        else
            record_outcome agents_md_symlink FAIL "CLAUDE.md exists but is neither a symlink to AGENTS.md nor a file whose first line is '@AGENTS.md'"
        fi
        return
    fi
    record_outcome agents_md_symlink FAIL "CLAUDE.md not found at the umbrella level ($UMBRELLA_DIR) — see ../../02-bootstrap/project-setup.md#required-root-files"
}

# 6. commit_msg_hook — NON-WAIVABLE. ../../01-foundations/git-workflow.md#commits requires the
# shared commit-msg hook (templates/hooks/commit-msg) installed at .git/hooks/commit-msg. FAILs
# unless the installed hook's sha256 matches this repo's own templates/hooks/commit-msg AND
# there's no documented-divergence note. A documented divergence is recorded as a sibling
# .git/hooks/commit-msg.divergence-reason file (a local, gitignored-by-nature location — .git/ is
# never tracked — so a project deliberately running a modified hook records why directly next to
# it, e.g. an extra project-specific check layered on top).
check_commit_msg_hook() {
    local hook_file="$CODE_REPO_DIR/.git/hooks/commit-msg"
    local reference_file="$UMBRELLA_DIR/sw_dev_handbook/templates/hooks/commit-msg"
    if [ ! -f "$reference_file" ]; then
        record_outcome commit_msg_hook FAIL "reference hook not found at $reference_file — cannot verify"
        return
    fi
    if [ ! -f "$hook_file" ]; then
        record_outcome commit_msg_hook FAIL "no .git/hooks/commit-msg installed in $CODE_REPO_DIR — see ../../01-foundations/git-workflow.md#commits"
        return
    fi
    local reference_hash hook_hash
    reference_hash="$(sha256_of "$reference_file")"
    hook_hash="$(sha256_of "$hook_file")"
    if [ "$reference_hash" = "$hook_hash" ]; then
        record_outcome commit_msg_hook PASS "installed commit-msg hook matches templates/hooks/commit-msg"
        return
    fi
    if [ -f "${hook_file}.divergence-reason" ]; then
        record_outcome commit_msg_hook PASS "installed commit-msg hook diverges from the template but a documented divergence reason exists (${hook_file}.divergence-reason)"
        return
    fi
    record_outcome commit_msg_hook FAIL "installed .git/hooks/commit-msg does not match templates/hooks/commit-msg's known hash, and no ${hook_file}.divergence-reason note documents why — see ../../01-foundations/git-workflow.md#commits"
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# permissive_subcommand_check <dev-script> <subcommand>: shared logic for dev_subcommands (#7) and
# handbook_check_wired (#8) — both need the same "confirm presence without assuming a specific
# ./dev shape" pattern (../../02-bootstrap/project-setup.md#build-wrapper--dev names the minimum
# subcommands but never mandates a case-statement implementation). Matches, in order: a `case`
# branch pattern for the subcommand, a shell function named after it, or a task-runner delegation
# line mentioning it (e.g. "make $subcommand", "just $subcommand"). Echoes "yes", "no", or
# "unknown" — "unknown" means the pattern search couldn't positively confirm OR deny presence, and
# callers must WARN rather than FAIL in that case, never guess.
permissive_subcommand_check() {
    local dev_script="$1" subcommand="$2"
    if [ ! -f "$dev_script" ]; then
        echo "unknown"
        return
    fi
    # A `case` branch: a line consisting of (optionally several `|`-separated) bare words
    # including our subcommand, immediately followed by a `)` — e.g. "lint)" or "lint|check)".
    if grep -qE "(^|\\|)${subcommand}(\\||\\))" "$dev_script"; then
        echo "yes"
        return
    fi
    # A shell function named after the subcommand: "subcommand() {" or "function subcommand".
    if grep -qE "^[[:space:]]*(function[[:space:]]+)?${subcommand}[[:space:]]*\\(\\)" "$dev_script"; then
        echo "yes"
        return
    fi
    # A task-runner delegation line naming the subcommand as an argument to a known runner.
    if grep -qE "(make|just|task)[[:space:]]+${subcommand}([[:space:]]|\$)" "$dev_script"; then
        echo "yes"
        return
    fi
    # Could not positively confirm, but also can't rule out a shape this pattern set doesn't
    # recognize (e.g. a dispatch table, an associative array keyed by subcommand name).
    echo "unknown"
}

# 7. dev_subcommands — ../../02-bootstrap/project-setup.md#build-wrapper--dev's minimum 5
# subcommands. Permissive pattern matching, WARN (never FAIL) on an unrecognized-but-possibly-
# valid shape — only FAIL on confirmed absence is not actually reachable with this pattern set
# (permissive_subcommand_check never returns a hard "no"), so genuine absence of the ./dev script
# itself is the only true FAIL path; a present ./dev with an unrecognized shape WARNs instead of
# failing, deliberately erring toward "verify manually" over a false FAIL.
check_dev_subcommands() {
    local dev_script="$CODE_REPO_DIR/dev"
    if [ ! -f "$dev_script" ]; then
        record_outcome dev_subcommands FAIL "no ./dev script found in $CODE_REPO_DIR — see ../../02-bootstrap/project-setup.md#build-wrapper--dev"
        return
    fi
    local subcommands=(bootstrap lint test build ci)
    local unknowns=()
    local sc result
    for sc in "${subcommands[@]}"; do
        result="$(permissive_subcommand_check "$dev_script" "$sc")"
        if [ "$result" = "unknown" ]; then
            unknowns+=("$sc")
        fi
    done
    if [ "${#unknowns[@]}" -eq 0 ]; then
        record_outcome dev_subcommands PASS "all 5 minimum ./dev subcommands positively matched"
    else
        record_outcome dev_subcommands WARN "could not positively confirm ./dev subcommand(s): ${unknowns[*]} — verify manually; this pattern search doesn't cover every valid ./dev shape (see ../../02-bootstrap/project-setup.md#build-wrapper--dev)"
    fi
}

# 8. handbook_check_wired — verifies THIS checker is actually reachable via ./dev handbook-check
# once copied in, not merely present on disk (../../02-bootstrap/project-setup.md#where-a-copied-
# automation-script-lives requires wiring every copied script into ./dev). Same permissive-match-
# plus-WARN-fallback approach as dev_subcommands above.
check_handbook_check_wired() {
    local dev_script="$CODE_REPO_DIR/dev"
    if [ ! -f "$dev_script" ]; then
        record_outcome handbook_check_wired FAIL "no ./dev script found in $CODE_REPO_DIR — cannot verify handbook-check is wired in"
        return
    fi
    local result
    result="$(permissive_subcommand_check "$dev_script" "handbook-check")"
    case "$result" in
    yes)
        record_outcome handbook_check_wired PASS "./dev handbook-check appears wired in $dev_script"
        ;;
    unknown)
        record_outcome handbook_check_wired WARN "could not positively confirm a 'handbook-check' subcommand in $dev_script — verify manually that this script is actually reachable via ./dev handbook-check, not just present on disk"
        ;;
    esac
}

# 9. gitignore_baseline — ../../02-bootstrap/project-setup.md#required-root-files' minimum
# .gitignore baseline. TODO: the handbook states this baseline as prose (OS cruft, local-only
# scratch/secrets, stack-specific build output) rather than one single copy-pasteable list; this
# check uses a conservative floor covering the OS-cruft entries explicitly named there
# (.DS_Store, Thumbs.db, Desktop.ini) plus one representative stack-build-output pattern (*.log)
# as a smoke check, not an exhaustive per-stack verification — a project with a stack-specific
# .gitignore template (templates/gitignore/*.gitignore) is expected to already exceed this floor.
check_gitignore_baseline() {
    local gitignore_file="$CODE_REPO_DIR/.gitignore"
    if [ ! -f "$gitignore_file" ]; then
        record_outcome gitignore_baseline FAIL "no .gitignore found in $CODE_REPO_DIR — see ../../02-bootstrap/project-setup.md#required-root-files"
        return
    fi
    local floor=(.DS_Store Thumbs.db Desktop.ini)
    local missing=()
    local entry
    for entry in "${floor[@]}"; do
        if ! grep -qF "$entry" "$gitignore_file"; then
            missing+=("$entry")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_outcome gitignore_baseline PASS ".gitignore covers the minimum OS-cruft baseline"
    else
        record_outcome gitignore_baseline FAIL ".gitignore is missing baseline entry/entries: ${missing[*]} — see ../../02-bootstrap/project-setup.md#required-root-files, or copy a ready-made template from templates/gitignore/"
    fi
}

# 10. baseline_schema_version — compares handbook-baseline.yml's own schema_version against this
# checker's KNOWN_BASELINE_SCHEMA_VERSION. A NEWER-than-known version gets a read-only migration-
# style note ("this checker may be out of date"), not a blind FAIL — only an OLDER/unrecognized
# value that this checker predates being genuinely unsupported would be a FAIL, and since every
# version this checker has ever known about is <= KNOWN_BASELINE_SCHEMA_VERSION, "unrecognized"
# in practice only ever means "newer" or "malformed".
check_baseline_schema_version() {
    local version
    if ! version="$(yq_baseline "$BASELINE_FILE" '.schema_version')"; then
        record_outcome baseline_schema_version FAIL "could not read schema_version from $BASELINE_FILE"
        return
    fi
    if ! [[ "$version" =~ ^[0-9]+$ ]]; then
        record_outcome baseline_schema_version FAIL "schema_version in $BASELINE_FILE is not a recognizable integer: '$version'"
        return
    fi
    if [ "$version" -eq "$KNOWN_BASELINE_SCHEMA_VERSION" ]; then
        record_outcome baseline_schema_version PASS "schema_version $version matches this checker's known version"
    elif [ "$version" -gt "$KNOWN_BASELINE_SCHEMA_VERSION" ]; then
        record_outcome baseline_schema_version WARN "schema_version $version is newer than this checker's known version ($KNOWN_BASELINE_SCHEMA_VERSION) — possible schema mismatch, consider updating this checker (read-only note, not a failure)"
    else
        record_outcome baseline_schema_version FAIL "schema_version $version is not recognized by this checker (known: $KNOWN_BASELINE_SCHEMA_VERSION)"
    fi
}

# 11. stack_folder_shape — a loose, best-effort shape check only (never a correctness check) that
# the profile's declared stack has roughly the expected top-level folder present. See each stack's
# own standard-folder-structure section in ../../02-bootstrap/project-setup.md for the full shape;
# this check looks for exactly one representative marker directory per stack, deliberately not a
# full structural verification.
check_stack_folder_shape() {
    local stack marker
    if ! stack="$(yq_front_matter "$PROFILE_FILE" '.stack')"; then
        record_outcome stack_folder_shape FAIL "could not read stack from $PROFILE_FILE"
        return
    fi
    case "$stack" in
    kmp-compose-swift) marker="shared" ;;
    pure-swift) marker="" ;; # no single fixed folder name (per-<App> naming) — skip
    python) marker="src" ;;
    go) marker="internal" ;;
    php) marker="app" ;;
    other | "") marker="" ;;
    *) marker="" ;;
    esac
    if [ -z "$marker" ]; then
        record_outcome stack_folder_shape WARN "no representative marker folder defined for stack '$stack' — skipping this best-effort shape check (verify manually against ../../02-bootstrap/project-setup.md's per-stack folder structure)"
        return
    fi
    if [ -d "$CODE_REPO_DIR/$marker" ]; then
        record_outcome stack_folder_shape PASS "found expected top-level '$marker/' for stack '$stack'"
    else
        record_outcome stack_folder_shape FAIL "stack is declared '$stack' but no top-level '$marker/' folder found in $CODE_REPO_DIR — see ../../02-bootstrap/project-setup.md's per-stack folder structure (this is a shape check only, not a correctness check)"
    fi
}

# 12. mobile_only_consistency — flags-only, never resolves: profile axis 7
# (mobile_only_no_backend) contradicting axis 6 (infrastructure_repo_needed) when both are true.
check_mobile_only_consistency() {
    local mobile_only infra_needed
    if ! mobile_only="$(yq_front_matter "$PROFILE_FILE" '.mobile_only_no_backend')"; then
        record_outcome mobile_only_consistency FAIL "could not read mobile_only_no_backend from $PROFILE_FILE"
        return
    fi
    if ! infra_needed="$(yq_front_matter "$PROFILE_FILE" '.infrastructure_repo_needed')"; then
        record_outcome mobile_only_consistency FAIL "could not read infrastructure_repo_needed from $PROFILE_FILE"
        return
    fi
    if [ "$mobile_only" = "true" ] && [ "$infra_needed" = "true" ]; then
        record_outcome mobile_only_consistency FAIL "profile contradiction: mobile_only_no_backend: true AND infrastructure_repo_needed: true cannot both hold — see ../../02-bootstrap/project-setup.md#project-profile (axis 7); this check only flags the contradiction, resolving it is a human decision"
    else
        record_outcome mobile_only_consistency PASS "no contradiction between mobile_only_no_backend and infrastructure_repo_needed"
    fi
}

# 13. script_self_placement — confirms THIS script, once copied, lives where
# ../../02-bootstrap/project-setup.md#where-a-copied-automation-script-lives says it should: the
# code repo's own scripts/ folder, never <project>-int, never the umbrella level.
check_script_self_placement() {
    local resolved_self
    resolved_self="$(cd -- "$script_dir" && pwd)"
    local expected_prefix="$CODE_REPO_DIR/scripts"
    case "$resolved_self" in
    "$expected_prefix" | "$expected_prefix"/*)
        record_outcome script_self_placement PASS "this script resolves to inside $expected_prefix"
        ;;
    *)
        record_outcome script_self_placement FAIL "this script's own resolved location ($resolved_self) is not inside the code repo's scripts/ folder ($expected_prefix) — see ../../02-bootstrap/project-setup.md#where-a-copied-automation-script-lives"
        ;;
    esac
}

# 14. profile_hash_drift — WARN-only, report-only. handbook-baseline.yml's profile.source_sha256
# (see ../../templates/handbook-baseline.yml.example's own header comment) exists so this checker,
# or a human reviewing the baseline, can tell whether 00-handbook-profile.md has been edited since
# the baseline was last reconciled against it via --migrate. Editing your own profile file is a
# completely normal, expected action whenever a Project Profile axis genuinely changes — a stale
# recorded hash is not itself a policy violation the way a missing required root file is, so this
# is WARN (report-only, "you should periodically reconcile"), never FAIL. The placeholder value
# "REPLACE_ME" (never migrated even once) is treated the same as any other genuine mismatch, not as
# a special case — either way, the actionable follow-up is the same: run --migrate.
check_profile_hash_drift() {
    if [ ! -f "$PROFILE_FILE" ]; then
        record_outcome profile_hash_drift FAIL "cannot compute a drift signal — $PROFILE_FILE does not exist"
        return
    fi
    local recorded_sha256 actual_sha256
    if ! recorded_sha256="$(yq_baseline "$BASELINE_FILE" '.profile.source_sha256')"; then
        record_outcome profile_hash_drift FAIL "could not read profile.source_sha256 from $BASELINE_FILE"
        return
    fi
    actual_sha256="$(sha256_of "$PROFILE_FILE")"
    if [ "$recorded_sha256" = "$actual_sha256" ]; then
        record_outcome profile_hash_drift PASS "handbook-baseline.yml's recorded profile.source_sha256 matches $PROFILE_FILE's current content"
    else
        record_outcome profile_hash_drift WARN "handbook-baseline.yml's recorded profile.source_sha256 ($recorded_sha256) does not match $PROFILE_FILE's current content ($actual_sha256) — the profile was edited (or never migrated) since the baseline was last reconciled; run ./handbook-check.sh.example --migrate to update the recorded hash (report-only: editing the profile is normal, this is not itself a policy violation)"
    fi
}

# ===================================================================================================
# Live/read-only checks (15-19) — each independently network-guarded: a failure reaching one API
# must never abort the whole script or block any other check, local or live.
# ===================================================================================================

resolve_repo() {
    if [ -n "${HANDBOOK_CHECK_REPO:-}" ]; then
        printf '%s' "$HANDBOOK_CHECK_REPO"
        return 0
    fi
    (cd "$CODE_REPO_DIR" && gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) || true
}

# gh_api_get <path>: read-only GET wrapper, GET-only by construction (no verb parameter exists to
# accidentally pass something else) — sets GH_API_STATUS/GH_API_BODY exactly like
# github-security-settings.sh.example's own gh_api_status(), same two-globals-not-a-return-value
# reasoning (see that script's header comment) and same bash-3.2-compatible design (no namerefs).
GH_API_STATUS=""
GH_API_BODY=""
gh_api_get() {
    local path="$1" out status body
    out="$(gh api "$path" -i 2>&1)" || true
    status="$(printf '%s\n' "$out" | awk '/^HTTP\// { print $2; exit }')"
    if [ -z "$status" ]; then
        GH_API_STATUS="ERR"
        GH_API_BODY="${out//$'\n'/ }"
        return 0
    fi
    body="$(printf '%s\n' "$out" | awk 'body{print} /^\r?$/{body=1}')"
    GH_API_STATUS="$status"
    GH_API_BODY="$body"
}

# 15. github_issues_vs_tracker — NON-WAIVABLE. ../../05-tooling/openproject.md#openproject-as-the-
# system-of-record requires OpenProject as the sole tracker; GitHub Issues enabled is only
# excepted for a project with real external users/contributors (the profile's own axes 3/3b are
# the "documented exception" this check looks for).
check_github_issues_vs_tracker() {
    if ! command -v gh >/dev/null 2>&1; then
        record_outcome github_issues_vs_tracker FAIL "gh CLI not found — cannot check GitHub Issues status (a local environment problem, not a network failure — see ../../05-tooling/openproject.md#openproject-as-the-system-of-record)"
        return
    fi
    local repo
    repo="$(resolve_repo)"
    if [ -z "$repo" ]; then
        record_outcome github_issues_vs_tracker FAIL "could not resolve owner/repo for $CODE_REPO_DIR — cannot check GitHub Issues status (a local git-config/repo-identity problem, not a network failure — see ../../05-tooling/openproject.md#openproject-as-the-system-of-record)"
        return
    fi
    gh_api_get "repos/$repo"
    case "$GH_API_STATUS" in
    2??)
        local has_issues
        if ! has_issues="$(printf '%s' "$GH_API_BODY" | jq -r 'if (.has_issues|type)=="boolean" then .has_issues else error("has_issues not boolean") end' 2>&1)"; then
            record_outcome github_issues_vs_tracker FAIL "could not determine has_issues for $repo (unexpected response shape — the API call itself succeeded, so this is a data problem, not a network failure)"
            return
        fi
        if [ "$has_issues" != "true" ]; then
            record_outcome github_issues_vs_tracker PASS "GitHub Issues is disabled on $repo"
            return
        fi
        local real_users real_contributors
        real_users="$(yq_front_matter "$PROFILE_FILE" '.real_external_users' 2>/dev/null || echo "")"
        real_contributors="$(yq_front_matter "$PROFILE_FILE" '.real_external_contributors' 2>/dev/null || echo "")"
        if [ "$real_users" = "true" ] || [ "$real_contributors" = "true" ]; then
            record_outcome github_issues_vs_tracker PASS "GitHub Issues is enabled on $repo, but the profile documents real external users/contributors (the documented exception) — see ../../05-tooling/openproject.md#openproject-as-the-system-of-record"
        else
            record_outcome github_issues_vs_tracker FAIL "GitHub Issues is enabled on $repo with no documented exception (profile shows no real external users/contributors) — see ../../05-tooling/openproject.md#openproject-as-the-system-of-record"
        fi
        ;;
    404)
        # A 404 proves the API was actually reached — this is not a transport failure, it means
        # $repo (resolved above) doesn't exist or isn't accessible with the current credentials, a
        # real, actionable local-identity problem, not a network blip.
        record_outcome github_issues_vs_tracker FAIL "GitHub API returned 404 for $repo — the resolved repo doesn't exist or isn't accessible (check gh auth / the repo's actual owner/name)"
        ;;
    *)
        record_outcome github_issues_vs_tracker INDETERMINATE "could not reach the GitHub API for $repo (status: $GH_API_STATUS)"
        ;;
    esac
}

# 16. branch_protection — WARN-only, purely informational, same raw-inventory-not-confirmation
# framing as github-security-settings.sh.example's own Rulesets check.
check_branch_protection() {
    if ! command -v gh >/dev/null 2>&1; then
        record_outcome branch_protection WARN "gh CLI not found — cannot report branch protection/Ruleset status"
        return
    fi
    local repo
    repo="$(resolve_repo)"
    if [ -z "$repo" ]; then
        record_outcome branch_protection WARN "could not resolve owner/repo — cannot report branch protection/Ruleset status"
        return
    fi
    gh_api_get "repos/$repo/rulesets"
    case "$GH_API_STATUS" in
    2??)
        local count
        count="$(printf '%s' "$GH_API_BODY" | jq -r 'if type=="array" then length else empty end' 2>/dev/null || true)"
        if [ -n "$count" ]; then
            record_outcome branch_protection WARN "$repo has $count Ruleset(s) configured (informational only — not a verification that main is protected; see ../../05-tooling/github.md#branch-protection)"
        else
            record_outcome branch_protection WARN "could not parse Rulesets response for $repo"
        fi
        ;;
    404)
        record_outcome branch_protection WARN "Rulesets endpoint returned 404 for $repo — could not determine branch protection status"
        ;;
    403)
        record_outcome branch_protection WARN "Rulesets not available for $repo — insufficient permissions, organization policy, or a plan-tier limitation"
        ;;
    *)
        record_outcome branch_protection WARN "could not determine branch protection status for $repo (status: $GH_API_STATUS)"
        ;;
    esac
}

# 17. dependabot_readonly — waivable FAIL if disabled (github.md:71 requires both Dependabot
# alerts and security updates enabled unconditionally). READS ONLY — this check never calls the
# enabling PUT itself (unlike github-security-settings.sh.example, which is the separate ENFORCER
# tool this check points at on finding either disabled).
check_dependabot_readonly() {
    if ! command -v gh >/dev/null 2>&1; then
        record_outcome dependabot_readonly FAIL "gh CLI not found — cannot check Dependabot status (a local environment problem, not a network failure)"
        return
    fi
    local repo
    repo="$(resolve_repo)"
    if [ -z "$repo" ]; then
        record_outcome dependabot_readonly FAIL "could not resolve owner/repo — cannot check Dependabot status (a local git-config/repo-identity problem, not a network failure)"
        return
    fi
    gh_api_get "repos/$repo/vulnerability-alerts"
    local va_status="$GH_API_STATUS"
    local va_enabled=0
    case "$va_status" in
    2??) va_enabled=1 ;;
    404) va_enabled=0 ;;
    *)
        record_outcome dependabot_readonly INDETERMINATE "could not determine Dependabot alerts status for $repo (status: $va_status)"
        return
        ;;
    esac
    gh_api_get "repos/$repo/automated-security-fixes"
    local asf_status="$GH_API_STATUS"
    local asf_enabled=0
    case "$asf_status" in
    2??) asf_enabled=1 ;;
    404) asf_enabled=0 ;;
    *)
        record_outcome dependabot_readonly INDETERMINATE "could not determine Dependabot security updates status for $repo (status: $asf_status)"
        return
        ;;
    esac
    if [ "$va_enabled" -eq 1 ] && [ "$asf_enabled" -eq 1 ]; then
        record_outcome dependabot_readonly PASS "Dependabot alerts and security updates are both enabled on $repo"
    else
        record_outcome dependabot_readonly FAIL "Dependabot alerts and/or security updates disabled on $repo (alerts enabled=$va_enabled, security updates enabled=$asf_enabled) — see ../../05-tooling/github.md#secret-scanning; run templates/scripts/github-security-settings.sh.example against this repo to enable them (this check is read-only and never enables anything itself)"
    fi
}

# 18. openproject_project_exists — SKIPPED with no OPENPROJECT_API_TOKEN credential (naming
# convention confirmed against templates/mcp/config.toml.example). FAIL (waivable) if a credential
# is present, the API reachable, but the declared tracker.project_identifier isn't a real project.
# INDETERMINATE (distinct from "reachable but not found") if the API itself is unreachable.
check_openproject_project_exists() {
    if [ -z "${OPENPROJECT_API_TOKEN:-}" ]; then
        record_outcome openproject_project_exists SKIPPED "no OPENPROJECT_API_TOKEN credential in the environment — see templates/mcp/config.toml.example for this variable's naming convention"
        return
    fi
    if [ -z "${OPENPROJECT_BASE_URL:-}" ]; then
        record_outcome openproject_project_exists FAIL "OPENPROJECT_API_TOKEN is set but OPENPROJECT_BASE_URL is not — cannot reach the API"
        return
    fi
    if ! command -v curl >/dev/null 2>&1; then
        record_outcome openproject_project_exists FAIL "curl not found — cannot reach the OpenProject API"
        return
    fi
    local identifier
    if ! identifier="$(yq_baseline "$BASELINE_FILE" '.tracker.project_identifier')"; then
        record_outcome openproject_project_exists FAIL "could not read tracker.project_identifier from $BASELINE_FILE"
        return
    fi
    if [ -z "$identifier" ] || [ "$identifier" = "REPLACE_ME" ]; then
        record_outcome openproject_project_exists FAIL "tracker.project_identifier in $BASELINE_FILE is unset/still the placeholder"
        return
    fi
    local http_code
    http_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
        -H "Authorization: Bearer $OPENPROJECT_API_TOKEN" \
        "${OPENPROJECT_BASE_URL%/}/api/v3/projects/$identifier" 2>/dev/null || echo "000")"
    case "$http_code" in
    200)
        record_outcome openproject_project_exists PASS "OpenProject project '$identifier' found"
        ;;
    404)
        record_outcome openproject_project_exists FAIL "OpenProject project '$identifier' (from $BASELINE_FILE's tracker.project_identifier) was not found via the API — see ../../05-tooling/openproject.md"
        ;;
    000)
        record_outcome openproject_project_exists INDETERMINATE "could not reach the OpenProject API at $OPENPROJECT_BASE_URL (network/timeout failure)"
        ;;
    *)
        record_outcome openproject_project_exists INDETERMINATE "unexpected OpenProject API response (HTTP $http_code) for project '$identifier'"
        ;;
    esac
}

# 19. latest_release_vs_pinned — WARN-only, reports "N releases behind" if applicable, never
# fails.
check_latest_release_vs_pinned() {
    if ! command -v gh >/dev/null 2>&1; then
        record_outcome latest_release_vs_pinned WARN "gh CLI not found — cannot compare against the latest sw_dev_handbook release"
        return
    fi
    local pinned
    pinned="$(yq_baseline "$BASELINE_FILE" '.handbook.pinned_tag' 2>/dev/null || true)"
    local latest
    if ! latest="$( (cd "$UMBRELLA_DIR/sw_dev_handbook" && gh release view --json tagName -q .tagName) 2>&1)"; then
        record_outcome latest_release_vs_pinned WARN "could not determine the latest sw_dev_handbook release — network/auth failure, or no releases exist yet"
        return
    fi
    if [ "$pinned" = "$latest" ]; then
        record_outcome latest_release_vs_pinned WARN "pinned tag ($pinned) is the latest release"
    else
        record_outcome latest_release_vs_pinned WARN "pinned tag ($pinned) is behind the latest release ($latest) — see ../../02-bootstrap/project-setup.md#repo-topology for the update procedure"
    fi
}

# ===================================================================================================
# print_not_checkable_notice — called unconditionally, every run, regardless of pass/fail.
# ===================================================================================================
print_not_checkable_notice() {
    cat <<'EOF'

--- Not automatically checkable ---
This script cannot verify:
  - Whether a declared Project Profile axis is actually true in the real world (only internal
    consistency between axes, and between axes and the filesystem, is checked).
  - Whether <project>-int's actual content is good (presence-only checked).
  - Whether a documented exception's stated reason in handbook-baseline.yml's exceptions[] is
    still valid (only that the entry exists and names a waivable check).
  - Whether CI is green on the latest commit.
  - Substantive conformance to any named ISO/compliance framework (a governance companion repo's
    mere presence is checked, never its content).
  - Whether architecture-principles.md#architecture-maturity-tiers's acceptance criteria are
    satisfied for any specific real decision this project has made.
EOF
}

# ===================================================================================================
# Waivers: apply handbook-baseline.yml's exceptions[] to FAIL outcomes, rejecting any entry that
# names a NON_WAIVABLE_CHECKS id, and never touching WARN/INDETERMINATE/SKIPPED outcomes at all.
# ===================================================================================================
apply_waivers() {
    local ids
    ids="$(yq_baseline "$BASELINE_FILE" '.exceptions[].waivable_for' 2>/dev/null || true)"
    if [ -z "$ids" ]; then
        return
    fi
    local id non_waivable_id is_non_waivable
    while IFS= read -r id; do
        [ -z "$id" ] && continue
        is_non_waivable=0
        for non_waivable_id in "${NON_WAIVABLE_CHECKS[@]}"; do
            if [ "$id" = "$non_waivable_id" ]; then
                is_non_waivable=1
                break
            fi
        done
        if [ "$is_non_waivable" -eq 1 ]; then
            echo "ERROR: handbook-baseline.yml's exceptions[] names '$id', which is in the fixed NON_WAIVABLE_CHECKS list (int_present, commit_msg_hook, github_issues_vs_tracker) and can never be waived — this exception entry is itself invalid and is ignored" >&2
            fail=1
            continue
        fi
        if [ "$(get_outcome "$id")" = "FAIL" ]; then
            echo "WAIVED [$id]: FAIL outcome waived per handbook-baseline.yml's exceptions[] ($(get_message "$id"))"
            set_outcome "$id" WAIVED
        fi
    done <<<"$ids"
}

# ===================================================================================================
# Run every check. Each is already internally network-guarded (live checks 15-19 never let a
# transport failure propagate as an unhandled error) — but every check is additionally wrapped
# here so a genuinely unexpected error inside any single check function can never abort the whole
# run and silently skip every check after it. The fallback outcome for this rare, defensive
# catch-all path is kind-aware (via LIVE_CHECK_IDS above): INDETERMINATE for one of the 5 live
# checks (consistent with INDETERMINATE meaning "could not complete due to something outside this
# script's control"), FAIL for every local/offline check (consistent with this file's own
# established "local problem = FAIL" rule — an unhandled crash in a local check is at least as bad
# as that check's normal, deterministic FAIL path).
# ===================================================================================================
run_check() {
    local fn="$1"
    if ! "$fn"; then
        local id="${fn#check_}"
        local is_live=0 live_id
        for live_id in "${LIVE_CHECK_IDS[@]}"; do
            if [ "$id" = "$live_id" ]; then
                is_live=1
                break
            fi
        done
        if [ "$is_live" -eq 1 ]; then
            record_outcome "$id" INDETERMINATE "check function $fn exited unexpectedly — treated as indeterminate rather than aborting the run"
        else
            record_outcome "$id" FAIL "check function $fn exited unexpectedly — treated as a failure (not indeterminate) rather than aborting the run, since this is a local/offline check"
        fi
    fi
}

echo "handbook-check: umbrella=$UMBRELLA_DIR project=$PROJECT_NAME"
echo "handbook-check: code repo=$CODE_REPO_DIR"
echo "handbook-check: profile=$PROFILE_FILE"
echo "handbook-check: baseline=$BASELINE_FILE"
echo

for fn in check_tag_pin check_int_present check_infra_governance_vs_profile \
    check_required_root_files check_agents_md_symlink check_commit_msg_hook \
    check_dev_subcommands check_handbook_check_wired check_gitignore_baseline \
    check_baseline_schema_version check_stack_folder_shape check_mobile_only_consistency \
    check_script_self_placement check_profile_hash_drift check_github_issues_vs_tracker \
    check_branch_protection check_dependabot_readonly check_openproject_project_exists \
    check_latest_release_vs_pinned; do
    run_check "$fn"
done

apply_waivers

print_not_checkable_notice

# --- --migrate: update handbook-baseline.yml in place for self-derivable fields only -------------
if [ "$migrate" -eq 1 ]; then
    if [ -f "$PROFILE_FILE" ]; then
        new_hash="$(sha256_of "$PROFILE_FILE")"
        yq -i ".profile.source_sha256 = \"$new_hash\"" "$BASELINE_FILE"
        echo
        echo "handbook-check: --migrate updated profile.source_sha256 in $BASELINE_FILE"
    fi
fi

# --- Final tally ------------------------------------------------------------------------------
# FAIL (unwaived) and INDETERMINATE both contribute to a nonzero exit; WARN, SKIPPED, WAIVED, and
# PASS never do — see the header comment's severity contract for the full two-independent-rules
# reasoning behind INDETERMINATE never being waivable even where that check's own FAIL is.
echo
for id in "${CHECK_IDS[@]}"; do
    case "$(get_outcome "$id")" in
    FAIL | INDETERMINATE) fail=1 ;;
    esac
done

if [ "$fail" -ne 0 ]; then
    echo "handbook-check: one or more checks failed or could not be determined" >&2
    exit 1
fi

echo "handbook-check: done"
