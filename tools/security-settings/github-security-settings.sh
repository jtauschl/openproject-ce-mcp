#!/usr/bin/env bash
set -euo pipefail

# Enforces/reports on a target GitHub repo's security settings via the `gh` CLI — see
# ../../05-tooling/github.md#secret-scanning (Dependabot alerts/security updates),
# ../../05-tooling/github.md#branch-protection (Rulesets), and
# ../../05-tooling/github.md#supply-chain-hardening (Dependency Review) for the policy each
# check below enforces or reports on.
#
# Dependabot alerts and Dependabot security updates are tier-independent (available on
# every plan) and are actually SET here if not already enabled — this script is an enforcer for
# those two, not just an auditor, and a failure to apply either one sets the script's final
# non-zero exit code. Private vulnerability reporting (public repos only — see its own section
# below) is ALSO actually set here if not already enabled, tier-independent the same way, but a
# failure to apply it is reported to stderr WITHOUT affecting the exit code — it is best-effort
# enforcement, not a hard gate like the two Dependabot checks. Every remaining check (secret
# scanning status, Rulesets/branch protection, Dependency Review product availability,
# .github/dependabot.yml presence) is purely report-only: either the setting is tier-gated or
# visibility-gated with nothing meaningful to "set" without knowing the org's plan or the repo's
# visibility, or (for dependabot.yml) not a settable API flag at all. A tier-gated check that
# gets a 403 back reports it as an OPEN set of possible causes — plan tier, insufficient
# permissions, or organization policy — not a single confident "not available on this plan" claim:
# GitHub's own REST references don't document 403 as a reliable plan-tier-only signal for either
# the Rulesets or the Dependency Review endpoint specifically (confirmed live against this repo's
# own Rulesets check, which currently 403s despite the authenticating token holding full `repo`
# scope — an ambiguous case a confident plan-tier claim would have mislabeled). See the plan-tier
# gaps already documented in github.md#branch-protection and #secret-scanning for the parts of
# that open set which genuinely are plan-tier-driven.
# A 403 on the two hard-gated, exit-code-affecting checks (Dependabot alerts, security updates)
# is reported differently still — see those two checks below — since those are available on
# every plan and a 403 there cannot mean "not on this plan" at all, not even as one of several
# possibilities. Private vulnerability reporting is also tier-independent, but its own 403
# handling (see its section below) reports "insufficient permissions or organization policy"
# without setting the script's exit code, matching its best-effort (not hard-gated) enforcement.
#
# Every status-determining `gh api` GET below goes through gh_api_status() (see its own comment),
# which distinguishes four outcomes for any endpoint: 2xx (success), 404 (a specific, per-endpoint
# meaning documented at each call site — sometimes "disabled", sometimes "not found"; never
# assumed generically), 403 (per-endpoint wording — an open set of causes for a tier-gated check,
# a specific permissions/org-policy message for a tier-independent one; never a single confident
# claim where the real cause is ambiguous), and
# anything else — another HTTP status, or a transport failure such as a DNS/network error or an
# auth token that expired mid-run — reported distinctly as "could not determine: <detail>", never
# silently folded into the 404 or 403 meaning. The enable PUTs (`gh api -X PUT ...`) are the one
# deliberate exception: they only ever run right after a GET already routed through
# gh_api_status() has determined the setting is disabled, so there's nothing to branch on beyond
# plain success/failure — they're called directly rather than through the four-way dispatch above.
# Report-only checks NEVER make a second, unguarded `gh api` network call to re-fetch data as
# JSON: gh_api_status() already captured the full response body on the same call that determined
# the status, and every call site below reuses that already-captured body (via a local `jq`
# filter) to pull out structured fields once its 2xx branch is reached, instead of re-fetching it.
# This matters under `set -euo pipefail`: an unguarded second `gh api` call can fail on a
# transient blip and abort the whole script, even for a check that's explicitly documented as
# report-only/never-hard-fail, and it opens a TOCTOU gap where the first call's 2xx result and the
# second call's data are no longer guaranteed to describe the same instant.
#
# `jq` extractions of a captured body are similarly guarded against aborting the script under
# `set -euo pipefail`: jq's own exit-code behavior is subtle (plain `.field` on missing-key JSON
# exits 0 and prints "null"; an empty body also exits 0 with no output; only malformed JSON exits
# non-zero) — see each extraction site below for the specific guard used and why. A guarded
# extraction never lets `set -euo pipefail` abort the script mid-run on a jq parse/type error —
# that failure mode is what every guard exists to eliminate — but a guard failure's DOWNSTREAM
# consequence still depends on which check it feeds: the Dependabot security updates extraction is
# the one exception to "report-only, never fails the run" — that check is tier-independent and
# enforced (see below), so a guard failure there deliberately sets fail=1 and contributes to the
# script's final exit 1, the same enforced-check contract as vulnerability-alerts. Every OTHER
# guarded extraction is genuinely report-only and never affects the exit code, including
# default_branch: it feeds exactly one downstream check (the Dependency Review SHA lookup), so a
# failure there is scoped to that one check reporting "could not determine" rather than treated as
# fatal to everything below it — the other report-only checks need nothing but repo_body, already
# captured once at the top, and must not be blocked by
# a field they never read.
#
# Known gaps:
# - Dependency Review's product-level availability IS checked here (via a trivial, no-diff
#   dependency-graph/compare call against the repo's own default-branch commit SHA), but whether
#   it's wired up as a *required, blocking* PR status check is a branch-protection/ruleset-level
#   fact, not a dependency-graph fact, and genuinely cannot be determined via this endpoint —
#   confirming that requires looking for three concrete things instead: (a) a Dependency Review
#   workflow file under .github/workflows/, (b) that workflow using
#   actions/dependency-review-action, and (c) that workflow's job registered as a required status
#   check in an active branch ruleset or classic branch protection rule (cross-reference the
#   Rulesets check's own output above it — see ../../05-tooling/github.md#supply-chain-hardening).
# - `.github/dependabot.yml`'s presence is checked, but not its contents — this script doesn't
#   generate or validate that file's shape.
# - The repo API's `security_and_analysis.secret_scanning.status` field is only present when the
#   repo is public, or private with GitHub Secret Protection available on the org's plan — on a
#   private repo without it, the field is silently absent (not `false`, just missing) even for an
#   authenticated repo admin; this script cannot distinguish "not on this plan" from "some other
#   reason it's missing" and reports both the same way.
# - Rulesets are reported as a raw inventory (name/target/enforcement/source per ruleset), NOT a
#   verified "main is protected" claim — this script does not parse ruleset rule bodies, so a tag
#   ruleset, a push ruleset, or one with enforcement "disabled"/"evaluate" is listed exactly like
#   an actually-enforcing branch ruleset protecting main; read the printed fields yourself.
# - Dependabot security updates' `paused` state is reported, but GitHub's REST API documents no
#   endpoint to un-pause it (only the initial enable PUT) — the paused case cannot be
#   auto-remediated the way the disabled case can (there is no PUT this script can issue to fix
#   it), so it is reported as an unresolved failure (fail=1, contributing to the script's final
#   exit 1) rather than silently treated as success, even though no corrective action was taken.
# - A single offline test (scripts/tests/test_github_security_settings.sh) table-tests this
#   script's HTTP-status-driven branching against a fake `gh` shadowing PATH with canned
#   status/body pairs — it does not, and cannot, verify the real GitHub REST API's actual
#   contract; that part is confirmed by live manual runs, not by any automated test.
#
# Usage: ./github-security-settings.sh [owner/repo]
#   e.g. ./github-security-settings.sh
#        ./github-security-settings.sh octocat/Hello-World
#   With no argument, targets the currently checked-out repo's own GitHub remote.

