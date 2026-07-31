#!/usr/bin/env bash
set -euo pipefail

# Installs/refreshes this project's .git/hooks/commit-msg from sw_dev_handbook's own
# templates/hooks/commit-msg, so the hook stays current without a developer having to remember to
# re-copy it by hand (see ../../02-bootstrap/project-setup.md#build-wrapper--dev — this script is
# meant to be copied into a code repo's own scripts/ folder and called as one step inside that
# project's own ./dev bootstrap, so it runs on every fresh clone and every re-pin, not just once).
#
# Fixes SDH-181: across sw_dev_handbook's 3 consumer pilots, every single one had a
# non-conformant commit-msg hook (2 of 3 missing it entirely, 1 of 3 had it installed but stale)
# because installing it was previously a one-time manual checklist step with nothing to catch
# drift or absence except an opt-in ./dev handbook-check run.
#
# Scoped to the one hook that exists today (templates/hooks/commit-msg) — not a generic
# templates/hooks/* installer. Generalize only if/when a second hook is ever added.
#
# Resolution logic mirrors handbook-check.sh.example's own: this script is copied into
# <code-repo>/scripts/, so the code repo is exactly one level up from this script's own resolved
# directory, and the umbrella directory is that code repo's own parent, confirmed by requiring a
# sibling sw_dev_handbook/ git clone to exist there.
script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
CODE_REPO_DIR="$(cd -- "$script_dir/.." && pwd)"
UMBRELLA_DIR="$(dirname -- "$CODE_REPO_DIR")"

if [ ! -d "$UMBRELLA_DIR/sw_dev_handbook" ] || [ ! -d "$UMBRELLA_DIR/sw_dev_handbook/.git" ]; then
    echo "sync-commit-msg-hook: could not locate the umbrella directory — expected a sibling" >&2
    echo "sw_dev_handbook/ git clone one level above the code repo ($UMBRELLA_DIR), given this" >&2
    echo "script's own resolved location at $script_dir — see" >&2
    echo "../../02-bootstrap/project-setup.md#repo-topology for the expected layout." >&2
    exit 1
fi

reference_file="$UMBRELLA_DIR/sw_dev_handbook/templates/hooks/commit-msg"
hook_file="$CODE_REPO_DIR/.git/hooks/commit-msg"
divergence_file="${hook_file}.divergence-reason"

if [ ! -f "$reference_file" ]; then
    echo "sync-commit-msg-hook: reference hook not found at $reference_file — cannot sync" >&2
    exit 1
fi

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

if [ ! -f "$hook_file" ]; then
    cp "$reference_file" "$hook_file"
    chmod +x "$hook_file"
    echo "sync-commit-msg-hook: installed .git/hooks/commit-msg"
    exit 0
fi

reference_hash="$(sha256_of "$reference_file")"
hook_hash="$(sha256_of "$hook_file")"

if [ "$reference_hash" = "$hook_hash" ]; then
    exit 0
fi

if [ -f "$divergence_file" ]; then
    exit 0
fi

echo "sync-commit-msg-hook: WARNING — installed .git/hooks/commit-msg diverges from" >&2
echo "templates/hooks/commit-msg and no $divergence_file note documents why. Leaving it" >&2
echo "untouched — if this divergence is intentional, document it by creating that file; if not," >&2
echo "re-run after removing the local file to pick up the current template." >&2
