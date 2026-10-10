"""server.json is the MCP Registry entry; the registry accepts it only if the
name appears in the PyPI README, and clients prompt for exactly the declared
environment variables."""

from __future__ import annotations

import json
import re
from importlib.metadata import metadata
from pathlib import Path
from typing import Any

import pytest

from openproject_ce_mcp.config import ConfigError, Settings

ROOT = Path(__file__).resolve().parent.parent
SERVER_JSON: dict[str, Any] = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
PACKAGE: dict[str, Any] = SERVER_JSON["packages"][0]
DECLARED: list[dict[str, Any]] = PACKAGE["environmentVariables"]

VALID_VALUES = {
    "OPENPROJECT_BASE_URL": "https://op.example.com",
    "OPENPROJECT_API_TOKEN": "token",
    "OPENPROJECT_READ_PROJECTS": "*",
    "OPENPROJECT_WRITE_PROJECTS": "*",
}


def _env_with_all_declared() -> dict[str, str]:
    return {variable["name"]: VALID_VALUES[variable["name"]] for variable in DECLARED}


def test_server_json_describes_this_package() -> None:
    package_metadata = metadata("openproject-ce-mcp")

    assert SERVER_JSON["packages"] == [PACKAGE]
    assert PACKAGE["registryType"] == "pypi"
    assert PACKAGE["identifier"] == package_metadata["Name"]
    assert SERVER_JSON["version"] == package_metadata["Version"]
    assert PACKAGE["version"] == package_metadata["Version"]
    assert SERVER_JSON["description"] == package_metadata["Summary"]


def test_readme_names_the_registry_entry() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert re.findall(r"^<!-- mcp-name: (\S+) -->$", readme, re.MULTILINE) == [SERVER_JSON["name"]]


@pytest.mark.parametrize("variable", DECLARED, ids=lambda variable: variable["name"])
def test_declared_variable_is_required_exactly_when_settings_requires_it(variable: dict[str, Any]) -> None:
    env = _env_with_all_declared()
    del env[variable["name"]]

    if variable["isRequired"]:
        with pytest.raises(ConfigError, match=variable["name"]):
            Settings.from_env(env)
    else:
        assert Settings.from_env(env) != Settings.from_env(_env_with_all_declared())
