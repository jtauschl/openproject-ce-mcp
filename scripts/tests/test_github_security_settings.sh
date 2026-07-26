#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git -C "$script_dir" rev-parse --show-toplevel)"

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT

cp "$repo_root/tools/security-settings/github-security-settings.sh" "$sandbox/"

# sandbox is also made into its own throwaway git repo (separate from repo_root, this test
# script's own real repo) so the no-argument invocation path can be exercised for real: the real
# script's own `git rev-parse --show-toplevel` needs an actual repo to succeed against, and
# `not-a-git-repo` case below needs a directory that deliberately is NOT one.
git init -q "$sandbox"
git -C "$sandbox" config user.email "test@example.invalid"
git -C "$sandbox" config user.name "test"

fake_bin="$sandbox/fake-bin"
mkdir -p "$fake_bin"
cases_file="$sandbox/cases.txt"
bodies_dir="$sandbox/bodies"
mkdir -p "$bodies_dir"

# The fake `gh` understands only the exact subset the real script calls:
#   gh auth status
#   gh repo view --json nameWithOwner -q .nameWithOwner   (the no-argument owner/repo resolution
#                                                            path; canned via $FAKE_GH_REPO_VIEW,
#                                                            see the no-argument test cases below)
#   gh api <path> -i [-X <method>] [-f key=value ...]
#   gh api <path> --jq <expr>          (used only by the PUT-failure/success fallthrough path,
#                                        which the real script never invokes with --jq; kept here
#                                        only for completeness/defensiveness)
#   gh api -X <method> <path>          (the enable PUTs)
#
# `-f key=value` args do not affect which canned case matches (routing is still by (METHOD, path)
# alone), but every invocation's full argv is appended, one line per call, to $FAKE_GH_CALL_LOG —
# this lets a test assert on the EXACT arguments a given call was made with (e.g. that the real
# script's default-branch-to-SHA lookup really did pass `-X GET -f sha=<branch> -f per_page=1`,
# not just that it hit the right path with no query args at all, which a route-only check could
# not distinguish from a broken or missing sha= parameter).
#
# Canned responses come from $cases_file, one line per case:
#   METHOD path status body-file-or--
# matched by exact (METHOD, path) pair. status "ERR" means: exit 1, print body-file's raw content
# (or a fixed transport-failure message if body-file is "--") to stderr, and emit NO "HTTP/" line
# at all -- this is what a real DNS/network failure looks like to gh_api_status(), not a synthetic
# shortcut. Any other status means: exit 1 if status is not 2xx (matching gh's own real behavior
# of exiting non-zero on any HTTP error response even with -i), after printing a well-formed
# "HTTP/1.1 <status> ..." line, an empty line, and then the body (from body-file, or nothing if
# "--"). An unmatched (METHOD, path) pair is a hard test-setup error (not a silent 404), so a real
# script call site added later that isn't covered here fails loudly instead of silently 404ing.
cat >"$fake_bin/gh" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail

cases_file="${FAKE_GH_CASES:?FAKE_GH_CASES not set}"
bodies_dir="${FAKE_GH_BODIES:?FAKE_GH_BODIES not set}"

if [ -n "${FAKE_GH_CALL_LOG:-}" ]; then
    printf '%s\n' "$*" >>"$FAKE_GH_CALL_LOG"
fi

if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
    exit 0
fi

if [ "${1:-}" = "repo" ] && [ "${2:-}" = "view" ]; then
    if [ -n "${FAKE_GH_REPO_VIEW:-}" ] && [ -f "${FAKE_GH_REPO_VIEW:-}" ]; then
        cat "$FAKE_GH_REPO_VIEW"
        exit 0
    fi
    echo "fake gh: repo view called with no FAKE_GH_REPO_VIEW canned response set" >&2
    exit 97
fi

if [ "${1:-}" != "api" ]; then
    echo "fake gh: unsupported invocation: $*" >&2
    exit 99
fi
shift

method="GET"
path=""
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
    arg="${args[$i]}"
    case "$arg" in
    -X)
        i=$((i + 1))
        method="${args[$i]}"
        ;;
    -i) ;;
    --jq)
        i=$((i + 1))
        ;;
    -f)
        i=$((i + 1))
        ;;
    -*)
        echo "fake gh: unsupported flag: $arg" >&2
        exit 99
        ;;
    *)
        path="$arg"
        ;;
    esac
    i=$((i + 1))
done

if [ -z "$path" ]; then
    echo "fake gh: no path parsed from: ${args[*]}" >&2
    exit 99
fi

match="$(awk -v m="$method" -v p="$path" '$1 == m && $2 == p { print; exit }' "$cases_file")"
if [ -z "$match" ]; then
    echo "fake gh: NO CANNED CASE for $method $path (test setup gap — add a line to the cases table)" >&2
    exit 98
fi

status="$(printf '%s\n' "$match" | awk '{print $3}')"
body_ref="$(printf '%s\n' "$match" | awk '{print $4}')"

body=""
if [ "$body_ref" != "--" ]; then
    body="$(cat "$bodies_dir/$body_ref")"
fi

if [ "$status" = "ERR" ]; then
    if [ -n "$body" ]; then
        printf '%s\n' "$body" >&2
    else
        echo "fake gh: simulated transport failure (no HTTP status line)" >&2
    fi
    exit 1
fi

printf 'HTTP/1.1 %s Simulated\r\n' "$status"
printf 'content-type: application/json\r\n'
printf '\r\n'
if [ -n "$body" ]; then
    printf '%s\n' "$body"
fi

case "$status" in
2??) exit 0 ;;
*) exit 1 ;;
esac
FAKE_GH
chmod +x "$fake_bin/gh"

call_log="$sandbox/call_log.txt"
repo_view_file="$sandbox/repo_view.json"
export FAKE_GH_CASES="$cases_file"
export FAKE_GH_BODIES="$bodies_dir"
export FAKE_GH_CALL_LOG="$call_log"
export FAKE_GH_REPO_VIEW="$repo_view_file"
export PATH="$fake_bin:$PATH"

run_script() {
    : >"$call_log"
    (cd "$sandbox" && PATH="$fake_bin:$PATH" ./github-security-settings.sh "$1")
}

