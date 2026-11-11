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
    OPENPROJECT_TEST_PROJECT   DISPOSABLE project identifier to use, no default
    OPENPROJECT_TEST_DESTRUCTIVE_TARGET
                               a non-loopback target only: the base URL again, as the acknowledgement that this
                               instance may be written to

A run that sets some of these but not all of them, or names a project that does not look disposable, stops before
the first test (``tools/live_target_guard.py``). ``docker/test/up.sh`` prints the set for a local instance.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient
from openproject_ce_mcp.config import Settings

# tools/ is not a package; the benchmark script loads the same guard the same way. This directory joins the
# path too, so a unit test that loads this file by path finds the helper next to it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_target_guard  # noqa: E402
from _live_cleanup import ClientRegistry, delete_all, require_admin_for_wide_writes  # noqa: E402
from _write_ref import write_ref  # noqa: E402

# Directory containing docker/test/compose.yml -- `docker compose exec` needs
# to run with this as its cwd (or -f pointed at it) to resolve the service name.
_DOCKER_TEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docker", "test")


class RailsCapabilityUnavailable(RuntimeError):
    """Raised by `_run_rails_script` when `capability_check` was given and
    evaluated false -- signals "this Ruby capability doesn't exist on this
    OpenProject version," distinguishable from a real script failure.
    Callers that are version-gated (multi_target_versions_enabled/_disabled)
    catch this and skip; callers that don't pass `capability_check` never
    see it.
    """


_RAILS_CAPABILITY_UNAVAILABLE_SENTINEL = "__RAILS_CAPABILITY_UNAVAILABLE__"


