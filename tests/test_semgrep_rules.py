"""The pinned semgrep rules: the installer fails closed, and the manifest generator maps pack rules to rule files."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_PATH = ROOT / "tools" / "update_semgrep_manifest.py"
_spec = importlib.util.spec_from_file_location("update_semgrep_manifest", _PATH)
assert _spec is not None and _spec.loader is not None
update_manifest = importlib.util.module_from_spec(_spec)
sys.modules["update_semgrep_manifest"] = update_manifest
_spec.loader.exec_module(update_manifest)

SHA = "0123456789abcdef0123456789abcdef01234567"

# --- the manifest generator --------------------------------------------------------------------------------------

PATHS = {
    "python/lang/security/audit/subprocess-shell-true.yaml",
    "python/lang/security/audit/two-rules.yml",
    "generic/secrets/security/detected-token.yaml",
}


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    [
        (
            "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true",
            "python/lang/security/audit/subprocess-shell-true.yaml",
        ),
        ("python.lang.security.audit.two-rules.second-rule", "python/lang/security/audit/two-rules.yml"),
        ("generic.secrets.security.detected-token.detected-token", "generic/secrets/security/detected-token.yaml"),
    ],
)
def test_a_rule_id_maps_to_the_file_that_holds_it(rule_id: str, expected: str) -> None:
    assert update_manifest.rule_file(rule_id, PATHS) == expected


def test_a_rule_without_a_file_at_the_commit_stops_the_generator() -> None:
    with pytest.raises(SystemExit, match="no rule file at this commit for the rule python.gone.rule"):
        update_manifest.rule_file("python.gone.rule", PATHS)


def test_the_generator_writes_the_manifest_and_the_pinned_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer = tmp_path / "install-semgrep-rules.sh"
    installer.write_text(f'before\nrules_sha="{"0" * 40}"\nafter\n', encoding="utf-8")
    manifest = tmp_path / "semgrep" / "rules.manifest"
    monkeypatch.setattr(update_manifest, "INSTALLER", installer)
    monkeypatch.setattr(update_manifest, "MANIFEST", manifest)
    monkeypatch.setattr(update_manifest, "tree_paths", lambda sha: PATHS)
    packs = {
        "p/python": ["python.lang.security.audit.two-rules.first", "python.lang.security.audit.two-rules.second"],
        "p/secrets": ["generic.secrets.security.detected-token.detected-token"],
    }
    monkeypatch.setattr(update_manifest, "pack_rule_ids", lambda pack: packs[pack])

    assert update_manifest.main(["update_semgrep_manifest.py", SHA]) == 0

    assert manifest.read_text(encoding="utf-8").splitlines() == [
        "generic/secrets/security/detected-token.yaml",
        "python/lang/security/audit/two-rules.yml",
    ]
    assert installer.read_text(encoding="utf-8") == f'before\nrules_sha="{SHA}"\nafter\n'


def test_the_generator_refuses_an_installer_without_a_pin_line_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = tmp_path / "install-semgrep-rules.sh"
    installer.write_text("no pin here\n", encoding="utf-8")
    manifest = tmp_path / "rules.manifest"
    monkeypatch.setattr(update_manifest, "INSTALLER", installer)
    monkeypatch.setattr(update_manifest, "MANIFEST", manifest)
    monkeypatch.setattr(update_manifest, "tree_paths", lambda sha: PATHS)
    monkeypatch.setattr(update_manifest, "pack_rule_ids", lambda pack: ["python.lang.security.audit.two-rules.first"])

    with pytest.raises(SystemExit, match="has no rules_sha line to update"):
        update_manifest.main(["update_semgrep_manifest.py", SHA])
    assert not manifest.exists()
    assert installer.read_text(encoding="utf-8") == "no pin here\n"


@pytest.mark.parametrize("argv", [["x"], ["x", "not-a-sha"], ["x", "A" * 40], ["x", SHA, "extra"]])
def test_the_generator_wants_exactly_one_full_lowercase_sha(argv: list[str]) -> None:
    assert update_manifest.main(argv) == 2


# --- the installer, against a local stand-in for github.com/semgrep/semgrep-rules ------------------------------------

needs_git = pytest.mark.skipif(
    os.name == "nt" or shutil.which("git") is None or shutil.which("bash") is None, reason="needs bash and git"
)


def _git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class _Upstream:
    """A local repository with two commits, reachable under the URL the installer fetches from."""

    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "upstream"
        self.path.mkdir()
        _git(self.path, "init", "--quiet")
        (self.path / "python").mkdir()
        (self.path / "python" / "rule.yaml").write_text("rules: []\n", encoding="utf-8")
        (self.path / "python" / "other.yaml").write_text("rules: []\n", encoding="utf-8")
        _git(self.path, "add", ".")
        _git(self.path, "commit", "--quiet", "-m", "one")
        self.first = _git(self.path, "rev-parse", "HEAD")
        (self.path / "python" / "later.yaml").write_text("rules: []\n", encoding="utf-8")
        _git(self.path, "add", ".")
        _git(self.path, "commit", "--quiet", "-m", "two")

    def install(
        self, tmp_path: Path, *, sha: str, manifest: list[str]
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run a copy of the installer with `sha` and `manifest` pinned, fetching from the local repository."""
        script = tmp_path / "tools" / "install-semgrep-rules.sh"
        script.parent.mkdir(parents=True)
        original = (ROOT / "tools" / "install-semgrep-rules.sh").read_text(encoding="utf-8")
        pinned = original.replace('rules_sha="' + _pinned_sha(original) + '"', f'rules_sha="{sha}"')
        assert pinned != original or sha == _pinned_sha(original)
        script.write_text(pinned, encoding="utf-8")
        script.chmod(0o755)
        (script.parent / "semgrep").mkdir()
        (script.parent / "semgrep" / "rules.manifest").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        target = tmp_path / "rules"
        target.mkdir()
        env = {
            **os.environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.path}.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/semgrep/semgrep-rules.git",
        }
        result = subprocess.run(
            ["bash", str(script), str(target)], env=env, capture_output=True, text=True, check=False
        )
        return result, target


