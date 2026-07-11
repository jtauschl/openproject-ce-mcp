"""Tests for doctor diagnostic command."""

from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
import pytest

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.doctor import EXIT_FAILURE, EXIT_SUCCESS, _run_doctor


@pytest.fixture
def make_doctor_settings():
    """Factory for creating test Settings."""

    def _make(**overrides):
        defaults = {
            "base_url": "https://test.openproject.example",
            "api_token": "test-token-123",
            "timeout": 30.0,
            "verify_ssl": True,
            "default_page_size": 20,
            "max_page_size": 50,
            "max_results": 100,
            "log_level": "WARNING",
            "read_projects": ("*",),
        }
        return Settings(**{**defaults, **overrides})

    return _make


@pytest.fixture
def mock_success_transport():
    """Mock transport for successful API calls."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if "users/me" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "name": "Test User",
                    "login": "testuser",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_auth_failure_transport():
    """Mock transport that returns 401."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"}, request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_timeout_transport():
    """Mock transport that raises timeout."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Request timed out")

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_connection_error_transport():
    """Mock transport that raises connection error."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    return httpx.MockTransport(handler)


# Binary check tests


def test_check_binary_always_passes():
    """Binary check should always pass (if doctor runs, binary exists)."""
    from openproject_ce_mcp.doctor import _check_binary

    result = _check_binary()
    assert result is True


def test_check_binary_reports_version(capsys):
    """Binary check should report version."""
    from openproject_ce_mcp import __version__
    from openproject_ce_mcp.doctor import _check_binary

    _check_binary()
    captured = capsys.readouterr()
    assert __version__ in captured.out
    assert "[OK] Binary:" in captured.out


# Client discovery tests


def test_discover_clients_with_detected_clients(monkeypatch):
    """Should find and report detected clients."""
    from openproject_ce_mcp.doctor import _discover_clients

    # Mock Client class
    mock_client = Mock()
    mock_client.label = "Test Client"
    mock_client.detected.return_value = True
    mock_client.target = Mock()
    mock_client.target.exists.return_value = True
    mock_client.target.__str__ = lambda self: "/path/to/config.json"
    mock_client.project_target = None

    # Mock _clients() from setup_cli
    with patch("openproject_ce_mcp.setup_cli._clients", return_value=[mock_client]):
        found = _discover_clients()

    assert len(found) == 1
    assert found[0][0] == mock_client


def test_discover_clients_shows_not_detected_configs(monkeypatch):
    """Should show configs even if client is not detected."""
    from openproject_ce_mcp.doctor import _discover_clients

    mock_client = Mock()
    mock_client.label = "Test Client"
    mock_client.detected.return_value = False  # Not detected
    mock_client.target = Mock()
    mock_client.target.exists.return_value = True
    mock_client.target.__str__ = lambda self: "/path/to/config.json"
    mock_client.project_target = None

    with patch("openproject_ce_mcp.setup_cli._clients", return_value=[mock_client]):
        found = _discover_clients()

    assert len(found) == 1  # Still found because config file exists


# Environment config tests


def test_env_config_with_settings_override(make_doctor_settings):
    """Should use settings override when provided."""
    from openproject_ce_mcp.doctor import _check_env_config

    settings = make_doctor_settings()
    env_ok, result_settings = _check_env_config(settings, {})

    assert env_ok is True
    assert result_settings is settings


def test_env_config_warns_on_verify_ssl_false(capsys, make_doctor_settings, monkeypatch):
    """Should warn when SSL verification is disabled."""
    from openproject_ce_mcp.doctor import _check_env_config

    # Don't use override - simulate loading from env
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "https://test.example.com")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "test-token")
    monkeypatch.setenv("OPENPROJECT_VERIFY_SSL", "false")

    _check_env_config(None, {})

    captured = capsys.readouterr()
    # Warning goes to stderr
    output = captured.out + captured.err
    assert "[WARN]" in output
    assert "SSL" in output


def test_env_config_warns_on_http_url(capsys, make_doctor_settings, monkeypatch):
    """Should warn on unencrypted HTTP connection."""
    from openproject_ce_mcp.doctor import _check_env_config

    # Don't use override - simulate loading from env
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "http://insecure.example.com")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "test-token")

    _check_env_config(None, {})

    captured = capsys.readouterr()
    # Warning goes to stderr
    output = captured.out + captured.err
    assert "[WARN]" in output
    assert "HTTP" in output