def _run_rails_script(
    script: str,
    *,
    result_key: str,
    env: dict[str, str] | None = None,
    capability_check: str | None = None,
) -> str:
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

    `capability_check`, when given, is a Ruby boolean expression (e.g.
    "Setting.respond_to?(:work_package_multiple_versions=)") checked
    structurally BEFORE `script` runs -- not by parsing stderr text for
    "NoMethodError," which would be fragile (message wording isn't a stable
    contract, and could false-positive on an unrelated NoMethodError from
    inside the script's own body). If it evaluates false, the real script
    body never runs and this function raises RailsCapabilityUnavailable
    instead of its normal return -- callers that are version-gated catch
    this and skip; callers that don't pass capability_check never see it
    (their contract is unchanged: fail loudly on any real error).

    TRUST BOUNDARY: `capability_check` is embedded as raw, unescaped Ruby
    source -- every caller must pass a fixed literal string (a hardcoded
    Ruby expression naming a method/setting to probe), never a value built
    from external input (env vars, fixture parameters, anything
    caller-controlled). Doing so would be real Ruby code injection, the
    same class of risk this function's own `env` parameter already exists
    specifically to avoid for script *values* -- this parameter has no
    equivalent safety net, so its literal-only contract must hold.
    """
    service = os.environ["OPENPROJECT_DOCKER_SERVICE"]
    env_args = [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]
    full_script = script
    if capability_check is not None:
        full_script = f'if {capability_check}\n{script}\nelse\n  puts "{_RAILS_CAPABILITY_UNAVAILABLE_SENTINEL}"\nend\n'
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", *env_args, service, "bundle", "exec", "rails", "runner", "-"],
        input=full_script,
        cwd=_DOCKER_TEST_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(f"Rails runner script failed:\n{proc.stderr}")
    if capability_check is not None and _RAILS_CAPABILITY_UNAVAILABLE_SENTINEL in proc.stdout.splitlines():
        raise RailsCapabilityUnavailable(f"capability check failed: {capability_check}")
    prefix = f"{result_key}="
    line = next((line for line in proc.stdout.splitlines() if line.startswith(prefix)), None)
    if line is None:
        pytest.fail(f"Rails runner did not print a {prefix} line:\n{proc.stdout}\n{proc.stderr}")
    return line.removeprefix(prefix)


@pytest.fixture(scope="session", autouse=True)
def _destructive_target_guard() -> None:
    """Stops the whole session before any test writes to a target nobody named on purpose.

    Without a base URL and a token there is no live target, and every fixture skips.
    """
    if not os.environ.get("OPENPROJECT_BASE_URL") and not os.environ.get("OPENPROJECT_API_TOKEN"):
        return
    try:
        live_target_guard.require_destructive_target(os.environ)
    except live_target_guard.LiveTargetRefused as refusal:
        pytest.exit(f"Refusing to run the destructive integration suite: {refusal}", returncode=2)


async def skip_if_unsupported(probe_call):
    """Await `probe_call()`; skip the test if it raises NotFoundError.

    Some domains (emoji reactions, project phases: added in 16.1) don't
    exist as routes at all on older supported servers -- a 404 there means
    "not on this version," not a real failure. Returns the probe's result
    so callers can reuse it instead of a second real call.
    """
    try:
        return await probe_call()
    except NotFoundError:
        pytest.skip("endpoint not available on this OpenProject version")


async def wait_for_not_found(get_call, *, timeout: float = 15.0) -> None:
    """Poll `get_call()` until it raises NotFoundError, or fail after `timeout`.

    Some deletes (groups, users) are `success_status: 202` server-side --
    background-job async, not synchronous -- so a GET right after delete can
    still find the resource briefly.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            await get_call()
        except NotFoundError:
            return
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(f"resource still found {timeout}s after a confirmed delete (async delete job never finished?)")
        await asyncio.sleep(0.5)


def disposable_project_identifier() -> str:
    """A fresh, valid project identifier for a test's own throwaway project.

    <=10 chars, starts with a letter. Project#identifier's format validator
    requires lowercase on classic-mode instances and uppercase on
    semantic-mode ones -- there is no single format both grammars accept
    (verified independently against live Docker instances of each: an
    uppercase identifier is rejected on classic mode with "Identifier is
    invalid.", a lowercase one is rejected on semantic mode with "Multiple
    field constraints have been violated."). Casing is derived from
    OPENPROJECT_TEST_PROJECT's own casing, which docker/test/up.sh already
    prints correctly per instance (lowercase "tst" for classic, uppercase
    "TST" for semantic -- see docker/test/README.md) -- an all-lowercase
    OPENPROJECT_TEST_PROJECT is treated as classic, anything containing an
    uppercase letter as semantic. This mirrors the same signal
    seed_wiki_page_id (below) already relies on.
    """
    test_project = os.environ["OPENPROJECT_TEST_PROJECT"].strip()
    suffix = uuid.uuid4().hex[:8]
    if test_project != test_project.lower():
        return f"IT{suffix.upper()}"
    return f"it{suffix}"


def _integration_settings() -> Settings | None:
    base_url = os.environ.get("OPENPROJECT_BASE_URL")
    api_token = os.environ.get("OPENPROJECT_API_TOKEN")
    if not base_url or not api_token:
        return None
    test_project = os.environ["OPENPROJECT_TEST_PROJECT"].strip()
    return Settings(
        base_url=base_url,
        api_token=SecretStr(api_token),
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
        enable_user_schedule_read=True,
        enable_user_schedule_write=True,
        enable_metadata_tools=True,
    )


@pytest.fixture(scope="function")
async def open_client():
    """Opens clients and closes every one of them after the test, in reverse order."""
    registry = ClientRegistry(
        before_open=require_admin_for_wide_writes(os.environ.get("OPENPROJECT_TEST_PROJECT", "").strip())
    )
    try:
        yield registry.open
    finally:
        await registry.close()


@pytest.fixture
async def client(open_client):
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    return await open_client(settings)


@pytest.fixture
async def start_scoped_client(open_client):
    """Starts clients with their own project scopes, each at the moment the
    test asks, and closes them after the test."""
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")

    async def start(*, read_projects: tuple[str, ...], write_projects: tuple[str, ...]) -> OpenProjectClient:
        return await open_client(
            dataclasses.replace(settings, read_projects=read_projects, write_projects=write_projects)
        )

    return start


@pytest.fixture
def test_project() -> str:
    project = os.environ.get("OPENPROJECT_TEST_PROJECT", "").strip()
    if not project:
        pytest.skip("OPENPROJECT_TEST_PROJECT not set")
    return project


@pytest.fixture
async def openproject_version() -> tuple[int, int]:
    """The instance's (major, minor), read from the API root's `coreVersion`,
    which OpenProject shows to admins only -- the integration token is one."""
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    async with httpx.AsyncClient(
        auth=("apikey", settings.api_token.get_secret_value()), timeout=settings.timeout
    ) as http:
        response = await http.get(f"{settings.base_url.rstrip('/')}/api/v3")
    response.raise_for_status()
    core_version = response.json().get("coreVersion")
    if core_version is None:
        pytest.skip("The token is not an admin: OpenProject shows `coreVersion` to admins only.")
    major, minor = core_version.split(".")[:2]
    return int(major), int(minor)


@pytest.fixture
async def denied_client(open_client):
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
    denied_settings = dataclasses.replace(
        settings,
        write_projects=("no-such-project-for-integration-tests",),
    )
    return await open_client(denied_settings)


@pytest.fixture
async def admin_write_disabled_client(open_client):
    """A client with OPENPROJECT_ENABLE_ADMIN_WRITE off, everything else
    (including enable_admin_read and both project allowlists) identical to
    the normal integration client -- for the Users/Groups admin-write-disabled
    denial tests. Users/Groups are gated by this dedicated opt-in flag
    (config.py's `enable_admin_write` field, mapped from
    OPENPROJECT_ENABLE_ADMIN_WRITE via access.py's _WRITE_SCOPE_ENV_VAR["admin"]),
    not the per-project write allowlist denied_client exercises -- keeping
    read access and the write allowlist unchanged from the normal client
    ensures PermissionDeniedError comes from the admin-write flag check
    (access.ensure_write_enabled("admin", ...)) the test is actually meant
    to exercise, not an unrelated read or allowlist gate.
    """
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    disabled_settings = dataclasses.replace(settings, enable_admin_write=False)
    return await open_client(disabled_settings)


@pytest.fixture
async def hide_custom_fields_client(open_client):
    """A client with every custom field hidden (OPENPROJECT_HIDE_CUSTOM_FIELDS
    equivalent, via a `cf_*` glob), for the hidden-custom-field-filter
    rejection test -- read/write scope stays identical to the default
    integration client, only hide_custom_fields differs."""
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    hidden_settings = dataclasses.replace(settings, hide_custom_fields=("cf_*",))
    return await open_client(hidden_settings)


@pytest.fixture
async def restricted_client(open_client):
    """A client authenticated as a genuinely permission-restricted OpenProject
    user (log_own_time granted, log_time/view_time_entries/manage_members
    withheld -- see docker/test/seed.rb) -- unlike denied_client (which tests
    only this MCP server's OWN write-allowlist config layer), this exercises
    a REAL OpenProject role boundary.

    Requires OPENPROJECT_RESTRICTED_API_TOKEN, set by docker/test/up.sh from
    seed.rb's restricted-user provisioning; skips cleanly if unset.
    """
    restricted_token = os.environ.get("OPENPROJECT_RESTRICTED_API_TOKEN")
    if not restricted_token:
        pytest.skip("OPENPROJECT_RESTRICTED_API_TOKEN not set")
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    restricted_settings = dataclasses.replace(settings, api_token=SecretStr(restricted_token))
    return await open_client(restricted_settings)


# ---------------------------------------------------------------------------
# Cleanup helpers for write tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def wp_ids(client: OpenProjectClient):
    """Yields a list to append created WP IDs; deletes them all after the test."""
    created: list[int] = []
    yield created

    async def delete_work_package(wp_id: int) -> object:
        return await client.work_package.delete(work_package_id=await write_ref(client, wp_id), confirm=True)

    await delete_all("work package", created, delete_work_package)


@pytest.fixture
async def version_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    await delete_all("version", created, lambda version_id: client.version.delete(version_id=version_id, confirm=True))


@pytest.fixture
async def news_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    await delete_all("news", created, lambda news_id: client.news.delete(news_id=news_id, confirm=True))


@pytest.fixture
async def time_entry_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    await delete_all("time entry", created, lambda te_id: client.time_entry.delete(time_entry_id=te_id, confirm=True))


@pytest.fixture
async def board_ids(client: OpenProjectClient):
    created: list[int] = []
    yield created
    await delete_all("board", created, lambda board_id: client.board.delete(board_id=board_id, confirm=True))


@pytest.fixture
async def meeting_ids(client: OpenProjectClient):
    """Yields a list to append created meeting IDs; deletes them all after
    the test. Agenda items/sections/outcomes cascade-delete with their
    parent meeting server-side (standard Rails dependent: :destroy on each
    association) -- registering only the parent Meeting's id here is
    sufficient cleanup for those sub-resources too. A meeting materialized
    from a recurring-meeting occurrence via init_recurring_meeting_occurrence
    is a real, standalone Meeting -- register its id here as well, not in a
    separate fixture.
    """
    created: list[int] = []
    yield created
    await delete_all("meeting", created, lambda meeting_id: client.meeting.delete(meeting_id=meeting_id, confirm=True))


@pytest.fixture
async def recurring_meeting_ids(client: OpenProjectClient):
    """Yields a list to append created recurring-meeting-series IDs; deletes
    them all after the test."""
    created: list[int] = []
    yield created
    await delete_all(
        "recurring meeting",
        created,
        lambda recurring_meeting_id: client.recurring_meeting.delete(
            recurring_meeting_id=recurring_meeting_id, confirm=True
        ),
    )


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
    await delete_all(
        "reminder", created, lambda reminder_id: client.reminder.delete(reminder_id=reminder_id, confirm=True)
    )


@pytest.fixture
async def group_ids(client: OpenProjectClient):
    """Yields a list to append created group IDs; deletes them all after the test.

    Groups are instance-wide, not project-scoped — unlike every other cleanup
    fixture here, cleanup touches state outside ``test_project``.
    """
    created: list[int] = []
    yield created
    await delete_all("group", created, lambda group_id: client.group.delete(group_id=group_id, confirm=True))


@pytest.fixture
async def storage_ids(client: OpenProjectClient):
    """Yields a list to append created storage IDs; deletes them all after the test.

    Storages are instance-wide, not project-scoped — the same caveat as
    ``group_ids`` above.
    """
    created: list[int] = []
    yield created
    await delete_all("storage", created, lambda storage_id: client.storage.delete(storage_id, confirm=True))


@pytest.fixture
async def user_ids(client: OpenProjectClient):
    """Yields a list to append created user IDs; deletes them all after the test.

    Users are instance-wide, not project-scoped — the same caveat as
    ``group_ids``/``project_refs`` above.
    """
    created: list[int] = []
    yield created
    await delete_all("user", created, lambda user_id: client.user.delete(user_id, confirm=True))


@pytest.fixture
async def second_user_client(client: OpenProjectClient, user_ids: list[int], open_client):
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
    create_result = await client.user.create(
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

    second_settings = dataclasses.replace(client.settings, api_token=SecretStr(token))
    return user_id, await open_client(second_settings)


@pytest.fixture
async def workflow_limited_editor_client(
    client: OpenProjectClient, test_project: str, user_ids: list[int], open_client
):
    """A client for a disposable member who may edit work packages but whose
    role grants one transition only: a Task may move from "New" to "In
    progress", a Bug none. The role, its workflow rows and the membership are
    provisioned through a Rails runner (OpenProject's REST API has no endpoint
    for workflows or roles), idempotently by role name.

    OpenProject 17.9 keys a workflow row to the type's default `TypeVariant`,
    earlier versions to the type itself; the script handles both.
    """
    if not os.environ.get("OPENPROJECT_DOCKER_SERVICE"):
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to provision a workflow-limited role)")

    suffix = uuid.uuid4().hex[:8]
    login = f"integration-test-{suffix}"
    create_result = await client.user.create(
        login=login,
        email=f"{login}@example.invalid",
        firstname="Integration",
        lastname=f"Limited {suffix}",
        password=f"Aa1!{uuid.uuid4().hex}",
        confirm=True,
    )
    assert create_result.ready, create_result.validation_errors
    user_id = create_result.user_id
    assert user_id is not None
    user_ids.append(user_id)

    script = """
        permissions = [:view_work_packages, :view_project, :edit_work_packages]
        role = ProjectRole.find_or_create_by!(name: "Integration Test Workflow Limited")
        role.update!(permissions: permissions)
        project = Project.where("LOWER(identifier) = ?", ENV.fetch("PROJECT_IDENTIFIER").downcase).first
        user = User.find(ENV.fetch("USER_ID"))
        member = Member.find_or_initialize_by(project: project, principal: user)
        member.roles = [role]
        member.save!
        task = Type.find_by!(name: "Task")
        from_status = Status.find_by!(name: "New")
        to_status = Status.find_by!(name: "In progress")
        Workflow.where(role_id: role.id).delete_all
        if Workflow.column_names.include?("type_variant_id")
          variant = TypeVariant.find_by!(type_id: task.id, is_default_variant: true)
          Workflow.create!(role: role, type_variant: variant, old_status: from_status, new_status: to_status)
        else
          Workflow.create!(role_id: role.id, type_id: task.id, old_status_id: from_status.id, new_status_id: to_status.id)
        end
        puts "TOKEN=#{Token::API.create!(user: user).plain_value}"
    """
    token = _run_rails_script(
        script, result_key="TOKEN", env={"PROJECT_IDENTIFIER": test_project.strip(), "USER_ID": str(user_id)}
    )
    return await open_client(dataclasses.replace(client.settings, api_token=SecretStr(token)))


@pytest.fixture
async def user_non_working_time_ids(client: OpenProjectClient):
    """Yields a list to append (user_ref, non_working_time_id) pairs; deletes
    them all after the test.

    User-scoped, not project-scoped -- same caveat as ``group_ids``/
    ``user_ids`` above.
    """
    created: list[tuple[str, int]] = []
    yield created
    await delete_all(
        "user non working time",
        created,
        lambda pair: client.user_non_working_time.delete(pair[0], pair[1], confirm=True),
    )


@pytest.fixture
async def user_working_hours_ids(client: OpenProjectClient):
    """Yields a list to append (user_ref, working_hours_id) pairs; deletes
    them all after the test.

    User-scoped, not project-scoped -- same caveat as ``group_ids``/
    ``user_ids`` above.
    """
    created: list[tuple[str, int]] = []
    yield created
    await delete_all(
        "user working hours", created, lambda pair: client.user_working_hours.delete(pair[0], pair[1], confirm=True)
    )


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
def internal_wiki_provider_id() -> int:
    """Returns the numeric id of OpenProject's internal wiki provider.

    The inline wiki link macro in a description, `[[[<provider id>:<identifier>]]]`,
    names the provider by this id, which the REST API never exposes (it links
    providers by their universal identifier, e.g. "internal"). Requires
    OPENPROJECT_DOCKER_SERVICE; skips cleanly if unset.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to look up the internal wiki provider id)")

    script = """
        provider = defined?(Wikis::InternalProvider) ? Wikis::InternalProvider.first : nil
        puts "PROVIDER_ID=#{provider&.id}"
    """
    value = _run_rails_script(script, result_key="PROVIDER_ID")
    if value == "":
        pytest.skip("this instance has no internal wiki provider (OpenProject 17.4+)")
    return int(value)


@pytest.fixture
def seed_post_id(test_project: str) -> int:
    """Returns the id of test_project's seeded forum post (Message).

    get_post has no create/list counterpart in OpenProject's own API (see
    docker/test/seed.rb's own comment on this) -- the seed script creates a
    Forum + one Message ahead of time, but the message's numeric id depends
    on the instance's DB history, not a fixed/predictable value, so it must
    be looked up via the same Rails-runner side channel used elsewhere in
    this file. Requires OPENPROJECT_DOCKER_SERVICE; skips cleanly if unset,
    same as seed_wiki_page_id.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to look up the seeded post id)")

    # Same case-insensitivity rationale as seed_wiki_page_id above.
    script = """
        project = Project.find_by("LOWER(identifier) = ?", ENV.fetch("PROJECT_IDENTIFIER").downcase)
        message = project && Forum.where(project: project).first&.messages&.first
        puts "MESSAGE_ID=#{message&.id}"
    """
    value = _run_rails_script(script, result_key="MESSAGE_ID", env={"PROJECT_IDENTIFIER": test_project.strip()})
    if value == "":
        pytest.skip(f"test_project {test_project!r} has no forum post (unexpected -- check docker/test/seed.rb ran)")
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
def meeting_title_in_database() -> Callable[[int], str | None]:
    """Returns a reader for a meeting's title straight from the database.

    The meeting representer cache keys on updated_at, which an `update_all`
    leaves untouched, so the API can keep serving a title the database no
    longer holds. Requires OPENPROJECT_DOCKER_SERVICE; skips cleanly if unset.
    """
    if not os.environ.get("OPENPROJECT_DOCKER_SERVICE"):
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to read a meeting title from the database)")

    script = """
        puts "TITLE=#{Meeting.where(id: Integer(ENV.fetch("MEETING_ID"))).pick(:title).to_json}"
    """

    def read(meeting_id: int) -> str | None:
        value: str | None = json.loads(
            _run_rails_script(script, result_key="TITLE", env={"MEETING_ID": str(meeting_id)})
        )
        return value

    return read


