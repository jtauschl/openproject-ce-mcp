"""Cross-checks that pyproject.toml's version and the runtime __version__
agree, guarding against the two independently-hardcoded strings this
project used to carry silently drifting apart again.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest

from openproject_ce_mcp import __version__

_ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject_toml() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert __version__ == data["project"]["version"]


def test_missing_dist_info_raises_a_remediation_hint_not_a_bare_package_not_found() -> None:
    """Regression: a stale/broken editable install (e.g. a venv whose
    symlinks survived a `brew upgrade python`) previously surfaced as a
    bare `PackageNotFoundError: openproject-ce-mcp` -- true, but with no
    hint that `uv sync --dev` is the fix. Simulates the missing-dist-info
    condition by patching `importlib.metadata.version` and re-importing the
    package fresh."""

    def fake_version(name: str) -> str:
        raise PackageNotFoundError(name)

    with (
        patch("importlib.metadata.version", side_effect=fake_version),
        patch("pathlib.Path.read_text", side_effect=FileNotFoundError),
    ):
        with pytest.raises(RuntimeError, match=r"uv sync --dev"):
            importlib.reload(importlib.import_module("openproject_ce_mcp"))

    # Reload once more with the patch lifted so later tests in the same
    # process see the real, correctly-populated __version__ again.
    importlib.reload(importlib.import_module("openproject_ce_mcp"))


def test_a_pyproject_of_another_project_is_not_taken_for_the_version() -> None:
    foreign = '[project]\nname = "another-project"\nversion = "9.9.9"\n'

    def fake_version(name: str) -> str:
        raise PackageNotFoundError(name)

    with (
        patch("importlib.metadata.version", side_effect=fake_version),
        patch("pathlib.Path.read_text", return_value=foreign),
    ):
        with pytest.raises(RuntimeError, match=r"uv sync --dev"):
            importlib.reload(importlib.import_module("openproject_ce_mcp"))

    importlib.reload(importlib.import_module("openproject_ce_mcp"))


def test_a_source_checkout_without_dist_info_reads_its_version_from_pyproject() -> None:
    def fake_version(name: str) -> str:
        raise PackageNotFoundError(name)

    with patch("importlib.metadata.version", side_effect=fake_version):
        reloaded = importlib.reload(importlib.import_module("openproject_ce_mcp"))
        source_version = reloaded.__version__

    importlib.reload(importlib.import_module("openproject_ce_mcp"))
    assert source_version == tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]["version"]


_HIDE_DIST_INFO = """\
import importlib.metadata as metadata

_real_version = metadata.version


def _version(name):
    if name == "openproject-ce-mcp":
        raise metadata.PackageNotFoundError(name)
    return _real_version(name)


metadata.version = _version
"""


def test_the_bare_checkout_shim_runs_without_the_project_installed(tmp_path: Path) -> None:
    (tmp_path / "sitecustomize.py").write_text(_HIDE_DIST_INFO)
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(_ROOT / "configure_mcp.py"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "openproject-ce-mcp is not installed" not in result.stderr