# Runs the script with NO argument, from inside $sandbox (already its own git repo — see the
# `git init` above) — exercises the documented default behavior (resolve owner/repo from the
# current checkout via `git rev-parse --show-toplevel` + `gh repo view`) that every other test
# case in this file bypasses by always passing an explicit "o/r" argument.
run_script_no_arg() {
    : >"$call_log"
    (cd "$sandbox" && PATH="$fake_bin:$PATH" ./github-security-settings.sh)
}

# Runs the script with NO argument from a directory that is deliberately NOT inside any git
# repo (a fresh mktemp -d outside $sandbox's own repo), to exercise the "not inside a git
# repository" guard's clean-failure path rather than a raw, unlabeled `git rev-parse` error.
# Explicitly removes any stale $repo_view_file left over from an earlier no-argument test case:
# this case's entire point is that `git rev-parse --show-toplevel` must fail cleanly BEFORE `gh
# repo view` is ever reached at all, so a stale canned repo-view response must not be able to
# mask that -- confirmed live that omitting this reset lets an unguarded `cd
# "$(git rev-parse --show-toplevel)"` regression pass silently: `git rev-parse` failing leaves
# its own error text on stderr and an EMPTY stdout, so `cd ""` (an empty argument) is a silent
# bash no-op that stays in the current directory rather than failing under `set -e` -- the script
# then continues and calls `gh repo view` right where it already was, which returns whatever
# stale value the fake happens to have cached from a previous case instead of erroring.
run_script_outside_git_repo() {
    local outside_dir
    outside_dir="$(mktemp -d)"
    trap 'rm -rf "$outside_dir"' RETURN
    cp "$sandbox/github-security-settings.sh" "$outside_dir/"
    rm -f "$repo_view_file"
    : >"$call_log"
    (cd "$outside_dir" && PATH="$fake_bin:$PATH" ./github-security-settings.sh)
}

assert_exit() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" != "$actual" ]; then
        echo "FAIL ($desc): expected exit $expected, got $actual" >&2
        exit 1
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "FAIL ($desc): expected output to contain: $needle" >&2
        echo "--- actual output ---" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

assert_not_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "FAIL ($desc): expected output NOT to contain: $needle" >&2
        echo "--- actual output ---" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

# Asserts $call_log (populated by run_script's most recent invocation) contains a line with
# EXACTLY these space-separated argv tokens, in order — not just "the right path was hit", but
# "the call was made with these precise flags/values". Used to prove the real script's
# default-branch-to-SHA lookup actually passes -X GET -f sha=<branch> -f per_page=1, since routing
# alone (METHOD, path) can't distinguish a correct call from one with a missing/wrong sha= value.
assert_call_logged() {
    local desc="$1" expected="$2"
    if ! grep -qxF "$expected" "$call_log"; then
        echo "FAIL ($desc): expected a logged gh call: $expected" >&2
        echo "--- actual call log ---" >&2
        cat "$call_log" >&2
        exit 1
    fi
}

write_cases() {
    cat >"$cases_file"
}

repo_ok_body='{"default_branch":"main","fork":false,"private":false}'
printf '%s' "$repo_ok_body" >"$bodies_dir/repo_ok.json"

sha_ok_body='[{"sha":"abc1234deadbeef"}]'
printf '%s' "$sha_ok_body" >"$bodies_dir/sha_ok.json"

dependabot_ok_body='{"content":"...","name":"dependabot.yml"}'
printf '%s' "$dependabot_ok_body" >"$bodies_dir/dependabot_ok.json"

rulesets_empty_body='[]'
printf '%s' "$rulesets_empty_body" >"$bodies_dir/rulesets_empty.json"

rulesets_mixed_body='[
  {"name":"protect-main","target":"branch","enforcement":"active","source_type":"Repository"},
  {"name":"tag-release","target":"tag","enforcement":"active","source_type":"Repository"},
  {"name":"eval-only","target":"branch","enforcement":"evaluate","source_type":"Repository"},
  {"name":"push-block","target":"push","enforcement":"active","source_type":"Repository"}
]'
printf '%s' "$rulesets_mixed_body" >"$bodies_dir/rulesets_mixed.json"

secret_scanning_present_body='{"default_branch":"main","fork":false,"private":false,"security_and_analysis":{"secret_scanning":{"status":"enabled"}}}'
printf '%s' "$secret_scanning_present_body" >"$bodies_dir/repo_secret_scanning_present.json"

repo_fork_body='{"default_branch":"main","fork":true,"private":false}'
printf '%s' "$repo_fork_body" >"$bodies_dir/repo_fork.json"

pvr_enabled_body='{"enabled":true}'
printf '%s' "$pvr_enabled_body" >"$bodies_dir/pvr_enabled.json"

# --- (a) both settings already enabled -------------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
printf '%s' '{"enabled":true,"paused":false}' >"$bodies_dir/asf_enabled.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "a: exit code" 0 "$code"
assert_contains "a: va already enabled" "Dependabot alerts: already enabled" "$out"
assert_contains "a: asf already enabled" "Dependabot security updates: already enabled" "$out"

# --- (b) both disabled (404) -> enabled via PUT ----------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 404 --
PUT repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 404 --
PUT repos/o/r/automated-security-fixes 204 --
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "b: exit code" 0 "$code"
assert_contains "b: va enabled now" "Dependabot alerts: was disabled, enabled it now" "$out"
assert_contains "b: asf enabled now" "Dependabot security updates: was disabled, enabled it now" "$out"

# --- (c) automated-security-fixes reports paused ----------------------------------------------
printf '%s' '{"enabled":true,"paused":true}' >"$bodies_dir/asf_paused.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_paused.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "c: exit code" 1 "$code"
assert_contains "c: paused warning" "PAUSED" "$out"

# --- (d) vulnerability-alerts 403 -> exit 1, tier-independent wording -------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 403 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "d1: exit code" 1 "$code"
assert_contains "d1: tier-independent 403 wording" "insufficient permissions, or blocked by organization policy" "$out"
assert_contains "d1: no plan-tier claim" "not a plan-tier gap" "$out"
assert_not_contains "d1: must not say not available on this plan" "Dependabot alerts: not available on this plan" "$out"