# SW_DEV_HANDBOOK_DOC_REF: set this to the sw_dev_handbook tag YOUR project is actually pinned to (see
# `git -C sw_dev_handbook describe --tags --exact-match` from the umbrella directory, or
# `sw_dev_handbook/CHANGELOG.md`'s latest released version) before relying on the doc links this
# script prints below — either edit the fallback value below directly when copying this template,
# or export SW_DEV_HANDBOOK_DOC_REF in the environment before running it (the `${VAR:-default}` form
# below means an already-exported value always wins over the fallback, unlike a plain `VAR=...`
# assignment, which would silently discard an inherited env var of the same name).
#
# The fallback is a DELIBERATELY INVALID placeholder, not `main` or any other value that would
# silently "work": sw_dev_handbook's own README documents that every consuming project pins to an
# explicit release tag, not a moving branch, specifically so a link resolved at one point in time
# can't silently describe a different policy version than the one actually governing that
# project — a blob URL defaulting to `main` (or any other real ref) would defeat that guarantee
# by working, just wrongly, for anyone who forgot to re-pin it after copying this template. An
# invalid placeholder instead makes every resulting doc link 404 loudly until it's actually set,
# which is far easier to notice than a link that resolves to the wrong policy version silently.
SW_DEV_HANDBOOK_DOC_REF="${SW_DEV_HANDBOOK_DOC_REF:-v0.8.0}"

if ! command -v gh >/dev/null 2>&1; then
    echo "github-security-settings: gh CLI not found — https://cli.github.com" >&2
    exit 1
fi

# jq is a hard runtime dependency (every structured-field extraction in this script goes through
# it) but, unlike gh, macOS does not ship it by default — check for it explicitly up front with a
# clear message, rather than letting a missing jq surface later as a misleading "could not
# determine default branch" failure indistinguishable from a real API/data problem.
if ! command -v jq >/dev/null 2>&1; then
    echo "github-security-settings: jq not found — https://jqlang.org/download/" >&2
    exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "github-security-settings: gh CLI not authenticated — run 'gh auth login'" >&2
    exit 1
fi

if [ -n "${1:-}" ]; then
    repo="$1"
else
    if ! repo_root="$(git rev-parse --show-toplevel 2>&1)"; then
        echo "github-security-settings: not inside a git repository (pass owner/repo explicitly instead): $repo_root" >&2
        exit 1
    fi
    cd "$repo_root"
    if ! repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>&1)"; then
        echo "github-security-settings: could not resolve owner/repo from the current checkout: $repo" >&2
        exit 1
    fi
fi

