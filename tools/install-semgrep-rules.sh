#!/usr/bin/env bash
# The Semgrep Rules License does not allow distributing the rules, so the repository holds only the list of rule files
# (tools/semgrep/rules.manifest) and a commit of github.com/semgrep/semgrep-rules; this script fetches exactly that
# commit and those files. Dependabot cannot track the commit: tools/update_semgrep_manifest.py bumps it together with
# the manifest, in one reviewed commit.
set -euo pipefail

target_dir="${1:?usage: install-semgrep-rules.sh <target-dir>}"

rules_sha="16b9e6d45f10649f6a531ec4838ed9924372c3bc"
manifest="$(dirname "$0")/semgrep/rules.manifest"

git -C "$target_dir" init --quiet
# Anchored patterns in no-cone mode: cone mode is directory-oriented and cannot name single files.
sed 's#^#/#' "$manifest" | git -C "$target_dir" sparse-checkout set --no-cone --stdin
git -C "$target_dir" fetch --quiet --depth 1 https://github.com/semgrep/semgrep-rules.git "$rules_sha"
# A fetch leaves HEAD on the initial branch, so the pinned commit is checked out by hand and then proven.
git -C "$target_dir" checkout --quiet --detach "$rules_sha"

head_sha="$(git -C "$target_dir" rev-parse HEAD)"
if [ "$head_sha" != "$rules_sha" ]; then
    echo "semgrep-rules: expected commit $rules_sha, got $head_sha" >&2
    exit 1
fi

# `git ls-files` also lists the index entries outside the sparse set, so the files actually present are compared.
expected="$(LC_ALL=C sort "$manifest")"
present="$(cd "$target_dir" && find . -path ./.git -prune -o -type f -print | sed 's#^\./##' | LC_ALL=C sort)"
if [ "$expected" != "$present" ]; then
    echo "semgrep-rules: the checked-out files differ from tools/semgrep/rules.manifest:" >&2
    diff <(printf '%s\n' "$expected") <(printf '%s\n' "$present") >&2 || true
    exit 1
fi
