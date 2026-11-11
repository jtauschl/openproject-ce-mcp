"""Tests for the doctor command: every OpenProject entry is checked on its own terms."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from _doctor_test_helpers import BASE_URL, TOKEN, VALID_ENV, FakeProbe, Sandbox, own_server_binary, server

from openproject_ce_mcp.doctor import checks
from openproject_ce_mcp.doctor.checks import Evaluation, evaluate, probe_key
from openproject_ce_mcp.doctor.discovery import claude_project
from openproject_ce_mcp.doctor.environment import EffectiveEnv, EnvMap, Syntax, resolve
from openproject_ce_mcp.doctor.files import parse_env_file, strip_jsonc
from openproject_ce_mcp.doctor.hosts import (
    ClaudeCodeHost,
    ClaudeDesktopHost,
    CursorHost,
    ServerSpec,
    Source,
    Subject,
    VsCodeAgentHost,
    VsCodeHost,
)
from openproject_ce_mcp.doctor.probe import ProbeResult
from openproject_ce_mcp.doctor.report import Level
from openproject_ce_mcp.doctor.run import EXIT_FAILURE, EXIT_SUCCESS, _run_doctor


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    return Sandbox(tmp_path, monkeypatch)


def _desktop_identity(box: Sandbox) -> str:
    return f"Claude Desktop openproject (~/{box.desktop_config.relative_to(box.home).as_posix()}, user)"


CLAUDE_USER = "Claude Code openproject (~/.claude.json, user scope)"


# ── masking ────────────────────────────────────────────────────────────────────


def test_a_broken_entry_is_not_masked_by_another_clients_entry_or_the_shell(box, capsys, monkeypatch):
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})
    box.write(box.desktop_config, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "shell-token")

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    desktop = _desktop_identity(box)
    assert any("OPENPROJECT_API_TOKEN is not set" in line for line in run.lines(desktop) if line.startswith("[FAIL]"))
    assert "FAIL" not in run.levels(CLAUDE_USER)
    assert f"1 entry failed; see the [FAIL] lines above:\n  - {desktop}\n" in run.out


# ── effective environment per host ─────────────────────────────────────────────


def test_vscode_overlays_env_file_then_env_with_null_unset_number_and_path_append(box):
    env_file = box.write(box.cwd / ".env", "A=from-file\nB=from-file\n# comment\nexport C='quoted'\n")
    ctx = box.ctx()
    ctx.shell_env.clear()
    ctx.shell_env.update({"PATH": "/usr/bin", "DROP": "x", "FROM_SHELL": "s"})
    spec = ServerSpec("cmd", (), {"B": "entry", "DROP": None, "PATH": "/extra", "NUM": "5"}, env_file=str(env_file))
    source = Source(box.vscode_workspace_mcp, "servers", Syntax.VSCODE, "workspace", box.cwd, reads_env_file=True)

    env = VsCodeHost().effective_env(spec, source, ctx).env

    assert env.get("A") == "from-file"
    assert env.get("B") == "entry"
    assert env.get("C") == "quoted"
    assert "DROP" not in env
    assert env.get("PATH") == "/usr/bin" + ctx.path_separator + "/extra"
    assert env.get("NUM") == "5"
    assert env.get("FROM_SHELL") == "s"


def test_vscode_env_file_with_a_byte_order_mark_keeps_its_first_key(box):
    env_file = box.cwd / "bom.env"
    env_file.write_bytes("\ufeffOPENPROJECT_BASE_URL=https://bom.example\n".encode())
    spec = ServerSpec("cmd", (), {}, env_file=str(env_file))
    source = Source(box.vscode_workspace_mcp, "servers", Syntax.VSCODE, "workspace", box.cwd, reads_env_file=True)

    env = VsCodeHost().effective_env(spec, source, box.ctx()).env

    assert env.get("OPENPROJECT_BASE_URL") == "https://bom.example"


def test_vscode_unreadable_env_file_fails(box):
    spec = ServerSpec("cmd", (), {}, env_file=str(box.cwd / "missing.env"))
    source = Source(box.vscode_workspace_mcp, "servers", Syntax.VSCODE, "workspace", box.cwd, reads_env_file=True)

    notes = VsCodeHost().effective_env(spec, source, box.ctx()).notes

    assert [n.level for n in notes] == [Level.FAIL]


def test_vscode_env_file_in_user_config_with_workspace_folder_is_unverifiable(box):
    spec = ServerSpec("cmd", (), {}, env_file="${workspaceFolder}/.env")
    source = Source(box.vscode_user_mcp, "servers", Syntax.VSCODE, "user profile", None, reads_env_file=True)

    notes = VsCodeHost().effective_env(spec, source, box.ctx()).notes

    assert [(n.level, n.unverified) for n in notes] == [(Level.WARN, True)]


def test_vscode_accepts_numbers_and_null_in_env(box, capsys):
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": server({**VALID_ENV, "OPENPROJECT_TIMEOUT": 7})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert box.probe.calls[0].get("OPENPROJECT_API_TOKEN") == TOKEN


def test_vscode_ignores_env_file_outside_its_own_files(box):
    env_file = box.write(box.cwd / ".env", f"OPENPROJECT_API_TOKEN={TOKEN}\n")
    spec = ServerSpec("cmd", (), {}, env_file=str(env_file))
    source = Source(box.mcp_json, "mcpServers", Syntax.COPILOT, "workspace", box.cwd)

    effective = VsCodeHost().effective_env(spec, source, box.ctx())

    assert "OPENPROJECT_API_TOKEN" not in effective.env
    assert [n.text for n in effective.notes] == ["VS Code ignores `envFile` in this file"]


# From VS Code's envfile.test.ts, whose cases come from motdotla/dotenv's tests/.env
# (Copyright (c) 2015, Scott Motte; BSD-2-Clause).
_DOTENV_EXAMPLE = """
BASIC=basic