# Runs `gh api <path> [extra gh-api args...]` and sets two globals: GH_API_STATUS and
# GH_API_BODY. Callers must read those two globals IMMEDIATELY after calling this function and
# before calling it again (it is not reentrant/stack-safe) — every call site below does so.
#
# A single space-joined "<status> <body>" return string was deliberately NOT used here: a real
# JSON response body is multi-line and can itself contain characters that make substring-splitting
# (e.g. "${line%% *}" / "${line#* }") fragile to reason about correctly, so status and body are
# instead carried back via two separate global variables, avoiding any encoding/decoding of the
# body at all. (Bash namerefs, i.e. `local -n`, would be another way to do this without globals,
# but are bash-4.3+ only — this script targets bash 3.2, the version macOS ships, so plain globals
# are used instead.)
#
# GH_API_STATUS is one of:
#   - a bare 3-digit HTTP status code (e.g. "204", "404", "403", "500") whenever a real HTTP
#     response came back, however unsuccessful. `gh api ... -i` (include headers) does NOT turn a
#     4xx/5xx response into a clean exit — it still exits non-zero on an HTTP error response,
#     verified live — so parsing the response's own `HTTP/<version> <code> <text>` status line is
#     what actually recovers the real code, not the exit status.
#   - the literal "ERR" when `gh` itself exited non-zero with NO parseable HTTP status line at all.
#     This only happens for a transport-level failure (DNS/network error, TLS failure, an auth
#     token that expired mid-run) — never for a normal HTTP error response — and is exactly the
#     case each call site below reports as "could not determine", instead of misreading it as a
#     403 or a 404. GH_API_BODY holds the raw combined stdout+stderr in this case, for the error
#     message only — it is not JSON and must never be passed to jq.
#
# GH_API_BODY is everything after the blank line `gh api -i` prints between the response headers
# and the response body (a real JSON body on any 2xx response with one). A caller needing
# structured fields out of a successful body filters GH_API_BODY locally via `jq` once
# GH_API_STATUS has already confirmed a 2xx — it never makes a second, unguarded `gh api` network
# call to re-fetch the same data (see the file header comment for why that matters).
GH_API_STATUS=""
GH_API_BODY=""
gh_api_status() {
    local path="$1" out status body
    shift
    out="$(gh api "$path" -i "$@" 2>&1)" || true
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

# Confirm the repo actually exists and is reachable before running any per-setting check below —
# without this, a nonexistent/inaccessible repo makes every later check fail in a way that could
# otherwise be misread as a genuine tier-gated 403/404, instead of a wrong repo name or a missing
# permission.
gh_api_status "repos/$repo"
repo_status="$GH_API_STATUS"
repo_body="$GH_API_BODY"
case "$repo_status" in
2??)
    # A genuinely empty body on an otherwise-2xx response is its own anomaly, handled once here
    # before either extraction below: `jq` run against truly empty stdin exits 0 with NO output
    # for ANY filter (confirmed live) — including a `type == "..."` guard filter that would
    # otherwise reliably catch a wrong-shaped-but-present value, since the filter never even runs
    # once against zero input documents. Without this upfront check, both extractions below would
    # silently "succeed" with an empty result on this specific anomaly, skipping their own
    # guard-failure warning entirely — caught by testing this exact scenario live.
    if [ -z "$repo_body" ]; then
        echo "github-security-settings: repo lookup for $repo returned an empty body despite a 2xx status" >&2
        repo_body_ok=0
    else
        repo_body_ok=1
    fi
    # default_branch is used by exactly one downstream check: the Dependency Review SHA lookup
    # (see there). Every other check in this script — both tier-independent enforcers, dependabot.
    # yml presence, secret scanning, Rulesets — needs nothing but repo_body, already captured
    # above, so a failure to determine the default branch must NOT be script-wide fatal; it would
    # needlessly block the two enforced checks (Dependabot alerts, security updates) on a
    # field they never even read. Guarded with plain `jq -r` (NOT `-er`): on failure, fall back to
    # an empty default_branch and let the Dependency Review section report "could not determine"
    # and skip its own probe — the same report-only-with-a-clear-reason pattern already used
    # everywhere else in this script, rather than treating this one field as an exception.
    default_branch=""
    if [ "$repo_body_ok" -eq 1 ]; then
        if ! default_branch="$(printf '%s' "$repo_body" | jq -r 'if (.default_branch | type) == "string" then .default_branch else error("default_branch field is not a string: \(.default_branch | tostring)") end' 2>&1)"; then
            echo "github-security-settings: could not determine default branch for $repo: $default_branch — Dependency Review will be reported as unavailable" >&2
            default_branch=""
        fi
    else
        echo "github-security-settings: could not determine default branch for $repo: repo body was empty — Dependency Review will be reported as unavailable" >&2
    fi
    # repo_is_fork feeds the Dependency Review 403 wording below (a 403 there can mean either a
    # plan-tier gap OR that the repo is a fork — GitHub restricts Dependency Review on forks
    # regardless of plan). Extracted once here, reusing repo_body already fetched above — no new
    # API call. Guarded with plain `jq -r` (NOT `-e`) PLUS an explicit type check inside the
    # filter itself: `-e` alone would exit 1 on a legitimate `false` value (misfiring on the
    # common, non-error case of "not a fork"), but a bare `.fork` without a type check would
    # silently succeed with the string "null" on a MISSING field too (jq's plain-field-access
    # behavior — confirmed live), which would then wrongly compare `= "true"` as false and treat
    # a genuinely-unknown fork status as "definitely not a fork" without ever surfacing a warning.
    # The `if (.fork|type) == "boolean" then .fork else error(...) end` filter makes a missing or
    # non-boolean field raise a real jq error (caught by the guard) while every legitimate
    # true/false value still exits 0 — confirmed live for all three cases. On guard failure, fall
    # back to the SAFER default of proceeding as if not a fork, i.e. keep the existing plan-tier
    # wording rather than asserting a fork-specific claim we couldn't actually confirm.
    repo_is_fork="false"
    if [ "$repo_body_ok" -eq 1 ]; then
        if ! repo_is_fork="$(printf '%s' "$repo_body" | jq -r 'if (.fork | type) == "boolean" then .fork else error("fork field is not boolean: \(.fork | tostring)") end' 2>&1)"; then
            echo "github-security-settings: could not determine fork status for $repo: $repo_is_fork — assuming not a fork" >&2
            repo_is_fork="false"
        fi
    else
        echo "github-security-settings: could not determine fork status for $repo: repo body was empty — assuming not a fork" >&2
    fi
    # repo_is_private feeds the private-vulnerability-reporting check below (that GitHub feature
    # is documented as public-repository-only — confirmed live and against GitHub's own product
    # docs — so attempting to enable it on a private repo isn't "might fail", it's structurally
    # impossible; checking first avoids a guaranteed-404 PUT and reports the real reason instead
    # of a generic "not available"). Extracted once here, reusing repo_body already fetched above
    # — no new API call. Same guarded-type-check pattern as repo_is_fork immediately above: `-e`
    # alone would exit 1 on a legitimate `false` (misfiring on the common "already public" case),
    # a bare `.private` without a type check would silently succeed with "null" on a missing
    # field. On guard failure, fall back to the SAFER default of proceeding as if PRIVATE (skips
    # the doomed-to-404 attempt rather than risking a wasted/confusing call when visibility
    # genuinely couldn't be confirmed).
    repo_is_private="true"
    if [ "$repo_body_ok" -eq 1 ]; then
        if ! repo_is_private="$(printf '%s' "$repo_body" | jq -r 'if (.private | type) == "boolean" then .private else error("private field is not boolean: \(.private | tostring)") end' 2>&1)"; then
            echo "github-security-settings: could not determine visibility for $repo: $repo_is_private — assuming private (skipping private vulnerability reporting check)" >&2
            repo_is_private="true"
        fi
    else
        echo "github-security-settings: could not determine visibility for $repo: repo body was empty — assuming private (skipping private vulnerability reporting check)" >&2
    fi
    ;;