# --- (d) vulnerability-alerts 500 -> exit 1, "could not determine current state" -------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 500 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "d2: exit code" 1 "$code"
assert_contains "d2: could not determine" "Dependabot alerts: could not determine current state" "$out"

# --- (d) top-level repo 404 -> exit 1, "repo not found", before any per-setting check ---------
write_cases <<EOF
GET repos/o/r 404 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "d3: exit code" 1 "$code"
assert_contains "d3: repo not found" "repo not found: o/r" "$out"

# --- (d) genuine transport failure (ERR, no HTTP status line at all) --------------------------
# Simulates what a real DNS/network failure looks like: gh exits non-zero with plain-text stderr
# and no HTTP/ line at all, for the very first call the script makes.
printf '%s' 'fake gh: simulated DNS resolution failure' >"$bodies_dir/transport_err.txt"
write_cases <<EOF
GET repos/o/r ERR transport_err.txt
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "d4: exit code" 1 "$code"
assert_contains "d4: could not determine reachability" "could not determine reachability of o/r" "$out"
assert_contains "d4: transport detail surfaced" "simulated DNS resolution failure" "$out"

# --- (e) missing dependabot.yml -> exit 0 (warning only) ---------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 404 --
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "e: exit code" 0 "$code"
assert_contains "e: warning text" "WARNING: .github/dependabot.yml not found" "$out"

# --- (f) mixed rulesets: all four rows print with correct fields ------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_mixed.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "f1: exit code" 0 "$code"
assert_contains "f1: branch/active row" "protect-main (target=branch, enforcement=active, source=Repository)" "$out"
assert_contains "f1: tag/active row" "tag-release (target=tag, enforcement=active, source=Repository)" "$out"
assert_contains "f1: branch/evaluate row" "eval-only (target=branch, enforcement=evaluate, source=Repository)" "$out"
assert_contains "f1: push/active row" "push-block (target=push, enforcement=active, source=Repository)" "$out"
assert_contains "f1: not-confirmation wording" "not confirmation main is protected" "$out"

# --- (f) empty rulesets array -> "0 configured" -------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "f2: exit code" 0 "$code"
assert_contains "f2: 0 configured" "Rulesets: 0 configured" "$out"

# --- (f) rulesets 403 -> open set of causes, NOT a confident plan-tier claim ---------------------
# GitHub's own REST reference documents only 200/404/500 for this endpoint, so an unexpected 403
# must not be asserted as reliably a plan-tier gap -- it could equally be insufficient permissions
# or an org policy block.
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 403 --
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "f3: exit code" 0 "$code"
assert_contains "f3: open-cause wording" "Rulesets: not available — insufficient permissions, organization policy, or a plan-tier limitation" "$out"
assert_not_contains "f3: must not assert plan-tier alone" "Rulesets: not available on this plan" "$out"

# --- rulesets 404 -> "not available, or could not determine" (NOT the old "0 configured") -----
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 404 --
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-404: exit code" 0 "$code"
assert_contains "rulesets-404: not available or could not determine" "Rulesets: not available, or could not determine (unexpected 404" "$out"
assert_not_contains "rulesets-404: must not say 0 configured" "Rulesets: 0 configured" "$out"

# --- rulesets unexpected 401 (report-only endpoint, must not hard-fail run) ----------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 401 --
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-401: exit code" 0 "$code"
assert_contains "rulesets-401: could not determine" "Rulesets: could not determine" "$out"

# --- rulesets unexpected 500 (report-only endpoint, must not hard-fail run) ----------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 500 --
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-500: exit code" 0 "$code"
assert_contains "rulesets-500: could not determine" "Rulesets: could not determine" "$out"

# --- (g) vulnerability-alerts PUT fails (403) -> exit 1, asf skipped, no stray asf call ----------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 404 --
PUT repos/o/r/vulnerability-alerts 403 --
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "g: exit code" 1 "$code"
assert_contains "g: failed to enable" "Dependabot alerts: failed to enable" "$out"
assert_contains "g: asf skipped" "Dependabot security updates: skipped" "$out"

# --- Dependency Review 403, non-fork -> exit 0 overall, plan-tier wording, no fork wording -----
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 403 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "dr-403: exit code" 0 "$code"
assert_contains "dr-403: open-cause wording" "Dependency Review: not available — plan-tier limitation, or the token/app lacks Contents: read" "$out"
assert_not_contains "dr-403: must not say fork wording" "this repository is a fork" "$out"
assert_contains "dr-403: workflow file pointer" ".github/workflows/" "$out"
assert_contains "dr-403: action pointer" "actions/dependency-review-action" "$out"
assert_contains "dr-403: required status check pointer" "required status check in an active branch ruleset or classic branch protection rule" "$out"

# --- Dependency Review 403, fork -> fork-specific wording, not plan-tier wording ----------------
write_cases <<EOF
GET repos/o/r 200 repo_fork.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 403 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "dr-403-fork: exit code" 0 "$code"
assert_contains "dr-403-fork: fork wording" "this repository is a fork" "$out"
assert_not_contains "dr-403-fork: must not say plan-tier-only wording" "Dependency Review: not available — plan-tier limitation, or the token/app lacks Contents: read" "$out"

# --- Dependency Review 404 -> "could not determine" ----------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 404 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "dr-404: exit code" 0 "$code"
assert_contains "dr-404: could not determine" "Dependency Review: could not determine (unexpected 404" "$out"

# --- Secret scanning: field present (public-repo shape) -------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_secret_scanning_present.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "secret-present: exit code" 0 "$code"
assert_contains "secret-present: status printed" "Secret scanning: enabled" "$out"

# --- Secret scanning: field absent ------------------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "secret-absent: exit code" 0 "$code"
assert_contains "secret-absent: not available" "Secret scanning: not available on this plan" "$out"

# --- automated-security-fixes 403 -> tier-independent wording, mirrors vulnerability-alerts ------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 403 --
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-403: exit code" 1 "$code"
assert_contains "asf-403: tier-independent wording" "Dependabot security updates: insufficient permissions, or blocked by organization policy" "$out"
assert_not_contains "asf-403: must not say not available on this plan" "Dependabot security updates: not available on this plan" "$out"