def _pinned_sha(script: str) -> str:
    marker = 'rules_sha="'
    start = script.index(marker) + len(marker)
    return script[start : script.index('"', start)]


@needs_git
def test_the_installer_checks_out_exactly_the_manifest_files_at_the_pinned_commit(tmp_path: Path) -> None:
    upstream = _Upstream(tmp_path)

    result, target = upstream.install(tmp_path, sha=upstream.first, manifest=["python/rule.yaml"])

    assert result.returncode == 0, result.stderr
    assert _git(target, "rev-parse", "HEAD") == upstream.first
    present = sorted(
        p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file() and ".git" not in p.parts
    )
    assert present == ["python/rule.yaml"]


@needs_git
def test_the_installer_fails_when_a_manifest_file_is_not_in_the_commit(tmp_path: Path) -> None:
    upstream = _Upstream(tmp_path)

    # later.yaml exists only in the second commit; the pinned first commit does not have it.
    result, _ = upstream.install(tmp_path, sha=upstream.first, manifest=["python/rule.yaml", "python/later.yaml"])

    assert result.returncode != 0
    assert "differ from tools/semgrep/rules.manifest" in result.stderr
    assert "python/later.yaml" in result.stderr


@needs_git
def test_the_installer_fails_for_a_commit_the_repository_does_not_have(tmp_path: Path) -> None:
    upstream = _Upstream(tmp_path)

    result, target = upstream.install(tmp_path, sha="f" * 40, manifest=["python/rule.yaml"])

    assert result.returncode != 0
    assert not (target / "python").exists()


def test_the_installer_refuses_to_run_without_a_target_directory() -> None:
    if os.name == "nt" or shutil.which("bash") is None:
        pytest.skip("needs bash")

    result = subprocess.run(
        ["bash", str(ROOT / "tools" / "install-semgrep-rules.sh")], capture_output=True, text=True, check=False
    )

    assert result.returncode != 0
    assert "usage: install-semgrep-rules.sh <target-dir>" in result.stderr
