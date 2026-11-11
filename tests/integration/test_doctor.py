"""Integration tests for doctor command against live OpenProject instance."""

from __future__ import annotations

import sys

import pytest

from openproject_ce_mcp.doctor.environment import EffectiveEnv, EnvMap
from openproject_ce_mcp.doctor.hosts import ProcessEnvHost, Subject
from openproject_ce_mcp.doctor.run import EXIT_FAILURE, EXIT_SUCCESS, _run_doctor

pytestmark = pytest.mark.integration


def _entry(base_url: str, token: str, verify_ssl: bool) -> Subject:
    env = EnvMap(
        {
            "OPENPROJECT_BASE_URL": base_url,
            "OPENPROJECT_API_TOKEN": token,
            "OPENPROJECT_VERIFY_SSL": "true" if verify_ssl else "false",
            "OPENPROJECT_READ_PROJECTS": "*",
        },
        case_insensitive=sys.platform == "win32",
    )
    return Subject(ProcessEnvHost(), "", effective=EffectiveEnv(env=env))


def test_doctor_live_connection(client):
    """The real connection check passes against the instance."""
    settings = client.settings

    exit_code = _run_doctor(
        entries=[_entry(settings.base_url, settings.api_token.get_secret_value(), settings.verify_ssl)]
    )

    assert exit_code == EXIT_SUCCESS


def test_doctor_detects_invalid_token(client):
    """The real connection check fails with a bad token."""
    settings = client.settings

    exit_code = _run_doctor(entries=[_entry(settings.base_url, "invalid-token-12345", settings.verify_ssl)])

    assert exit_code == EXIT_FAILURE