# --- automated-security-fixes 500 -> "could not determine current state" -------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 500 --
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-500: exit code" 1 "$code"
assert_contains "asf-500: could not determine" "Dependabot security updates: could not determine current state" "$out"

# --- automated-security-fixes: malformed 2xx JSON -> guarded, exit 1 (enforced check, not report-
# only), "could not determine", NOT a raw jq parse-error abort ------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_malformed.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
printf '{not valid json' >"$bodies_dir/asf_malformed.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-malformed: exit code" 1 "$code"
assert_contains "asf-malformed: could not determine" "Dependabot security updates: could not determine current state" "$out"
assert_not_contains "asf-malformed: must not falsely report already enabled" "Dependabot security updates: already enabled" "$out"

# --- repo_is_fork: field missing entirely -> guard must catch it (plain jq -r '.fork' would
# silently succeed with "null"), falls back to non-fork wording on a subsequent Dependency Review
# 403 -------------------------------------------------------------------------------------------
printf '%s' '{"default_branch":"main"}' >"$bodies_dir/repo_no_fork_field.json"
write_cases <<EOF
GET repos/o/r 200 repo_no_fork_field.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 403 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "fork-field-missing: exit code" 0 "$code"
assert_contains "fork-field-missing: fork-status-unknown warning" "could not determine fork status for o/r" "$out"
assert_contains "fork-field-missing: falls back to open-cause wording" "Dependency Review: not available — plan-tier limitation, or the token/app lacks Contents: read" "$out"
assert_not_contains "fork-field-missing: must not say fork wording" "this repository is a fork" "$out"

# --- default branch containing "/" is passed via query param, never interpolated into the path ---
# Proves slash-safety comes from the query-parameter mechanism, not from switching to a SHA per
# se: even with default_branch "release/v2" in the repo body, the fake gh's case table only ever
# needs ONE entry for the commits lookup -- "repos/o/r/commits", with no branch name in the path
# at all, because the branch name travels as a -f query arg the fake gh discards without routing
# on it. If the real script ever regressed to interpolating the branch name into the URL path
# (e.g. "repos/o/r/commits/release/v2"), the fake gh's "NO CANNED CASE" hard-failure would fire on
# that unmatched path instead of silently passing.
printf '%s' '{"default_branch":"release/v2","fork":false}' >"$bodies_dir/repo_slash_branch.json"
write_cases <<EOF
GET repos/o/r 200 repo_slash_branch.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "slash-branch: exit code" 0 "$code"
assert_contains "slash-branch: dependency review available" "Dependency Review: product available on this plan" "$out"
# Prove the ACTUAL call shape, not just that some call hit the right path: -X GET and both -f
# query params (sha=<branch>, per_page=1) must be present verbatim. Path-only routing couldn't
# distinguish this from a call with a missing or wrong sha= value, since the fake gh's case-table
# matching ignores -f contents entirely (see the file header comment) — this assertion is what
# actually closes that gap by inspecting the logged argv directly.
assert_call_logged "slash-branch: exact commits lookup call shape" "api repos/o/r/commits -i -X GET -f sha=release/v2 -f per_page=1"

# --- resolving default branch to a SHA fails (report-only, must not hard-fail the run) ------------
printf '%s' 'fake gh: simulated transient failure resolving commit' >"$bodies_dir/sha_transport_err.txt"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits ERR sha_transport_err.txt
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-resolve-err: exit code" 0 "$code"
assert_contains "sha-resolve-err: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"

# ============================================================================================
# Guarded-jq-extraction cases (malformed / unexpected 2xx JSON must not hard-abort report-only
# checks, per-site guard design).
# ============================================================================================

# --- top-level repo body malformed entirely -> BOTH default_branch and repo_is_fork guards fire
# (neither is fatal, per the report-only contract), the run continues and every other check that
# doesn't need repo_body's fields still gets a fair shot -- but here the repo GET itself is the
# thing that returned malformed JSON, so essentially every subsequent call in the table is
# unreachable (the fake gh's cases table below intentionally has no further entries: the real
# script's flow after a malformed repo_body still tries vulnerability-alerts/etc, which would 404
# loudly against an empty cases table if this ever regressed to attempting them past a totally
# broken repo lookup -- so the assertions here only check the two guard messages themselves,
# accepting that the run's overall exit code depends on what those subsequent lookups do).
write_cases <<EOF
GET repos/o/r 200 repo_malformed.json
EOF
printf '{not valid json' >"$bodies_dir/repo_malformed.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
# The captured jq diagnostic is expected to appear EMBEDDED in the wrapper message (same pattern
# as put_out elsewhere in this script) -- what must NOT happen is the raw jq error appearing
# UNWRAPPED as the entire output (i.e. a `set -e`/jq-triggered abort with no "could not determine"
# framing at all), which the assert_contains below rules out.
assert_contains "repo-body-malformed: default_branch guard message" "could not determine default branch for o/r" "$out"
assert_contains "repo-body-malformed: fork guard message" "could not determine fork status for o/r" "$out"

# --- top-level repo body is a genuinely empty response body on a 2xx -> same two guards fire,
# neither is script-wide fatal, Dependency Review specifically reports "could not determine" while
# the two tier-independent enforced checks (which don't need default_branch/fork at all) still run
# and succeed normally -----------------------------------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_empty.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
EOF
printf '' >"$bodies_dir/repo_empty.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "default-branch-empty-not-fatal: exit code" 0 "$code"
assert_contains "default-branch-empty-not-fatal: default_branch guard message" "could not determine default branch for o/r" "$out"
assert_contains "default-branch-empty-not-fatal: alerts still ran" "Dependabot alerts: already enabled" "$out"
assert_contains "default-branch-empty-not-fatal: asf still ran" "Dependabot security updates: already enabled" "$out"
assert_contains "default-branch-empty-not-fatal: dependency review could not determine" "Dependency Review: could not determine" "$out"
# Secret scanning reuses the same empty repo_body -- must ALSO report "could not determine",
# NEVER the ordinary "not available on this plan" message, since that message specifically means
# "the field was legitimately absent from a real, successfully-parsed body", which is not what
# happened here (the body never parsed as JSON containing that field at all -- it never parsed as
# anything, being zero bytes). Conflating the two would misreport a genuine API/data anomaly as an
# unremarkable, expected plan-tier gap.
assert_contains "default-branch-empty-not-fatal: secret scanning could not determine" "Secret scanning: could not determine: repo body was empty" "$out"
assert_not_contains "default-branch-empty-not-fatal: secret scanning must not say not available on this plan" "Secret scanning: not available on this plan" "$out"

