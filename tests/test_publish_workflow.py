from __future__ import annotations

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
