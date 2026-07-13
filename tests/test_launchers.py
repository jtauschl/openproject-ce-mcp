"""Executable tests for the source-install/uninstall launcher scripts (OPM-167).

Marked ``launcher`` -- excluded from the default ``pytest`` run (see
pyproject.toml's ``addopts``) and run only in the ubuntu-only ``launchers``
CI job (.github/workflows/test.yml), since bash/POSIX-executable-stub
semantics and pwsh availability aren't reliably identical across the full
OS matrix. get.ps1/uninstall.ps1 are exercised via pwsh running on Linux,
which validates their actual PowerShell logic (git/Python detection,
clone/pull branching, file-existence guards) -- platform-agnostic
PowerShell, not Windows-specific PATHEXT/.exe resolution.

Harness: every launcher subprocess gets a ``fakebin`` directory as its
*sole* PATH entry, containing symlinks to the real, resolved-once absolute
paths of the few external tools the scripts actually use (scanned directly
from their source, not assumed) plus conditionally-present stub
`git`/`python3`/`python`/`py` scripts that log their invocation and are
controllable via env vars. get.sh also opens /dev/tty, which fails outright
under a plain subprocess (no controlling terminal) -- run via a real pty
instead so that path behaves as it would interactively.
"""

from __future__ import annotations

import os
import re
import selectors
import shutil
import subprocess
import time
from pathlib import Path

import pytest

# `pty` is Unix-only. pytest must import this module during collection to
# discover its tests (marker-based deselection happens after collection), so
# a module-level `import pty` would break collection on Windows even though
# every test here ends up deselected there. Deferred into _run_pty instead,
# which is only ever called from the ubuntu-only launchers CI job.

pytestmark = pytest.mark.launcher

REPO_ROOT = Path(__file__).resolve().parent.parent
GET_SH = REPO_ROOT / "get.sh"
GET_PS1 = REPO_ROOT / "get.ps1"
UNINSTALL_SH = REPO_ROOT / "uninstall.sh"
UNINSTALL_PS1 = REPO_ROOT / "uninstall.ps1"

# Resolved once, on this test process's own unmodified PATH -- never rely on
# a manipulated PATH (fakebin) to find interpreters/tools themselves.
SH = shutil.which("sh")
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")
_REAL_TOOLS = {name: shutil.which(name) for name in ("rm", "find", "dirname", "mkdir")}

GET_SCRIPTS = [GET_SH] + ([GET_PS1] if PWSH else [])
UNINSTALL_SCRIPTS = [UNINSTALL_SH] + ([UNINSTALL_PS1] if PWSH else [])

_GIT_STUB = """#!/bin/sh
echo "git $*" >> "$FAKE_LOG"
case "$1" in
  clone)
    dest="$3"
    mkdir -p "$dest/.git"
    printf '' > "$dest/configure_mcp.py"
    ;;
esac
"""

_PYTHON_STUB = """#!/bin/sh
echo "python $* (cwd=$(pwd))" >> "$FAKE_LOG"
arg1="$1"
if [ "$arg1" = "-3" ]; then arg1="$2"; fi
if [ "$arg1" = "-c" ]; then
  if [ "${FAKE_PY_VERSION_OK:-1}" = "1" ]; then
    echo True
    exit 0
  fi
  echo False
  exit 1
fi
exit "${FAKE_PY_EXIT:-0}"
"""


def _fakebin(tmp_path: Path, *, git: bool = True, python: bool = True) -> Path:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name, target in _REAL_TOOLS.items():
        if target:
            (fakebin / name).symlink_to(target)
    if git:
        _write_executable(fakebin / "git", _GIT_STUB)
    if python:
        for name in ("python3", "python", "py"):
            _write_executable(fakebin / name, _PYTHON_STUB)
    return fakebin


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _env(fakebin: Path, log: Path, **extra: str) -> dict[str, str]:
    home = str(fakebin.parent)
    env = {"PATH": str(fakebin), "FAKE_LOG": str(log), "HOME": home, "USERPROFILE": home}
    env.update(extra)
    return env