404)
    echo "github-security-settings: repo not found: $repo" >&2
    exit 1
    ;;
403)
    echo "github-security-settings: access forbidden for $repo (insufficient permissions?)" >&2
    exit 1
    ;;
*)
    echo "github-security-settings: could not determine reachability of $repo: $repo_body" >&2
    exit 1
    ;;
esac

fail=0

echo "github-security-settings: checking $repo"

# --- Dependabot alerts (vulnerability-alerts) — tier-independent, enforced -------------------
# GET returns 204 (enabled) or 404 (disabled — the normal "off" state, not an error), no JSON
# body either way.
gh_api_status "repos/$repo/vulnerability-alerts"
va_status="$GH_API_STATUS"
va_detail="$GH_API_BODY"
va_ok=0
case "$va_status" in
2??)
    echo "Dependabot alerts: already enabled"
    va_ok=1
    ;;
404)
    if put_out="$(gh api -X PUT "repos/$repo/vulnerability-alerts" 2>&1)"; then
        echo "Dependabot alerts: was disabled, enabled it now"
        va_ok=1
    else
        echo "Dependabot alerts: failed to enable (repo admin rights required): $put_out" >&2
        fail=1
    fi
    ;;
403)
    # This setting is available on every GitHub plan tier (see the file header comment), so a 403
    # here cannot mean "not on this plan" — it means insufficient permissions or an org policy
    # block, unlike the genuinely tier-gated or visibility-gated checks below (secret scanning,
    # Rulesets, Dependency Review, private vulnerability reporting), which legitimately can 403/404
    # for plan-tier or visibility reasons.
    echo "Dependabot alerts: insufficient permissions, or blocked by organization policy (this setting is available on every GitHub plan tier, so a 403 here is not a plan-tier gap)" >&2
    fail=1
    ;;
*)
    echo "Dependabot alerts: could not determine current state: $va_detail" >&2
    fail=1
    ;;
esac

