"""Integration tests for storages/project_storages.

Requires the Nextcloud Docker fixture: `docker/test/up.sh 177nc` (sets
SEED_NEXTCLOUD_STORAGE=1, which seeds a Storages::NextcloudStorage +
Storages::ProjectStorage row via save(validate: false) -- bypassing
OpenProject's live host-reachability/setup-completeness probe. See
docker/test/README.md and docker/test/seed.rb.

Admin write is instance-wide, like Groups/Users -- never run against a real,
actively-used OpenProject instance.

Write-path note (verified against real source before writing these tests,
not assumed): `Storages::NextcloudStorage`'s own provider contract
(GeneralInformationContract) runs a SYNCHRONOUS live HTTP probe
(NextcloudCompatibleHostValidator) against `{host}/ocs/v2.php/cloud/capabilities`
and `{host}/index.php/apps/integration_openproject/check-config` whenever the
`host` attribute changes on create/update -- this is not a hypothetical, it
is exactly what the seed fixture's own `save(validate: false)` bypasses (see
the fixture commit's message). This means:
- Creating a NEW Nextcloud storage against an unreachable/non-Nextcloud host
  is EXPECTED to fail this probe (InvalidInputError, 422) -- tested below as
  the actual, realistic outcome, not as a workaround.
- OneDrive/Sharepoint have NO such host-reachability validator in their own
  provider contracts (OneDriveContract/SharepointContract only validate
  field presence/format, no live HTTP calls) -- their write-path tests do
  not have this complication, and the Enterprise-gate rejection test below
  sends OneDrive-shaped payload with a valid tenant_id and no host (per
  OneDriveContract's `validates :host, absence: true`) specifically so the
  Enterprise-gate error is the ONLY validation error (avoiding OpenProject's
  MultipleErrors wrapper, which would otherwise obscure the message text
  this test asserts on).
- update_storage's `name`-only rename (no `host` in the PATCH payload) does NOT
  re-trigger the module-level *live-reachability* probe
  (`NextcloudCompatibleHostValidator#validate_each` only fires
  `validate_capabilities`/`validate_setup_completeness` `if host_changed`,
  i.e. only when `host` is actually part of the PATCH). However, OpenProject's
  contract layer re-validates the *entire* model on every PATCH, including
  attributes the request never touched -- so a separate, unconditional
  validator (`SecureContextUriValidator`, core `app/validators/`, not gated on
  `host_changed`) still runs against the storage's existing `host` value.
  This project's own seed fixture (`docker/test/seed.rb`) sets
  `host: "http://nextcloud/"` -- plain HTTP, non-localhost -- which
  `SecureContextUriValidator` always rejects (`url_not_secure_context` /
  "Host is not providing a Secure Context"). A name-only PATCH against the
  seeded storage reliably 422s with this error, confirming it is not client-side host
  re-injection and not a version regression -- it is the seed fixture's own
  host value failing an always-on server-side validator, independent of the
  actual PATCH body. The Docker Nextcloud fixture has no TLS termination, so
  the seed can't simply switch to `https://` without a larger fixture change;
  the test below instead documents and asserts this expected failure rather
  than assuming a rename can succeed against this storage.
"""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


async def _seed_storage_or_skip(client: OpenProjectClient):
    """The seed Nextcloud storage only exists when `up.sh 177nc` seeded it
    (SEED_NEXTCLOUD_STORAGE=1) -- absent on every other `up.sh` invocation,
    which is the normal case for versions other than 17.7. Skip rather than
    fail when it's missing; this is a fixture-availability gap, not a
    version floor to enforce."""
    listed = await client.storage.list_storages()
    matches = [s for s in listed.results if s.name == "Seed Nextcloud Storage"]
    if not matches:
        pytest.skip("seed Nextcloud storage not present -- run `up.sh 177nc` to seed it")
    return matches[0]


# --- Read path: against the seeded Nextcloud storage/project_storage --------


