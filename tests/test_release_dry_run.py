"""The release dry run exercises the credential-free part of the release path and can never publish anything."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DRY_RUN = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-dry-run.yml"


def _text() -> str:
    return DRY_RUN.read_text(encoding="utf-8")


def _code() -> str:
    return "\n".join(line for line in _text().splitlines() if not line.lstrip().startswith("#"))


def test_it_runs_on_pushes_to_release_branches_and_nothing_else() -> None:
    on = _code().split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    assert 'branches: ["release/**"]' in on
    assert re.findall(r"^  (\w[\w-]*):", on, re.MULTILINE) == ["push"]
    assert "tags" not in on


def test_it_filters_on_the_files_it_exercises() -> None:
    block = _code().split("    paths:\n", 1)[1].split("\n\n", 1)[0]

    assert set(re.findall(r"^\s+- (\S+)$", block, re.MULTILINE)) >= {
        ".github/workflows/publish.yml",
        ".github/workflows/test.yml",
        ".github/workflows/release-dry-run.yml",
        ".github/actions/verify-dist/**",
        "tools/verify_dist.py",
        "pyproject.toml",
    }


def test_it_has_no_write_permission_secret_environment_or_publishing_step() -> None:
    code = _code()

    assert "\npermissions: {}\n" in code
    for forbidden in (
        "write",
        "id-token",
        "secrets",
        "environment:",
        "upload-artifact",
        "attest",
        "uv publish",
        "gh release",
        "gh api",
        "TAP_REPO_PAT",
        "pypi",
    ):
        assert forbidden not in code, forbidden


@pytest.mark.parametrize("job", ["test", "verify"])
def test_each_job_is_limited_to_reading_the_repository(job: str) -> None:
    block = _code().split(f"\n  {job}:\n", 1)[1].split("\n\n  ", 1)[0]

    assert "permissions:\n      contents: read" in block


def test_it_calls_the_test_workflow_apart_from_the_normal_run_and_verifies_like_publish() -> None:
    code = _code()

    assert "uses: ./.github/workflows/test.yml" in code
    assert "concurrency-group-suffix: dry-run" in code
    assert "artifact-id: ${{ needs.test.outputs.dist-artifact-id }}" in code
    assert "digests: ${{ needs.test.outputs.dist-digests }}" in code
    assert "uses: ./.github/actions/verify-dist" in code