# API connectivity tests


@pytest.mark.asyncio
async def test_api_connectivity_success(make_doctor_settings, mock_success_transport, capsys):
    """Should report successful API connection."""
    from openproject_ce_mcp.doctor import _check_api_connectivity

    settings = make_doctor_settings()
    api_ok, user = await _check_api_connectivity(settings, mock_success_transport)

    assert api_ok is True
    assert user is not None
    assert user.name == "Test User"

    captured = capsys.readouterr()
    assert "[OK] API:" in captured.out
    assert "Test User" in captured.out


@pytest.mark.asyncio
async def test_api_connectivity_auth_failure(make_doctor_settings, mock_auth_failure_transport, capsys):
    """Should detect authentication failures."""
    from openproject_ce_mcp.doctor import _check_api_connectivity

    settings = make_doctor_settings()
    api_ok, user = await _check_api_connectivity(settings, mock_auth_failure_transport)

    assert api_ok is False
    assert user is None

    captured = capsys.readouterr()
    assert "[FAIL] API:" in captured.err
    assert "authentication" in captured.err.lower()


@pytest.mark.asyncio
async def test_api_connectivity_timeout(make_doctor_settings, mock_timeout_transport, capsys):
    """Should detect connection timeouts."""
    from openproject_ce_mcp.doctor import _check_api_connectivity

    settings = make_doctor_settings()
    api_ok, user = await _check_api_connectivity(settings, mock_timeout_transport)

    assert api_ok is False
    assert user is None

    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "[FAIL] API:" in output
    # Check for timeout-related message (client may say "timed out" or "timeout")
    assert "timeout" in output.lower() or "timed out" in output.lower()


@pytest.mark.asyncio
async def test_api_connectivity_connection_error(make_doctor_settings, mock_connection_error_transport, capsys):
    """Should detect connection errors."""
    from openproject_ce_mcp.doctor import _check_api_connectivity

    settings = make_doctor_settings()
    api_ok, user = await _check_api_connectivity(settings, mock_connection_error_transport)

    assert api_ok is False
    assert user is None

    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "[FAIL] API:" in output
    # OpenProject client wraps connection errors - accept either message
    assert "cannot connect" in output.lower() or "could not reach" in output.lower()


# Tool registration tests


def test_tool_registration_reports_count(make_doctor_settings, capsys):
    """Should report number of registered tools."""
    from openproject_ce_mcp.doctor import _check_tool_registration

    settings = make_doctor_settings()
    result = _check_tool_registration(settings)

    assert result is True

    captured = capsys.readouterr()
    assert "[OK] Tools:" in captured.out
    assert "would register" in captured.out


def test_tool_registration_respects_write_flags(make_doctor_settings, capsys):
    """Tool count should vary based on write flags."""
    from openproject_ce_mcp.doctor import _check_tool_registration

    # All write enabled
    settings_all = make_doctor_settings(
        enable_work_package_write=True,
        enable_project_write=True,
    )
    _check_tool_registration(settings_all)
    captured_all = capsys.readouterr()

    # All write disabled
    settings_none = make_doctor_settings(
        enable_work_package_write=False,
        enable_project_write=False,
    )
    _check_tool_registration(settings_none)
    captured_none = capsys.readouterr()

    # Extract tool counts
    import re

    match_all = re.search(r"Tools: (\d+)", captured_all.out)
    match_none = re.search(r"Tools: (\d+)", captured_none.out)

    assert match_all and match_none
    count_all = int(match_all.group(1))
    count_none = int(match_none.group(1))

    # With write enabled, should have more tools
    assert count_all > count_none


# Exit code tests


def test_doctor_returns_success_on_all_pass(make_doctor_settings, mock_success_transport):
    """Should return EXIT_SUCCESS when all checks pass."""
    settings = make_doctor_settings()

    with patch("openproject_ce_mcp.doctor._discover_clients", return_value=[]):
        with patch("openproject_ce_mcp.doctor._check_config_parsing", return_value=(True, {})):
            exit_code = _run_doctor(settings_override=settings, transport=mock_success_transport)

    assert exit_code == EXIT_SUCCESS


