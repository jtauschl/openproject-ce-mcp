from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import op_sources
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "fetch-sources.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="fetch-sources.sh is a POSIX shell tool for maintainer machines"
)


@pytest.fixture
def git_env(monkeypatch) -> dict[str, str]:
    # A hook exports GIT_DIR and friends, which would point every git call
    # below at the hooked repository instead of the temporary ones.
    for name in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(name)
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
    }


def _git(*args: str, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, env=env)


@pytest.fixture
def upstream(tmp_path, git_env) -> Path:
    """A local stand-in for opf/openproject carrying every pinned tag (plus one newer)."""
    repo = tmp_path / "upstream"
    for rel in ("lib/api/v3/work_packages/api.rb", "modules/meeting/lib/api/v3/meetings/api.rb", "frontend/app.ts"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n")
    _git("init", "-q", str(repo), env=git_env)
    _git("-C", str(repo), "config", "uploadpack.allowFilter", "true", env=git_env)
    _git("-C", str(repo), "add", ".", env=git_env)
    _git("-C", str(repo), "commit", "-q", "-m", "source", env=git_env)
    # One commit per release, as upstream: tags sharing a commit would make
    # `git describe --exact-match` pick an arbitrary one of them.
    for tag in [*op_sources.pinned_versions().values(), "v17.9.99"]:
        _git("-C", str(repo), "commit", "-q", "--allow-empty", "-m", tag, env=git_env)
        _git("-C", str(repo), "tag", tag, env=git_env)
    return repo


def _fetch(script: Path, upstream: Path, dest: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["bash", str(script)],
        check=True,
        capture_output=True,
        text=True,
        env={**env, "OPENPROJECT_SOURCES_REPO": upstream.as_uri(), "OPENPROJECT_SOURCES_DIR": str(dest)},
    )
    return result.stdout


def test_fetch_checks_out_every_pin_at_its_tag_with_only_the_api_subtrees(tmp_path, upstream, git_env):
    dest = tmp_path / "op-sources"
    _fetch(_SCRIPT, upstream, dest, git_env)

    pins = op_sources.pinned_versions()
    assert sorted(p.name for p in dest.iterdir()) == sorted(pins)
    assert op_sources.checkout_problems(pins, dest) == []
    newest = dest / list(pins)[-1]
    assert (newest / "lib/api/v3/work_packages/api.rb").exists()
    assert (newest / "modules/meeting/lib/api/v3/meetings/api.rb").exists()
    assert not (newest / "frontend").exists()


def test_a_bumped_pin_leaves_the_old_checkout_and_the_guard_reports_it(tmp_path, upstream, git_env):
    dest = tmp_path / "op-sources"
    _fetch(_SCRIPT, upstream, dest, git_env)

    bumped = tmp_path / "tools" / "api-check" / "fetch-sources.sh"
    bumped.parent.mkdir(parents=True)
    newest_version, newest_tag = list(op_sources.pinned_versions().items())[-1]
    bumped.write_text(_SCRIPT.read_text().replace(f'"{newest_version}:{newest_tag}"', f'"{newest_version}:v17.9.99"'))
    out = _fetch(bumped, upstream, dest, git_env)

    assert f"[{newest_version}] already present" in out
    assert "cloning" not in out
    assert op_sources.checkout_problems(op_sources.pinned_versions(bumped), dest) == [
        f"{newest_version}: checkout is at {newest_tag}, pin is v17.9.99 -- delete {dest / newest_version} and re-run"
    ]

    shutil.rmtree(dest / newest_version)
    _fetch(bumped, upstream, dest, git_env)
    assert op_sources.checkout_problems(op_sources.pinned_versions(bumped), dest) == []