async def test_list_storages_finds_seed_nextcloud_storage(client: OpenProjectClient) -> None:
    storage = await _seed_storage_or_skip(client)
    assert storage.provider_type == "Nextcloud"
    # The fixture deliberately bypasses live OAuth/setup validation, so the
    # storage stays unconfigured.
    assert storage.configured is False


async def test_get_storage_returns_nextcloud_fields(client: OpenProjectClient) -> None:
    seed = await _seed_storage_or_skip(client)

    detail = await client.storage.get_storage(seed.id)

    assert detail.provider_type == "Nextcloud"
    assert detail.has_application_password is False
    # forbiddenFileNameCharacters was added to the storage representer in
    # 17.1 (absent in 16.x/17.0, verified against op-sources) -- an older
    # instance legitimately reports None here rather than the string.
    if detail.forbidden_file_name_characters is not None:
        assert detail.forbidden_file_name_characters == '<>:"\\/|?*'
    assert detail.tenant_id is None
    assert detail.drive_id is None


async def _seed_project_storage_or_skip(client: OpenProjectClient):
    """Same fixture-availability gap as _seed_storage_or_skip, for the
    project_storage side."""
    listed = await client.project_storage.list_project_storages()
    matches = [ps for ps in listed.results if ps.storage_name == "Seed Nextcloud Storage"]
    if not matches:
        pytest.skip("seed Nextcloud project storage not present -- run `up.sh 177nc` to seed it")
    return matches[0]


async def test_list_project_storages_finds_seed_link(client: OpenProjectClient) -> None:
    project_storage = await _seed_project_storage_or_skip(client)
    assert project_storage.project_folder_mode == "inactive"
    assert project_storage.project is not None


async def test_get_project_storage_returns_creator(client: OpenProjectClient) -> None:
    seed = await _seed_project_storage_or_skip(client)

    detail = await client.project_storage.get_project_storage(seed.id)

    assert detail.creator is not None
    assert detail.storage_name == "Seed Nextcloud Storage"


# --- Write path: update against the seeded storage (always rejected, see below) --


async def test_update_storage_rename_rejected_by_seeded_insecure_host(client: OpenProjectClient) -> None:
    """A name-only PATCH never re-injects `host` (see storage_service.update:
    the `_links` key is only built when `host is not None`), but OpenProject's
    contract layer still re-validates the storage's existing `host` on every
    PATCH. The seed fixture's `http://nextcloud/` host is plain HTTP on a
    non-localhost hostname, which `SecureContextUriValidator` always rejects
    -- so even this no-op-on-host rename 422s. See the module docstring
    for the full explanation."""
    seed = await _seed_storage_or_skip(client)

    new_name = f"Seed Nextcloud Storage [{uuid.uuid4().hex[:8]}]"
    with pytest.raises(InvalidInputError, match="[Ss]ecure [Cc]ontext"):
        await client.storage.update(storage_id=seed.id, name=new_name, confirm=True)


async def test_delete_file_link_deletes_seeded_link(client: OpenProjectClient, test_project: str) -> None:
    """delete_file_link's successful-delete path -- previously only
    covered by tests/integration/test_write_denials.py's denial check, which
    itself skips whenever no file link happens to exist. seed.rb's
    "seed-file-link-deletable.txt" row exists specifically for this test to
    consume; find_or_create in the seed means a repeat `up.sh` run reseeds it,
    so deleting it here doesn't leave the fixture permanently gone. The
    "seed-file-link-persistent.txt" row is a separate, untouched fixture for
    test_write_denials.py -- this test must not delete that one."""
    work_packages = await client.work_package.list(project=test_project, limit=50)
    file_link_id = None
    owning_wp_id = None
    for wp in work_packages.results:
        links = await client.file_link.list_for_work_package(wp.id)
        match = next((link for link in links.results if link.title == "seed-file-link-deletable.txt"), None)
        if match is not None:
            file_link_id = match.id
            owning_wp_id = wp.id
            break
    if file_link_id is None:
        pytest.skip(
            "no 'seed-file-link-deletable.txt' file link in test_project -- run docker/test/up.sh 177nc to seed one"
        )

    preview = await client.file_link.delete(file_link_id, confirm=False)
    assert preview.state == "preview"
    assert preview.ready is True

    delete_result = await client.file_link.delete(file_link_id, confirm=True)
    assert delete_result.state == "confirmed"
    assert delete_result.ready is True

    remaining = await client.file_link.list_for_work_package(owning_wp_id)
    assert all(link.id != file_link_id for link in remaining.results)


