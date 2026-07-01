"""Shared fixtures for integration tests against a live OpenProject instance.

WARNING — these fixtures build a FULLY WRITE-ENABLED client (every
``enable_*_write`` flag on, plus ``auto_confirm_write=True``) and the write tests
create and DELETE real data. Run them ONLY against a disposable test instance or a
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

import os

import pytest

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings

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


def _integration_settings() -> Settings | None:
    base_url = os.environ.get("OPENPROJECT_BASE_URL")
    api_token = os.environ.get("OPENPROJECT_API_TOKEN")
    if not base_url or not api_token:
        return None
    return Settings(
        base_url=base_url,
        api_token=api_token,
        auto_confirm_write=True,
        timeout=30,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        enable_admin_write=True,
        enable_project_write=True,
        enable_work_package_write=True,
        enable_membership_write=True,
        enable_version_write=True,
        enable_board_write=True,
    )


@pytest.fixture
def client():
    settings = _integration_settings()
    if settings is None:
        pytest.skip("OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN not set")
    # Fail fast before handing out a write-enabled client aimed at a protected project.
    _resolve_test_project()
    return OpenProjectClient(settings)


@pytest.fixture
def test_project() -> str:
    return _resolve_test_project()


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
