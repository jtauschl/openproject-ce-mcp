"""Integration tests for doctor command against live OpenProject instance."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.doctor import EXIT_FAILURE, EXIT_SUCCESS, _run_doctor

pytestmark = pytest.mark.integration


def test_doctor_live_connection(client):
    """Doctor should pass all checks against real instance."""
    # Use the settings from the integration client fixture
    settings = client.settings

    exit_code = _run_doctor(settings_override=settings)

    assert exit_code == EXIT_SUCCESS


def test_doctor_detects_invalid_token(client):
    """Doctor should detect authentication failure with bad token."""
    # Create settings with invalid token (reuse base_url from client)
    from openproject_ce_mcp.config import Settings

    bad_settings = Settings(
        base_url=client.settings.base_url,
        api_token="invalid-token-12345",
        timeout=client.settings.timeout,
        verify_ssl=client.settings.verify_ssl,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        allowed_projects=("*",),
    )

    exit_code = _run_doctor(settings_override=bad_settings)

    assert exit_code == EXIT_FAILURE