# --- Dependabot security updates (automated-security-fixes) — tier-independent, enforced
# GET returns 200 with {"enabled":true/false,"paused":true/false} once vulnerability-alerts is
# enabled. Just like vulnerability-alerts above, GitHub returns 404 on THIS endpoint's own GET
# when THIS setting itself is off — not when vulnerability-alerts is off. There is no
# cross-dependency where one endpoint's 404 reflects the other setting's state; the check above
# guarantees vulnerability-alerts is enabled by this point (unless enabling it just failed, in
# which case this check is skipped entirely — va_ok stays 0 — rather than making a call whose
# result would be ambiguous).
if [ "$va_ok" -eq 1 ]; then
    gh_api_status "repos/$repo/automated-security-fixes"
    asf_status="$GH_API_STATUS"
    asf_body="$GH_API_BODY"
    case "$asf_status" in
    2??)
        # This setting is tier-independent and enforced (see the file header), so unlike the
        # report-only guarded extractions elsewhere in this script, a guard failure here sets
        # fail=1 rather than just printing "could not determine" and moving on — the same
        # enforced-check contract as vulnerability-alerts above. Guarded with plain `jq -r` (NOT
        # `-e`) for BOTH fields together in one call: a single malformed/unexpected body should
        # produce one clear failure message, not two, and `-e` would misfire on a legitimate
        # `paused:false` the same way it would on `.fork:false` elsewhere in this script. The
        # filter also explicitly type-checks both fields, exactly like the `.fork` extraction
        # above: syntactically-valid-but-wrong-shaped JSON (e.g. `{}`, `{"enabled":null}`, or a
        # string/number instead of a boolean) would otherwise let this `if` succeed with an EMPTY
        # asf_enabled — which then fails the `= "true"` check below and falls into the PUT-to-
        # enable branch, i.e. a schema anomaly would silently trigger a live, mutating API call
        # against a state we never actually confirmed was "disabled". Confirmed live: `{}` and
        # `{"enabled":"yes","paused":false}` both raise a real jq error under this filter (guard
        # fires, no PUT attempted) while `{"enabled":true,"paused":false}` still passes cleanly.
        #
        # A genuinely EMPTY body is its own anomaly, checked explicitly BEFORE calling jq at all:
        # `jq` run against zero-length stdin exits 0 with NO output for ANY filter — including
        # this type-check filter — because the filter never runs once against zero input
        # documents (confirmed live, the same behavior already documented and guarded against for
        # repo_body above). Without this, an empty asf_body would silently produce empty
        # asf_enabled/asf_paused, which then falls into the PUT-to-enable branch below — the exact
        # dangerous "unconfirmed disabled state triggers a live mutating call" scenario the type
        # check above exists to prevent, just via a different route the type check alone can't see.
        if [ -z "$asf_body" ]; then
            asf_fields="response body was empty"
            asf_fields_ok=1
        elif asf_fields="$(printf '%s' "$asf_body" | jq -r 'if (.enabled | type) == "boolean" and (.paused | type) == "boolean" then [.enabled, .paused] | @tsv else error("enabled/paused fields are not both boolean: enabled=\(.enabled | tostring), paused=\(.paused | tostring)") end' 2>&1)"; then
            asf_fields_ok=0
        else
            asf_fields_ok=1
        fi
        if [ "$asf_fields_ok" -eq 0 ]; then
            asf_enabled="${asf_fields%%$'\t'*}"
            asf_paused="${asf_fields#*$'\t'}"
            if [ "$asf_enabled" = "true" ] && [ "$asf_paused" = "true" ]; then
                echo "Dependabot security updates: enabled but PAUSED — no new fix PRs will be generated; GitHub's REST API has no documented un-pause endpoint (only the initial enable), so this cannot be auto-remediated and is reported as an unresolved failure — see https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/troubleshoot-dependency-security/dependabot-updates-stopped" >&2
                fail=1
            elif [ "$asf_enabled" = "true" ]; then
                echo "Dependabot security updates: already enabled"
            else
                if put_out="$(gh api -X PUT "repos/$repo/automated-security-fixes" 2>&1)"; then
                    echo "Dependabot security updates: was disabled, enabled it now"
                else
                    echo "Dependabot security updates: failed to enable (repo admin rights required): $put_out" >&2
                    fail=1
                fi
            fi
        else
            echo "Dependabot security updates: could not determine current state: $asf_fields" >&2
            fail=1
        fi
        ;;
    404)
        # Disabled — this endpoint's own GET 404s when automated-security-fixes itself is off,
        # not an error. See the comment block above this `if` for why this isn't
        # vulnerability-alerts' state leaking through.
        if put_out="$(gh api -X PUT "repos/$repo/automated-security-fixes" 2>&1)"; then
            echo "Dependabot security updates: was disabled, enabled it now"
        else
            echo "Dependabot security updates: failed to enable (repo admin rights required): $put_out" >&2
            fail=1
        fi
        ;;
    403)
        # Same tier-independence caveat as vulnerability-alerts above: this setting is available
        # on every GitHub plan tier, so a 403 here cannot mean "not on this plan" either.
        echo "Dependabot security updates: insufficient permissions, or blocked by organization policy (this setting is available on every GitHub plan tier, so a 403 here is not a plan-tier gap)" >&2
        fail=1
        ;;
    *)
        echo "Dependabot security updates: could not determine current state: $asf_body" >&2
        fail=1
        ;;
    esac
else
    echo "Dependabot security updates: skipped (Dependabot alerts is not confirmed enabled above)"
fi

# --- .github/dependabot.yml existence — tier-independent, report-only -----------------------
gh_api_status "repos/$repo/contents/.github/dependabot.yml"
ddy_status="$GH_API_STATUS"
ddy_detail="$GH_API_BODY"
case "$ddy_status" in
2??)
    echo ".github/dependabot.yml: present"
    ;;
404)
    echo "WARNING: .github/dependabot.yml not found in $repo — version-update PRs won't be generated (see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#required-github-files)"
    ;;
403)
    echo ".github/dependabot.yml: could not check (insufficient permissions)" >&2
    ;;
*)
    echo ".github/dependabot.yml: could not determine presence: $ddy_detail" >&2
    ;;
esac

