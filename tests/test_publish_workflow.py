from __future__ import annotations

import re
from pathlib import Path

PUBLISH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"


def _release_step() -> str:
    text = PUBLISH.read_text(encoding="utf-8")
    return text[text.index("- name: Create GitHub Release") :]


def test_the_new_draft_is_taken_from_the_create_response_not_listed_again() -> None:
    step = _release_step()
    created = step.index('-X POST "repos/$GITHUB_REPOSITORY/releases"')

    assert "list_releases" not in step[created:], (
        "GitHub may not list a release created a moment ago; use the response of the create call"
    )


def test_the_draft_is_only_created_for_a_tag_that_exists() -> None:
    step = _release_step()

    assert step.index('git/ref/tags/$tag" --silent') < step.index('-X POST "repos/$GITHUB_REPOSITORY/releases"')


_JOBS = (
    "verify-tag",
    "test",
    "validate-server-json",
    "publish",
    "prepare-homebrew-formula",
    "push-homebrew-formula",
    "registry",
)


def _job(name: str) -> str:
    text = PUBLISH.read_text(encoding="utf-8")
    start = text.index(f"\n  {name}:\n")
    following = [i for i in (text.find(f"\n  {other}:\n", start + 1) for other in _JOBS if other != name) if i > start]
    return text[start : min(following, default=len(text))]


def _first_step(job: str) -> str:
    return job.split("    steps:\n", 1)[1].lstrip().split("\n\n", 1)[0]


def test_every_job_holding_a_credential_checks_the_tag_before_any_other_step() -> None:
    for name in ("verify-tag", "publish", "prepare-homebrew-formula", "push-homebrew-formula", "registry"):
        assert "Verify tag is an exact plain SemVer" in _first_step(_job(name)), name


def test_the_reusable_test_workflow_starts_only_after_the_tag_check() -> None:
    assert "    needs: verify-tag\n    uses: ./.github/workflows/test.yml" in _job("test")


# --- no build or lint tool beside the release rights; the tested artifact is what gets published ---------------------

TEST_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
ACTION = Path(__file__).resolve().parents[1] / ".github" / "actions" / "verify-dist" / "action.yml"
_RIGHTS = ("id-token: write", "contents: write", "attestations: write")
_BUILD_OR_LINT_TOOLS = ("uv build", "uv run", "uvx", "twine", "pip install", "--project tools/lint")


def _holds_release_rights(job: str) -> bool:
    return any(right in job for right in _RIGHTS)


def _step(job: str, marker: str) -> str:
    start = job.index(marker)
    following = job.find("\n      - ", start + 1)
    return job[start : following if following != -1 else len(job)]


def test_no_job_with_release_rights_runs_a_build_or_lint_tool() -> None:
    privileged = [
        name
        for name in _JOBS
        if f"\n  {name}:\n" in PUBLISH.read_text(encoding="utf-8") and _holds_release_rights(_job(name))
    ]

    assert set(privileged) == {"publish", "registry"}
    for name in privileged:
        code = "\n".join(line for line in _job(name).splitlines() if not line.lstrip().startswith("#"))
        for tool in _BUILD_OR_LINT_TOOLS:
            assert tool not in code, f"{name}: {tool}"


def test_the_publish_job_keeps_no_credential_in_the_checkout_and_pins_uv() -> None:
    job = _job("publish")
    checkout = _step(job, "actions/checkout@")
    setup_uv = _step(job, "astral-sh/setup-uv@")

    assert "persist-credentials: false" in checkout
    assert re.search(r'version: "\d+\.\d+\.\d+"', setup_uv)


def test_the_publish_job_verifies_the_tested_artifact_before_it_attests_and_publishes() -> None:
    job = _job("publish")
    verify = _step(job, "uses: ./.github/actions/verify-dist")

    assert "artifact-id: ${{ needs.test.outputs.dist-artifact-id }}" in verify
    assert "digests: ${{ needs.test.outputs.dist-digests }}" in verify
    assert "version: ${{ steps.version.outputs.version }}" in verify
    assert (
        job.index("uses: ./.github/actions/verify-dist")
        < job.index("actions/attest-build-provenance@")
        < job.index("run: uv publish")
    )


def test_every_use_of_the_verify_action_follows_a_checkout_in_the_same_job() -> None:
    dry_run = (PUBLISH.parent / "release-dry-run.yml").read_text(encoding="utf-8")
    jobs = {"publish.yml publish": _job("publish"), "release-dry-run.yml verify": dry_run.split("\n  verify:\n", 1)[1]}

    for name, job in jobs.items():
        assert "uses: ./.github/actions/verify-dist" in job, name
        assert job.index("actions/checkout@") < job.index("uses: ./.github/actions/verify-dist"), name


def test_the_verify_action_pins_the_download_like_test_yml_and_keeps_inputs_out_of_scripts() -> None:
    action = ACTION.read_text(encoding="utf-8")
    pinned = re.search(r"actions/download-artifact@([0-9a-f]{40})", TEST_WORKFLOW.read_text(encoding="utf-8"))

    assert pinned is not None and f"actions/download-artifact@{pinned.group(1)}" in action
    assert "artifact-ids: ${{ inputs.artifact-id }}" in action
    for line in action.splitlines():
        if "${{ inputs." in line:
            assert line.strip().split(":")[0] in {"ARTIFACT_ID", "DIGESTS", "VERSION", "artifact-ids"}, line


def test_the_test_workflow_hands_its_artifact_to_the_callers_by_id() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    build = text.split("\n  build:\n", 1)[1].split("\n  install-smoke:\n", 1)[0]

    assert "value: ${{ jobs.build.outputs.dist-artifact-id }}" in text
    assert "value: ${{ jobs.build.outputs.dist-digests }}" in text
    assert "dist-artifact-id: ${{ steps.dist.outputs.artifact-id }}" in build
    assert "dist-digests: ${{ steps.digests.outputs.digests }}" in build
    upload = _step(build, "- name: Upload built dist")
    assert "id: dist" in upload and "if-no-files-found: error" in upload
    assert "retention-days: ${{ startsWith(github.ref, 'refs/tags/') && 30 || 1 }}" in upload
    assert "persist-credentials: false" in _step(build, "actions/checkout@")
    assert (
        build.index("id: digests")
        < build.index("- name: Build again")
        < build.index("- name: Generate and check the SBOM")
    )


def test_every_consumer_downloads_the_dist_artifact_by_id() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    downloads = text.split("actions/download-artifact@")[1:]

    assert len(downloads) == 2
    for download in downloads:
        assert "artifact-ids: ${{ needs.build.outputs.dist-artifact-id }}" in download.split("\n\n", 1)[0]
        assert "name: dist" not in download.split("\n\n", 1)[0]


def test_a_called_test_workflow_can_be_kept_apart_from_the_normal_run() -> None:
    text = TEST_WORKFLOW.read_text(encoding="utf-8")

    assert "inputs.concurrency-group-suffix" in text.split("\nconcurrency:\n", 1)[1].split("\n\n", 1)[0]