def test_doctor_returns_failure_on_api_error(make_doctor_settings, mock_auth_failure_transport):
    """Should return EXIT_FAILURE when API check fails."""
    settings = make_doctor_settings()

    with patch("openproject_ce_mcp.doctor._discover_clients", return_value=[]):
        with patch("openproject_ce_mcp.doctor._check_config_parsing", return_value=(True, {})):
            exit_code = _run_doctor(settings_override=settings, transport=mock_auth_failure_transport)

    assert exit_code == EXIT_FAILURE


def test_doctor_returns_failure_on_config_error(monkeypatch):
    """Should return EXIT_FAILURE when env config fails."""
    from openproject_ce_mcp.config import ConfigError

    # Simulate Settings.from_env() raising ConfigError
    def mock_from_env(**kwargs):
        raise ConfigError("Missing OPENPROJECT_BASE_URL")

    monkeypatch.setattr("openproject_ce_mcp.config.Settings.from_env", mock_from_env)

    with patch("openproject_ce_mcp.doctor._discover_clients", return_value=[]):
        with patch("openproject_ce_mcp.doctor._check_config_parsing", return_value=(True, {})):
            exit_code = _run_doctor()

    assert exit_code == EXIT_FAILURE


# Config parsing tests


def test_config_parsing_valid_json(tmp_path):
    """Should parse valid JSON config with openproject entry."""
    from openproject_ce_mcp.doctor import _check_config_parsing

    config_file = tmp_path / "test_config.json"
    config_file.write_text(
        """{
        "mcpServers": {
            "openproject": {
                "command": "openproject-ce-mcp",
                "env": {
                    "OPENPROJECT_BASE_URL": "https://test.example.com",
                    "OPENPROJECT_API_TOKEN": "test-token"
                }
            }
        }
    }"""
    )

    mock_client = Mock()
    mock_client.label = "Test"
    mock_client.fmt = "json"
    mock_client.root_key = "mcpServers"

    with patch(
        "openproject_ce_mcp.setup_cli._read_client_env",
        return_value={"OPENPROJECT_BASE_URL": "https://test.example.com"},
    ):
        all_ok, env = _check_config_parsing([(mock_client, config_file)])

    assert all_ok is True
    assert "OPENPROJECT_BASE_URL" in env


def test_config_parsing_invalid_json(tmp_path, capsys):
    """Should detect invalid JSON."""
    from openproject_ce_mcp.doctor import _check_config_parsing

    config_file = tmp_path / "bad_config.json"
    config_file.write_text("{invalid json")

    mock_client = Mock()
    mock_client.label = "Test"
    mock_client.fmt = "json"
    mock_client.root_key = "mcpServers"

    all_ok, env = _check_config_parsing([(mock_client, config_file)])

    assert all_ok is False
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.err
    assert "invalid JSON" in captured.err


def test_config_parsing_missing_openproject_entry(tmp_path, capsys):
    """Should warn when openproject entry is missing."""
    from openproject_ce_mcp.doctor import _check_config_parsing

    config_file = tmp_path / "config.json"
    config_file.write_text('{"mcpServers": {}}')

    mock_client = Mock()
    mock_client.label = "Test"
    mock_client.fmt = "json"
    mock_client.root_key = "mcpServers"

    all_ok, env = _check_config_parsing([(mock_client, config_file)])

    # Missing entry is warning, not failure
    assert all_ok is True
    captured = capsys.readouterr()
    assert "[WARN]" in captured.err
    assert "no openproject entry" in captured.err


# Restart hints tests


def test_restart_hints_printed(capsys):
    """Should print restart hints for clients."""
    from openproject_ce_mcp.doctor import _print_restart_hints

    mock_client = Mock()
    mock_client.label = "Test Client"
    mock_client.restart_hint = "Restart the app"

    _print_restart_hints([(mock_client, Mock())])

    captured = capsys.readouterr()
    assert "Restart needed for:" in captured.out
    assert "Test Client" in captured.out
    assert "Restart the app" in captured.out


def test_restart_hints_deduplicated(capsys):
    """Should deduplicate clients with multiple configs."""
    from openproject_ce_mcp.doctor import _print_restart_hints

    mock_client = Mock()
    mock_client.label = "Test Client"
    mock_client.restart_hint = "Restart the app"

    # Same client appears twice (global + project config)
    _print_restart_hints([(mock_client, Mock()), (mock_client, Mock())])

    captured = capsys.readouterr()
    # Should only appear once
    assert captured.out.count("Test Client") == 1