# --- Secret scanning status — tier-gated, report-only ----------------------------------------
# The repo API's own top-level GET always succeeds (2xx) if we got this far (repo_status was
# already confirmed 2xx above) — the field itself is what's conditionally present, not the call.
# Reuses repo_body (already fetched above) instead of making a second `gh api repos/$repo` call.
#
# Guarded with plain `jq -r` (NOT `-e`): a genuinely absent field is expected to produce empty
# output on success — that's the normal "not on this plan" case, already handled below, and must
# stay indistinguishable from it. `-e` would exit 4 on that legitimate empty-output case and
# wrongly report it as an extraction failure instead of the correct, ordinary "not available"
# message. The filter explicitly type-checks the status field WHEN PRESENT (absent/null still
# passes through as legitimately empty via the `then empty` branch) — a numeric or otherwise
# non-string status would otherwise print raw and unlabeled (e.g. "Secret scanning: 7") as if it
# were a real, known status string, rather than being flagged as an unexpected API shape.
#
# Reuses repo_body, but MUST check repo_body_ok explicitly first rather than assume it: `jq`
# against a genuinely empty repo_body would otherwise succeed with empty output for this filter
# too (confirmed live, same zero-input-documents behavior as every other empty-body case in this
# script), which is indistinguishable from the legitimate "field absent" case below and would
# misreport a genuinely empty/unparseable repo response as an ordinary "not available on this
# plan" instead of the real "could not determine" — repo_body_ok is exactly the flag this script
# already threads through default_branch/repo_is_fork above for the identical reason; this site
# had been missing that same check.
if [ "$repo_body_ok" -eq 0 ]; then
    echo "Secret scanning: could not determine: repo body was empty" >&2
elif secret_scanning_status="$(printf '%s' "$repo_body" | jq -r 'def s: .security_and_analysis.secret_scanning.status; if (s == null) then empty elif (s | type) == "string" then s else error("secret_scanning.status is not a string: \(s | tostring)") end' 2>&1)"; then
    if [ -n "$secret_scanning_status" ]; then
        echo "Secret scanning: $secret_scanning_status"
    else
        echo "Secret scanning: not available on this plan (or not visible without admin rights on $repo) — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#secret-scanning"
    fi
else
    echo "Secret scanning: could not determine: $secret_scanning_status" >&2
fi

# --- Rulesets / branch protection — tier-gated, report-only ----------------------------------
# This is a raw inventory, NOT confirmation that `main` is actually protected — target/enforcement/
# source_type are printed per ruleset precisely so a tag ruleset, a push ruleset, or one with
# enforcement "disabled"/"evaluate" isn't mistaken for an enforcing branch ruleset protecting main.
#
# `-f per_page=100` requests GitHub's maximum page size (its default is only 30) — this covers the
# overwhelming majority of real repos in a single call without the added complexity of full
# Link-header-driven pagination, but a repo with more than 100 rulesets would still only see the
# first 100 here; the "N configured" line below is phrased to reflect that ("at least N", not a
# bare "N") specifically so this known limitation isn't silently misreported as a complete count.
gh_api_status "repos/$repo/rulesets" -X GET -f per_page=100
rs_status="$GH_API_STATUS"
rs_detail="$GH_API_BODY"
case "$rs_status" in
2??)
    # Guarded with plain `jq -r` (NOT `-e`): empty output after a successful guard is the correct,
    # meaningful "0 rulesets configured" signal, already handled by the existing empty/nonempty
    # logic below — `-e` would exit 4 on a legitimately-empty `[]` array and wrongly report that
    # as an extraction failure instead of "0 configured". The filter also explicitly requires the
    # response root to be an array before iterating: a `{}` or `null` root would otherwise iterate
    # to zero rows too (jq's `.[]` on a non-array either errors or, for an object, iterates its
    # values — neither is "0 rulesets", it's an unexpected shape that should be flagged, not
    # silently reported as a legitimate empty inventory). EACH ITEM is also validated to have
    # name/target/enforcement/source_type all present as strings — without this, an item like
    # `{}` would print as "null (target=null, enforcement=null, source=null)", a row that LOOKS
    # like real ruleset data but is actually just jq's default stringification of missing fields
    # (confirmed live). A mixed valid+invalid array can print the valid rows' text before the
    # invalid item's error is raised (jq's streaming evaluation order) — harmless here since the
    # guard only branches on the overall exit code, and the partial text is discarded either way
    # once the failure path takes over.
    #
    # A genuinely EMPTY body is checked explicitly first, same reasoning as Dependabot security
    # updates above: `jq` against zero-length stdin exits 0 with no output for any filter, including
    # the array-root check, so it must be caught before calling jq at all rather than relying on
    # the filter to catch it.
    if [ -z "$rs_detail" ]; then
        ruleset_rows="response body was empty"
        ruleset_rows_ok=1
    elif ruleset_rows="$(printf '%s' "$rs_detail" | jq -r 'if type == "array" then .[] | if (.name | type) == "string" and (.target | type) == "string" and (.enforcement | type) == "string" and (.source_type | type) == "string" then "\(.name) (target=\(.target), enforcement=\(.enforcement), source=\(.source_type))" else error("ruleset item has an unexpected shape: \(tostring)") end else error("rulesets response root is not an array: \(type)") end' 2>&1)"; then
        ruleset_rows_ok=0
    else
        ruleset_rows_ok=1
    fi
    if [ "$ruleset_rows_ok" -eq 0 ]; then
        if [ -z "$ruleset_rows" ]; then
            echo "Rulesets: 0 configured — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#branch-protection"
        else
            # "at least N", not a bare "N": per_page=100 above caps this at the first 100
            # rulesets, so a count exactly at that boundary can't be asserted as the true total.
            echo "Rulesets: at least $(printf '%s\n' "$ruleset_rows" | wc -l | tr -d ' ') configured (review target/enforcement below — this is an inventory, not confirmation main is protected):"
            while IFS= read -r ruleset_row; do
                echo "  - $ruleset_row"
            done <<<"$ruleset_rows"
        fi
    else
        echo "Rulesets: could not determine: $ruleset_rows" >&2
    fi
    ;;
