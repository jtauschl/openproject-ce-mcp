"""Shared same-origin-check helper (ADR 0001).

Package-root shared kernel: pure, dependency-free URL parsing used by both
Adapters (via `app/adapters/_text.py`, which re-exports it for backward
compatibility and its own `link_to_web_url` helper) and Services that need
to reject a caller-supplied absolute URL pointing at a foreign origin.

Extracted once `BoardService._resolve_query_reference_href` needed the exact
same same-origin check `app/adapters/_text.py`'s `origin_from_url` already
provided, but `services` cannot import from `adapters` (enforced by
`tests/test_architecture_boundaries.py`) -- found during the Boards
migration's step-6 reuse/simplification audit.
"""

from __future__ import annotations

from urllib.parse import urlparse


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"
