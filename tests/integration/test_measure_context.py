"""Live part of tools/measure-context.py: the response-size table and the
null-cost measurement, run against the disposable Docker test instance."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_PATH = Path(__file__).resolve().parents[2] / "tools" / "measure-context.py"
_spec = importlib.util.spec_from_file_location("measure_context_live", _PATH)
measure_context = importlib.util.module_from_spec(_spec)
sys.modules["measure_context_live"] = measure_context
_spec.loader.exec_module(measure_context)


def test_live_measurement_reports_every_table_row_and_returns_the_listed_rows(test_project, monkeypatch, capsys):
    # Byte-based stand-in for tiktoken (optional extra, network-fetched encoding).
    monkeypatch.setattr(measure_context, "_tokens", lambda raw: len(raw.encode()) // 4)
    monkeypatch.setenv("OPENPROJECT_TEST_PROJECT", test_project)

    rows = asyncio.run(measure_context.measure_response_sizes())
    out = capsys.readouterr().out

    assert rows, "the measurement lists the seeded work packages it created"
    measured = {
        "list_work_packages (MCP)",
        "list_work_packages with select",
        "get_work_package",
        "search_work_packages",
        "update_work_package",
        "bulk_create_work_packages",
        "bulk_update_work_packages",
        "bulk_create_work_packages with select",
        "bulk_update_work_packages with select",
    }
    lines = out.splitlines()
    for label in measured:
        start = next((i for i, line in enumerate(lines) if line.startswith(label)), None)
        assert start is not None, f"{label} missing from the report"
        # A row reports its saving on its own line or on the "MCP:" line below it.
        saving = re.search(r"\(-(\d+)% vs\. raw\)", "\n".join(lines[start : start + 3]))
        assert saving, f"no saving reported for {label}"
        assert int(saving.group(1)) > 0, f"{label} is not smaller than the raw API payload"

    measure_context.measure_null_distinguishability_cost(rows)
    assert f"Measured on {len(rows)} real seeded work packages" in capsys.readouterr().out