# --- Write path: create/delete a NEW storage ---------------------------------


async def test_create_storage_one_drive_rejected_without_enterprise_token(
    client: OpenProjectClient, storage_ids: list[int]
) -> None:
    """Exercises the REAL OpenProject contract validation end-to-end (not a
    mock): OneDriveStorage overrides allowed_by_enterprise_token? to check
    EnterpriseToken.allows_to?(:one_drive_sharepoint_file_storage), which a
    Community Edition instance never satisfies.

    Even a syntactically valid GUID tenant_id (matching OneDriveContract's own
    /\\A(?:[a-f0-9]{8}-...|consumers)\\z/i regex, confirmed against source)
    still triggers a SECOND validation error alongside the Enterprise-gate
    one ("Directory (tenant) ID is invalid.", root cause not identified --
    not OneDriveContract's own format validator, which this tenant value
    satisfies) -- OpenProject's own MultipleErrors wrapper DOES fire here.
    This is exactly the scenario that surfaced a real client-side bug:
    raise_for_status previously only read the top-level `message` ("Multiple
    field constraints have been violated."), silently discarding
    `_embedded.errors[]`'s real per-field detail -- fixed the same session
    (see _combined_message in app/transport/errors.py), so the Enterprise
    text now reliably appears in the raised error's message even when
    other, unrelated validation errors are also present. No `host` is sent
    (OneDrive's own contract requires host to be ABSENT).
    """
    name = f"[integration-test] OneDrive {uuid.uuid4().hex[:8]}"

    with pytest.raises(InvalidInputError, match="[Ee]nterprise"):
        await client.storage.create(
            name=name,
            provider_type="OneDrive",
            tenant_id="11111111-1111-1111-1111-111111111111",
            confirm=True,
        )

    # No storage should have been created -- nothing to register for cleanup,
    # but assert list_storages doesn't show it either, as defense in depth.
    listed = await client.storage.list_storages()
    assert not any(s.name == name for s in listed.results)


async def test_create_storage_rejects_unknown_provider_type_before_any_http_call(
    client: OpenProjectClient,
) -> None:
    """provider_type is validated client-side against a fixed URN map before
    any request is made -- exercised here against the real server too (in
    case the client-side pre-check has a bug and the request went out, real
    defense in depth, not merely a mock assertion)."""
    with pytest.raises(InvalidInputError, match="provider_type"):
        await client.storage.create(name="Should Not Be Created", provider_type="Dropbox", confirm=True)


async def test_create_storage_nextcloud_unreachable_host_rejected_by_live_probe(
    client: OpenProjectClient, storage_ids: list[int]
) -> None:
    """A new Nextcloud storage's `host` is synchronously probed for live
    Nextcloud reachability/setup-completeness on create
    (NextcloudCompatibleHostValidator) -- an unreachable host is genuinely
    rejected by OpenProject itself, not by this MCP. This is the realistic
    outcome for a create_storage call against a host with no real Nextcloud
    + "OpenProject Integration" app behind it (the seeded fixture's own
    `http://nextcloud/` bypasses this via save(validate: false) specifically
    because a real contract-validated create would hit this same check --
    see this file's module docstring)."""
    name = f"[integration-test] Nextcloud {uuid.uuid4().hex[:8]}"

    with pytest.raises(InvalidInputError):
        await client.storage.create(
            name=name,
            provider_type="Nextcloud",
            host="http://nextcloud-integration-test-unreachable.invalid/",
            authentication_method="two_way_oauth2",
            confirm=True,
        )

    listed = await client.storage.list_storages()
    assert not any(s.name == name for s in listed.results)
