# Sibling test files import from this module as `from _tools_test_helpers import
# ...` (no package prefix), which relies on pytest's default rootless import mode
# adding this directory to sys.path. Revisit if the project ever switches to
# `--import-mode=importlib` (e.g. as part of the OPM-26 test-architecture work).
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings


def make_settings() -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
    )


@dataclass
class FakeAppContext:
    client: OpenProjectClient


class FakeContext:
    def __init__(self, client: OpenProjectClient) -> None:
        self.request_context = SimpleNamespace(lifespan_context=FakeAppContext(client=client))
