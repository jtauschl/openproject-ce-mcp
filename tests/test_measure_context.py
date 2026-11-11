from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from openproject_ce_mcp.tools import CORE_TOOLS

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

    assert len(counts) == 6
    assert counts == sorted(set(counts))


def _profile_lines(out: str) -> dict[tuple[str, str], int]:
    return {
        (m["label"], m["profile"]): int(m["count"])
        for m in re.finditer(r"^(?P<label>.+), profile (?P<profile>\w+) -- (?P<count>\d+) tools,", out, re.M)
    }


def test_profile_table_gives_core_next_to_full_for_the_same_settings(capsys):
    asyncio.run(measure_context.measure_tool_profiles())
    lines = _profile_lines(capsys.readouterr().out)

    glama = "Glama settings (every project readable and writable)"
    assert lines[(glama, "core")] == len(CORE_TOOLS)
    assert lines[(glama, "core")] < lines[(glama, "full")]
    reads = "project reads enabled, no writes"
    assert lines[(reads, "core")] < lines[(reads, "full")]


def test_profile_table_does_not_add_scenarios_to_the_catalog_table(capsys):
    asyncio.run(measure_context.measure_tool_profiles())

    assert _catalog_lines(capsys.readouterr().out) == {}


def test_catalog_never_duplicates_the_server_instructions_into_tool_descriptions(capsys):
    asyncio.run(measure_context.measure_tools_list())
    out = capsys.readouterr().out

    assert "server.instructions is CE_INSTRUCTIONS: True" in out
    assert "tools whose description duplicates it: none" in out


def test_export_writes_the_wire_form_of_the_glama_and_full_catalogs(tmp_path):
    asyncio.run(measure_context.export_catalogs(tmp_path))

    glama = json.loads((tmp_path / "tools_glama.json").read_text())["tools"]
    full = json.loads((tmp_path / "tools_full.json").read_text())["tools"]
    assert {tool["name"] for tool in glama} < {tool["name"] for tool in full}
    assert all("inputSchema" in tool and "input_schema" not in tool for tool in glama + full)


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


