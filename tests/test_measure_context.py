from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "measure-context.py"
_spec = importlib.util.spec_from_file_location("measure_context", _PATH)
measure_context = importlib.util.module_from_spec(_spec)
sys.modules["measure_context"] = measure_context
_spec.loader.exec_module(measure_context)


@pytest.fixture(autouse=True)
def _offline_token_count(monkeypatch):
    # The real counter needs the optional tiktoken extra and its network-fetched
    # encoding; a byte-based stand-in keeps every comparison meaningful.
    monkeypatch.setattr(measure_context, "_tokens", lambda raw: len(raw.encode()) // 4)


def _catalog_lines(out: str) -> dict[str, int]:
    return {m["label"]: int(m["count"]) for m in re.finditer(r"^(?P<label>[^:\n]+): (?P<count>\d+) tools,", out, re.M)}


def test_catalog_profiles_widen_from_fresh_install_to_every_scope(capsys):
    asyncio.run(measure_context.measure_tools_list())
    counts = list(_catalog_lines(capsys.readouterr().out).values())

    assert len(counts) == 5
    assert counts[0] < counts[1] < counts[2] < counts[3] < counts[4]


def test_catalog_never_duplicates_the_server_instructions_into_tool_descriptions(capsys):
    asyncio.run(measure_context.measure_tools_list())
    out = capsys.readouterr().out

    assert "server.instructions is CE_INSTRUCTIONS: True" in out
    assert "tools whose description duplicates it: none" in out


def test_report_states_the_saving_against_the_raw_payload(capsys):
    measure_context._report("get_work_package", "x" * 400, "x" * 100)
    out = capsys.readouterr().out

    assert "Raw: 400 bytes, ~100 tokens" in out
    assert "MCP: 100 bytes, ~25 tokens (-75% vs. raw)" in out


@dataclass
class _Row:
    id: int
    subject: str
    responsible: str | None


def test_null_cost_counts_rows_with_the_selected_field_unset(capsys):
    rows = [_Row(1, "a", None), _Row(2, "b", "Jane"), _Row(3, "c", None)]
    measure_context.measure_null_distinguishability_cost(rows)
    out = capsys.readouterr().out

    assert "(3 rows, 2 with responsible=None)" in out
    elided, explicit = (int(n) for n in re.findall(r"~(\d+) tokens", out)[:2])
    assert explicit >= elided


def test_response_measurement_is_skipped_without_a_live_instance(monkeypatch, capsys):
    for name in ("OPENPROJECT_BASE_URL", "OPENPROJECT_API_TOKEN", "OPENPROJECT_TEST_PROJECT"):
        monkeypatch.delenv(name, raising=False)

    assert asyncio.run(measure_context.measure_response_sizes()) is None


async def test_raw_baseline_waits_as_long_as_the_operator_configured(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_TIMEOUT", "37")
    settings = measure_context._measurement_settings("https://op.example.com", "token", "TST")

    async with measure_context._raw_api(settings) as http:
        assert (settings.timeout, http.timeout) == (37.0, httpx.Timeout(37.0))