@pytest.fixture
async def project_refs(client: OpenProjectClient, open_client):
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
    unrestricted_client = await open_client(unrestricted_settings)

    async def delete_and_wait(project_ref: str) -> None:
        await unrestricted_client.project.delete(project_ref=project_ref, confirm=True)
        # The delete runs as a background job; the next test's project create or work package form
        # deadlocks or fails on 16.0 while it still holds the nested-set rows.
        for _ in range(60):
            try:
                await unrestricted_client.project.get(project_ref)
            except NotFoundError:
                return
            await asyncio.sleep(0.5)
        raise TimeoutError("the background delete job did not finish within 30 s")

    created: list[str] = []
    yield created
    await delete_all("project", created, delete_and_wait)


_WP_MULTI_VERSIONS_CAPABILITY_CHECK = "Setting.respond_to?(:work_package_multiple_versions=)"


def _set_multi_target_versions(*, enabled: bool) -> bool:
    """Force Setting::WorkPackageMultipleVersions to a known state via a Rails
    runner script (OpenProject's REST API has no endpoint for instance-wide
    settings), then re-read Setting::WorkPackageMultipleVersions.active? and
    return the value it actually reached. Requires OPENPROJECT_DOCKER_SERVICE;
    callers must skip on that themselves first, matching every other
    _run_rails_script caller in this file.

    Raises RailsCapabilityUnavailable if Setting.work_package_multiple_versions=
    doesn't exist on this OpenProject version (16.0-17.6) -- callers
    (multi_target_versions_enabled/_disabled) catch this and skip instead of
    crashing on a live NoMethodError.

    Setting.work_package_multiple_versions=true is not always sufficient on
    its own: on OpenProject 17.7 (targetVersions/this setting are not
    17.8-exclusive -- both already exist there), .active? additionally
    requires an experimental OpenProject::FeatureDecisions flag this project
    does not set, so the plain Setting write alone leaves .active? false --
    verified directly against the pinned 17.7 sources
    (Setting::WorkPackageMultipleVersions.active? there checks
    `Setting.work_package_multiple_versions? &&
    OpenProject::FeatureDecisions.work_package_multiple_versions_active?`).
    17.8 drops that extra gate. Re-reading .active? rather than trusting the
    write succeeded is what lets callers (multi_target_versions_enabled)
    detect and skip cleanly on 17.7 instead of proceeding as if multi-version
    writes were actually enabled. OpenProject 17.8.0 ships this setting with
    default: true (config/constants/settings/definition.rb of the image) --
    docker/test/seed.rb already forces it to a known state on every up.sh
    run (see that script's own comment), but a test must not rely on
    whichever state seed.rb happened to leave it in, since another test in
    the same session may have changed it.
    """
    script = f"""
        Setting.work_package_multiple_versions = {"true" if enabled else "false"}
        puts "VALUE=#{{Setting::WorkPackageMultipleVersions.active?}}"
    """
    return _run_rails_script(script, result_key="VALUE", capability_check=_WP_MULTI_VERSIONS_CAPABILITY_CHECK) == "true"