404)
    # GitHub's docs describe 404 on this endpoint as "Resource not found" — a genuine
    # error/unavailability condition, NOT a documented signal for "zero rulesets configured".
    # The legitimate "0 configured" case is a 200 with body `[]`, already handled above.
    echo "Rulesets: not available, or could not determine (unexpected 404 — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#branch-protection)" >&2
    ;;
403)
    # GitHub's own REST reference for this endpoint documents only 200/404/500 as expected
    # responses (reading rulesets needs only metadata:read) — an actual 403 is therefore NOT
    # reliably a plan-tier signal the way it might first appear; it could equally be insufficient
    # token/app permissions or an organization policy blocking the call. Reported as an open set
    # of possible causes rather than asserting the plan-tier interpretation with false confidence.
    echo "Rulesets: not available — insufficient permissions, organization policy, or a plan-tier limitation (GitHub's docs list only 200/404/500 for this endpoint, so an unexpected 403 isn't reliably one specific cause) — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#branch-protection"
    ;;
*)
    echo "Rulesets: could not determine: $rs_detail" >&2
    ;;
esac

# --- Private vulnerability reporting — visibility-gated (public repos only), best-effort enable -
# GitHub documents this as a public-repository feature only ("Owners and administrators of public
# repositories can allow security researchers to report vulnerabilities securely..." — GitHub's
# own product docs, not just an inference from behavior) — confirmed live: GET on this endpoint
# returns 200 with a real {"enabled": bool} body on a public repo, 404 on a private one, regardless
# of admin rights. This is NOT the same kind of "maybe/plan-tier-ambiguous" 403 as Rulesets/
# Dependency Review below — a private repo is a documented, structural exclusion, so this check is
# skipped entirely (not attempted-then-404-reported) when repo_is_private is true, using the
# extraction already done once in the top-level repo lookup above.
if [ "$repo_is_private" = "true" ]; then
    echo "Private vulnerability reporting: not available (this repository is private — GitHub restricts this feature to public repositories) — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#secret-scanning"
else
    gh_api_status "repos/$repo/private-vulnerability-reporting"
    pvr_status="$GH_API_STATUS"
    pvr_detail="$GH_API_BODY"
    case "$pvr_status" in
    2??)
        # A genuinely EMPTY body is checked explicitly first, same reasoning as every other
        # empty-body case in this script (Dependabot security updates, Rulesets): `jq` against
        # zero-length stdin exits 0 with NO output for ANY filter, including this type-check
        # filter — so an empty pvr_detail would otherwise make the `if` below succeed with an
        # EMPTY pvr_enabled, which is not "true", so it falls into the else branch and issues a
        # live, mutating PUT against a state that was never actually confirmed "disabled". This
        # is the exact bug class that took multiple review rounds to fully eliminate from the
        # Dependabot security updates check earlier in this file — confirmed live before writing
        # this guard, not assumed safe by analogy.
        if [ -z "$pvr_detail" ]; then
            echo "Private vulnerability reporting: could not determine current state: response body was empty" >&2
        elif pvr_enabled="$(printf '%s' "$pvr_detail" | jq -r 'if (.enabled | type) == "boolean" then .enabled else error("enabled field is not boolean: \(.enabled | tostring)") end' 2>&1)"; then
            if [ "$pvr_enabled" = "true" ]; then
                echo "Private vulnerability reporting: already enabled"
            else
                if put_out="$(gh api -X PUT "repos/$repo/private-vulnerability-reporting" 2>&1)"; then
                    echo "Private vulnerability reporting: was disabled, enabled it now"
                else
                    echo "Private vulnerability reporting: failed to enable (repo admin rights required): $put_out" >&2
                fi
            fi
        else
            echo "Private vulnerability reporting: could not determine current state: $pvr_enabled" >&2
        fi
        ;;
    404)
        # A public repo can still 404 here in principle (e.g. the feature genuinely toggled off
        # at an org policy level in a way that removes the endpoint rather than just reporting
        # enabled:false) — report distinctly from the private-repository skip above rather than
        # conflating the two different "not available" reasons.
        echo "Private vulnerability reporting: could not determine (unexpected 404 on a public repository) — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#secret-scanning" >&2
        ;;
    403)
        echo "Private vulnerability reporting: not available — insufficient permissions or organization policy" >&2
        ;;
    *)
        echo "Private vulnerability reporting: could not determine: $pvr_detail" >&2
        ;;
    esac
fi