def _run_pty(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 10) -> tuple[int, str]:
    """Run cmd with a real pty as stdin/stdout/stderr. A plain subprocess has
    no controlling terminal, so a script that opens /dev/tty (get.sh) would
    fail with 'Device not configured' even though the existence/readability
    checks preceding it pass -- a pty makes /dev/tty genuinely openable.

    The read loop is deadline-bound via ``selectors`` rather than a plain
    blocking ``os.read`` -- a launcher that hangs while holding the pty open
    would otherwise never reach ``proc.wait(timeout=...)`` at all, since that
    call only happens after the read loop returns.

    ``start_new_session=True`` detaches the child from any controlling
    terminal via ``setsid()``. On macOS/BSD a session leader auto-acquires
    the first tty it opens as its controlling terminal, but Linux does not --
    it requires an explicit ``TIOCSCTTY`` ioctl, without which get.sh's own
    ``/dev/tty`` open fails with ENXIO ("No such device or address") even
    though its preceding ``-e``/``-r`` checks pass. Claim it explicitly via
    ``preexec_fn`` so this works the same on both.
    """
    import fcntl  # Unix-only; deferred alongside pty so collection never fails on Windows.
    import pty
    import termios

    def _claim_controlling_tty() -> None:
        try:
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        except OSError:
            pass  # already the controlling terminal (e.g. macOS/BSD auto-acquire) -- fine.

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            preexec_fn=_claim_controlling_tty,
        )
        os.close(slave_fd)
        slave_fd = -1
        chunks: list[bytes] = []
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as sel:
            sel.register(master_fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not sel.select(timeout=remaining):
                    break  # no data before the deadline -- treat as hung
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        try:
            returncode = proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = proc.wait(timeout=2)
        return returncode, b"".join(chunks).decode(errors="replace")
    finally:
        if slave_fd != -1:
            os.close(slave_fd)
        os.close(master_fd)


def _run_launcher(script: Path, *, cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    if script.suffix == ".ps1":
        result = subprocess.run(
            [PWSH, "-File", str(script)], cwd=cwd, env=env, capture_output=True, text=True, timeout=10
        )
        return result.returncode, result.stdout + result.stderr
    interpreter = SH if script.name == "get.sh" else BASH
    return _run_pty([interpreter, str(script)], cwd=cwd, env=env)


# ── get.sh / get.ps1 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_clones_into_fresh_target(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    target = tmp_path / "target"
    rc, out = _run_launcher(script, cwd=tmp_path, env=_env(fakebin, log, DIR=str(target)))
    assert rc == 0, out
    log_text = log.read_text()
    assert "clone" in log_text
    assert (target / ".git").is_dir()
    assert (target / "configure_mcp.py").exists()


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_pulls_existing_target(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").mkdir()
    (target / "configure_mcp.py").write_text("")
    rc, out = _run_launcher(script, cwd=tmp_path, env=_env(fakebin, log, DIR=str(target)))
    assert rc == 0, out
    log_text = log.read_text()
    assert "clone" not in log_text
    assert "pull" in log_text


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_honors_dir_override(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "custom-target"
    env = _env(fakebin, log, DIR=str(target))
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    rc, out = _run_launcher(script, cwd=tmp_path, env=env)
    assert rc == 0, out
    assert (target / ".git").is_dir()
    assert not (home / "openproject-ce-mcp").exists()


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_fails_without_git(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path, git=False)
    log = tmp_path / "fake.log"
    rc, out = _run_launcher(script, cwd=tmp_path, env=_env(fakebin, log, DIR=str(tmp_path / "target")))
    assert rc == 1
    assert "git" in out.lower()


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_fails_without_suitable_python(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    env = _env(fakebin, log, DIR=str(tmp_path / "target"), FAKE_PY_VERSION_OK="0")
    rc, out = _run_launcher(script, cwd=tmp_path, env=env)
    assert rc == 1
    assert "python" in out.lower()


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_detects_incomplete_checkout(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").mkdir()
    rc, out = _run_launcher(script, cwd=tmp_path, env=_env(fakebin, log, DIR=str(target)))
    assert rc == 1
    assert "incomplete" in out.lower()
    # The version probe legitimately runs before the checkout is validated;
    # what must never happen is the actual configure_mcp.py exec.
    assert not log.exists() or "configure_mcp.py" not in log.read_text()


@pytest.mark.parametrize("script", GET_SCRIPTS, ids=lambda p: p.name)
def test_get_propagates_exit_code(tmp_path: Path, script: Path) -> None:
    fakebin = _fakebin(tmp_path)
    log = tmp_path / "fake.log"
    env = _env(fakebin, log, DIR=str(tmp_path / "target"), FAKE_PY_EXIT="7")
    rc, out = _run_launcher(script, cwd=tmp_path, env=env)
    assert rc == 7, out


# ── uninstall.sh / uninstall.ps1 ─────────────────────────────────────────────


def _copy_script(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    dest.write_text(src.read_text())
    dest.chmod(0o755)
    return dest


def _seed_artifacts(root: Path) -> None:
    for name in (".venv", ".pytest_cache", ".ruff_cache", ".op-sources"):
        d = root / name
        d.mkdir()
        (d / "marker").write_text("x")
    (root / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "pkg" / "__pycache__" / "x.pyc").write_text("x")
    (root / "foo.egg-info").mkdir()
    (root / "foo.egg-info" / "PKG-INFO").write_text("x")


def _artifacts_gone(root: Path) -> bool:
    return not any(
        (root / rel).exists()
        for rel in (".venv", ".pytest_cache", ".ruff_cache", ".op-sources", "pkg/__pycache__", "foo.egg-info")
    )


@pytest.mark.parametrize("src", UNINSTALL_SCRIPTS, ids=lambda p: p.name)
def test_uninstall_removes_all_local_artifacts(tmp_path: Path, src: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    script = _copy_script(src, root)
    _seed_artifacts(root)
    fakebin = _fakebin(tmp_path, git=False)
    log = tmp_path / "fake.log"
    rc, out = _run_launcher(script, cwd=root, env=_env(fakebin, log))
    assert rc == 0, out
    assert _artifacts_gone(root)


@pytest.mark.parametrize("src", UNINSTALL_SCRIPTS, ids=lambda p: p.name)
def test_uninstall_invokes_configure_mcp_uninstall(tmp_path: Path, src: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    script = _copy_script(src, root)
    fakebin = _fakebin(tmp_path, git=False)
    log = tmp_path / "fake.log"
    rc, out = _run_launcher(script, cwd=root, env=_env(fakebin, log))
    assert rc == 0, out
    assert "--uninstall" in log.read_text()


@pytest.mark.parametrize("src", UNINSTALL_SCRIPTS, ids=lambda p: p.name)
def test_uninstall_tolerates_missing_directories(tmp_path: Path, src: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    script = _copy_script(src, root)
    fakebin = _fakebin(tmp_path, git=False)
    log = tmp_path / "fake.log"
    rc, out = _run_launcher(script, cwd=root, env=_env(fakebin, log))
    assert rc == 0, out


@pytest.mark.parametrize("src", UNINSTALL_SCRIPTS, ids=lambda p: p.name)
def test_uninstall_skips_gracefully_without_python(tmp_path: Path, src: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    script = _copy_script(src, root)
    _seed_artifacts(root)
    fakebin = _fakebin(tmp_path, git=False, python=False)
    log = tmp_path / "fake.log"
    rc, out = _run_launcher(script, cwd=root, env=_env(fakebin, log))
    assert rc == 0, out
    assert _artifacts_gone(root)


# ── static parity checks (cheap drift alarms, not behavioral proof) ─────────


def test_uninstall_scripts_target_the_same_static_paths() -> None:
    # Named top-level paths only. __pycache__/*.egg-info are pruned via a
    # separate, dynamic find/Get-ChildItem step (different syntax entirely,
    # not part of this static list) -- their removal is proven behaviorally
    # by test_uninstall_removes_all_local_artifacts above, not by text
    # comparison here.
    sh_match = re.search(r"rm -rf ((?:\.\S+\s*)+)", UNINSTALL_SH.read_text())
    # Anchor on a dot-prefixed first element -- uninstall.ps1 has an earlier,
    # unrelated @("python", "python3") array for interpreter detection.
    ps1_match = re.search(r"@\((\"\.[^)]+)\)", UNINSTALL_PS1.read_text())
    assert sh_match and ps1_match
    sh_paths = set(sh_match.group(1).split())
    ps1_paths = {p.strip().strip('"') for p in ps1_match.group(1).split(",")}
    assert sh_paths == ps1_paths == {".venv", ".pytest_cache", ".ruff_cache", ".op-sources"}


def _readme_section(readme: str, heading: str) -> str:
    start = readme.index(heading)
    end = readme.index("</details>", start)
    return readme[start:end]


def test_readme_documents_get_sh_destination_and_dir_override() -> None:
    section = _readme_section((REPO_ROOT / "README.md").read_text(), "Alternative: install from source")
    assert "~/openproject-ce-mcp" in section
    assert "DIR=" in section
    assert 'DEST="${DIR:-$HOME/openproject-ce-mcp}"' in GET_SH.read_text()


def test_readme_documents_get_ps1_destination_and_dir_override() -> None:
    section = _readme_section((REPO_ROOT / "README.md").read_text(), "Alternative: install from source")
    assert "%USERPROFILE%\\openproject-ce-mcp" in section
    assert "$env:DIR" in section
    assert 'Join-Path $env:USERPROFILE "openproject-ce-mcp"' in GET_PS1.read_text()


def test_readme_uninstall_section_mentions_venv_and_op_sources() -> None:
    # README describes .op-sources descriptively ("the API-source clones"),
    # not by its literal env/dir name -- check what's actually there.
    section = _readme_section((REPO_ROOT / "README.md").read_text(), "Uninstalling a source install")
    assert ".venv" in section
    assert "API-source clones" in section
    assert "caches" in section
