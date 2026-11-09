"""shfmt reaches the shell-lint job as a pinned, checksum-verified release binary, never through a run-time Go download."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-shfmt.sh"


def _required_version() -> str:
    match = re.search(r'^required_shfmt_version="([^"]+)"$', (ROOT / "dev").read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "dev no longer defines required_shfmt_version"
    return match.group(1)


def _installer_field(name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', INSTALLER.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"the installer no longer defines {name}"
    return match.group(1)


def test_the_installer_pins_the_version_the_dev_gate_requires() -> None:
    assert _installer_field("version") == _required_version()


def test_contributing_names_the_version_the_dev_gate_requires() -> None:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert re.search(r"`shfmt`\s+" + re.escape(_required_version()) + r"\b", text)


def test_the_pinned_checksum_is_a_sha256() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", _installer_field("sha256"))


def test_the_installer_is_linted_with_the_other_shell_scripts() -> None:
    dev = (ROOT / "dev").read_text(encoding="utf-8")

    assert "tools/install-shfmt.sh" in dev.split("shell_scripts=(", 1)[1].split(")", 1)[0]


def test_the_shell_job_installs_shfmt_with_the_installer_and_no_go_toolchain() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  shell-scripts:\n", 1)[1]

    assert 'tools/install-shfmt.sh "$RUNNER_TEMP"' in job
    assert "go install" not in job


# The installer runs on the Linux runner; the macOS and Windows jobs only dispatch and tag builds run pytest there, and
# neither ships sha256sum by default. The Linux jobs run these tests on every push.
runs_installer = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sha256sum") is None,
    reason="the installer needs a POSIX shell and sha256sum",
)


def _fake_curl(bin_dir: Path, *, body: bytes | None) -> None:
    """Stands in for curl: writes `body` to the -o target, or fails like `curl -f` on an HTTP error."""
    script = bin_dir / "curl"
    if body is None:
        script.write_text("#!/bin/sh\nexit 22\n", encoding="utf-8")
    else:
        payload = bin_dir / "payload"
        payload.write_bytes(body)
        script.write_text(
            f'#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\ncp "{payload}" "$2"\n',
            encoding="utf-8",
        )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def _run_installer(
    tmp_path: Path, installer: Path, body: bytes | None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir, target = tmp_path / "bin", tmp_path / "target"
    bin_dir.mkdir()
    target.mkdir()
    _fake_curl(bin_dir, body=body)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(["bash", str(installer), str(target)], env=env, capture_output=True, text=True, check=False)
    return result, target


def _installer_expecting(tmp_path: Path, content: bytes) -> Path:
    """A copy of the installer whose pinned checksum is that of `content`, so a test controls match and mismatch."""
    text = INSTALLER.read_text(encoding="utf-8")
    pinned = re.sub(r'^sha256="[0-9a-f]{64}"$', f'sha256="{hashlib.sha256(content).hexdigest()}"', text, flags=re.M)
    assert pinned != text
    copy = tmp_path / "install-shfmt.sh"
    copy.write_text(pinned, encoding="utf-8")
    return copy


@runs_installer
def test_a_verified_download_becomes_the_executable_shfmt(tmp_path: Path) -> None:
    content = b"#!/bin/sh\necho verified\n"

    result, target = _run_installer(tmp_path, _installer_expecting(tmp_path, content), content)

    assert result.returncode == 0, result.stderr
    assert (target / "shfmt").read_bytes() == content
    assert (target / "shfmt").stat().st_mode & stat.S_IXUSR
    assert [entry.name for entry in target.iterdir()] == ["shfmt"]


@runs_installer
def test_a_download_with_the_wrong_checksum_leaves_nothing_behind(tmp_path: Path) -> None:
    result, target = _run_installer(tmp_path, _installer_expecting(tmp_path, b"expected"), b"tampered")

    assert result.returncode != 0
    assert list(target.iterdir()) == []


@runs_installer
def test_a_failed_download_leaves_nothing_behind(tmp_path: Path) -> None:
    result, target = _run_installer(tmp_path, INSTALLER, None)

    assert result.returncode != 0
    assert list(target.iterdir()) == []


@runs_installer
def test_the_installer_refuses_to_run_without_a_target_directory() -> None:
    result = subprocess.run(["bash", str(INSTALLER)], capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "usage: install-shfmt.sh <target-dir>" in result.stderr


@pytest.mark.parametrize("name", ["version", "sha256"])
def test_the_installer_defines_its_pins_once(name: str) -> None:
    assert len(re.findall(rf"^{name}=", INSTALLER.read_text(encoding="utf-8"), re.MULTILINE)) == 1
