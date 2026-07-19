"""Shared write/delete-tool behavioral-contract case table (OPM-209 / Phase D).

One `WriteToolCase` per registered write/delete MCP tool -- the exhaustiveness
mechanism `tests/unit/test_write_confirm_contracts.py` enforces against
`WRITE_TOOLS_BY_SCOPE`/`PERSONAL_MUTATION_TOOLS`/`ATTACHMENT_UPLOAD_TOOLS`. Split
across per-scope builder modules (`_write_contract_cases_*.py`) purely to keep any
one file reviewable; this module just merges their output. Shared dataclasses live
in `_write_contract_cases_types.py` (imported bare, no package prefix -- this
directory has no `__init__.py` and relies on pytest's default rootless import
mode, matching the existing `_client_test_helpers.py`/`_tools_test_helpers.py`
convention).
"""

from __future__ import annotations

from _write_contract_cases_membership_version_board_admin import MEMBERSHIP_VERSION_BOARD_ADMIN_CASES
from _write_contract_cases_personal_attachment import PERSONAL_ATTACHMENT_CASES
from _write_contract_cases_project import PROJECT_CASES
from _write_contract_cases_types import MaterializedWriteToolCase, WriteToolCase, materialize_case
from _write_contract_cases_work_package import WORK_PACKAGE_CASES

__all__ = [
    "MaterializedWriteToolCase",
    "WriteToolCase",
    "materialize_case",
    "WRITE_TOOL_CASES",
]

WRITE_TOOL_CASES: dict[str, WriteToolCase] = {
    **PROJECT_CASES,
    **WORK_PACKAGE_CASES,
    **MEMBERSHIP_VERSION_BOARD_ADMIN_CASES,
    **PERSONAL_ATTACHMENT_CASES,
}
