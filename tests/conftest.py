"""Shared unit-test fixtures.

``create_app`` now enriches the MCP server instructions with the instance's live
feature flags, which means it performs a one-shot network fetch at construction
time. Unit tests build ``create_app`` against a non-existent host, so without a
stub every such test would block on the HTTP timeout. This autouse fixture makes
the fetch a no-op by default (returns no flags → static instructions only); tests
that specifically exercise enrichment monkeypatch ``_fetch_active_feature_flags``
themselves.
"""

from __future__ import annotations

import pytest

import openproject_ce_mcp.server as server


@pytest.fixture(autouse=True)
def _offline_feature_flags(monkeypatch, request):
    if "allow_feature_flag_fetch" in request.keywords:
        return
    monkeypatch.setattr(server, "_fetch_active_feature_flags", lambda settings: None)
