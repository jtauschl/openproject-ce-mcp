#!/usr/bin/env bash
set -euo pipefail

# Installs/refreshes this project's .git/hooks/commit-msg from a shared reference hook
# template, so the hook stays current without a developer having to remember to
# re-copy it by hand. Meant to be called as one step inside this project's own ./dev
# bootstrap, so it runs on every fresh clone and every re-pin, not just once.
#
# The reference hook file's location defaults to a repo-topology assumption (see below),
# but can be overridden via COMMIT_MSG_HOOK_REFERENCE for other layouts/setups.
#
# Scoped to the one hook that exists today (commit-msg) — not a generic hooks/*
# installer. Generalize only if/when a second hook is ever added.
script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
CODE_REPO_DIR="$(cd -- "$script_dir/.." && pwd)"

if [ -n "${COMMIT_MSG_HOOK_REFERENCE:-}" ]; then
    reference_file="$COMMIT_MSG_HOOK_REFERENCE"
else
    # Default layout: a sibling shared-tooling clone one level above this code repo,
    # holding a reusable commit-msg hook template at templates/hooks/commit-msg.
    UMBRELLA_DIR="$(dirname -- "$CODE_REPO_DIR")"
    reference_file="$UMBRELLA_DIR/shared-dev-tooling/templates/hooks/commit-msg"
fi

hook_file="$CODE_REPO_DIR/.git/hooks/commit-msg"
divergence_file="${hook_file}.divergence-reason"

if [ ! -f "$reference_file" ]; then
    echo "sync-commit-msg-hook: reference hook not found at $reference_file — cannot sync." >&2
    echo "Set COMMIT_MSG_HOOK_REFERENCE to point at your commit-msg hook template if the" >&2
    echo "default sibling-directory layout doesn't apply here." >&2
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
echo "the reference hook template and no $divergence_file note documents why. Leaving it" >&2
echo "untouched — if this divergence is intentional, document it by creating that file; if not," >&2
echo "re-run after removing the local file to pick up the current template." >&2