# --- ruleset_rows extraction: malformed JSON on 2xx -> report-only, exit 0, "could not determine"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_malformed.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
printf '{not valid json' >"$bodies_dir/rulesets_malformed.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-malformed: exit code" 0 "$code"
assert_contains "rulesets-malformed: could not determine" "Rulesets: could not determine" "$out"

# --- secret_scanning_status extraction: wrong-typed field on an otherwise-valid 2xx repo body ----
# repo_status is 2xx (200) and default_branch/fork both parse fine (so the fatal default_branch
# guard does NOT fire and this case actually reaches the secret-scanning extraction) -- but
# security_and_analysis is a number instead of an object, which breaks
# `.security_and_analysis.secret_scanning.status` specifically ("Cannot index number with string
# \"status\"", jq exit 5) without breaking `.default_branch` or `.fork`, since those are separate
# top-level fields on the same document. This is report-only: exit 0, wrapped in a "could not
# determine" message (the captured jq diagnostic is embedded inside that wrapper, same pattern as
# put_out elsewhere in this script -- what must NOT happen is the run hard-aborting instead).
write_cases <<EOF
GET repos/o/r 200 repo_secret_scanning_wrong_type.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
printf '{"default_branch":"main","fork":false,"security_and_analysis":5}' >"$bodies_dir/repo_secret_scanning_wrong_type.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "secret-scanning-wrong-type: exit code" 0 "$code"
assert_contains "secret-scanning-wrong-type: could not determine" "Secret scanning: could not determine" "$out"

# --- sha extraction ([.0].sha): malformed JSON on 2xx -> Dependency Review "could not determine",
# report-only, exit 0, dependency-graph/compare call skipped entirely (no canned case needed) -----
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 commits_malformed.json
EOF
printf '{not valid json' >"$bodies_dir/commits_malformed.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-malformed: exit code" 0 "$code"
assert_contains "sha-malformed: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"
# The jq error detail must be CAPTURED INTO the message itself (proves the extraction's jq call
# redirects stderr into the captured variable, same as every other guarded extraction in this
# script) -- not just present somewhere in the test's combined stdout+stderr capture, which would
# also be true if the detail leaked out via a separate, unlabeled stderr line instead.
assert_contains "sha-malformed: jq error detail captured INTO the message" "to a commit SHA: jq: parse error" "$out"

# --- sha extraction ([.0].sha): empty body on 2xx -> same report-only "could not determine" ------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 commits_empty.json
EOF
printf '' >"$bodies_dir/commits_empty.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-empty: exit code" 0 "$code"
assert_contains "sha-empty: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"

# --- sha extraction ([.0].sha): valid JSON but empty array -> guard must catch null .[0].sha -----
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 commits_empty_array.json
EOF
printf '[]' >"$bodies_dir/commits_empty_array.json"
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-empty-array: exit code" 0 "$code"
assert_contains "sha-empty-array: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"

# ============================================================================================
# SW_DEV_HANDBOOK_DOC_REF: this project's adopted copy hardcodes its own pinned tag as the
# ${VAR:-default} fallback (v0.8.0, per README.md's "Maintenance" section), deliberately
# diverging from the generic template's invalid placeholder default -- so this project's own
# test asserts against that pinned tag, not the template's placeholder. An already-exported
# environment value must still override it, proving the `${VAR:-default}` form is used, not a
# plain `VAR=...` assignment that would silently discard an inherited value.
# ============================================================================================

# --- default (no env override): every doc link uses this project's pinned sw_dev_handbook tag ---
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "doc-ref-default: exit code" 0 "$code"
assert_contains "doc-ref-default: pinned tag in link" "blob/v0.8.0/" "$out"
assert_not_contains "doc-ref-default: must not silently use main" "blob/main/" "$out"

# --- SW_DEV_HANDBOOK_DOC_REF exported in the environment -> actually overrides the pinned default ---
code=0
out="$( (cd "$sandbox" && PATH="$fake_bin:$PATH" SW_DEV_HANDBOOK_DOC_REF="v1.2.3" ./github-security-settings.sh "o/r" 2>&1))" || code=$?
assert_exit "doc-ref-override: exit code" 0 "$code"
assert_contains "doc-ref-override: override value in link" "blob/v1.2.3/" "$out"
assert_not_contains "doc-ref-override: must not still show the pinned default" "blob/v0.8.0/" "$out"

# --- jq missing entirely -> clean, explicit exit 1 with an install pointer, BEFORE any gh call is
# attempted -- not a confusing failure deep inside the first jq extraction. Built via a curated
# PATH of explicit symlinks to just the tools this test setup itself needs (bash, coreutils, git,
# the fake gh) plus NO jq — safer/more portable than trying to strip jq's real install directory
# out of PATH, since jq commonly ships alongside other required tools in the same directory.
no_jq_bin="$sandbox/no-jq-bin"
mkdir -p "$no_jq_bin"
for tool in bash awk cat mktemp grep sed tr wc dirname basename printf true false rm mkdir chmod cp git; do
    tool_path="$(command -v "$tool" 2>/dev/null || true)"
    if [ -n "$tool_path" ]; then
        ln -sf "$tool_path" "$no_jq_bin/$tool"
    fi
done
ln -sf "$fake_bin/gh" "$no_jq_bin/gh"
code=0
out="$( (cd "$sandbox" && PATH="$no_jq_bin" ./github-security-settings.sh "o/r" 2>&1))" || code=$?
assert_exit "jq-missing: exit code" 1 "$code"
assert_contains "jq-missing: clear message" "jq not found" "$out"