# --- Dependency Review — product availability checked, "required PR check" wiring is not -----
# GitHub has no repo-settings flag for Dependency Review itself, but dependency-graph/compare DOES
# exist and its availability tracks the same plan gate — a 403 on it signals the product isn't on
# this plan (or, distinctly, that the repo is a fork — see below), the same way the secret-scanning
# field-presence check above signals its own gate.
#
# Resolve the default branch to its current commit SHA first via a query parameter
# (`-X GET -f sha=$default_branch`, NOT interpolated into the URL path), then compare that SHA
# against itself. A valid GitHub default-branch name can contain "/" (e.g. "release/v2"); passing
# it as a query-string value rather than a path segment is what actually avoids corrupting the
# request — verified live: a slash-heavy branch name passed via `-f sha=...` returns a clean,
# uncorrupted response, because it never touches the URL path at all. Resolving to a SHA is still
# valuable on top of that — it's more precise (pinned to one exact commit, not "whatever the
# default branch currently points to" at the moment of the call) — but the slash-safety itself
# comes from the query parameter, not from resolving to a SHA per se. This SHA lookup is itself a
# report-only, non-hard-failing probe, consistent with the rest of this section: on anything but a
# clean 2xx, Dependency Review is reported as "could not determine" and the script moves on rather
# than aborting.
#
# default_branch is empty here if its own extraction, above, already failed (a report-only guard —
# see the file header comment) — in that case there's no branch name to look up a SHA for at all,
# so the lookup call itself is skipped rather than attempting a call that would only 404/error on
# an empty sha= value anyway; sha_status is set to "SKIP" (not a real HTTP status, never confused
# with one) purely so the case statement below has a single, explicit branch for this state.
default_branch_sha=""
if [ -n "$default_branch" ]; then
    gh_api_status "repos/$repo/commits" -X GET -f "sha=$default_branch" -f per_page=1
    sha_status="$GH_API_STATUS"
    sha_detail="$GH_API_BODY"
else
    sha_status="SKIP"
    sha_detail="default branch for $repo could not be determined — see the earlier warning"
fi
case "$sha_status" in
2??)
    # Guarded with `jq -er` PLUS an explicit non-empty-string type check on the extracted value: a
    # healthy 2xx body from this endpoint always has a non-null, non-empty-string SHA at index 0,
    # so anything else here — missing/null (empty array), an empty string, or a wrong-typed value
    # like a number — is a genuine anomaly worth flagging distinctly (unlike the
    # report-only-with-empty-is-fine sites above). `-e` alone already correctly fails on an empty
    # array or a null `.sha` (both produce a falsy/absent result `-e` rejects) and on truly empty
    # stdin (confirmed live: exits 4, no separate empty-body pre-check needed here unlike
    # Dependabot security updates/Rulesets above) — the added type/length check specifically catches
    # a *present but wrong-shaped* sha value (empty string, number) that a bare `-e` would not.
    # On guard failure, Dependency Review is reported as "could not determine" and the compare
    # call below is skipped — exactly the same pattern already used for a transport-level (ERR)
    # SHA-resolution failure in the `*)` branch below.
    if ! default_branch_sha="$(printf '%s' "$sha_detail" | jq -er 'if (.[0].sha | type) == "string" and (.[0].sha | length) > 0 then .[0].sha else error("commits[0].sha is not a non-empty string: \(.[0].sha | tostring)") end' 2>&1)"; then
        echo "Dependency Review: could not determine (failed to resolve default branch '$default_branch' to a commit SHA: $default_branch_sha)" >&2
        default_branch_sha=""
    fi
    ;;
*)
    echo "Dependency Review: could not determine (failed to resolve default branch '$default_branch' to a commit SHA: $sha_detail)" >&2
    ;;
esac

if [ -n "$default_branch_sha" ]; then
    gh_api_status "repos/$repo/dependency-graph/compare/$default_branch_sha...$default_branch_sha"
    dr_status="$GH_API_STATUS"
    dr_detail="$GH_API_BODY"
    case "$dr_status" in
    2??)
        echo "Dependency Review: product available on this plan (dependency-graph/compare reachable)"
        ;;
    403)
        # GitHub documents this endpoint as also 403ing specifically for forked repositories, not
        # just for a plan-tier gap — conflating the two would misdirect a fork owner into checking
        # billing instead of the (unfixable, by-design) fork restriction. repo_is_fork was
        # extracted once, near the top, right after default_branch (see there for its own guard
        # and fallback).
        if [ "$repo_is_fork" = "true" ]; then
            echo "Dependency Review: not available (this repository is a fork — GitHub restricts Dependency Review on forks; if unexpected for a non-fork use case, also check plan tier)"
        else
            # This endpoint requires Contents: read on top of any plan-tier gate — the earlier
            # repo-lookup call succeeding doesn't prove that permission is actually held, since a
            # narrower-scoped token/app installation can read basic repo metadata while still
            # lacking contents access specifically. A 403 here for a non-fork repo is therefore
            # reported as an open set of causes, not asserted as a plan-tier gap with false
            # confidence.
            echo "Dependency Review: not available — plan-tier limitation, or the token/app lacks Contents: read on this repo — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#supply-chain-hardening"
        fi
        ;;
    404)
        echo "Dependency Review: could not determine (unexpected 404 on $default_branch_sha...$default_branch_sha — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#supply-chain-hardening)" >&2
        ;;
    *)
        echo "Dependency Review: could not determine: $dr_detail" >&2
        ;;
    esac
fi
echo "Dependency Review: even when the product is available, whether it's configured as a REQUIRED, blocking PR status check is a branch-protection/ruleset-level fact this script cannot check here — confirm it by looking for three things: (a) a Dependency Review workflow file under .github/workflows/, (b) that workflow using actions/dependency-review-action, and (c) that workflow's job registered as a required status check in an active branch ruleset or classic branch protection rule (cross-reference the Rulesets output above) — see https://github.com/jtauschl/sw_dev_handbook/blob/$SW_DEV_HANDBOOK_DOC_REF/05-tooling/github.md#supply-chain-hardening"

if [ "$fail" -ne 0 ]; then
    echo "github-security-settings: one or more tier-independent settings failed to apply or could not be determined on $repo" >&2
    exit 1
fi

echo "github-security-settings: done"
