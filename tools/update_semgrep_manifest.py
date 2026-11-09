"""Regenerate tools/semgrep/rules.manifest and the pinned SHA of tools/install-semgrep-rules.sh.

The manifest lists the rule files of github.com/semgrep/semgrep-rules, at one commit, that hold the rules of the
registry packs `p/python` and `p/secrets` (the handbook's Python default). Only paths are committed: the Semgrep Rules
License does not allow distributing the rules, so CI fetches them at the pinned commit (tools/install-semgrep-rules.sh).
A bump is one reviewed commit that changes the SHA and the manifest together.

Usage: python tools/update_semgrep_manifest.py <full commit sha of semgrep/semgrep-rules>
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "semgrep" / "rules.manifest"
INSTALLER = ROOT / "tools" / "install-semgrep-rules.sh"
PACKS = ("p/python", "p/secrets")
RULE_SUFFIXES = (".yaml", ".yml")
NOT_RULES = (".test.yaml", ".test.yml", ".fixed.yaml", ".fixed.yml")
SHA = re.compile(r"[0-9a-f]{40}")
PACK_RULE_ID = re.compile(r"^- id: (\S+)$", re.MULTILINE)
USER_AGENT = {"User-Agent": "openproject-ce-mcp-tools"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=60) as response:  # noqa: S310
        data: bytes = response.read()
    return data


def pack_rule_ids(pack: str) -> list[str]:
    ids = PACK_RULE_ID.findall(_get(f"https://semgrep.dev/c/{pack}").decode())
    if not ids:
        raise SystemExit(f"pack {pack} lists no rules")
    return ids


def tree_paths(sha: str) -> set[str]:
    tree = json.loads(_get(f"https://api.github.com/repos/semgrep/semgrep-rules/git/trees/{sha}?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("the tree listing of semgrep-rules is truncated")
    return {
        entry["path"]
        for entry in tree["tree"]
        if entry["type"] == "blob" and entry["path"].endswith(RULE_SUFFIXES) and not entry["path"].endswith(NOT_RULES)
    }


def rule_file(rule_id: str, paths: set[str]) -> str:
    """A rule id is the dotted path of its file without the suffix, then the rule's own id inside the file.

    A rule file whose name contains a dot cannot be told from a path separator; it is not found and stops the run.
    """
    parts = rule_id.split(".")
    for end in range(len(parts) - 1, 0, -1):
        for suffix in RULE_SUFFIXES:
            candidate = "/".join(parts[:end]) + suffix
            if candidate in paths:
                return candidate
    raise SystemExit(f"no rule file at this commit for the rule {rule_id}")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not SHA.fullmatch(argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    sha = argv[1]
    script = INSTALLER.read_text(encoding="utf-8")
    if not re.search(r'^rules_sha="[0-9a-f]{40}"$', script, flags=re.MULTILINE):
        raise SystemExit(f"{INSTALLER.name} has no rules_sha line to update")
    paths = tree_paths(sha)
    files = sorted({rule_file(rule_id, paths) for pack in PACKS for rule_id in pack_rule_ids(pack)})
    pinned = re.sub(r'^rules_sha="[0-9a-f]{40}"$', f'rules_sha="{sha}"', script, flags=re.MULTILINE)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text("\n".join(files) + "\n", encoding="utf-8")
    INSTALLER.write_text(pinned, encoding="utf-8")
    print(f"{len(files)} rule files for {', '.join(PACKS)} at {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