# ============================================================================================
# automated-security-fixes: schema-valid-but-wrong-shaped 2xx JSON must NOT be silently treated
# as "disabled" (which would trigger a live, mutating PUT against a state never actually
# confirmed) -- must instead hit the guarded type-check and report a clean failure.
# ============================================================================================

# --- automated-security-fixes: 2xx body is `{}` (valid JSON, both fields absent) -> guard must
# catch it via the explicit boolean type-check, exit 1, "could not determine" -- and, critically,
# NO PUT call may appear anywhere in the call log (a stray PUT would mean the guard failed to
# stop a schema anomaly from being treated as "disabled").
printf '{}' >"$bodies_dir/asf_empty_object.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_empty_object.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-empty-object: exit code" 1 "$code"
assert_contains "asf-empty-object: could not determine" "Dependabot security updates: could not determine current state" "$out"
assert_not_contains "asf-empty-object: must not report was-disabled-enabled" "Dependabot security updates: was disabled, enabled it now" "$out"
if grep -q '^PUT repos/o/r/automated-security-fixes' "$call_log" 2>/dev/null || grep -qF 'api repos/o/r/automated-security-fixes -i -X PUT' "$call_log"; then
    echo "FAIL (asf-empty-object: no stray PUT): a PUT call was made against automated-security-fixes despite the schema anomaly" >&2
    cat "$call_log" >&2
    exit 1
fi

# --- automated-security-fixes: 2xx body has wrong-typed fields (strings instead of booleans) ------
printf '{"enabled":"yes","paused":"no"}' >"$bodies_dir/asf_wrong_type.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_wrong_type.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-wrong-type: exit code" 1 "$code"
assert_contains "asf-wrong-type: could not determine" "Dependabot security updates: could not determine current state" "$out"
assert_not_contains "asf-wrong-type: must not report was-disabled-enabled" "Dependabot security updates: was disabled, enabled it now" "$out"

# --- automated-security-fixes: 2xx body is a GENUINELY EMPTY response (not "{}", zero bytes) -----
# This is the specific edge case a bare type-check filter CANNOT catch on its own: `jq` run against
# zero-length stdin exits 0 with NO output for ANY filter, including a `type == "boolean"` guard,
# because the filter never runs once against zero input documents (confirmed live). Without an
# explicit pre-check for this, asf_enabled/asf_paused would both be empty, which is NOT "true", so
# the code falls into the PUT-to-enable branch -- exactly the dangerous "unconfirmed disabled state
# triggers a live mutating call" scenario the type-check guard exists to prevent, just reached via
# a different route the type check alone can't see. Critically: NO PUT call may appear in the log.
printf '' >"$bodies_dir/asf_empty_body.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_empty_body.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "asf-empty-body: exit code" 1 "$code"
assert_contains "asf-empty-body: could not determine" "Dependabot security updates: could not determine current state" "$out"
assert_not_contains "asf-empty-body: must not report was-disabled-enabled" "Dependabot security updates: was disabled, enabled it now" "$out"
if grep -q '^PUT repos/o/r/automated-security-fixes' "$call_log" 2>/dev/null || grep -qF 'api repos/o/r/automated-security-fixes -i -X PUT' "$call_log"; then
    echo "FAIL (asf-empty-body: no stray PUT): a PUT call was made against automated-security-fixes despite a genuinely empty response body" >&2
    cat "$call_log" >&2
    exit 1
fi

# --- Secret scanning: status field present but wrong-typed (a number, not a string) -> guard fires,
# report-only, exit 0, "could not determine" -- must NOT print the raw number as if it were a real,
# known status string (e.g. must not print "Secret scanning: 7") ---------------------------------
printf '{"default_branch":"main","fork":false,"security_and_analysis":{"secret_scanning":{"status":7}}}' >"$bodies_dir/repo_secret_scanning_numeric.json"
write_cases <<EOF
GET repos/o/r 200 repo_secret_scanning_numeric.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "secret-scanning-numeric: exit code" 0 "$code"
assert_contains "secret-scanning-numeric: could not determine" "Secret scanning: could not determine" "$out"
assert_not_contains "secret-scanning-numeric: must not print raw number as status" "Secret scanning: 7" "$out"

# --- Rulesets: response root is `{}` (valid JSON, but not an array) -> guard fires, report-only,
# exit 0, "could not determine" -- must NOT report "0 configured", since that specifically claims a
# legitimate empty *array* was seen, not an unexpected object shape ------------------------------
printf '{}' >"$bodies_dir/rulesets_not_array.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_not_array.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-not-array: exit code" 0 "$code"
assert_contains "rulesets-not-array: could not determine" "Rulesets: could not determine" "$out"
assert_not_contains "rulesets-not-array: must not say 0 configured" "Rulesets: 0 configured" "$out"
# Also proves the actual call includes -f per_page=100 (GitHub's max page size, vs. its 30 default)
# -- routing alone (METHOD, path) can't distinguish this from a call with no per_page override.
assert_call_logged "rulesets-not-array: per_page=100 requested" "api repos/o/r/rulesets -i -X GET -f per_page=100"

# --- Rulesets: response root IS a valid array, but an item inside it is malformed (`[{}]`) -> the
# array-root check alone would let this through (jq's `.[]` genuinely iterates a valid array), but
# the per-item field-type check must still fire -- without it, `[{}]` would print as
# "null (target=null, enforcement=null, source=null)", a row that LOOKS like real ruleset data but
# is really just jq's default stringification of entirely-missing fields (confirmed live) ---------
printf '[{}]' >"$bodies_dir/rulesets_bad_item.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_bad_item.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-bad-item: exit code" 0 "$code"
assert_contains "rulesets-bad-item: could not determine" "Rulesets: could not determine" "$out"
assert_not_contains "rulesets-bad-item: must not print null-field row as real data" "null (target=null" "$out"

# --- Rulesets: mixed array with one valid item and one malformed item -> guard must still fire
# overall (report-only "could not determine"), not silently report just the valid row and drop the
# other -- proves the per-item check isn't bypassed just because SOME items in the array are fine --
printf '[{"name":"ok-one","target":"branch","enforcement":"active","source_type":"Repository"},{}]' >"$bodies_dir/rulesets_mixed_bad.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_mixed_bad.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-mixed-bad: exit code" 0 "$code"
assert_contains "rulesets-mixed-bad: could not determine" "Rulesets: could not determine" "$out"

