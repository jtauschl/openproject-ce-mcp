"""Shared dataclasses for the write/delete-tool behavioral-contract case table
(OPM-209 / Phase D). Split out from `_write_contract_cases.py` so the per-scope
builder modules (`_write_contract_cases_*.py`) can import these types without a
circular import against the module that merges their output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from openproject_ce_mcp.config import Settings


@dataclass(frozen=True)
class MaterializedWriteToolCase:
    """The actual kwargs/settings to use for one test invocation -- produced either
    directly from a WriteToolCase's static fields, or (for the one tool needing
    per-test dynamic setup, the attachment upload) via `WriteToolCase.materialize`.
    """

    kwargs: Mapping[str, Any]
    settings: Settings


@dataclass(frozen=True)
class WriteToolCase:
    tool: str
    kwargs: Mapping[str, Any]
    settings: Settings
    write_scope: str
    handler: Callable[[httpx.Request], httpx.Response]
    write_request: tuple[str, str]
    denial_mode: Literal["raises", "bulk_result"] = "raises"
    materialize: Callable[[Path], MaterializedWriteToolCase] | None = field(default=None)


def materialize_case(case: WriteToolCase, tmp_path: Path) -> MaterializedWriteToolCase:
    if case.materialize is not None:
        return case.materialize(tmp_path)
    return MaterializedWriteToolCase(kwargs=case.kwargs, settings=case.settings)