# previous line intentionally left blank
AFTER_LINE=after_line
EMPTY=
EMPTY_SINGLE_QUOTES=''
EMPTY_DOUBLE_QUOTES=""
EMPTY_BACKTICKS=``
SINGLE_QUOTES='single_quotes'
SINGLE_QUOTES_SPACED='    single quotes    '
DOUBLE_QUOTES="double_quotes"
DOUBLE_QUOTES_SPACED="    double quotes    "
DOUBLE_QUOTES_INSIDE_SINGLE='double "quotes" work inside single quotes'
DOUBLE_QUOTES_WITH_NO_SPACE_BRACKET="{ port: $MONGOLAB_PORT}"
SINGLE_QUOTES_INSIDE_DOUBLE="single 'quotes' work inside double quotes"
BACKTICKS_INSIDE_SINGLE='`backticks` work inside single quotes'
BACKTICKS_INSIDE_DOUBLE="`backticks` work inside double quotes"
BACKTICKS=`backticks`
BACKTICKS_SPACED=`    backticks    `
DOUBLE_QUOTES_INSIDE_BACKTICKS=`double "quotes" work inside backticks`
SINGLE_QUOTES_INSIDE_BACKTICKS=`single 'quotes' work inside backticks`
DOUBLE_AND_SINGLE_QUOTES_INSIDE_BACKTICKS=`double "quotes" and single 'quotes' work inside backticks`
EXPAND_NEWLINES="expand\\nnew\\nlines"
DONT_EXPAND_UNQUOTED=dontexpand\\nnewlines
DONT_EXPAND_SQUOTED='dontexpand\\nnewlines'
# COMMENTS=work
INLINE_COMMENTS=inline comments # work #very #well
INLINE_COMMENTS_SINGLE_QUOTES='inline comments outside of #singlequotes' # work
INLINE_COMMENTS_DOUBLE_QUOTES="inline comments outside of #doublequotes" # work
INLINE_COMMENTS_BACKTICKS=`inline comments outside of #backticks` # work
INLINE_COMMENTS_SPACE=inline comments start with a#number sign. no space required.
EQUAL_SIGNS=equals==
RETAIN_INNER_QUOTES={"foo": "bar"}
RETAIN_INNER_QUOTES_AS_STRING='{"foo": "bar"}'
RETAIN_INNER_QUOTES_AS_BACKTICKS=`{"foo": "bar's"}`
TRIM_SPACE_FROM_UNQUOTED=    some spaced out string
USERNAME=therealnerdybeast@example.tld
\t\tSPACED_KEY = parsed
"""


def test_parse_env_file_matches_vscode():
    parsed = parse_env_file(_DOTENV_EXAMPLE)

    assert parsed == {
        "BASIC": "basic",
        "AFTER_LINE": "after_line",
        "EMPTY": "",
        "EMPTY_SINGLE_QUOTES": "",
        "EMPTY_DOUBLE_QUOTES": "",
        "EMPTY_BACKTICKS": "",
        "SINGLE_QUOTES": "single_quotes",
        "SINGLE_QUOTES_SPACED": "    single quotes    ",
        "DOUBLE_QUOTES": "double_quotes",
        "DOUBLE_QUOTES_SPACED": "    double quotes    ",
        "DOUBLE_QUOTES_INSIDE_SINGLE": 'double "quotes" work inside single quotes',
        "DOUBLE_QUOTES_WITH_NO_SPACE_BRACKET": "{ port: $MONGOLAB_PORT}",
        "SINGLE_QUOTES_INSIDE_DOUBLE": "single 'quotes' work inside double quotes",
        "BACKTICKS_INSIDE_SINGLE": "`backticks` work inside single quotes",
        "BACKTICKS_INSIDE_DOUBLE": "`backticks` work inside double quotes",
        "BACKTICKS": "backticks",
        "BACKTICKS_SPACED": "    backticks    ",
        "DOUBLE_QUOTES_INSIDE_BACKTICKS": 'double "quotes" work inside backticks',
        "SINGLE_QUOTES_INSIDE_BACKTICKS": "single 'quotes' work inside backticks",
        "DOUBLE_AND_SINGLE_QUOTES_INSIDE_BACKTICKS": "double \"quotes\" and single 'quotes' work inside backticks",
        "EXPAND_NEWLINES": "expand\nnew\nlines",
        "DONT_EXPAND_UNQUOTED": "dontexpand\\nnewlines",
        "DONT_EXPAND_SQUOTED": "dontexpand\\nnewlines",
        "INLINE_COMMENTS": "inline comments",
        "INLINE_COMMENTS_SINGLE_QUOTES": "inline comments outside of #singlequotes",
        "INLINE_COMMENTS_DOUBLE_QUOTES": "inline comments outside of #doublequotes",
        "INLINE_COMMENTS_BACKTICKS": "inline comments outside of #backticks",
        "INLINE_COMMENTS_SPACE": "inline comments start with a",
        "EQUAL_SIGNS": "equals==",
        "RETAIN_INNER_QUOTES": '{"foo": "bar"}',
        "RETAIN_INNER_QUOTES_AS_STRING": '{"foo": "bar"}',
        "RETAIN_INNER_QUOTES_AS_BACKTICKS": '{"foo": "bar\'s"}',
        "TRIM_SPACE_FROM_UNQUOTED": "some spaced out string",
        "USERNAME": "therealnerdybeast@example.tld",
        "SPACED_KEY": "parsed",
    }


@pytest.mark.parametrize(
    "text",
    [
        "SERVER=localhost\rPASSWORD=password\rDB=tests\r",
        "SERVER=localhost\nPASSWORD=password\nDB=tests\n",
        "SERVER=localhost\r\nPASSWORD=password\r\nDB=tests\r\n",
    ],
)
def test_parse_env_file_line_breaks(text):
    assert list(parse_env_file(text).items()) == [("SERVER", "localhost"), ("PASSWORD", "password"), ("DB", "tests")]


def test_parse_env_file_colon_separator_and_carriage_return_escape():
    assert parse_env_file('A: 1\nB="x\\ry"\nBUFFER=true') == {"A": "1", "B": "x\ry", "BUFFER": "true"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": {"b": 1}, // note\n}', {"a": {"b": 1}}),
        ("[1, /* c */ ]", [1]),
        ('{"url": "http://x//y", /* "k": 1, */ "n": [1,2,],}', {"url": "http://x//y", "n": [1, 2]}),
        ('{"s": "a,}"}', {"s": "a,}"}),
    ],
)
def test_jsonc_comments_then_trailing_commas(text, expected):
    import json

    try:
        parsed = json.loads(strip_jsonc(text))
    except json.JSONDecodeError:
        parsed = "not JSON"
    assert parsed == expected


def test_jsonc_block_comment_keeps_line_numbers_of_later_errors():
    import json

    with pytest.raises(json.JSONDecodeError) as error:
        json.loads(strip_jsonc('{\n/* one\ntwo\n*/\n"a": }'))
    assert error.value.lineno == 5


@pytest.mark.parametrize(
    ("switch", "entrypoint", "allowlist"),
    [
        ("1", None, True),
        ("true", None, True),
        ("YES", "local-agent", True),
        ("0", "local-agent", False),
        ("false", "local-agent", False),
        ("off", None, False),
        (None, "local-agent", True),
        (None, "cli", False),
        (None, None, False),
        ("maybe", "local-agent", True),
        ("maybe", None, False),
    ],
)
def test_claude_code_allowlist_switch_truth_table(switch, entrypoint, allowlist):
    env = {}
    if switch is not None:
        env["CLAUDE_CODE_MCP_ALLOWLIST_ENV"] = switch
    if entrypoint is not None:
        env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
    assert ClaudeCodeHost.allowlist_mode(env) is allowlist


def test_claude_code_settings_env_blocks_follow_precedence_and_the_entry_wins(box, capsys):
    box.write(
        box.home / ".claude" / "settings.json", {"env": {"OPENPROJECT_API_TOKEN": TOKEN, "OPENPROJECT_TIMEOUT": "11"}}
    )
    box.write(
        box.cwd / ".claude" / "settings.json", {"env": {"OPENPROJECT_TIMEOUT": "12", "OPENPROJECT_MAX_RESULTS": "90"}}
    )
    box.write(box.cwd / ".claude" / "settings.local.json", {"env": {"OPENPROJECT_MAX_RESULTS": "80"}})
    box.write(box.system / "managed-settings.json", {"env": {"OPENPROJECT_DEFAULT_PAGE_SIZE": "7"}})
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_DEFAULT_PAGE_SIZE": "8"})
    box.write(box.claude_state, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    (probe_env,) = box.probe.calls
    assert probe_env.get("OPENPROJECT_API_TOKEN") == TOKEN
    assert probe_env.get("OPENPROJECT_MAX_RESULTS") == "80"
    assert probe_env.get("OPENPROJECT_DEFAULT_PAGE_SIZE") == "8"


def test_claude_code_allowlist_mode_makes_shell_and_settings_keys_unverifiable(box, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MCP_ALLOWLIST_ENV", "1")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", TOKEN)
    box.write(box.claude_state, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert any("allowlist mode" in line and "OPENPROJECT_API_TOKEN" in line for line in run.lines(CLAUDE_USER))
    assert box.probe.calls == []


@pytest.mark.parametrize(
    ("entry_extra", "level"),
    [({}, "WARN"), ({"OPENPROJECT_MAX_PAGE_SIZE": "200"}, "FAIL")],
)
def test_claude_code_allowlist_contradiction_is_certain_only_with_the_entrys_own_values(box, entry_extra, level):
    ctx = box.ctx()
    ctx.shell_env.update({"CLAUDE_CODE_MCP_ALLOWLIST_ENV": "1", "OPENPROJECT_MAX_PAGE_SIZE": "10"})
    env = {**VALID_ENV, "OPENPROJECT_MAX_RESULTS": "20", **entry_extra}
    source = Source(box.mcp_json, "mcpServers", Syntax.CLAUDE_CODE, "project", box.cwd)
    host = ClaudeCodeHost([], [])

    evaluation = evaluate(
        Subject(host, "x", effective=host.effective_env(ServerSpec("cmd", (), env), source, ctx)), ctx
    )

    (finding,) = [f for f in evaluation.findings if "must not exceed OPENPROJECT_MAX_RESULTS" in f.text]
    assert finding.level.value == level


def test_claude_code_allowlist_mode_without_the_key_anywhere_fails(box, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MCP_ALLOWLIST_ENV", "true")
    box.write(box.claude_state, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert "FAIL" in run.levels(CLAUDE_USER)


def test_claude_code_names_agent_proxy_and_shell_prefix(box, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SHELL_PREFIX", "/usr/bin/wrapper")
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})

    box.write(box.mcp_json, {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.out.count("[INFO] Claude Code: Claude Code can add its agent proxy settings") == 1
    assert "[INFO] Claude Code: CLAUDE_CODE_SHELL_PREFIX in this shell wraps the server command" in run.out
    assert not any("agent proxy" in line for line in run.lines(CLAUDE_USER))


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_claude_desktop_gets_the_base_set_and_only_entry_openproject_keys(box, platform):
    ctx = box.ctx(platform)
    ctx.shell_env.clear()
    shell = {"HOME": "/h", "PATH": "/p", "SYSTEMROOT": "C:\\Windows", "OPENPROJECT_TIMEOUT": "9", "OTHER": "x"}
    ctx.shell_env.update(shell)
    spec = ServerSpec("cmd", (), {"OPENPROJECT_BASE_URL": BASE_URL})

    env = (
        ClaudeDesktopHost()
        .effective_env(spec, Source(box.desktop_config, "mcpServers", Syntax.UNKNOWN, "user"), ctx)
        .env
    )

    assert env.get("HOME") == "/h" and env.get("PATH") == "/p"
    assert ("SYSTEMROOT" in env) is (platform == "win32")
    assert "OPENPROJECT_TIMEOUT" not in env
    assert "OTHER" not in env
    assert env.get("OPENPROJECT_BASE_URL") == BASE_URL


def test_cursor_warns_for_a_key_only_the_shell_has_and_names_inherited_shell_variables(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", TOKEN)
    monkeypatch.setenv("OPENPROJECT_ENABLE_ADMIN_WRITE", "true")
    box.write(
        box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}}
    )

    run = box.run(capsys)

    identity = "Cursor openproject (~/.cursor/mcp.json, user)"
    text = "\n".join(run.lines(identity))
    assert run.exit_code == EXIT_SUCCESS
    assert "works only if Cursor inherits this shell's variables" in text
    assert "OPENPROJECT_ENABLE_ADMIN_WRITE is set in this shell" in text
    assert "FAIL" not in run.levels(identity)
    assert box.probe.calls == []


def test_cursor_missing_key_everywhere_fails(box, capsys):
    box.write(
        box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}}
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE


def test_probe_base_set_for_an_entry_only_host(box, capsys, monkeypatch):
    monkeypatch.setenv("UNRELATED", "do-not-forward")
    monkeypatch.setenv("LANG", "C.UTF-8")
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    (probe_env,) = box.probe.calls
    assert probe_env.get("PATH") == str(box.bin)
    assert probe_env.get("HOME") == str(box.home)
    assert probe_env.get("LANG") == "C.UTF-8"
    assert "UNRELATED" not in probe_env
    assert probe_env.get("OPENPROJECT_MAX_RETRIES") == "0"
    assert probe_env.get("OPENPROJECT_TIMEOUT") == "5"
    assert "platform minimum" in run.out


# ── one file, several hosts ────────────────────────────────────────────────────


def test_one_mcp_json_entry_differs_between_claude_code_and_vscode(box, capsys):
    box.detect_vscode()
    box.write(box.home / ".claude" / "settings.json", {"env": {"OPENPROJECT_API_TOKEN": TOKEN}})
    box.write(box.mcp_json, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    claude = "Claude Code openproject (.mcp.json, project scope)"
    vscode = "VS Code openproject (.mcp.json, workspace)"
    assert any("API: connected" in line for line in run.lines(claude))
    assert any("OPENPROJECT_API_TOKEN is not set in the entry" in line for line in run.lines(vscode))
    assert not any("API: connected" in line for line in run.lines(vscode))
    assert [call.get("OPENPROJECT_API_TOKEN") for call in box.probe.calls] == [TOKEN]


def test_vscode_expands_mcp_json_with_the_copilot_rules(box, capsys, monkeypatch):
    box.detect_vscode()
    monkeypatch.setenv("OP_TOKEN", TOKEN)
    entry = server({"OPENPROJECT_BASE_URL": "${OP_BASE:-" + BASE_URL + "}", "OPENPROJECT_API_TOKEN": "${OP_TOKEN}"})
    box.write(box.mcp_json, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    vscode = "VS Code openproject (.mcp.json, workspace)"
    assert any("API: connected" in line for line in run.lines(vscode))
    assert {(call.get("OPENPROJECT_BASE_URL"), call.get("OPENPROJECT_API_TOKEN")) for call in box.probe.calls} == {
        (BASE_URL, TOKEN)
    }


def test_vscode_reads_a_workspace_mcp_json_without_the_mcp_servers_wrapper(box, capsys):
    box.detect_vscode()
    box.write(box.mcp_json, {"openproject": server()})

    run = box.run(capsys)

    assert any("API: connected" in line for line in run.lines("VS Code openproject (.mcp.json, workspace)"))


def test_vscode_takes_discovered_files_literally(box, capsys, monkeypatch):
    box.detect_vscode()
    monkeypatch.setenv("OP_TOKEN", TOKEN)
    box.write(box.vscode_user_mcp.parent / "settings.json", {"chat.mcp.discovery.enabled": {"claude-desktop": True}})
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN": "${OP_TOKEN}"})
    box.write(box.desktop_config, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    discovered = [line for line in run.out.splitlines() if "Claude Desktop via discovery" in line and "API:" in line]
    assert discovered and all("API: connected" in line for line in discovered)
    assert [call.get("OPENPROJECT_API_TOKEN") for call in box.probe.calls] == ["${OP_TOKEN}"]


@pytest.mark.parametrize(
    ("setting", "copilot_on_extension_host"),
    [(None, True), (False, False), ({"copilot": False}, False), ({"claude-desktop": True}, True), (True, True)],
)
def test_copilot_file_follows_the_discovery_setting(box, capsys, setting, copilot_on_extension_host):
    box.detect_vscode()
    if setting is not None:
        box.write(box.vscode_user_mcp.parent / "settings.json", {"chat.mcp.discovery.enabled": setting})
    box.write(box.home / ".copilot" / "mcp-config.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert (
        bool(run.lines("VS Code openproject (~/.copilot/mcp-config.json, Copilot user)")) is copilot_on_extension_host
    )
    assert run.lines("VS Code Agent Host openproject (~/.copilot/mcp-config.json, Copilot user)")


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        (None, set()),
        (True, {"Claude Desktop", "Cursor user", "Cursor workspace", "Windsurf"}),
        ({"cursor-global": True, "windsurf": "yes"}, {"Cursor user"}),
        ({"claude-desktop": True, "cursor-workspace": True}, {"Claude Desktop", "Cursor workspace"}),
    ],
)
def test_discovered_sources_follow_the_setting(box, capsys, setting, expected):
    box.detect_vscode()
    if setting is not None:
        box.write(box.vscode_user_mcp.parent / "settings.json", {"chat.mcp.discovery.enabled": setting})
    for path in (
        box.desktop_config,
        box.home / ".cursor" / "mcp.json",
        box.cwd / ".cursor" / "mcp.json",
        box.home / ".codeium" / "windsurf" / "mcp_config.json",
    ):
        box.write(path, {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    found = {
        label
        for label in ("Claude Desktop", "Cursor user", "Cursor workspace", "Windsurf")
        if f"VS Code ({label} via discovery)" in run.out
    }
    assert found == expected


def test_inheriting_host_with_a_key_it_may_inherit_warns_and_exits_zero(box, capsys):
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    summary = run.out.split("could not be fully verified; see the [WARN] lines above:\n", 1)[1]
    assert {line for line in summary.splitlines() if line} == {
        "  - VS Code openproject (.vscode/mcp.json, workspace)",
        "  - VS Code Agent Host openproject (.vscode/mcp.json, workspace)",
    }
    assert "All checks passed" not in run.out
    assert box.probe.calls == []


def test_allowlist_host_missing_the_key_fails(box, capsys):
    box.write(box.desktop_config, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE


def test_env_file_key_is_fine_on_the_extension_host_and_a_warning_on_the_agent_host(box, capsys):
    env_file = box.write(box.root / "secrets.env", f"OPENPROJECT_API_TOKEN={TOKEN}\n")
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL}, envFile=str(env_file))
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": entry}})

    run = box.run(capsys)

    ext = "VS Code openproject (.vscode/mcp.json, workspace)"
    agent = "VS Code Agent Host openproject (.vscode/mcp.json, workspace)"
    assert any("API: connected" in line for line in run.lines(ext))
    agent_text = "\n".join(run.lines(agent))
    assert "missing in Agent Host sessions with the Codex agent; `envFile` is not read there" in agent_text
    assert "FAIL" not in run.levels(agent)
    assert run.exit_code == EXIT_SUCCESS


def test_env_file_in_mcp_json_is_ignored_by_the_extension_host(box, capsys):
    box.detect_vscode()
    env_file = box.write(box.root / "secrets.env", f"OPENPROJECT_API_TOKEN={TOKEN}\n")
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL}, envFile=str(env_file))
    box.write(box.mcp_json, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    ext = "VS Code openproject (.mcp.json, workspace)"
    text = "\n".join(run.lines(ext))
    assert "VS Code ignores `envFile` in this file" in text
    assert "OPENPROJECT_API_TOKEN is not set in the entry" in text
    assert box.probe.calls == []


def test_agent_host_does_not_take_a_required_key_from_the_shell(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", TOKEN)
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}})

    run = box.run(capsys)

    agent = "VS Code Agent Host openproject (.vscode/mcp.json, workspace)"
    assert any("OPENPROJECT_API_TOKEN is not set in the entry" in line for line in run.lines(agent))
    assert not any("API:" in line for line in run.lines(agent))
    assert any("API: connected" in line for line in run.lines("VS Code openproject (.vscode/mcp.json, workspace)"))


@pytest.mark.parametrize(
    ("extra", "level"),
    [
        ({"OPENPROJECT_DEFAULT_PAGE_SIZE": "60", "OPENPROJECT_MAX_PAGE_SIZE": "50"}, "FAIL"),
        ({"OPENPROJECT_DEFAULT_PAGE_SIZE": "60"}, "WARN"),
    ],
)
def test_agent_host_contradiction_fails_only_when_the_entry_sets_both_values(box, extra, level):
    ctx = box.ctx()
    spec = ServerSpec("cmd", (), {**VALID_ENV, **extra})
    source = Source(box.vscode_workspace_mcp, "servers", Syntax.VSCODE, "workspace", box.cwd)
    effective = VsCodeAgentHost().effective_env(spec, source, ctx)

    evaluation = evaluate(Subject(VsCodeAgentHost(), "x", effective=effective), ctx)

    (finding,) = [f for f in evaluation.findings if "DEFAULT_PAGE_SIZE" in f.text]
    assert finding.level.value == level


@pytest.mark.parametrize(
    ("page_size", "level"),
    [("${OPM_UNSET_PAGE_SIZE}", "WARN"), ("50", "FAIL")],
)
def test_inheriting_host_contradiction_with_an_unresolved_placeholder_is_not_a_fail(box, page_size, level):
    ctx = box.ctx()
    env = {**VALID_ENV, "OPENPROJECT_MAX_RESULTS": "20", "OPENPROJECT_MAX_PAGE_SIZE": page_size}
    source = Source(box.mcp_json, "mcpServers", Syntax.CLAUDE_CODE, "project", box.cwd)
    host = ClaudeCodeHost([], [])
    effective = host.effective_env(ServerSpec("cmd", (), env), source, ctx)

    evaluation = evaluate(Subject(host, "x", effective=effective), ctx)

    (finding,) = [f for f in evaluation.findings if "must not exceed OPENPROJECT_MAX_RESULTS" in f.text]
    assert finding.level.value == level


def test_input_placeholder_entry_is_not_forwarded_to_the_agent_host(box, capsys):
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN": "${input:op-token}"})
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": entry}})

    run = box.run(capsys)

    assert "needs interactive input, so VS Code does not forward it to the Agent Host" in run.out
    assert "VS Code Agent Host openproject" not in run.out
    assert "OPENPROJECT_API_TOKEN uses a placeholder" in "\n".join(
        run.lines("VS Code openproject (.vscode/mcp.json, workspace)")
    )
    assert box.probe.calls == []


def test_vscode_workspace_file_with_comments_and_trailing_commas_is_read(box, capsys):
    box.write(
        box.vscode_workspace_mcp,
        '{\n  // OpenProject\n  "servers": {"openproject": {"command": "openproject-ce-mcp", /* c */ "env": {'
        + f'"OPENPROJECT_BASE_URL": "{BASE_URL}", "OPENPROJECT_API_TOKEN": "a//b",'
        + "},},},\n}\n",
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert box.probe.calls[0].get("OPENPROJECT_API_TOKEN") == "a//b"


# ── Windows names ──────────────────────────────────────────────────────────────


def test_env_map_folds_names_only_when_case_insensitive():
    windows = EnvMap({"Path": "a"}, case_insensitive=True)
    windows["PATH"] = "b"
    posix = EnvMap({"Path": "a"}, case_insensitive=False)
    posix["PATH"] = "b"

    assert list(windows) == ["PATH"] and windows.get("path") == "b"
    assert sorted(posix) == ["PATH", "Path"]


def test_windows_lower_case_required_key_in_an_entry_satisfies_it(box):
    ctx = box.ctx("win32")
    spec = ServerSpec("cmd", (), {"openproject_base_url": BASE_URL, "openproject_api_token": TOKEN})
    effective = ClaudeDesktopHost().effective_env(
        spec, Source(box.desktop_config, "mcpServers", Syntax.UNKNOWN, "user"), ctx
    )

    evaluation = evaluate(Subject(ClaudeDesktopHost(), "x", effective=effective), ctx)

    assert not evaluation.failed
    assert evaluation.settings is not None and evaluation.settings.api_token.get_secret_value() == TOKEN


def test_posix_lower_case_required_key_does_not_satisfy_it(box):
    ctx = box.ctx("linux")
    spec = ServerSpec("cmd", (), {"openproject_base_url": BASE_URL, "openproject_api_token": TOKEN})
    effective = ClaudeDesktopHost().effective_env(
        spec, Source(box.desktop_config, "mcpServers", Syntax.UNKNOWN, "user"), ctx
    )

    assert evaluate(Subject(ClaudeDesktopHost(), "x", effective=effective), ctx).failed


def test_windows_path_from_two_layers_collides_into_one_key(box):
    ctx = box.ctx("win32")
    ctx.shell_env.clear()
    ctx.shell_env["Path"] = r"C:\a"
    spec = ServerSpec("cmd", (), {"PATH": r"C:\b"})

    env = VsCodeHost().effective_env(spec, Source(box.vscode_workspace_mcp, "servers", Syntax.VSCODE, "w"), ctx).env

    assert [name for name in env if name.upper() == "PATH"] == ["PATH"]
    assert env.get("path") == r"C:\a;C:\b"


def test_probe_dedupe_key_folds_names_on_windows_only():
    def key(items: dict[str, str], windows: bool) -> tuple:
        env = EnvMap(items, case_insensitive=windows)
        effective = EffectiveEnv(env=env)
        return probe_key(Evaluation(Subject(CursorHost(), "x", effective=effective), probe_env=env))

    upper = {"OPENPROJECT_TIMEOUT": "5", "HTTPS_PROXY": "http://p"}
    lower = {"openproject_timeout": "5", "https_proxy": "http://p"}
    assert key(upper, windows=True) == key(lower, windows=True)
    assert key(upper, windows=False) != key(lower, windows=False)


# ── states ─────────────────────────────────────────────────────────────────────


def _disabled_in(box: Sandbox, where: str, names: dict) -> None:
    if where == "claude.json":
        box.write(box.claude_state, {"projects": {str(box.cwd): names}})
    elif where == "user settings":
        box.write(box.home / ".claude" / "settings.json", names)
    elif where == "project settings":
        box.write(box.cwd / ".claude" / "settings.json", names)
    elif where == "local settings":
        box.write(box.cwd / ".claude" / "settings.local.json", names)
    else:
        box.write(box.system / "managed-settings.json", names)


_SOURCES = ["claude.json", "user settings", "project settings", "local settings", "managed"]
_PROJECT = "Claude Code openproject (.mcp.json, project scope)"


@pytest.mark.parametrize("where", _SOURCES)
def test_disabled_mcp_json_server_is_inactive_and_does_not_count(box, capsys, where):
    _disabled_in(box, where, {"disabledMcpjsonServers": ["openproject"]})
    box.write(box.mcp_json, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": "not a url"})}})

    run = box.run(capsys)

    assert any("inactive (disabled in Claude Code (disabledMcpjsonServers))" in line for line in run.lines(_PROJECT))
    assert "FAIL" in run.levels(_PROJECT)
    assert run.exit_code == EXIT_SUCCESS
    assert "no active OpenProject entry" in run.out
    assert "All checks passed" not in run.out


def test_disabled_mcp_json_servers_does_not_disable_other_scopes(box, capsys):
    box.write(box.home / ".claude" / "settings.json", {"disabledMcpjsonServers": ["openproject"]})
    box.write(box.claude_state, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": "not a url"})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert not any("inactive" in line for line in run.lines(CLAUDE_USER))


@pytest.mark.parametrize("scope", ["user", "local", "project"])
def test_disabled_mcp_servers_in_the_project_entry_disables_every_scope(box, capsys, scope):
    broken = server({"OPENPROJECT_BASE_URL": "not a url"})
    project = {"disabledMcpServers": ["openproject"]}
    state: dict = {"projects": {str(box.cwd): project}}
    if scope == "user":
        state["mcpServers"] = {"openproject": broken}
    elif scope == "local":
        project["mcpServers"] = {"openproject": broken}
    else:
        box.write(box.mcp_json, {"mcpServers": {"openproject": broken}})
    box.write(box.claude_state, state)

    run = box.run(capsys)

    assert "inactive (disabled in Claude Code (disabledMcpServers))" in run.out
    assert run.exit_code == EXIT_SUCCESS


@pytest.mark.parametrize("where", _SOURCES[1:])
def test_disabled_mcp_servers_in_a_settings_file_has_no_effect(box, capsys, where):
    _disabled_in(box, where, {"disabledMcpServers": ["openproject"]})
    box.write(box.mcp_json, {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": "not a url"})}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert not any("inactive" in line for line in run.lines(_PROJECT))


def test_shadowed_entry_is_validated_and_counts(box, capsys):
    box.write(
        box.claude_state,
        {
            "mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": "not a url"})},
            "projects": {str(box.cwd): {"mcpServers": {"openproject": server()}}},
        },
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("shadowed here by Claude Code openproject" in line for line in run.lines(CLAUDE_USER))
    assert "FAIL" in run.levels(CLAUDE_USER)
    local = f"Claude Code openproject (~/.claude.json, local scope, projects[{box.cwd}])"
    assert any("API: connected" in line for line in run.lines(local))


def test_local_scope_key_is_the_git_root(box, capsys, monkeypatch):
    git = shutil.which("git", path=box.original_path)
    if git is None:
        pytest.skip("git is not installed")
    monkeypatch.setenv("PATH", os.pathsep.join([str(box.bin), str(Path(git).parent)]))
    subprocess.run(["git", "init", "-q", str(box.cwd)], check=True)
    sub = box.cwd / "sub"
    sub.mkdir()
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=sub, capture_output=True, text=True
    ).stdout.strip()
    box.write(box.claude_state, {"projects": {root: {"mcpServers": {"openproject": server()}}}})
    ctx = box.ctx()
    ctx = type(ctx)(shell_env=ctx.shell_env, cwd=sub, home=ctx.home, platform=ctx.platform, system=ctx.system)

    capsys.readouterr()
    exit_code = _run_doctor(probe=box.probe, ctx=ctx, codex=None)

    assert exit_code == EXIT_SUCCESS
    assert f"local scope, projects[{root}]" in capsys.readouterr().out


def test_remote_http_entry_is_reported_and_skipped(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": {"type": "http", "url": "https://mcp.example.invalid"}}})

    run = box.run(capsys)

    assert any("HTTP server; not checked" in line for line in run.lines(CLAUDE_USER))
    assert "no active OpenProject entry" in run.out
    assert run.exit_code == EXIT_SUCCESS


def test_entry_detected_by_command_not_by_name(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"tracker": server(command="/opt/x/bin/openproject-ce-mcp")}})

    run = box.run(capsys)

    assert run.lines("Claude Code tracker (~/.claude.json, user scope)")


def test_shape_errors_are_per_entry_failures(box, capsys):
    box.write(
        box.claude_state,
        {"mcpServers": {"openproject": {"command": "x", "env": ["not", "a", "map"]}, "openproject-2": "nope"}},
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("`env` is not an object" in line for line in run.lines(CLAUDE_USER))
    assert any("not an object" in line for line in run.lines("Claude Code openproject-2 (~/.claude.json, user scope)"))


def test_servers_section_that_is_not_a_mapping_fails_without_crashing(box, capsys):
    box.write(box.desktop_config, {"mcpServers": ["openproject"]})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert "has a `mcpServers` that is not an object" in run.out


# ── placeholders ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "syntax", "expected"),
    [
        ("${env:A}/x", Syntax.VSCODE, "1/x"),
        ("${env:MISSING}", Syntax.VSCODE, None),
        ("${workspaceFolder}/.env", Syntax.VSCODE, f"{Path('/ws')}/.env"),
        ("${userHome}/f", Syntax.VSCODE, f"{Path('/home/u')}/f"),
        ("${input:token}", Syntax.VSCODE, None),
        ("${A}", Syntax.VSCODE, None),
        ("${A}-${B:-dflt}", Syntax.CLAUDE_CODE, "1-dflt"),
        ("${MISSING}", Syntax.CLAUDE_CODE, None),
        ("${env:A}", Syntax.CLAUDE_CODE, "${env:A}"),
        ("${A}", Syntax.LITERAL, "${A}"),
        ("${A}", Syntax.UNKNOWN, None),
        ("plain", Syntax.UNKNOWN, "plain"),
        ("${A}/${B:-d}", Syntax.COPILOT, "1/d"),
        ("$A", Syntax.COPILOT, "$A"),
        ("${MISSING}", Syntax.COPILOT, None),
        ("${env:A}", Syntax.COPILOT, "${env:A}"),
        ("${B:-${A}}", Syntax.COPILOT, "${A}"),
        ("${B:-x}y}", Syntax.COPILOT, "xy}"),
        ("${B:-'}'}", Syntax.COPILOT, "''}"),
        ("${B:-$(a})}", Syntax.COPILOT, "$(a})"),
        ("${EMPTY:-d}", Syntax.COPILOT, ""),
        ("$" + "{MISSING}" + "x" * 1000, Syntax.COPILOT, "$" + "{MISSING}" + "x" * 1000),
    ],
)
def test_placeholders_per_syntax(value, syntax, expected):
    lookup = {"A": "1", "EMPTY": ""}
    assert resolve(value, syntax, lookup, workspace=Path("/ws"), home=Path("/home/u")) == expected


def test_copilot_names_are_case_insensitive_on_windows_only():
    windows = EnvMap({"Path": "p"}, case_insensitive=True)
    posix = EnvMap({"Path": "p"}, case_insensitive=False)

    assert resolve("${PATH}", Syntax.COPILOT, windows, workspace=None, home=Path("/h")) == "p"
    assert resolve("${PATH}", Syntax.COPILOT, posix, workspace=None, home=Path("/h")) is None


def test_vscode_workspace_folder_is_unknown_in_a_user_config():
    assert resolve("${workspaceFolder}", Syntax.VSCODE, {}, workspace=None, home=Path("/h")) is None


def test_boolean_key_placeholder_falls_back_to_its_default_and_is_named(box, capsys):
    entry = server({**VALID_ENV, "OPENPROJECT_VERIFY_SSL": "${input:verify}"})
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": entry}})

    run = box.run(capsys)

    identity = "VS Code openproject (.vscode/mcp.json, workspace)"
    text = "\n".join(run.lines(identity))
    assert "OPENPROJECT_VERIFY_SSL uses a placeholder this doctor cannot resolve; checked with its default" in text
    assert "FAIL" not in run.levels(identity)
    assert "SSL verification disabled" not in text
    assert run.exit_code == EXIT_SUCCESS
    assert box.probe.calls == []


def test_unresolvable_placeholder_in_an_unknown_host_is_unverifiable(box, capsys):
    entry = server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN": "${env:OP_TOKEN}"})
    box.write(box.desktop_config, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "OPENPROJECT_API_TOKEN uses a placeholder" in "\n".join(run.lines(_desktop_identity(box)))


# ── command check ───────────────────────────────────────────────────────────────


def test_missing_absolute_command_fails(box, capsys):
    box.write(
        box.claude_state, {"mcpServers": {"openproject": server(command=str(box.root / "nope" / "openproject-ce-mcp"))}}
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("does not exist" in line for line in run.lines(CLAUDE_USER) if line.startswith("[FAIL]"))


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable bit; the doctor skips the check there")
def test_non_executable_absolute_command_fails(box, capsys):
    path = box.write(box.root / "tool" / "openproject-ce-mcp", "")
    box.write(box.claude_state, {"mcpServers": {"openproject": server(command=str(path))}})

    run = box.run(capsys)

    assert any("is not executable" in line for line in run.lines(CLAUDE_USER) if line.startswith("[FAIL]"))


def test_relative_command_not_found_warns(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server(command="no-such-server")}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert any(
        "`no-such-server` is not on PATH here" in line for line in run.lines(CLAUDE_USER) if line.startswith("[WARN]")
    )


def test_desktop_command_only_on_a_non_default_path_warns_but_not_for_vscode(box, capsys):
    box.executable("op-fake-server-546")
    entry = server(command="op-fake-server-546")
    box.write(box.desktop_config, {"mcpServers": {"openproject": entry}})
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": entry}})

    run = box.run(capsys, platform="darwin")

    desktop = "\n".join(run.lines(_desktop_identity(box)))
    vscode = "\n".join(run.lines("VS Code openproject (.vscode/mcp.json, workspace)"))
    assert f"resolves only through {box.bin}, which is not on the macOS default PATH" in desktop
    assert "macOS default PATH" not in vscode
    assert run.exit_code == EXIT_SUCCESS


def test_launcher_package_and_version_spec_are_reported(box, capsys):
    box.executable("uvx")
    box.write(
        box.claude_state, {"mcpServers": {"openproject": server(command="uvx", args=["openproject-ce-mcp@0.4.2"])}}
    )

    run = box.run(capsys)

    assert any("uvx runs openproject-ce-mcp@0.4.2" in line for line in run.lines(CLAUDE_USER))


def test_launcher_package_url_credentials_are_not_printed(box, capsys):
    box.executable("uvx")
    spec = "git+https://user:ghp_secret@github.com/org/repo"
    entry = server(command="uvx", args=["--from", spec, "openproject-ce-mcp"])
    box.write(box.claude_state, {"mcpServers": {"openproject": entry}})

    run = box.run(capsys)

    assert "ghp_secret" not in run.out
    assert any("uvx runs git+https://***@github.com/org/repo" in line for line in run.lines(CLAUDE_USER))


def test_executable_from_another_install_warns_naming_both(box, capsys):
    other = box.executable("openproject-ce-mcp", box.root / "other-venv" / "bin")
    box.write(box.claude_state, {"mcpServers": {"openproject": server(command=str(other))}})

    run = box.run(capsys)

    own = own_server_binary()
    assert own.exists(), "the test environment installs the console script next to the interpreter"
    assert any(str(other) in line and str(own) in line for line in run.lines(CLAUDE_USER) if line.startswith("[WARN]"))


def test_own_install_does_not_warn(box, capsys):
    own = own_server_binary()
    box.write(box.claude_state, {"mcpServers": {"openproject": server(command=str(own))}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "All checks passed." in run.out


# ── connectivity and tools, deduplicated ────────────────────────────────────────


def test_probe_runs_once_per_distinct_connection_environment(box, capsys):
    box.write(
        box.claude_state,
        {
            "mcpServers": {
                "openproject": server(),
                "openproject-other": server({**VALID_ENV, "OPENPROJECT_API_TOKEN": "fake-token-2"}),
            }
        },
    )
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert sorted(call.get("OPENPROJECT_API_TOKEN") for call in box.probe.calls) == ["fake-token-1", "fake-token-2"]
    assert len([line for line in run.out.splitlines() if "API: connected" in line]) == 3


def test_tool_preview_runs_once_per_distinct_settings(box, capsys, monkeypatch):
    calls = []
    original = checks.tool_names
    monkeypatch.setattr(checks, "tool_names", lambda settings: calls.append(settings) or original(settings))
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert len(calls) == 1
    assert len([line for line in run.out.splitlines() if "would register" in line]) == 2


def test_failed_probe_fails_the_entry_and_shows_no_token(box, capsys):
    box.probe = FakeProbe(ProbeResult(False, category="auth_error", message="authentication failed"))
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("API: auth_error: authentication failed" in line for line in run.lines(CLAUDE_USER))
    assert TOKEN not in run.out


def test_scope_summary_and_insecure_warnings_carry_the_identity(box, capsys):
    env = {
        **VALID_ENV,
        "OPENPROJECT_VERIFY_SSL": "false",
        "OPENPROJECT_ALLOWED_PROJECTS_READ": "DEMO",
        "OPENPROJECT_ENABLE_PERSONAL_READ": "true",
        "OPENPROJECT_ENABLE_PERSONAL_WRITE": "true",
    }
    box.write(box.claude_state, {"mcpServers": {"openproject": server(env)}})

    run = box.run(capsys)

    text = "\n".join(run.lines(CLAUDE_USER))
    assert "SSL verification disabled" in text
    # A removed variable name is ignored like any unknown one, without a warning.
    assert "OPENPROJECT_ALLOWED_PROJECTS_READ" not in text
    assert "    Personal-data writes: True" in run.out


# ── fallback and exit status ────────────────────────────────────────────────────


def test_fallback_to_the_process_environment_when_no_client_configures_openproject(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_BASE_URL", BASE_URL)
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", TOKEN)

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert any("API: connected" in line for line in run.lines("process environment"))
    assert "All checks passed." in run.out


def test_fallback_with_an_invalid_process_environment_fails(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_BASE_URL", BASE_URL)

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("OPENPROJECT_API_TOKEN is not set" in line for line in run.lines("process environment"))


def test_unreadable_config_prevents_the_fallback(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_BASE_URL", BASE_URL)
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", TOKEN)
    box.write(box.claude_state, '{"mcpServers": {')

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert "~/.claude.json is not valid JSON (line 1, column 17)" in run.out
    assert "process environment" not in run.out.split("platform minimum", 1)[1]


def test_all_checks_passed_only_when_everything_was_verified(box, capsys):
    box.write(
        box.claude_state,
        {"mcpServers": {"openproject": server(command=str(own_server_binary()))}},
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert run.out.rstrip().endswith("All checks passed.")


def test_entries_seam_replaces_discovery(box, capsys):
    effective = EffectiveEnv(env=EnvMap(VALID_ENV, case_insensitive=False))
    subject = Subject(CursorHost(), "injected entry", effective=effective)

    run = box.run(capsys, entries=[subject])

    assert run.exit_code == EXIT_SUCCESS
    assert any("API: connected" in line for line in run.lines("Cursor injected entry"))


def test_restart_hints_name_each_client_with_a_counting_entry_once(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server(), "openproject-2": server()}})

    run = box.run(capsys)

    hints = run.out.split("Restart needed for:\n", 1)[1].split("\n\n", 1)[0]
    assert hints.count("  - Claude Code") == 1


def test_check_binary_reports_version(capsys):
    from openproject_ce_mcp import __version__
    from openproject_ce_mcp.doctor.run import _check_binary

    _check_binary()
    out = capsys.readouterr().out
    assert __version__ in out and "[OK] Binary:" in out


def test_check_binary_reports_the_python_running_it(capsys):
    import platform

    from openproject_ce_mcp.doctor.run import _check_binary

    _check_binary()

    out = capsys.readouterr().out
    assert f"[OK] Python: {platform.python_version()} ({sys.executable})" in out


def test_a_python_below_the_minimum_fails_before_the_checks_are_imported(capsys, monkeypatch):
    import openproject_ce_mcp.doctor as doctor

    monkeypatch.setattr(doctor, "MIN_PYTHON", (sys.version_info[0], sys.version_info[1] + 1))
    monkeypatch.delitem(sys.modules, "openproject_ce_mcp.doctor.run", raising=False)

    exit_code = doctor.run_doctor()

    assert exit_code == EXIT_FAILURE
    assert capsys.readouterr().out.startswith("[FAIL] Python:")
    assert "openproject_ce_mcp.doctor.run" not in sys.modules


def test_the_minimum_python_itself_passes_the_gate(monkeypatch):
    import openproject_ce_mcp.doctor as doctor
    from openproject_ce_mcp.doctor import run as doctor_run

    monkeypatch.setattr(doctor, "MIN_PYTHON", tuple(sys.version_info[:2]))
    monkeypatch.setattr(doctor_run, "run_doctor", lambda: EXIT_SUCCESS)

    assert doctor.run_doctor() == EXIT_SUCCESS


# ── MCP dispatch ───────────────────────────────────────────────────────────────


def test_dispatch_check_verifies_each_counting_entry(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert any(
        "MCP: dispatch rejects unknown arguments (checked in process)" in line for line in run.lines(CLAUDE_USER)
    )


def test_dispatch_check_runs_once_per_distinct_settings(box, capsys, monkeypatch):
    calls = []
    original = checks._build_and_verify_dispatch

    async def counting(settings):
        calls.append(settings)
        await original(settings)

    monkeypatch.setattr(checks, "_build_and_verify_dispatch", counting)
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert len(calls) == 1
    assert len([line for line in run.out.splitlines() if "dispatch rejects unknown arguments" in line]) == 2


def test_dispatch_check_leaves_the_doctors_logging_as_it_was():
    import asyncio
    import logging

    from openproject_ce_mcp.config import Settings

    root = logging.getLogger()
    before = (root.level, root.handlers[:], [handler.formatter for handler in root.handlers])
    settings = Settings.from_env(
        environ={**VALID_ENV, "OPENPROJECT_LOG_LEVEL": "DEBUG", "OPENPROJECT_LOG_FORMAT": "json"}
    )

    asyncio.run(checks.dispatch_finding(settings))

    assert (root.level, root.handlers[:], [handler.formatter for handler in root.handlers]) == before


def test_a_failing_dispatch_check_fails_the_entry(box, capsys, monkeypatch):
    async def broken(settings):
        raise RuntimeError("no tools/call handler")

    monkeypatch.setattr(checks, "_build_and_verify_dispatch", broken)
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("MCP: dispatch check failed (RuntimeError)" in line for line in run.lines(CLAUDE_USER))


def test_a_hanging_dispatch_check_fails_at_its_timeout(monkeypatch):
    import asyncio

    from openproject_ce_mcp.config import Settings

    async def hang(settings):
        await asyncio.sleep(999)

    monkeypatch.setattr(checks, "_build_and_verify_dispatch", hang)

    finding = asyncio.run(checks.dispatch_finding(Settings.from_env(VALID_ENV), timeout=0.05))

    assert finding.level is Level.FAIL
    assert "did not complete within 0.05 s" in finding.text


# ── configuration file permissions ─────────────────────────────────────────────

# chmod has no effect on Windows filesystems, so these could only pass there by accident.
posix_mode_bits = pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX mode bits")


@posix_mode_bits
def test_a_file_with_an_entry_open_to_group_or_others_warns(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}}).chmod(0o644)
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}}).chmod(0o604)

    run = box.run(capsys)

    assert (
        "[WARN] Permissions: ~/.claude.json is readable or writable by group or others (mode 0o644); "
        f"`chmod 600 {box.claude_state}` restricts it to you"
    ) in run.out
    assert "[WARN] Permissions: ~/.cursor/mcp.json is readable or writable by group or others (mode 0o604)" in run.out
    assert TOKEN not in run.out


@posix_mode_bits
def test_a_codex_layer_file_with_an_entry_is_checked_too(box, capsys):
    box.write(box.codex_config, '[mcp_servers.openproject]\ncommand = "openproject-ce-mcp"\n').chmod(0o640)

    run = box.run(capsys)

    assert "[WARN] Permissions: ~/.codex/config.toml is readable or writable by group or others (mode 0o640)" in run.out


@posix_mode_bits
def test_an_owner_only_file_and_a_file_without_an_entry_do_not_warn(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}}).chmod(0o600)
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"other": {"command": "x"}}}).chmod(0o644)

    run = box.run(capsys)

    assert "Permissions" not in run.out


def test_permissions_are_not_checked_on_windows(box):
    from openproject_ce_mcp.doctor.discovery import permission_notes

    path = box.write(box.claude_state, "{}")
    path.chmod(0o644)

    assert permission_notes([path], box.ctx("win32")) == [
        "[INFO] Permissions: not checked on Windows (POSIX mode bits do not apply)"
    ]


def test_doctor_output_has_no_value_from_a_config(box, capsys, monkeypatch):
    secret = "sentinel-secret-546"
    box.write(
        box.claude_state,
        {
            "mcpServers": {
                "openproject": server({**VALID_ENV, "OPENPROJECT_API_TOKEN": secret, "OPENPROJECT_TIMEOUT": "abc"})
            }
        },
    )

    run = box.run(capsys)

    assert secret not in run.out
    assert os.environ.get("OPENPROJECT_API_TOKEN") is None


# ── output ─────────────────────────────────────────────────────────────────────


def test_scope_summary_is_printed_once_per_distinct_settings(box, capsys):
    box.write(box.claude_state, {"mcpServers": {"openproject": server()}})
    box.write(box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server()}})

    run = box.run(capsys)

    assert run.out.count("    Read projects:") == 1
    assert f"    scope as for {CLAUDE_USER}" in run.out


def test_entries_that_differ_only_in_the_host_share_one_block(box, capsys):
    own = str(own_server_binary())
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": server(command=own)}})

    run = box.run(capsys)

    merged = "VS Code, VS Code Agent Host openproject (.vscode/mcp.json, workspace)"
    assert any(line.startswith(f"[OK] {merged}: API: connected") for line in run.out.splitlines())
    assert "] VS Code openproject (" not in run.out
    assert run.exit_code == EXIT_SUCCESS and run.out.rstrip().endswith("All checks passed.")


def test_entries_with_different_findings_keep_separate_blocks(box, capsys):
    entry = server(envFile=str(box.root / "missing.env"))
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": entry}})

    run = box.run(capsys)

    assert "VS Code, VS Code Agent Host" not in run.out
    assert "FAIL" in run.levels("VS Code openproject (.vscode/mcp.json, workspace)")
    assert "FAIL" not in run.levels("VS Code Agent Host openproject (.vscode/mcp.json, workspace)")


@pytest.mark.parametrize(
    ("key", "stored"),
    [
        (PureWindowsPath("C:/Users/me/repo"), "C:/Users/me/repo"),
        (PureWindowsPath("C:/Users/me/repo"), "C:\\Users\\me\\repo"),
        (PurePosixPath("/home/me/repo"), "/home/me/repo"),
    ],
)
def test_claude_project_is_found_under_either_slash_form(key, stored):
    entry = {"mcpServers": {}}

    assert claude_project({stored: entry, "other": {}}, key) == (stored, entry)


def test_claude_project_is_none_without_a_matching_key():
    assert claude_project({"C:/elsewhere": {}}, PureWindowsPath("C:/Users/me/repo")) is None