# --- Rulesets: 100 valid items (the per_page=100 cap) -> reported as "at least 100 configured",
# not a bare "100", since that count could legitimately be a truncated first page ------------------
ruleset_100_body="["
i=0
while [ "$i" -lt 100 ]; do
    if [ "$i" -gt 0 ]; then ruleset_100_body="$ruleset_100_body,"; fi
    ruleset_100_body="$ruleset_100_body{\"name\":\"r$i\",\"target\":\"branch\",\"enforcement\":\"active\",\"source_type\":\"Repository\"}"
    i=$((i + 1))
done
ruleset_100_body="$ruleset_100_body]"
printf '%s' "$ruleset_100_body" >"$bodies_dir/rulesets_100.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_100.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-100: exit code" 0 "$code"
assert_contains "rulesets-100: at-least wording" "Rulesets: at least 100 configured" "$out"

# --- Rulesets: genuinely empty response body (zero bytes, not "[]") -> guard fires, report-only,
# exit 0, "could not determine" -- same empty-stdin-defeats-any-filter reasoning as the
# automated-security-fixes empty-body case above -------------------------------------------------
printf '' >"$bodies_dir/rulesets_empty_body.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty_body.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "rulesets-empty-body: exit code" 0 "$code"
assert_contains "rulesets-empty-body: could not determine" "Rulesets: could not determine" "$out"
assert_not_contains "rulesets-empty-body: must not say 0 configured" "Rulesets: 0 configured" "$out"

# --- sha extraction: .[0].sha present but an empty string (not missing, not null, just "") -------
printf '[{"sha":""}]' >"$bodies_dir/commits_empty_sha_string.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 commits_empty_sha_string.json
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-empty-string: exit code" 0 "$code"
assert_contains "sha-empty-string: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"

# --- sha extraction: .[0].sha present but a number, not a string ---------------------------------
printf '[{"sha":12345}]' >"$bodies_dir/commits_numeric_sha.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 commits_numeric_sha.json
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "sha-numeric: exit code" 0 "$code"
assert_contains "sha-numeric: could not determine" "Dependency Review: could not determine (failed to resolve default branch" "$out"

# ============================================================================================
# default_branch: a failure to determine it must be scoped to Dependency Review only, NOT
# script-wide fatal -- the two tier-independent enforced checks must still run and succeed.
# ============================================================================================

# --- default_branch missing/malformed on an otherwise-valid 2xx repo body (fork IS present and
# valid, only default_branch itself is broken) -> Dependabot alerts and security updates
# both still run and succeed; only Dependency Review reports "could not determine" -------------
printf '{"default_branch":123,"fork":false}' >"$bodies_dir/repo_bad_default_branch.json"
write_cases <<EOF
GET repos/o/r 200 repo_bad_default_branch.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "default-branch-bad-not-fatal: exit code" 0 "$code"
assert_contains "default-branch-bad-not-fatal: alerts still ran" "Dependabot alerts: already enabled" "$out"
assert_contains "default-branch-bad-not-fatal: asf still ran" "Dependabot security updates: already enabled" "$out"
assert_contains "default-branch-bad-not-fatal: rulesets still ran" "Rulesets: 0 configured" "$out"
assert_contains "default-branch-bad-not-fatal: dependency review reports could-not-determine" "Dependency Review: could not determine" "$out"
# No commits/dependency-graph calls should appear at all -- default_branch never resolved to a
# usable value, so the SHA lookup must be skipped entirely, not attempted with a bad value.
if grep -qF 'repos/o/r/commits' "$call_log"; then
    echo "FAIL (default-branch-bad-not-fatal: no stray commits call): a commits lookup was attempted despite default_branch never resolving" >&2
    cat "$call_log" >&2
    exit 1
fi

# ============================================================================================
# No-argument invocation: the documented default path (resolve owner/repo from the current
# checkout via `git rev-parse --show-toplevel` + `gh repo view`), never exercised by any case
# above (which all pass an explicit "o/r" argument).
# ============================================================================================

# --- no argument, inside a git repo -> resolves via gh repo view, otherwise behaves exactly like
# passing that same owner/repo explicitly ---------------------------------------------------------
# The real script invokes `gh repo view --json nameWithOwner -q .nameWithOwner`, i.e. `gh` itself
# applies the `-q` jq filter and the script only ever sees the already-extracted plain string —
# the canned response here mirrors that same already-filtered shape, not the raw JSON object.
printf 'o/r' >"$repo_view_file"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script_no_arg 2>&1)" || code=$?
assert_exit "no-arg: exit code" 0 "$code"
assert_contains "no-arg: checking the resolved repo" "github-security-settings: checking o/r" "$out"
assert_contains "no-arg: alerts already enabled" "Dependabot alerts: already enabled" "$out"

# --- no argument, NOT inside any git repo -> clean, explicit exit 1 naming the problem and the
# workaround, NOT a raw/unlabeled `git rev-parse: fatal: not a git repository...` leak -----------
code=0
out="$(run_script_outside_git_repo 2>&1)" || code=$?
assert_exit "no-arg-outside-git: exit code" 1 "$code"
assert_contains "no-arg-outside-git: clear message" "not inside a git repository" "$out"
assert_contains "no-arg-outside-git: workaround pointer" "pass owner/repo explicitly instead" "$out"

# ============================================================================================
# Private vulnerability reporting: visibility-gated (public repos only). GitHub documents this
# as a public-repository feature — confirmed live and against GitHub's own product docs — so a
# private repo is a structural exclusion, not a plan-tier maybe. Uses repo_ok.json's own
# "private":false as the public baseline; a dedicated private-repo fixture proves the skip path.
# ============================================================================================

