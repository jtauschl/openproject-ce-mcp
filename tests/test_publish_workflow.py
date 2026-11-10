from __future__ import annotations

import re
from pathlib import Path

import pytest

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


# --- every job of publish.yml sits behind the tag check, and a job added later cannot miss it ---------------------------

TAG_CHECK_STEP = (
    "- name: Verify tag is an exact plain SemVer (no pre-release suffix)\n"
    "        run: |\n"
    r'          if [[ ! "$GITHUB_REF_NAME" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then' + "\n"
    "            echo \"::error::Tag '$GITHUB_REF_NAME' is not an exact plain vMAJOR.MINOR.PATCH tag"
    ' — refusing to publish" >&2\n'
    "            exit 1\n"
    "          fi"
)
TAG_TRIGGER = "v[0-9]+.[0-9]+.[0-9]+"
# These status functions run a job although a job it needs failed or was skipped.
_STATUS_FUNCTION = re.compile(r"\b(always|failure|cancelled)\s*\(")
_CREDENTIAL = re.compile(r"secrets\.|^\s+secrets:|^    environment:|^\s+[a-z-]+:\s*write\b", re.MULTILINE)


def _code(text: str) -> str:
    """The text without comment lines, so a comment can neither start nor end a job or carry a setting."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _jobs_of(text: str) -> dict[str, str]:
    """The top-level jobs of a workflow as name to body text, comments dropped."""
    jobs: dict[str, str] = {}
    name = None
    for line in _code(text).split("\njobs:\n", 1)[1].splitlines():
        key = re.fullmatch(r"  ([\"']?)([A-Za-z0-9_-]+)\1:\s*(#.*)?", line)
        if key:
            name = key.group(2)
            jobs[name] = ""
        elif name is not None:
            jobs[name] += line + "\n"
    return jobs


def _jobs() -> dict[str, str]:
    return _jobs_of(PUBLISH.read_text(encoding="utf-8"))


def _job(name: str) -> str:
    return _jobs()[name]


def _first_step(job: str) -> str:
    return job.split("    steps:\n", 1)[1].lstrip().split("\n\n", 1)[0]


def _needs(job: str) -> set[str]:
    """The jobs a job needs, whether written as a scalar, an inline list or a multi-line list."""
    lines = job.splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"    needs:\s*(.*)", line)
        if not match:
            continue
        inline = re.sub(r"\s+#.*$", "", match.group(1)).strip()
        if inline:
            return {name.strip(" \"'") for name in inline.strip("[]").split(",") if name.strip(" \"'")}
        found = set()
        for following in lines[index + 1 :]:
            item = re.fullmatch(r"      - (\S+)\s*(#.*)?", following)
            if not item:
                break
            found.add(item.group(1).strip("\"'"))
        return found
    return set()


def _condition(job: str) -> str:
    """The job-level `if:`, including the continuation lines of a block scalar or a folded line."""
    lines = job.splitlines()
    for index, line in enumerate(lines):
        if re.fullmatch(r"    if:.*", line):
            condition = [line]
            for following in lines[index + 1 :]:
                if not following.strip() or len(following) - len(following.lstrip()) > 4:
                    condition.append(following)
                else:
                    break
            return "\n".join(condition)
    return ""


def _gated(name: str, jobs: dict[str, str], seen: frozenset[str] = frozenset()) -> bool:
    needs = _needs(jobs[name])
    return "verify-tag" in needs or any(
        other in jobs and other not in seen and _gated(other, jobs, seen | {name}) for other in needs
    )


def _after_publish(name: str, jobs: dict[str, str], seen: frozenset[str] = frozenset()) -> bool:
    needs = _needs(jobs[name])
    return "publish" in needs or any(
        other in jobs and other not in seen and _after_publish(other, jobs, seen | {name}) for other in needs
    )


def _violations(text: str) -> list[str]:
    jobs = _jobs_of(text)
    problems: list[str] = []
    for name, job in jobs.items():
        if not re.search(r"^    permissions:", job, re.MULTILINE):
            problems.append(f"{name}: no permissions of its own")
        if name == "verify-tag":
            if "continue-on-error" in job:
                problems.append("verify-tag: continue-on-error would let a failed check count as passed")
            if _first_step(job) != TAG_CHECK_STEP:
                problems.append("verify-tag: not the canonical tag check")
            continue
        if not _gated(name, jobs):
            problems.append(f"{name}: does not need verify-tag")
        if _STATUS_FUNCTION.search(_condition(job)):
            problems.append(f"{name}: a status function in its if: runs it although verify-tag failed")
        if re.search(r"^    uses:", job, re.MULTILINE):
            if _CREDENTIAL.search(job) and "verify-tag" not in _needs(job):
                problems.append(f"{name}: a credentialed reusable-workflow job must need verify-tag directly")
        elif (_CREDENTIAL.search(job) or _after_publish(name, jobs)) and _first_step(job) != TAG_CHECK_STEP:
            problems.append(f"{name}: a credentialed or release-following job must start with the canonical tag check")
    code = _code(text)
    triggers = re.search(r"\n    tags:\n((?:      - .*\n)+)", code)
    if triggers is None or [t.strip(' -"') for t in triggers.group(1).splitlines()] != [TAG_TRIGGER]:
        problems.append("the tag trigger is not exactly the strict glob")
    return problems


def test_every_job_of_publish_yml_is_gated_on_the_tag_check_and_credentialed_jobs_check_it_themselves() -> None:
    assert _violations(PUBLISH.read_text(encoding="utf-8")) == []


def test_the_current_jobs_are_found_and_classified() -> None:
    jobs = _jobs()

    assert set(jobs) == {
        "verify-tag",
        "test",
        "validate-server-json",
        "publish",
        "prepare-homebrew-formula",
        "push-homebrew-formula",
        "registry",
    }
    assert {name for name, job in jobs.items() if _CREDENTIAL.search(job)} == {
        "publish",
        "push-homebrew-formula",
        "registry",
    }
    assert {name for name in jobs if name != "verify-tag" and _after_publish(name, jobs)} == {
        "prepare-homebrew-formula",
        "push-homebrew-formula",
        "registry",
    }


def _mutated(old: str, new: str, *, job: str | None = None) -> str:
    """The real workflow with one edit, inside one job when named, and proof that the edit changed something."""
    text = PUBLISH.read_text(encoding="utf-8")
    if job is None:
        assert old in text, old
        return text.replace(old, new, 1)
    start = text.index(f"\n  {job}:\n")
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", text[start + 1 :])
    stop = start + 1 + following.start() if following else len(text)
    section = text[start:stop]
    assert old in section, (job, old)
    return text[:start] + section.replace(old, new, 1) + text[stop:]


_NEW_JOB = (
    "\n  extra:\n    runs-on: ubuntu-latest\n{needs}    permissions: {permissions}\n    steps:\n      - run: echo hi\n"
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            _mutated("    needs: verify-tag\n    runs-on", "    runs-on", job="validate-server-json"),
            "validate-server-json: does not",
        ),
        (_mutated("    needs: verify-tag\n    uses", "    uses", job="test"), "test: does not need verify-tag"),
        (
            _mutated(
                "    needs: verify-tag\n    runs-on", "    # needs: verify-tag\n    runs-on", job="validate-server-json"
            ),
            "validate-server-json: does not",
        ),
        (
            _mutated("needs: verify-tag\n    runs-on", "needs: [nowhere]\n    runs-on", job="validate-server-json"),
            "validate-server-json: does not",
        ),
        (_mutated("Verify tag is an exact plain SemVer", "Check the tag", job="registry"), "registry: a credentialed"),
        (_mutated("exit 1", "exit 0", job="registry"), "registry: a credentialed"),
        (
            _mutated(
                "        run: |\n          if [[",
                "        if: false\n        run: |\n          if [[",
                job="push-homebrew-formula",
            ),
            "push-homebrew-formula: a credentialed",
        ),
        (
            _mutated(
                "exit 1\n          fi\n",
                "exit 1\n          fi\n        continue-on-error: true\n",
                job="prepare-homebrew-formula",
            ),
            "prepare-homebrew-formula: a credentialed",
        ),
        (_mutated("    permissions: {}\n", "", job="verify-tag"), "verify-tag: no permissions"),
        (
            _mutated("    steps:\n", "    continue-on-error: true\n    steps:\n", job="verify-tag"),
            "verify-tag: continue-on-error",
        ),
        (
            _mutated(
                "    needs: [test, validate-server-json]\n",
                "    needs: [test, validate-server-json]\n    if: always()\n",
                job="publish",
            ),
            "publish: a status function",
        ),
        (
            _mutated(
                "    needs: verify-tag\n    uses",
                "    needs: verify-tag\n    if: ${{ !cancelled() }}\n    uses",
                job="test",
            ),
            "test: a status function",
        ),
        (
            _mutated(
                "    needs: [test, validate-server-json]\n",
                "    needs: [test, validate-server-json]\n    if: >-\n      always()\n",
                job="publish",
            ),
            "publish: a status function",
        ),
        (
            _mutated(
                "    needs: [test, validate-server-json]\n",
                "    needs: [test, validate-server-json]\n    if:\n      ${{ !cancelled() }}\n",
                job="publish",
            ),
            "publish: a status function",
        ),
        (
            _mutated("exit 1\n          fi\n", "exit 1\n          fi\n          echo extra\n", job="verify-tag"),
            "verify-tag: not the canonical tag check",
        ),
        (
            PUBLISH.read_text(encoding="utf-8")
            + '\n  "extra":\n    runs-on: ubuntu-latest\n    permissions: {}\n    steps:\n      - run: echo ${{ secrets.TOKEN }}\n',
            "extra: does not need verify-tag",
        ),
        (_mutated(f'- "{TAG_TRIGGER}"', '- "v*"'), "the tag trigger"),
        (_mutated(f'- "{TAG_TRIGGER}"', f'- "{TAG_TRIGGER}"\n      - "x*"'), "the tag trigger"),
        (
            PUBLISH.read_text(encoding="utf-8")
            + _NEW_JOB.format(needs="", permissions="{}").replace("echo hi", "echo ${{ secrets.TOKEN }}"),
            "extra: does not need verify-tag",
        ),
        (
            PUBLISH.read_text(encoding="utf-8")
            + _NEW_JOB.format(needs="    needs: verify-tag\n", permissions="{}").replace(
                "echo hi", "echo ${{ secrets.TOKEN }}"
            ),
            "extra: a credentialed",
        ),
        (
            PUBLISH.read_text(encoding="utf-8")
            + _NEW_JOB.format(needs="    needs: verify-tag\n", permissions="\n      packages: write"),
            "extra: a credentialed",
        ),
        (
            PUBLISH.read_text(encoding="utf-8")
            + "\n  extra:\n    needs: verify-tag\n    uses: ./.github/workflows/test.yml\n    permissions: {}\n    secrets: inherit\n".replace(
                "needs: verify-tag\n    uses", "needs: test\n    uses"
            ),
            "extra: a credentialed reusable-workflow job",
        ),
        (
            PUBLISH.read_text(encoding="utf-8")
            + _NEW_JOB.format(needs="    needs: verify-tag\n", permissions="{}").replace("    permissions: {}\n", ""),
            "extra: no permissions",
        ),
    ],
)
def test_a_job_that_escapes_the_tag_check_is_found(text: str, expected: str) -> None:
    assert any(problem.startswith(expected) for problem in _violations(text)), _violations(text)


@pytest.mark.parametrize(
    "text",
    [
        _mutated("  validate-server-json:\n", "  # fake-job:\n  validate-server-json:\n"),
        _mutated("    steps:\n", "    # needs: nothing\n    steps:\n", job="registry"),
        _mutated("needs: verify-tag\n    runs-on", "needs: [verify-tag]\n    runs-on", job="validate-server-json"),
        _mutated(
            "needs: verify-tag\n    runs-on", "needs: [ test , verify-tag ]\n    runs-on", job="validate-server-json"
        ),
        _mutated(
            "needs: verify-tag\n    runs-on", "needs:\n      - verify-tag\n    runs-on", job="validate-server-json"
        ),
        _mutated(
            "needs: verify-tag\n    runs-on",
            "needs: verify-tag # the tag check\n    runs-on",
            job="validate-server-json",
        ),
        _mutated("needs: verify-tag\n    runs-on", "needs: ['verify-tag']\n    runs-on", job="validate-server-json"),
        _mutated(
            "needs: verify-tag\n    runs-on",
            "needs:\n      - verify-tag # the tag check\n    runs-on",
            job="validate-server-json",
        ),
        _mutated(
            "    needs: verify-tag\n    uses", "    needs: verify-tag\n    if: ${{ success() }}\n    uses", job="test"
        ),
    ],
)
def test_comments_and_every_form_of_needs_are_read_correctly(text: str) -> None:
    assert _violations(text) == []


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
    privileged = [name for name, job in _jobs().items() if _holds_release_rights(job)]

    assert set(privileged) == {"publish", "registry"}
    for name in privileged:
        for tool in _BUILD_OR_LINT_TOOLS:
            assert tool not in _job(name), f"{name}: {tool}"


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
        job.index("uses: ./.github/actions/verify-dist") < job.index("actions/attest@") < job.index("run: uv publish")
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


def test_the_publish_job_attests_with_the_pinned_attest_action_not_the_wrapper() -> None:
    attest = _step(_job("publish"), "actions/attest@")

    assert re.match(r"actions/attest@[0-9a-f]{40} # v\d+\.\d+\.\d+\n", attest)
    assert 'subject-path: "dist/*"' in attest
    assert "attest-build-provenance" not in _code(PUBLISH.read_text(encoding="utf-8"))
