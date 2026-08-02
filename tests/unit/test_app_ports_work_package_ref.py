from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.work_package_ref import work_package_ref


def test_work_package_ref_quotes_a_numeric_id() -> None:
    assert work_package_ref(42) == "42"


def test_work_package_ref_quotes_a_project_prefixed_identifier() -> None:
    assert work_package_ref("PROJ-123") == "PROJ-123"


def test_work_package_ref_rejects_path_traversal_segment() -> None:
    """Regression: this shared encoder had no
    traversal check -- a value like "../projects/42" quotes to itself
    unchanged (quote() never escapes ".") and httpx then normalizes ".."
    away when building the request, redirecting to an unrelated endpoint
    and bypassing whichever project-link allowlist check the intended
    work-package lookup would have applied."""
    with pytest.raises(InvalidInputError, match="work_package_id"):
        work_package_ref("../projects/42")


def test_work_package_ref_rejects_bare_dot_segment() -> None:
    with pytest.raises(InvalidInputError, match="work_package_id"):
        work_package_ref(".")
