"""Shared fixtures for integration tests against a live OpenProject instance.

WARNING — these fixtures build a FULLY WRITE-ENABLED client (every
``enable_*_write`` flag on) and the write tests create and DELETE real data.
Every write/delete call passes ``confirm=True`` explicitly — there is no
auto-confirm setting. Run them ONLY against a disposable test instance or a
throwaway test project. NEVER point ``OPENPROJECT_BASE_URL`` /
``OPENPROJECT_API_TOKEN`` at a production instance or a project whose data you care
about — a failed cleanup, a bug, or an interrupted run can leave or destroy data.

Integration tests are opt-in: they are excluded from the default run and only
collected with ``-m integration``. When creds are absent every fixture skips.

Required environment variables:
    OPENPROJECT_BASE_URL       e.g. https://op.example.com
    OPENPROJECT_API_TOKEN      API token with admin access
    OPENPROJECT_TEST_PROJECT   DISPOSABLE project identifier to use (default: mcp-test)
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings

# Directory containing docker/test/compose.yml -- `docker compose exec` needs
# to run with this as its cwd (or -f pointed at it) to resolve the service name.
_DOCKER_TEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docker", "test")


def _run_rails_script(script: str, *, result_key: str, env: dict[str, str] | None = None) -> str:
    """Run a Ruby script via `docker compose exec ... rails runner` and return
    the value of a `puts "<result_key>=<value>"` line it's expected to print.

    Side channel for state OpenProject's own REST API has no endpoint for
    (minting another user's API token, reading DB-only identifiers) --
    requires OPENPROJECT_DOCKER_SERVICE; callers must check/skip on that
    themselves before calling this, since the skip reason differs per caller.

    `env`, when given, is passed to the container via `docker compose exec -e`
    (one flag pair per entry) so a caller-controlled value (e.g. a project
    identifier) reaches the script through `ENV[...]` in Ruby rather than
    being interpolated into the script's own source text -- interpolating an
    arbitrary Python-side string into Ruby source via f-string + repr() is a
    real code-injection risk (a value containing a single quote can make
    repr() emit a double-quoted Ruby literal, enabling "#{...}" interpolation
    inside the runner), not just a style preference.
    """
    service = os.environ["OPENPROJECT_DOCKER_SERVICE"]
    env_args = [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", *env_args, service, "bundle", "exec", "rails", "runner", "-"],
        input=script,
        cwd=_DOCKER_TEST_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(f"Rails runner script failed:\n{proc.stderr}")
    prefix = f"{result_key}="
    line = next((line for line in proc.stdout.splitlines() if line.startswith(prefix)), None)
    if line is None:
        pytest.fail(f"Rails runner did not print a {prefix} line:\n{proc.stdout}\n{proc.stderr}")
    return line.removeprefix(prefix)


# Project identifiers that must never be used as the disposable test project.
# These name real, non-throwaway projects; running the write suite against them
# would create and delete production data. Override the guard deliberately by
# setting OPENPROJECT_TEST_PROJECT to a throwaway project (default: mcp-test).
_PROTECTED_TEST_PROJECTS = frozenset({"openproject-ce-mcp"})


def _resolve_test_project() -> str:
    """Return the disposable test project, refusing known non-throwaway ones."""
    project = os.environ.get("OPENPROJECT_TEST_PROJECT", "mcp-test").strip()
    if project.lower() in _PROTECTED_TEST_PROJECTS:
        pytest.fail(
            f"Refusing to run write integration tests against protected project "
            f"'{project}'. Set OPENPROJECT_TEST_PROJECT to a disposable/throwaway "
            f"project (default: mcp-test)."
        )
    return project


def disposable_project_identifier() -> str:
    """A fresh, valid project identifier for a test's own throwaway project.

    Must satisfy BOTH identifier grammars this suite can run against: classic
    mode's lowercase/hyphen-friendly rules, and semantic mode's much stricter
    ones (uppercase letters/digits/underscore only, must start with a letter,
    max 10 characters -- verified live against a Docker instance with
    SEED_SEMANTIC=1, e.g. Project#identifier's format/length validators
    reject "integration-test-<8 hex chars>", the pattern every call site here
    used before this helper existed). An uppercase, <=10-char identifier is
    accepted by both grammars, so this format works unconditionally rather
    than needing to branch on which mode the instance is running in.
    """
    return f"IT{uuid.uuid4().hex[:8].upper()}"


def _integration_settings() -> Settings | None:
    base_url = os.environ.get("OPENPROJECT_BASE_URL")
    api_token = os.environ.get("OPENPROJECT_API_TOKEN")
    test_project = os.environ.get("OPENPROJECT_TEST_PROJECT", "mcp-test").strip()
    if not base_url or not api_token:
        return None
    return Settings(
        base_url=base_url,
        api_token=api_token,
        timeout=30,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=(test_project,),
        write_projects=(test_project,),
        enable_admin_read=True,
        enable_admin_write=True,
        enable_project_write=True,
        enable_work_package_write=True,
        enable_membership_write=True,
        enable_version_write=True,
        enable_board_write=True,
        enable_personal_read=True,
        enable_personal_write=True,
        enable_metadata_tools=True,
    )


@pytest.fixture
async def client():
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    # Fail fast before handing out a write-enabled client aimed at a protected project.
    _resolve_test_project()
    client_instance = OpenProjectClient(settings)
    await client_instance.initialize()
    return client_instance


@pytest.fixture
def test_project() -> str:
    return _resolve_test_project()


@pytest.fixture
async def denied_client():
    """A client scoped to deny writes to ``test_project`` while still allowing reads.

    Read stays scoped to ``test_project`` so a live HAL link resolving to that
    project passes the read-allowlist gate every write-allowlist check runs
    first; only the write allowlist is configured to a literal, non-matching
    identifier, so PermissionDeniedError comes from the write-scope check the
    test is actually meant to exercise, not the unrelated read gate.
    """
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    _resolve_test_project()
    denied_settings = dataclasses.replace(
        settings,
        write_projects=("no-such-project-for-integration-tests",),
    )
    client_instance = OpenProjectClient(denied_settings)
    await client_instance.initialize()
    return client_instance


# ---------------------------------------------------------------------------
# Cleanup helpers for write tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def wp_ids(client: OpenProjectClient):
    """Yields a list to append created WP IDs; deletes them all after the test."""
    created: list[int] = []
    yield created
    for wp_id in created:
        try:
            await client.delete_work_package(work_package_id=wp_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def version_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    for version_id in created:
        try:
            await client.delete_version(version_id=version_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def news_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    for news_id in created:
        try:
            await client.delete_news(news_id=news_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def time_entry_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    for te_id in created:
        try:
            await client.delete_time_entry(time_entry_id=te_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def group_ids(client: OpenProjectClient):
    """Yields a list to append created group IDs; deletes them all after the test.

    Groups are instance-wide, not project-scoped — unlike every other cleanup
    fixture here, cleanup touches state outside ``test_project``.
    """
    created: list[int] = []
    yield created
    for group_id in created:
        try:
            await client.delete_group(group_id=group_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def grid_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    for grid_id in created:
        try:
            await client.delete_grid(grid_id=grid_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def reminder_ids(client: OpenProjectClient):
    """Yields a list to append created reminder IDs; deletes them all after the test.

    Reminders are per-user, not project-scoped -- like group_ids, cleanup
    reaches outside test_project, but delete_reminder's own allowlist check
    resolves the reminder's underlying work package's project, which stays
    within test_project for every current test that uses this fixture.
    """
    created: list[int] = []
    yield created
    for reminder_id in created:
        try:
            await client.delete_reminder(reminder_id=reminder_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def user_ids(client: OpenProjectClient):
    """Yields a list to append created user IDs; deletes them all after the test.

    Users are instance-wide, not project-scoped — the same caveat as
    ``group_ids``/``project_refs`` above.
    """
    created: list[int] = []
    yield created
    for user_id in created:
        try:
            await client.delete_user(user_id, confirm=True)
        except Exception:
            pass


@pytest.fixture
async def second_user_client(client: OpenProjectClient, user_ids: list[int]):
    """Creates a real, disposable second OpenProject user via create_user, then
    mints an API token for them via a Rails-runner side channel (the same
    mechanism docker/test/seed.rb uses for the admin's own token — OpenProject's
    REST API has no endpoint to mint a token for another user, only the Rails
    console can) and returns a second, fully independent OpenProjectClient
    authenticated as that user.

    Needed for tests that must prove a notification/activity was triggered BY
    one user and observed FROM a different user's own perspective (list_notifications/
    mark_notification_read have no `user` parameter -- they always act on the
    token owner's own inbox), which a single admin-token client can't exercise.

    Requires OPENPROJECT_DOCKER_SERVICE (e.g. "op-17-4") naming the running
    docker/test/compose.yml service to `docker compose exec` into; skips
    cleanly if unset, since minting a second real user's token has no
    REST-API-only equivalent to fall back to. Only ever run this against the
    disposable Docker test instance -- never a real, actively-used one.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to mint a second user's API token)")

    suffix = uuid.uuid4().hex[:8]
    login = f"integration-test-{suffix}"
    create_result = await client.create_user(
        login=login,
        email=f"{login}@example.invalid",
        firstname="Integration",
        lastname=f"Test {suffix}",
        # Never used for login (auth is via the minted token below); must still
        # satisfy the instance's password complexity policy (lower/upper/digit/special).
        password=f"Aa1!{uuid.uuid4().hex}",
        confirm=True,
    )
    assert create_result.ready, create_result.validation_errors
    user_id = create_result.user_id
    assert user_id is not None
    user_ids.append(user_id)

    script = f"""
        user = User.find({user_id})
        token = Token::API.create!(user: user)
        puts "TOKEN=#{{token.plain_value}}"
    """
    token = _run_rails_script(script, result_key="TOKEN")

    second_settings = dataclasses.replace(client.settings, api_token=token)
    second_client = OpenProjectClient(second_settings)
    await second_client.initialize()
    return user_id, second_client


@pytest.fixture
def seed_wiki_page_id(test_project: str) -> int:
    """Returns the id of test_project's seeded wiki page.

    get_wiki_page has no create/list counterpart in OpenProject's own API (see
    docker/test/seed.rb's own comment on this) -- the seed script creates one
    page ahead of time, but its numeric id depends on the instance's DB
    history, not a fixed/predictable value, so it must be looked up via the
    same Rails-runner side channel used elsewhere in this file. Requires
    OPENPROJECT_DOCKER_SERVICE; skips cleanly if unset.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to look up the seeded wiki page id)")

    # Project.find_by(identifier:) is case-sensitive, and the stored casing
    # itself varies: classic mode always lowercases, but semantic mode
    # (verified live against a Docker instance with SEED_SEMANTIC=1) stores
    # the identifier exactly as seeded (e.g. "TST", uppercase) -- comparing
    # case-insensitively in Ruby avoids having to guess which mode produced
    # the running instance's actual casing.
    script = """
        project = Project.find_by("LOWER(identifier) = ?", ENV.fetch("PROJECT_IDENTIFIER").downcase)
        page = project&.wiki&.pages&.first
        puts "PAGE_ID=#{page&.id}"
    """
    value = _run_rails_script(script, result_key="PAGE_ID", env={"PROJECT_IDENTIFIER": test_project.strip()})
    if value == "":
        pytest.skip(f"test_project {test_project!r} has no wiki page (unexpected -- check docker/test/seed.rb ran)")
    return int(value)


@pytest.fixture
def seed_project_phase_id(test_project: str) -> int:
    """Returns the id of test_project's seeded Project::Phase instance.

    get_project_phase has no list/create counterpart in OpenProject's own API
    (a project has zero phase instances by default; docker/test/seed.rb
    creates one ahead of time). Requires OPENPROJECT_DOCKER_SERVICE; skips
    cleanly if unset, same as seed_wiki_page_id.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to look up the seeded project phase id)")

    # Same case-insensitivity rationale as seed_wiki_page_id above.
    script = """
        project = Project.find_by("LOWER(identifier) = ?", ENV.fetch("PROJECT_IDENTIFIER").downcase)
        phase = project && Project::Phase.where(project_id: project.id).first
        puts "PHASE_ID=#{phase&.id}"
    """
    value = _run_rails_script(script, result_key="PHASE_ID", env={"PROJECT_IDENTIFIER": test_project.strip()})
    if value == "":
        pytest.skip(f"test_project {test_project!r} has no project phase (unexpected -- check docker/test/seed.rb ran)")
    return int(value)


@pytest.fixture
async def project_refs(client: OpenProjectClient):
    """Yields a list to append created project identifiers; deletes them all
    after the test.

    Projects are instance-wide, not scoped to ``test_project`` — the same
    caveat as ``group_ids`` above. Only used by tests that genuinely need a
    second, disposable project (e.g. as a parent-project picklist candidate),
    which by construction lives outside test_project's own read/write
    allowlist — cleanup therefore needs its own unrestricted client rather
    than the scoped ``client`` fixture, or delete_project's own allowlist
    check would reject the cleanup call.
    """
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    created: list[str] = []
    yield created
    for project_ref in created:
        try:
            await unrestricted_client.delete_project(project_ref=project_ref, confirm=True)
        except Exception:
            pass