_MULTI_VERSIONS_UNSUPPORTED_SKIP = (
    "Setting::WorkPackageMultipleVersions does not exist on this OpenProject version (requires 17.7+)"
)


@pytest.fixture
def multi_target_versions_enabled():
    """Forces Setting::WorkPackageMultipleVersions on for the duration of the
    test, restoring the prior value afterward. Requires
    OPENPROJECT_DOCKER_SERVICE; skips cleanly if unset -- the same
    requirement _run_rails_script itself has, checked here up front so the
    skip reason names this fixture specifically. Also skips cleanly if the
    setting doesn't exist on this OpenProject version at all (16.0-17.6,
    see RailsCapabilityUnavailable), or if the setting could not actually be
    activated (e.g. OpenProject 17.7 without its experimental
    FeatureDecisions flag -- see _set_multi_target_versions's docstring)
    rather than letting the test proceed against a server that will reject
    its multi-value write.
    """
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to toggle Setting::WorkPackageMultipleVersions)")
    try:
        script = 'puts "VALUE=#{Setting.work_package_multiple_versions?}"'
        previous = (
            _run_rails_script(script, result_key="VALUE", capability_check=_WP_MULTI_VERSIONS_CAPABILITY_CHECK)
            == "true"
        )
        actual = _set_multi_target_versions(enabled=True)
    except RailsCapabilityUnavailable:
        pytest.skip(_MULTI_VERSIONS_UNSUPPORTED_SKIP)
    if not actual:
        _set_multi_target_versions(enabled=previous)
        pytest.skip(
            "Setting::WorkPackageMultipleVersions.active? stayed false after enabling the setting -- "
            "on OpenProject 17.7 this also requires an experimental OpenProject::FeatureDecisions flag "
            "this project does not set."
        )
    yield
    _set_multi_target_versions(enabled=previous)