@pytest.mark.parametrize("project", ["OPM", "tst"], ids=["production-like project", "remote target not acknowledged"])
def test_live_part_refuses_before_any_request_when_the_target_was_not_named(monkeypatch, project):
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "https://op.example.com")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "token")
    monkeypatch.setenv("OPENPROJECT_TEST_PROJECT", project)
    monkeypatch.delenv("OPENPROJECT_TEST_DESTRUCTIVE_TARGET", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("a refused run must not build a client")

    monkeypatch.setattr(measure_context, "OpenProjectClient", forbidden)
    monkeypatch.setattr(measure_context, "_raw_api", forbidden)

    with pytest.raises(SystemExit) as refusal:
        asyncio.run(measure_context.measure_response_sizes())

    assert "Refusing to write measurement work packages" in str(refusal.value)
    assert "token" not in str(refusal.value)


def test_live_part_is_skipped_without_a_live_target(monkeypatch, capsys):
    monkeypatch.delenv("OPENPROJECT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENPROJECT_API_TOKEN", raising=False)

    assert asyncio.run(measure_context.measure_response_sizes()) is None
    assert "Skipped" in capsys.readouterr().out


# ── Cleanup of the work packages the live part creates ──────────────────────


def _settings_for(base_url: str = "http://localhost:8178"):
    return measure_context._measurement_settings(base_url, "token", "tst")


class _FakeClient:
    instances: list = []

    def __init__(self, settings, fail_initialize: bool = False):
        self.closed = False
        self.initialized = False
        self.fail_initialize = fail_initialize
        _FakeClient.instances.append(self)

    async def initialize(self):
        if self.fail_initialize:
            raise RuntimeError("initialize failed")
        self.initialized = True

    async def aclose(self):
        self.closed = True


def _raw_api_answering(monkeypatch, status_by_id: dict[int, int], seen: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        work_package_id = int(request.url.path.rsplit("/", 1)[1])
        assert request.method == "DELETE"
        seen.append(work_package_id)
        return httpx.Response(status_by_id.get(work_package_id, 204), request=request)

    def factory(settings):
        return httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(measure_context, "_raw_api", factory)


@pytest.fixture
def fake_client(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(measure_context, "OpenProjectClient", _FakeClient)
    return _FakeClient


def test_a_finished_measurement_deletes_every_recorded_work_package_and_closes_the_client(monkeypatch, fake_client):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (client, created):
            assert client.initialized
            created.extend([11, 12, 13])

    asyncio.run(run())

    assert seen == [11, 12, 13]
    assert [c.closed for c in fake_client.instances] == [True]


def test_a_work_package_that_is_already_gone_is_not_a_failure(monkeypatch, fake_client):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {12: 404}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (_, created):
            created.extend([11, 12, 13])

    asyncio.run(run())

    assert seen == [11, 12, 13]


def test_a_failed_deletion_does_not_stop_the_others_and_ends_the_run_with_the_id(monkeypatch, fake_client):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {12: 500, 14: 403}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (_, created):
            created.extend([11, 12, 13, 14])

    with pytest.raises(SystemExit) as ended:
        asyncio.run(run())

    assert seen == [11, 12, 13, 14]
    assert "work package 12" in str(ended.value) and "work package 14" in str(ended.value)
    assert "work package 11" not in str(ended.value) and "work package 13" not in str(ended.value)
    assert [c.closed for c in fake_client.instances] == [True]


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt(), asyncio.CancelledError()])
def test_an_error_or_interrupt_in_the_body_still_deletes_and_closes(monkeypatch, fake_client, error):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (_, created):
            created.extend([21, 22])
            raise error

    with pytest.raises(type(error)):
        asyncio.run(run())

    assert seen == [21, 22]
    assert [c.closed for c in fake_client.instances] == [True]


def test_a_cleanup_failure_after_an_error_is_reported_without_hiding_the_error(monkeypatch, fake_client, capsys):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {22: 500}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (_, created):
            created.extend([21, 22])
            raise RuntimeError("the measurement broke")

    with pytest.raises(RuntimeError, match="the measurement broke"):
        asyncio.run(run())

    assert "Cleanup failed: work package 22" in capsys.readouterr().err
    assert [c.closed for c in fake_client.instances] == [True]


def test_a_client_that_cannot_initialize_is_still_closed(monkeypatch):
    clients = []

    def factory(settings):
        client = _FakeClient(settings, fail_initialize=True)
        clients.append(client)
        return client

    monkeypatch.setattr(measure_context, "OpenProjectClient", factory)
    _raw_api_answering(monkeypatch, {}, [])

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False):
            raise AssertionError("the body must not run")

    with pytest.raises(RuntimeError, match="initialize failed"):
        asyncio.run(run())

    assert [c.closed for c in clients] == [True]


def test_keep_leaves_the_work_packages_and_still_closes_the_client(monkeypatch, fake_client):
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=True) as (_, created):
            created.extend([31, 32])

    asyncio.run(run())

    assert seen == []
    assert [c.closed for c in fake_client.instances] == [True]


def test_keep_is_a_parsed_option_of_the_script(monkeypatch):
    received = {}

    async def fake_measure(*, keep=False):
        received["keep"] = keep

    monkeypatch.setattr(measure_context, "measure_tools_list", lambda: asyncio.sleep(0))
    monkeypatch.setattr(measure_context, "measure_response_sizes", fake_measure)
    monkeypatch.setattr(sys, "argv", ["measure-context.py", "--keep"])
    asyncio.run(measure_context.main())
    assert received == {"keep": True}

    monkeypatch.setattr(sys, "argv", ["measure-context.py"])
    asyncio.run(measure_context.main())
    assert received == {"keep": False}


def test_a_failing_close_after_an_error_does_not_replace_the_error(monkeypatch, capsys):
    class _BrokenClose(_FakeClient):
        async def aclose(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(measure_context, "OpenProjectClient", _BrokenClose)
    seen: list[int] = []
    _raw_api_answering(monkeypatch, {}, seen)

    async def run():
        async with measure_context._measurement_workspace(_settings_for(), keep=False) as (_, created):
            created.append(41)
            raise RuntimeError("the measurement broke")

    with pytest.raises(RuntimeError, match="the measurement broke"):
        asyncio.run(run())

    assert seen == [41]
    assert "cleanup itself failed: RuntimeError: close failed" in capsys.readouterr().err