# --- private repo -> check skipped entirely, NO private-vulnerability-reporting call is EVER
# made. Proven via the call log directly (assert_call_logged's negation), not by relying on the
# fake gh's "NO CANNED CASE" error text propagating into $out -- confirmed during this
# implementation that that text does NOT reliably indicate a hard test failure the way earlier
# planning assumed: gh_api_status() absorbs a fake-gh error into its own "ERR"/"could not
# determine" handling instead of crashing the script or the test harness, so the presence of
# that text in $out is not on its own proof that a call was skipped -- only the call log is.
printf '{"default_branch":"main","fork":false,"private":true}' >"$bodies_dir/repo_private.json"
write_cases <<EOF
GET repos/o/r 200 repo_private.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-private-repo: exit code" 0 "$code"
assert_contains "pvr-private-repo: skip message" "Private vulnerability reporting: not available (this repository is private" "$out"
if grep -qF "repos/o/r/private-vulnerability-reporting" "$call_log"; then
    echo "FAIL (pvr-private-repo: no stray call): a private-vulnerability-reporting call was made despite the repo being private" >&2
    cat "$call_log" >&2
    exit 1
fi

# --- public repo, already enabled -> "already enabled", no PUT attempted -------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_enabled.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-already-enabled: exit code" 0 "$code"
assert_contains "pvr-already-enabled: message" "Private vulnerability reporting: already enabled" "$out"
if grep -qF "-X PUT repos/o/r/private-vulnerability-reporting" "$call_log" 2>/dev/null || grep -qF "api repos/o/r/private-vulnerability-reporting -i -X PUT" "$call_log"; then
    echo "FAIL (pvr-already-enabled: no stray PUT): a PUT call was made despite the setting already being enabled" >&2
    cat "$call_log" >&2
    exit 1
fi

# --- public repo, disabled -> PUT enables it ------------------------------------------------------
printf '{"enabled":false}' >"$bodies_dir/pvr_disabled.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_disabled.json
PUT repos/o/r/private-vulnerability-reporting 204 --
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-disabled: exit code" 0 "$code"
assert_contains "pvr-disabled: message" "Private vulnerability reporting: was disabled, enabled it now" "$out"

# --- public repo, PUT fails -> report-only, does NOT fail the run (unlike the two tier-independent
# enforced settings) -------------------------------------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_disabled.json
PUT repos/o/r/private-vulnerability-reporting 403 --
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-put-fails: exit code" 0 "$code"
assert_contains "pvr-put-fails: message" "Private vulnerability reporting: failed to enable" "$out"

# --- public repo, unexpected 404 on the PVR endpoint itself -> "could not determine", distinct
# from the private-repo skip message --------------------------------------------------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 404 --
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-404: exit code" 0 "$code"
assert_contains "pvr-404: message" "Private vulnerability reporting: could not determine (unexpected 404 on a public repository)" "$out"
assert_not_contains "pvr-404: must not say private-repo message" "this repository is private" "$out"

# --- public repo, 403 -> "insufficient permissions or organization policy" -----------------------
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 403 --
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-403: exit code" 0 "$code"
assert_contains "pvr-403: message" "Private vulnerability reporting: not available — insufficient permissions or organization policy" "$out"

# --- top-level repo body has a wrong-typed "private" field (a string, not a boolean) -> guard
# fires, falls back to "assumed private", check is skipped -- same as a missing field, confirmed
# via the call log, not just the printed message -----------------------------------------------
printf '{"default_branch":"main","fork":false,"private":"no"}' >"$bodies_dir/repo_private_wrong_type.json"
write_cases <<EOF
GET repos/o/r 200 repo_private_wrong_type.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-private-wrong-type: exit code" 0 "$code"
assert_contains "pvr-private-wrong-type: guard warning" "could not determine visibility for o/r" "$out"
assert_contains "pvr-private-wrong-type: skip message" "Private vulnerability reporting: not available (this repository is private" "$out"
if grep -qF "repos/o/r/private-vulnerability-reporting" "$call_log"; then
    echo "FAIL (pvr-private-wrong-type: no stray call): a private-vulnerability-reporting call was made despite an unconfirmed visibility" >&2
    cat "$call_log" >&2
    exit 1
fi

# --- public repo, PVR endpoint's own response body is genuinely EMPTY (zero bytes, not "{}") ------
# This is the exact bug this implementation's own self-review found and fixed before ever
# shipping this check: `jq` against zero-length stdin exits 0 with NO output for ANY filter,
# including the `.enabled` type-check filter -- an unguarded extraction would let pvr_enabled end
# up empty (not "true"), falling into the PUT-to-enable branch and issuing a live, mutating call
# against a state that was never actually confirmed "disabled". Proven two ways: the message must
# say "could not determine" (not "was disabled, enabled it now"), AND no PUT call may appear in
# the call log at all.
printf '' >"$bodies_dir/pvr_empty_body.json"
write_cases <<EOF
GET repos/o/r 200 repo_ok.json
GET repos/o/r/vulnerability-alerts 204 --
GET repos/o/r/automated-security-fixes 200 asf_enabled.json
GET repos/o/r/contents/.github/dependabot.yml 200 dependabot_ok.json
GET repos/o/r/rulesets 200 rulesets_empty.json
GET repos/o/r/private-vulnerability-reporting 200 pvr_empty_body.json
GET repos/o/r/commits 200 sha_ok.json
GET repos/o/r/dependency-graph/compare/abc1234deadbeef...abc1234deadbeef 200 --
EOF
code=0
out="$(run_script "o/r" 2>&1)" || code=$?
assert_exit "pvr-empty-body: exit code" 0 "$code"
assert_contains "pvr-empty-body: could not determine" "Private vulnerability reporting: could not determine current state: response body was empty" "$out"
assert_not_contains "pvr-empty-body: must not report was-disabled-enabled" "Private vulnerability reporting: was disabled, enabled it now" "$out"
if grep -qF "-X PUT repos/o/r/private-vulnerability-reporting" "$call_log" 2>/dev/null || grep -qF "api repos/o/r/private-vulnerability-reporting -i -X PUT" "$call_log"; then
    echo "FAIL (pvr-empty-body: no stray PUT): a PUT call was made against private-vulnerability-reporting despite a genuinely empty response body" >&2
    cat "$call_log" >&2
    exit 1
fi

echo "test_github_security_settings.sh: all cases passed"