@pytest.fixture
def multi_target_versions_disabled():
    """Forces Setting::WorkPackageMultipleVersions off for the duration of
    the test, restoring the prior value afterward. See
    multi_target_versions_enabled's docstring for the shared rationale.
    Disabling never has the 17.7 FeatureDecisions caveat (the AND in
    .active? means turning the plain Setting off always makes .active?
    false), so there's nothing to verify or skip on for that reason -- but
    the setting can still not exist at all on this OpenProject version
    (16.0-17.6), which is what RailsCapabilityUnavailable catches below."""
    service = os.environ.get("OPENPROJECT_DOCKER_SERVICE")
    if not service:
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to toggle Setting::WorkPackageMultipleVersions)")
    try:
        script = 'puts "VALUE=#{Setting.work_package_multiple_versions?}"'
        previous = (
            _run_rails_script(script, result_key="VALUE", capability_check=_WP_MULTI_VERSIONS_CAPABILITY_CHECK)
            == "true"
        )
        _set_multi_target_versions(enabled=False)
    except RailsCapabilityUnavailable:
        pytest.skip(_MULTI_VERSIONS_UNSUPPORTED_SKIP)
    yield
    _set_multi_target_versions(enabled=previous)


async def find_file_link(client: OpenProjectClient, project: str, title: str) -> tuple[int, int] | None:
    """(file link id, id of its work package) of the first link with `title` in the project, or None.
    Pages through every work package: the seeded container is the project's oldest one, which a first page
    of a list sorted newest first stops reaching once the project holds more than one page of them."""
    offset: int | None = 1
    while offset is not None:
        page = await client.work_package.list(project=project, limit=50, offset=offset)
        for wp in page.results:
            links = await client.file_link.list_for_work_package(wp.id)
            match = next((link for link in links.results if link.title == title), None)
            if match is not None:
                return match.id, wp.id
        offset = page.next_offset
    return None
