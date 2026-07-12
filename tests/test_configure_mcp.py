from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

# The interactive setup lives in the package at src/openproject_ce_mcp/setup_cli.py.
# Load it explicitly by file path so it resolves the same way under every pytest
# runner regardless of sys.path (and independent of the root configure_mcp.py shim).
_SPEC = importlib.util.spec_from_file_location(
    "openproject_ce_mcp_setup_cli",
    Path(__file__).resolve().parent.parent / "src" / "openproject_ce_mcp" / "setup_cli.py",
)
assert _SPEC and _SPEC.loader
c = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(c)

# tomllib is stdlib only on 3.11+. Import it optionally so the JSON/backup/flow
# tests still run on 3.10; only the TOML round-trip assertions are guarded.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

_needs_tomllib = pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")

ENV = {
    "OPENPROJECT_BASE_URL": "https://op.example.com",
    "OPENPROJECT_API_TOKEN": 'opapi-with"quote\\and-backslash',
}
CMD = "/home/user/openproject-ce-mcp/.venv/bin/openproject-ce-mcp"


# ── JSON merge (mcpServers / servers) ──────────────────────────────────────────


def test_merge_json_new_file_mcp_servers() -> None:
    data = json.loads(c._merge_json("", "mcpServers", CMD, ENV, stdio=False))
    server = data["mcpServers"]["openproject"]
    assert server["command"] == CMD
    assert server["env"] == ENV
    assert "type" not in server


def test_merge_json_servers_uses_stdio() -> None:
    data = json.loads(c._merge_json("", "servers", CMD, ENV, stdio=True))
    server = data["servers"]["openproject"]
    assert server["type"] == "stdio"
    assert server["command"] == CMD


def test_merge_json_preserves_other_servers_and_settings() -> None:
    existing = json.dumps(
        {
            "mcpServers": {"other": {"command": "/bin/other"}},
            "theme": "dark",
            "unrelated": {"nested": [1, 2, 3]},
        }
    )
    out = json.loads(c._merge_json(existing, "mcpServers", CMD, ENV, stdio=False))
    # openproject added…
    assert out["mcpServers"]["openproject"]["command"] == CMD
    # …other server kept…
    assert out["mcpServers"]["other"] == {"command": "/bin/other"}
    # …and unrelated top-level settings untouched.
    assert out["theme"] == "dark"
    assert out["unrelated"] == {"nested": [1, 2, 3]}


def test_merge_json_replaces_existing_openproject() -> None:
    existing = json.dumps({"mcpServers": {"openproject": {"command": "/old/path", "env": {"X": "1"}}}})
    out = json.loads(c._merge_json(existing, "mcpServers", CMD, ENV, stdio=False))
    assert out["mcpServers"]["openproject"]["command"] == CMD
    assert out["mcpServers"]["openproject"]["env"] == ENV


def test_toml_quote_escapes_specials() -> None:
    assert c._toml_quote('a"b\\c') == '"a\\"b\\\\c"'


# ── Codex TOML merge (text-level, no TOML writer) ──────────────────────────────


@_needs_tomllib
def test_merge_codex_toml_new_file_round_trips() -> None:
    data = tomllib.loads(c._merge_codex_toml("", CMD, ENV))
    server = data["mcp_servers"]["openproject"]
    assert server["command"] == CMD
    # Quotes and backslashes in the token must survive TOML escaping.
    assert server["env"]["OPENPROJECT_API_TOKEN"] == ENV["OPENPROJECT_API_TOKEN"]


@_needs_tomllib
def test_merge_codex_toml_preserves_other_tables() -> None:
    existing = '[some_setting]\nkey = "value"\n\n[mcp_servers.other]\ncommand = "/bin/other"\n'
    merged = c._merge_codex_toml(existing, CMD, ENV)
    data = tomllib.loads(merged)
    assert data["some_setting"]["key"] == "value"
    assert data["mcp_servers"]["other"]["command"] == "/bin/other"
    assert data["mcp_servers"]["openproject"]["command"] == CMD


@_needs_tomllib
def test_merge_codex_toml_replaces_existing_openproject() -> None:
    existing = (
        '[mcp_servers.openproject]\ncommand = "/old"\n\n'
        '[mcp_servers.openproject.env]\nOLD = "1"\n\n'
        '[mcp_servers.keep]\ncommand = "/bin/keep"\n'
    )
    merged = c._merge_codex_toml(existing, CMD, ENV)
    data = tomllib.loads(merged)
    assert data["mcp_servers"]["openproject"]["command"] == CMD
    assert "OLD" not in data["mcp_servers"]["openproject"].get("env", {})
    # A sibling server that shares the prefix name must NOT be dropped.
    assert data["mcp_servers"]["keep"]["command"] == "/bin/keep"


# ── detection ───────────────────────────────────────────────────────────────────


def test_detects_codex_via_config_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_home", lambda: tmp_path)
    monkeypatch.setattr(c.shutil, "which", lambda _name: None)
    assert c._detect_codex() is False
    (tmp_path / ".codex").mkdir()
    assert c._detect_codex() is True


def test_detects_claude_code_via_binary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_home", lambda: tmp_path)
    monkeypatch.setattr(c.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert c._detect_claude_code() is True


def test_clients_only_offers_detected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_home", lambda: tmp_path)
    monkeypatch.setattr(c.shutil, "which", lambda _name: None)
    # No client artifacts present → nothing detected.
    assert [cl for cl in c._clients() if cl.detected()] == []


# ── write + backup ──────────────────────────────────────────────────────────────


def _codex_client(target: Path, *, detect: bool = True, project_target: Path | None = None) -> c.Client:
    return c.Client(
        "codex",
        "Codex",
        target,
        "toml",
        lambda: detect,
        "docs/codex.md",
        project_target=project_target,
        restart_hint="reload Codex",
    )


def _json_client(target: Path, *, detect: bool = True, project_target: Path | None = None) -> c.Client:
    return c.Client(
        "claude-code",
        "Claude Code",
        target,
        "json",
        lambda: detect,
        "docs/claude.md",
        root_key="mcpServers",
        project_target=project_target,
        restart_hint="run /mcp",
    )


@_needs_tomllib
def test_write_client_config_creates_file(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "config.toml"
    assert c._write_client_config(_codex_client(target), CMD, ENV) is True
    assert target.exists()
    data = tomllib.loads(target.read_text())
    assert data["mcp_servers"]["openproject"]["command"] == CMD


def test_write_client_config_backs_up_and_preserves(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "/x"}}, "theme": "dark"}))
    monkeypatch.setattr(c, "_backup", lambda p: p.rename(p.with_name(f"{p.name}.bak.fixed")))
    assert c._write_client_config(_json_client(target), CMD, ENV) is True
    backup = tmp_path / ".claude.json.bak.fixed"
    assert backup.exists(), "existing config must be backed up before rewriting"
    result = json.loads(target.read_text())
    # openproject merged in, existing server + unrelated settings preserved.
    assert result["mcpServers"]["openproject"]["command"] == CMD
    assert result["mcpServers"]["other"] == {"command": "/x"}
    assert result["theme"] == "dark"


def test_write_client_config_skips_unparseable_file(monkeypatch, tmp_path: Path, capsys) -> None:
    target = tmp_path / ".claude.json"
    target.write_text("{ this is not valid json ")
    monkeypatch.setattr(c, "_backup", lambda p: None)
    assert c._write_client_config(_json_client(target), CMD, ENV) is False
    # Original file left untouched.
    assert target.read_text() == "{ this is not valid json "
    assert "could not be parsed" in capsys.readouterr().out


def test_backup_preserves_extension(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("x = 1\n")
    c._backup(target)
    backups = list(tmp_path.glob("config.toml.bak.*"))
    assert len(backups) == 1
    assert not target.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows does not honor POSIX chmod bits, even when _IS_WINDOWS is forced False",
)
def test_backup_chmods_backup_on_posix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_IS_WINDOWS", False)
    target = tmp_path / "config.toml"
    target.write_text("x = 1\n")
    target.chmod(0o644)

    c._backup(target)

    backup = next(tmp_path.glob("config.toml.bak.*"))
    assert backup.stat().st_mode & 0o777 == 0o600


def test_git_warning_noops_when_git_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    def _missing_git(*_args, **_kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(c.subprocess, "run", _missing_git)

    c._git_warning_for_unignored_file(tmp_path / ".mcp.json")

    assert capsys.readouterr().out == ""


def test_git_warning_noops_outside_git_repo(monkeypatch, tmp_path: Path, capsys) -> None:
    def _run(cmd, **_kwargs):
        assert "rev-parse" in cmd
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="not a repo")

    monkeypatch.setattr(c.subprocess, "run", _run)

    c._git_warning_for_unignored_file(tmp_path / ".mcp.json")

    assert capsys.readouterr().out == ""


def test_git_warning_noops_when_file_is_ignored(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = []

    def _run(cmd, **_kwargs):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        if "check-ignore" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(c.subprocess, "run", _run)

    c._git_warning_for_unignored_file(tmp_path / ".mcp.json")

    assert any("check-ignore" in cmd for cmd in calls)
    assert capsys.readouterr().out == ""


def test_git_warning_prints_when_file_is_not_ignored(monkeypatch, tmp_path: Path, capsys) -> None:
    def _run(cmd, **_kwargs):
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        if "check-ignore" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(c.subprocess, "run", _run)

    target = tmp_path / ".mcp.json"
    c._git_warning_for_unignored_file(target)

    out = capsys.readouterr().out
    assert str(target) in out
    assert "not ignored" in out
    assert ".gitignore" in out


# ── registration mode (asked up front, non-interactive) ─────────────────────────


class _AnswerBook:
    """Matches queued answers to wizard prompts by prompt content, not call order.

    Each key is a literal substring expected to appear in exactly one live prompt's
    text (checked on every call, not just at construction time — see OPM-132: a
    construction-time-only "is one key nested in another" check would miss two
    independent keys that both happen to match the same longer prompt). A key's
    value is a single answer or a queue: the tool-groups validation retry loop
    reprompts with a label that is a strict extension of the initial one
    ("Enabled tool groups" -> "Enabled tool groups — comma-separated, check
    spelling"), so one key with a multi-item queue naturally covers an initial ask
    plus its retries.
    """

    def __init__(self, answers: Mapping[str, str | Sequence[str]]) -> None:
        self._queues: dict[str, list[str]] = {
            key: [value] if isinstance(value, str) else list(value) for key, value in answers.items()
        }

    def __call__(self, prompt: str) -> str:
        matches = [key for key in self._queues if key in prompt]
        if not matches:
            raise AssertionError(f"no answer registered for prompt: {prompt!r}")
        if len(matches) > 1:
            raise AssertionError(f"multiple answers match prompt {prompt!r}: {matches}")
        queue = self._queues[matches[0]]
        if not queue:
            raise AssertionError(f"answer queue exhausted for {matches[0]!r} (prompt: {prompt!r})")
        return queue.pop(0)

    def assert_consumed(self) -> None:
        leftover = {key: queue for key, queue in self._queues.items() if queue}
        if leftover:
            raise AssertionError(f"answers registered but never consumed: {leftover}")


@contextmanager
def _answers(monkeypatch, answers: Mapping[str, str | Sequence[str]]):
    """Drive ``_choose_targets`` (or similar) with prompt-keyed answers.

    Yields the ``_AnswerBook`` and asserts everything was consumed on a normal
    exit — if the ``with`` body raises, that exception propagates first and this
    check is skipped, so a genuine failure is never masked.
    """
    book = _AnswerBook(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": book(prompt))
    yield book
    book.assert_consumed()


def test_answer_book_raises_on_two_independent_keys_matching_one_prompt() -> None:
    # "Enable" and "writes" don't contain each other (neither is a substring of
    # the other), so a construction-time-only "is one key nested in another"
    # check would miss this — both still match "Enable admin writes?" and the
    # runtime check in __call__ must catch it.
    book = _AnswerBook({"Enable": "y", "writes": "n"})
    with pytest.raises(AssertionError, match="multiple answers match"):
        book("Enable admin writes?")


def test_answer_book_raises_on_unregistered_prompt() -> None:
    book = _AnswerBook({"Configure globally": "y"})
    with pytest.raises(AssertionError, match="no answer registered"):
        book("Some other prompt")


def test_answer_book_assert_consumed_reports_leftover_key() -> None:
    book = _AnswerBook({"Configure globally": "y", "Configure project-scoped": "n"})
    book("Configure globally (user-wide)?")
    with pytest.raises(AssertionError, match="Configure project-scoped"):
        book.assert_consumed()


def test_answer_book_does_not_mutate_caller_supplied_list() -> None:
    caller_list = ["y", "n"]
    book = _AnswerBook({"Enabled tool groups": caller_list})
    book("Enabled tool groups")
    assert caller_list == ["y", "n"], "must copy, not pop from the caller's own list"


def test_choose_targets_both_gates_no(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate no, project gate no → nothing.
    with _answers(monkeypatch, {"Configure globally": "", "Configure project-scoped": ""}):
        assert c._choose_targets([codex]) == ([], [], [], [])


def test_choose_targets_global_only(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate yes, per-client yes; project gate is skipped because scopes are
    # configured in separate runs.
    with _answers(monkeypatch, {"Configure globally": "y", "Configure Codex?": "y"}):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([codex])
    assert global_clients == [codex]
    assert project_clients == []
    assert remove_global_clients == []
    assert remove_project_clients == []


def test_choose_targets_project_only(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate no; project gate yes, per-client yes.
    answers = {"Configure globally": "", "Configure project-scoped": "y", "Configure Codex?": "y"}
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == [codex]
    assert remove_global_clients == []
    assert remove_project_clients == []


def test_choose_targets_project_offers_undetected(monkeypatch, tmp_path: Path) -> None:
    # A client NOT detected still gets offered in the project gate (default n),
    # answer y anyway → it is selected. It is NOT offered in the global gate
    # (not even prompted: the global gate is skipped entirely when nothing is
    # detected, so no "Configure globally" key is registered here).
    codex = _codex_client(tmp_path / "config.toml", detect=False, project_target=tmp_path / ".codex" / "config.toml")
    answers = {"Configure project-scoped": "y", "Configure Codex?": "y"}
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == [codex]
    assert remove_global_clients == []
    assert remove_project_clients == []


def test_choose_targets_claude_code_default_yes_when_alone(monkeypatch, tmp_path: Path) -> None:
    # Claude Code undetected + no other project client detected → project default y,
    # so pressing Enter selects it. Global gate skipped entirely (nothing detected).
    claude = _json_client(tmp_path / ".claude.json", detect=False, project_target=tmp_path / ".mcp.json")
    answers = {"Configure project-scoped": "y", "Configure Claude Code?": ""}
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([claude])
    assert project_clients == [claude]
    assert global_clients == []
    assert remove_global_clients == []
    assert remove_project_clients == []


def test_choose_targets_offers_global_removal_when_global_gate_no(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"env": ENV}}}))
    claude = _json_client(target, project_target=tmp_path / ".mcp.json")

    answers = {
        "Configure globally": "n",
        "Remove existing global Claude Code": "y",
        "Configure project-scoped": "n",
    }
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([claude])

    assert global_clients == []
    assert project_clients == []
    assert remove_global_clients == [claude]
    assert remove_project_clients == []


def test_choose_targets_offers_project_removal_when_project_gate_no(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"env": ENV}}}))
    claude = _json_client(tmp_path / ".claude.json", detect=False, project_target=target)

    answers = {"Configure project-scoped": "n", "Remove existing project-scoped Claude Code": "y"}
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([claude])

    assert global_clients == []
    assert project_clients == []
    assert remove_global_clients == []
    assert remove_project_clients == [claude]


def test_choose_targets_global_config_can_remove_existing_project(monkeypatch, tmp_path: Path) -> None:
    project_target = tmp_path / ".mcp.json"
    project_target.write_text(json.dumps({"mcpServers": {"openproject": {"env": ENV}}}))
    claude = _json_client(tmp_path / ".claude.json", project_target=project_target)

    answers = {
        "Configure globally": "y",
        "Configure Claude Code?": "y",
        "Remove existing project-scoped Claude Code": "y",
    }
    with _answers(monkeypatch, answers):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([claude])

    assert global_clients == [claude]
    assert project_clients == []
    assert remove_global_clients == []
    assert remove_project_clients == [claude]


def test_has_openproject_config_detects_json_entry_without_env(tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"command": "old"}}}))
    claude = _json_client(tmp_path / ".claude.json", project_target=target)

    assert c._has_openproject_config(claude, target) is True


def test_has_openproject_config_detects_codex_toml_without_tomllib(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text('[mcp_servers.openproject]\ncommand = "old"\n')
    codex = _codex_client(tmp_path / "global.toml", project_target=target)
    monkeypatch.setattr(c, "_tomllib", None)

    assert c._has_openproject_config(codex, target) is True


def test_apply_global_registration_writes_chosen(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".claude.json"
    client = _json_client(target)
    c._apply_global_registration([client], CMD, ENV)
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["mcpServers"]["openproject"]["command"] == CMD


def test_apply_global_registration_empty_is_noop(tmp_path: Path) -> None:
    # No clients chosen → nothing written, no error.
    c._apply_global_registration([], CMD, ENV)


# ── regression: TOML multi-line array preservation (bug #1) ─────────────────────


@_needs_tomllib
def test_merge_codex_toml_preserves_multiline_array_table() -> None:
    # A multi-line array value has continuation lines that start with "[". The old
    # skip logic toggled on any line starting with "[", flipping skipping off
    # mid-table and leaking orphaned array fragments into the output. The table
    # (and the openproject block) must both survive as valid TOML.
    existing = '[mcp_servers.other]\ncommand = "/bin/other"\nargs = [\n  "--flag",\n  "--another",\n]\n'
    merged = c._merge_codex_toml(existing, CMD, ENV)
    data = tomllib.loads(merged)
    assert data["mcp_servers"]["other"]["command"] == "/bin/other"
    assert data["mcp_servers"]["other"]["args"] == ["--flag", "--another"]
    assert data["mcp_servers"]["openproject"]["command"] == CMD


def test_strip_codex_openproject_keeps_array_continuation_lines() -> None:
    # Text-level check that runs on 3.10 too: continuation lines beginning with
    # "[" must not be treated as table headers.
    existing = "[keep]\nvalues = [\n  [1, 2],\n  [3, 4],\n]\n"
    kept = c._strip_codex_openproject(existing)
    assert "values = [" in kept
    assert "[1, 2]," in kept
    assert "[3, 4]," in kept


# ── regression: dotted / inline openproject refusal (bug #2) ────────────────────


def test_merge_codex_toml_refuses_inline_table() -> None:
    existing = 'mcp_servers.openproject = { command = "/old" }\n'
    with pytest.raises(c.CodexMergeError):
        c._merge_codex_toml(existing, CMD, ENV)


def test_merge_codex_toml_refuses_dotted_key() -> None:
    existing = 'mcp_servers.openproject.command = "/old"\n'
    with pytest.raises(c.CodexMergeError):
        c._merge_codex_toml(existing, CMD, ENV)


def test_write_client_config_skips_dotted_codex(monkeypatch, tmp_path, capsys) -> None:
    target = tmp_path / "config.toml"
    original = 'mcp_servers.openproject.command = "/old"\n'
    target.write_text(original)
    monkeypatch.setattr(c, "_backup", lambda p: None)
    assert c._write_client_config(_codex_client(target), CMD, ENV) is False
    # File left byte-for-byte untouched.
    assert target.read_text() == original
    assert "could not be parsed" in capsys.readouterr().out


# ── regression: non-dict JSON refusal (bug #4) ──────────────────────────────────


def test_merge_json_refuses_non_dict_toplevel() -> None:
    with pytest.raises(ValueError):
        c._merge_json("[1, 2, 3]", "mcpServers", CMD, ENV, stdio=False)


def test_merge_json_refuses_non_dict_root_key() -> None:
    with pytest.raises(ValueError):
        c._merge_json('{"mcpServers": []}', "mcpServers", CMD, ENV, stdio=False)


def test_write_client_config_skips_non_dict_json(monkeypatch, tmp_path, capsys) -> None:
    target = tmp_path / ".claude.json"
    original = "[1, 2, 3]"
    target.write_text(original)
    monkeypatch.setattr(c, "_backup", lambda p: None)
    assert c._write_client_config(_json_client(target), CMD, ENV) is False
    # Existing (unexpected-shape) data must not be clobbered.
    assert target.read_text() == original
    assert "could not be parsed" in capsys.readouterr().out


# ── regression: backup timestamp collision (bug #6) ─────────────────────────────


def test_backup_collision_keeps_both(monkeypatch, tmp_path: Path) -> None:
    # Freeze the timestamp so two backups land in the "same second".
    class _FixedNow:
        @staticmethod
        def now():
            import datetime as _dt

            return _dt.datetime(2026, 1, 2, 3, 4, 5)

    monkeypatch.setattr(c, "datetime", _FixedNow)

    first = tmp_path / "config.toml"
    first.write_text("first\n")
    c._backup(first)
    # Re-create the same path and back it up again in the same frozen second.
    first.write_text("second\n")
    c._backup(first)

    backups = sorted(p.name for p in tmp_path.glob("config.toml.bak.*"))
    assert len(backups) == 2, f"both backups must be kept, got {backups}"
    contents = {p.read_text() for p in tmp_path.glob("config.toml.bak.*")}
    assert contents == {"first\n", "second\n"}


# ── uninstall (remove openproject from client configs) ──────────────────────────


def test_remove_json_openproject_keeps_others() -> None:
    existing = json.dumps(
        {
            "mcpServers": {"openproject": {"command": "/x"}, "github": {"command": "/gh"}},
            "theme": "dark",
        }
    )
    out = json.loads(c._remove_json_openproject(existing, "mcpServers"))
    assert "openproject" not in out["mcpServers"]
    assert out["mcpServers"]["github"] == {"command": "/gh"}
    assert out["theme"] == "dark"


def test_remove_json_openproject_drops_emptied_map() -> None:
    existing = json.dumps({"mcpServers": {"openproject": {"command": "/x"}}, "editorMode": "vim"})
    out = json.loads(c._remove_json_openproject(existing, "mcpServers"))
    assert "mcpServers" not in out  # emptied map removed
    assert out["editorMode"] == "vim"


def test_remove_json_openproject_noop_when_absent() -> None:
    existing = json.dumps({"mcpServers": {"github": {"command": "/gh"}}})
    assert c._remove_json_openproject(existing, "mcpServers") is None


@_needs_tomllib
def test_remove_codex_openproject_keeps_siblings() -> None:
    existing = (
        '[some]\nk = "v"\n\n'
        '[mcp_servers.openproject]\ncommand = "/x"\n\n'
        '[mcp_servers.openproject.env]\nA = "1"\n\n'
        '[mcp_servers.keep]\ncommand = "/keep"\n'
    )
    stripped = c._strip_codex_openproject(existing)
    data = tomllib.loads(stripped)
    assert "openproject" not in data.get("mcp_servers", {})
    assert data["mcp_servers"]["keep"]["command"] == "/keep"
    assert data["some"]["k"] == "v"


def test_remove_client_config_backs_up_and_removes(monkeypatch, tmp_path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"command": "/x"}, "gh": {"command": "/gh"}}}))
    monkeypatch.setattr(c, "_backup", lambda p: p.rename(p.with_name(f"{p.name}.bak.fixed")))
    client = c.Client(
        "claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers"
    )
    assert c._remove_client_config(client) is True
    assert (tmp_path / ".claude.json.bak.fixed").exists()
    result = json.loads(target.read_text())
    assert "openproject" not in result["mcpServers"]
    assert "gh" in result["mcpServers"]


def test_remove_client_config_noop_when_no_entry(tmp_path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"gh": {"command": "/gh"}}}))
    client = c.Client(
        "claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers"
    )
    assert c._remove_client_config(client) is False


# ── run mode / command / config-path resolution (installed vs. clone) ───────────


def test_installed_mode_true_when_no_repo_markers(monkeypatch, tmp_path: Path) -> None:
    # Point the repo-root at a bare dir with no pyproject.toml / src tree.
    monkeypatch.setattr(c, "_REPO_ROOT", tmp_path)
    assert c._installed_mode() is True


def test_installed_mode_false_in_checkout(monkeypatch, tmp_path: Path) -> None:
    # Simulate a checkout: pyproject.toml at root and this module under src/.
    (tmp_path / "pyproject.toml").write_text("")
    pkg = tmp_path / "src" / "openproject_ce_mcp"
    pkg.mkdir(parents=True)
    setup_file = pkg / "setup_cli.py"
    setup_file.write_text("")
    monkeypatch.setattr(c, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(c, "__file__", str(setup_file))
    assert c._installed_mode() is False


def test_server_command_clone_uses_venv() -> None:
    assert c._server_command(installed=False) == (str(c._venv_binary()), True)


def test_server_command_installed_prefers_which(monkeypatch) -> None:
    monkeypatch.setattr(c.shutil, "which", lambda name: "/usr/local/bin/openproject-ce-mcp")
    assert c._server_command(installed=True) == ("/usr/local/bin/openproject-ce-mcp", True)


def test_server_command_installed_falls_back_to_sibling(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c.shutil, "which", lambda name: None)
    monkeypatch.setattr(c, "_IS_WINDOWS", False)
    launcher = tmp_path / "openproject-ce-mcp-setup"
    launcher.write_text("")
    sibling = tmp_path / "openproject-ce-mcp"
    sibling.write_text("")
    monkeypatch.setattr(c.sys, "argv", [str(launcher)])
    # Sibling found next to the launcher → resolved absolute path.
    assert c._server_command(installed=True) == (str(sibling), True)


def test_server_command_installed_last_resort_bare_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c.shutil, "which", lambda name: None)
    monkeypatch.setattr(c, "_IS_WINDOWS", False)
    # launcher dir has no sibling binary; argv[0] is an absolute path in a dir
    # with no server binary → falls through to the bare name, unresolved.
    monkeypatch.setattr(c.sys, "argv", [str(tmp_path / "openproject-ce-mcp-setup")])
    assert c._server_command(installed=True) == ("openproject-ce-mcp", False)


def test_resolve_mcp_json_clone_uses_launch_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PWD", str(tmp_path))
    assert c._resolve_mcp_json(None, installed=False) == tmp_path / ".mcp.json"


def test_project_cwd_prefers_pwd_for_uv_directory(monkeypatch, tmp_path: Path) -> None:
    launch_dir = tmp_path / "launch"
    repo_dir = tmp_path / "repo"
    launch_dir.mkdir()
    repo_dir.mkdir()
    monkeypatch.chdir(repo_dir)
    monkeypatch.setenv("PWD", str(launch_dir))
    assert c._project_cwd() == launch_dir
    assert c._resolve_mcp_json("local", installed=False) == launch_dir / ".mcp.json"


def test_resolve_mcp_json_installed_project_dir_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PWD", str(tmp_path))
    (tmp_path / ".git").mkdir()
    assert c._resolve_mcp_json(None, installed=True) == tmp_path / ".mcp.json"


def test_resolve_mcp_json_installed_bare_dir_is_global(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no project markers
    monkeypatch.setenv("PWD", str(tmp_path))
    assert c._resolve_mcp_json(None, installed=True) is None


def test_resolve_mcp_json_local_forces_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PWD", str(tmp_path))
    assert c._resolve_mcp_json("local", installed=True) == tmp_path / ".mcp.json"


def test_resolve_mcp_json_global_is_none() -> None:
    assert c._resolve_mcp_json("global", installed=True) is None
    assert c._resolve_mcp_json("global", installed=False) is None


def test_looks_like_project_dir(tmp_path: Path) -> None:
    assert c._looks_like_project_dir(tmp_path) is False
    (tmp_path / ".git").mkdir()
    assert c._looks_like_project_dir(tmp_path) is True


def test_install_deps_skipped_when_installed(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(c.subprocess, "run", lambda *a, **k: called.append(a))
    c._install_deps("uv", installed=True)
    assert called == []


def test_doc_locations_installed_are_urls() -> None:
    docs = c._doc_locations(installed=True)
    assert all(v.startswith("https://github.com/") for v in docs.values())
    assert "cursor.md" in docs["Cursor:"]


def test_read_client_env_json_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"env": {"OPENPROJECT_BASE_URL": "https://op.x"}}}}))
    client = c.Client(
        "claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers"
    )
    assert c._read_client_env(client) == {"OPENPROJECT_BASE_URL": "https://op.x"}


def test_read_client_env_missing_file_returns_empty(tmp_path: Path) -> None:
    client = c.Client(
        "claude-code",
        "Claude Code",
        tmp_path / "nope.json",
        "json",
        lambda: True,
        "docs/claude.md",
        root_key="mcpServers",
    )
    assert c._read_client_env(client) == {}


def test_merge_prefill_field_wise_priority(tmp_path: Path) -> None:
    # Global config has a full entry; a project config has only the base URL.
    # Field-wise merge: project URL wins, global token survives (not discarded).
    global_f = tmp_path / "global.json"
    global_f.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://global.example",
                            "OPENPROJECT_API_TOKEN": "gtok",
                        }
                    }
                }
            }
        )
    )
    project_f = tmp_path / "project.json"
    project_f.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://project.example",
                        }
                    }
                }
            }
        )
    )
    gclient = c.Client("g", "G", global_f, "json", lambda: True, "d", root_key="mcpServers")
    pclient = c.Client("p", "P", tmp_path / "unused", "json", lambda: True, "d", root_key="mcpServers")
    merged = c._merge_prefill([(gclient, global_f), (pclient, project_f)])
    assert merged["OPENPROJECT_BASE_URL"] == "https://project.example"  # project overrides
    assert merged["OPENPROJECT_API_TOKEN"] == "gtok"  # global token preserved


def test_merge_prefill_empty_project_token_does_not_blank_global_token(tmp_path: Path) -> None:
    # Presence-based override is a deliberate exception for project-scope keys
    # only (OPM-125) — an empty OPENPROJECT_API_TOKEN in a higher-priority
    # source must NOT blank out a real token from a lower-priority one.
    global_f = tmp_path / "global.json"
    global_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": {"OPENPROJECT_API_TOKEN": "gtok"}}}}))
    project_f = tmp_path / "project.json"
    project_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": {"OPENPROJECT_API_TOKEN": ""}}}}))
    gclient = c.Client("g", "G", global_f, "json", lambda: True, "d", root_key="mcpServers")
    pclient = c.Client("p", "P", tmp_path / "unused", "json", lambda: True, "d", root_key="mcpServers")
    merged = c._merge_prefill([(gclient, global_f), (pclient, project_f)])
    assert merged["OPENPROJECT_API_TOKEN"] == "gtok"


def _scope_clients(tmp_path: Path, global_env: dict, project_env: dict) -> tuple:
    global_f = tmp_path / "global.json"
    global_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": global_env}}}))
    project_f = tmp_path / "project.json"
    project_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": project_env}}}))
    gclient = c.Client("g", "G", global_f, "json", lambda: True, "d", root_key="mcpServers")
    pclient = c.Client("p", "P", tmp_path / "unused", "json", lambda: True, "d", root_key="mcpServers")
    return [(gclient, global_f), (pclient, project_f)]


def test_merge_scope_prefill_source_priority_beats_new_vs_legacy_key_choice(tmp_path: Path) -> None:
    # OPM-125 review: a higher-priority source's LEGACY key must still win over
    # a lower-priority source's NEW key — source priority is resolved first,
    # new-vs-legacy only within a single source. Merging all sources' raw keys
    # into one dict first (as a plain field-wise merge would) loses this
    # ordering, since both keys end up side by side with no source attached.
    pairs = _scope_clients(
        tmp_path,
        global_env={"OPENPROJECT_READ_PROJECTS": "*"},
        project_env={"OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM"},
    )
    read_value, _, read_used_legacy, _ = c._merge_scope_prefill(pairs)
    assert read_value == "OPM"
    assert read_used_legacy is True


def test_merge_scope_prefill_project_legacy_empty_overrides_global_new_wildcard(tmp_path: Path) -> None:
    pairs = _scope_clients(
        tmp_path,
        global_env={"OPENPROJECT_READ_PROJECTS": "*"},
        project_env={"OPENPROJECT_ALLOWED_PROJECTS_READ": ""},
    )
    read_value, _, _, _ = c._merge_scope_prefill(pairs)
    assert read_value == ""


def test_merge_scope_prefill_project_new_key_empty_overrides_global_legacy_scope(tmp_path: Path) -> None:
    pairs = _scope_clients(
        tmp_path,
        global_env={"OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM"},
        project_env={"OPENPROJECT_READ_PROJECTS": ""},
    )
    read_value, _, read_used_legacy, _ = c._merge_scope_prefill(pairs)
    assert read_value == ""
    assert read_used_legacy is False


def test_merge_scope_prefill_new_key_wins_over_legacy_within_same_source(tmp_path: Path) -> None:
    pairs = _scope_clients(
        tmp_path,
        global_env={},
        project_env={"OPENPROJECT_READ_PROJECTS": "OPM", "OPENPROJECT_ALLOWED_PROJECTS_READ": "TST"},
    )
    read_value, _, read_used_legacy, _ = c._merge_scope_prefill(pairs)
    assert read_value == "OPM"
    assert read_used_legacy is False


# ── _merge_tool_groups_prefill (OPM-126) ────────────────────────────────────────


def test_merge_tool_groups_prefill_source_priority_beats_new_vs_legacy_key_choice(tmp_path: Path) -> None:
    # Same error class as OPM-125's _merge_scope_prefill review: a higher-priority
    # source's LEGACY-derived value must still win over a lower-priority source's
    # NEW key.
    pairs = _scope_clients(
        tmp_path,
        global_env={"OPENPROJECT_TOOLS": "projects"},
        project_env={
            "OPENPROJECT_ENABLE_PROJECT_READ": "false",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "true",
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "false",
            "OPENPROJECT_ENABLE_VERSION_READ": "false",
            "OPENPROJECT_ENABLE_BOARD_READ": "false",
        },
    )
    value, used_legacy = c._merge_tool_groups_prefill(pairs)
    assert used_legacy is True
    groups = value.split(",")
    assert "work-packages" in groups
    assert "projects" not in groups


def test_merge_tool_groups_prefill_new_key_wins_over_legacy_within_same_source(tmp_path: Path) -> None:
    pairs = _scope_clients(
        tmp_path,
        global_env={},
        project_env={"OPENPROJECT_TOOLS": "boards", "OPENPROJECT_ENABLE_PROJECT_READ": "true"},
    )
    value, used_legacy = c._merge_tool_groups_prefill(pairs)
    assert value == "boards"
    assert used_legacy is False


def test_merge_tool_groups_prefill_migrates_legacy_flags_to_groups(tmp_path: Path) -> None:
    pairs = _scope_clients(
        tmp_path,
        global_env={},
        project_env={
            "OPENPROJECT_ENABLE_PROJECT_READ": "true",
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": "false",
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": "true",
            "OPENPROJECT_ENABLE_VERSION_READ": "true",
            "OPENPROJECT_ENABLE_BOARD_READ": "true",
            "OPENPROJECT_ENABLE_METADATA_TOOLS": "true",
        },
    )
    value, used_legacy = c._merge_tool_groups_prefill(pairs)
    assert used_legacy is True
    assert set(value.split(",")) == {"projects", "memberships", "versions", "boards", "extended"}


def test_merge_tool_groups_prefill_explicit_empty_new_key_overrides_legacy(tmp_path: Path) -> None:
    # Presence, not truthiness: an explicit empty OPENPROJECT_TOOLS must win over
    # a nonempty legacy flag in the same source, not silently resurrect it.
    pairs = _scope_clients(
        tmp_path,
        global_env={},
        project_env={"OPENPROJECT_TOOLS": "", "OPENPROJECT_ENABLE_PROJECT_READ": "true"},
    )
    value, used_legacy = c._merge_tool_groups_prefill(pairs)
    assert value == ""
    assert used_legacy is False


def test_shim_reexports_public_names() -> None:
    # The root configure_mcp.py shim must re-export main and helpers so get.sh
    # and any importer keep working.
    import importlib.util

    shim_path = Path(__file__).resolve().parent.parent / "configure_mcp.py"
    spec = importlib.util.spec_from_file_location("configure_mcp_shim", shim_path)
    assert spec and spec.loader
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    assert callable(shim.main)
    assert callable(shim._merge_json)


# ── gate behaviour: no clients, global gate not offered ─────────────────────────


def test_choose_targets_no_detected_skips_global_gate(monkeypatch, tmp_path: Path) -> None:
    # No detected clients → global gate is not offered at all; project gate still
    # offers project-capable clients (default n for undetected).
    codex = _codex_client(tmp_path / "config.toml", detect=False, project_target=tmp_path / ".codex" / "config.toml")
    # Only the project gate consumes an answer here (global gate skipped). Say no.
    with _answers(monkeypatch, {"Configure project-scoped": ""}):
        global_clients, project_clients, remove_global_clients, remove_project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == []
    assert remove_global_clients == []
    assert remove_project_clients == []


# ── project-local writes preserve other MCP servers (the "github exists" case) ──


def test_write_project_json_preserves_github(tmp_path: Path) -> None:
    # Existing .mcp.json (Claude/Cursor shape) with a github server must survive;
    # only mcpServers.openproject is added.
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"github": {"command": "github-mcp-server"}}}))
    client = _json_client(tmp_path / ".claude.json", project_target=target)
    assert c._write_client_config(client, CMD, ENV, target=target) is True
    data = json.loads(target.read_text())
    assert data["mcpServers"]["github"]["command"] == "github-mcp-server"
    assert data["mcpServers"]["openproject"]["command"] == CMD


def test_write_project_vscode_servers_stdio_preserves_github(tmp_path: Path) -> None:
    target = tmp_path / ".vscode" / "mcp.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"servers": {"github": {"type": "stdio", "command": "x"}}}))
    client = c.Client(
        "vscode",
        "VS Code",
        tmp_path / "g.json",
        "json",
        lambda: True,
        "docs/github.md",
        root_key="servers",
        stdio=True,
        project_target=target,
    )
    assert c._write_client_config(client, CMD, ENV, target=target) is True
    data = json.loads(target.read_text())
    assert data["servers"]["github"]["command"] == "x"
    assert data["servers"]["openproject"]["type"] == "stdio"
    assert data["servers"]["openproject"]["command"] == CMD


def test_write_project_codex_toml_preserves_github(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "config.toml"
    target.parent.mkdir()
    target.write_text('[mcp_servers.github]\ncommand = "x"\n')
    client = _codex_client(tmp_path / "g.toml", project_target=target)
    assert c._write_client_config(client, CMD, ENV, target=target) is True
    text = target.read_text()
    assert "[mcp_servers.github]" in text
    assert "[mcp_servers.openproject]" in text


def test_write_project_invalid_json_left_untouched(tmp_path: Path, capsys) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text("{ not valid json ")
    client = _json_client(tmp_path / ".claude.json", project_target=target)
    assert c._write_client_config(client, CMD, ENV, target=target) is False
    assert target.read_text() == "{ not valid json "  # untouched
    assert "could not be parsed" in capsys.readouterr().out


def test_write_project_backs_up_existing(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"github": {"command": "x"}}}))
    monkeypatch.setattr(c, "_backup", lambda p: p.rename(p.with_name(f"{p.name}.bak.fixed")))
    client = _json_client(tmp_path / ".claude.json", project_target=target)
    c._write_client_config(client, CMD, ENV, target=target)
    assert (tmp_path / ".mcp.json.bak.fixed").exists()  # backup taken for project file


def test_write_client_config_target_not_client_target(tmp_path: Path) -> None:
    # Regression guard: passing target=P writes to P and does NOT touch client.target.
    global_target = tmp_path / ".claude.json"
    project_target = tmp_path / ".mcp.json"
    client = _json_client(global_target, project_target=project_target)
    c._write_client_config(client, CMD, ENV, target=project_target)
    assert project_target.exists()
    assert not global_target.exists()  # global untouched


def test_uninstall_removes_openproject_from_project_keeps_github(tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"command": "x"},
                    "openproject": {"command": CMD},
                }
            }
        )
    )
    client = _json_client(tmp_path / ".claude.json", project_target=target)
    assert c._remove_client_config(client, target=target) is True
    data = json.loads(target.read_text())
    assert "openproject" not in data["mcpServers"]
    assert "github" in data["mcpServers"]


# ── main() orchestration (happy paths + abort), prompts fully patched ───────────


def _run_main(
    monkeypatch,
    tmp_path: Path,
    clients,
    answers: Mapping[str, str | Sequence[str]],
    secret: str = "opapi-tok",
    *,
    strict: bool = True,
) -> None:
    """Drive main() with patched infra + prompt-keyed answers for input; getpass.

    ``answers`` feeds the gate/bool/text prompts (input), matched by prompt
    content via ``_AnswerBook`` — not by call order. The token (getpass) returns
    ``secret`` directly (there is only one secret-style prompt in the wizard, so
    it doesn't need to go through the answer book). Returns nothing — assert on
    written files. If ``main()`` raises (e.g. an expected ``SystemExit``), that
    propagates immediately and the consumed-check below is skipped, so it never
    masks a genuine failure. Pass ``strict=False`` to skip the consumed-check on a
    normal exit too, for a test that deliberately over-registers answers.
    """
    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)  # installed: no uv sync, cwd paths
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: clients)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PWD", str(tmp_path))
    book = _AnswerBook(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": book(prompt))
    monkeypatch.setattr(c.getpass, "getpass", lambda prompt="": secret)
    c.main([])
    if strict:
        book.assert_consumed()


# When ``advanced`` is answered yes, the wizard always asks 16 further optional
# fields regardless of write access; 5 more (the per-category write toggles) are
# asked additionally when write access is also enabled. Tests that drive the
# advanced flow but don't care about these specific values merge one or both of
# these in with "" (keep-default) answers, rather than retyping all 16-21 keys
# — and rather than relying on iterator-exhaustion padding the way the old
# positional lists did, which is exactly the silent-absorption failure mode
# OPM-132 removes.
_WRITE_CONTROL_DEFAULTS: dict[str, str] = {
    "Enable work-package writes": "",
    "Enable project writes": "",
    "Enable membership writes": "",
    "Enable version writes": "",
    "Enable board writes": "",
}
_ADVANCED_ONLY_DEFAULTS: dict[str, str] = {
    "Hidden project fields": "",
    "Hidden work-package fields": "",
    "Hidden activity fields": "",
    "Hidden custom fields": "",
    "Enable admin writes": "",
    "Attachment upload root": "",
    "Default page size": "",
    "Max page size": "",
    "Max total results": "",
    "List text preview char limit": "",
    "Request timeout seconds": "",
    "Verify TLS certificates?": "",
    "Max retries for 429": "",
    "Retry base delay seconds": "",
    "Retry max delay seconds": "",
    "Log level": "",
}


def test_main_global_only_writes_no_mcp_json(monkeypatch, tmp_path: Path) -> None:
    gtarget = tmp_path / ".claude.json"
    claude = _json_client(gtarget, project_target=tmp_path / ".mcp.json")
    # global gate y, per-client y; project gate is skipped; then creds default
    # (write access off, advanced off, so nothing beyond these 6 is ever asked).
    answers = {
        "Configure globally": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)
    assert gtarget.exists(), "global claude config should be written"
    assert not (tmp_path / ".mcp.json").exists(), "no project .mcp.json for global-only"


def test_main_project_cursor_writes_cursor_file(monkeypatch, tmp_path: Path) -> None:
    ctarget = tmp_path / ".cursor" / "mcp.json"
    cursor = c.Client(
        "cursor",
        "Cursor",
        tmp_path / "g.json",
        "json",
        lambda: True,
        "docs/cursor.md",
        root_key="mcpServers",
        project_target=ctarget,
        restart_hint="reload",
    )
    # global gate n; project gate y, cursor y; then creds default.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Cursor?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [cursor], answers)
    assert ctarget.exists(), "cursor project config should be written"
    data = json.loads(ctarget.read_text())
    assert data["mcpServers"]["openproject"]["command"] == "openproject-ce-mcp"


def test_main_neither_aborts_before_token(monkeypatch, tmp_path: Path) -> None:
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    token_asked = {"v": False}

    def _boom(_prompt=""):
        token_asked["v"] = True
        return "opapi-x"

    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: [claude])
    monkeypatch.chdir(tmp_path)
    book = _AnswerBook({"Configure globally": "n", "Configure project-scoped": "n"})
    monkeypatch.setattr("builtins.input", lambda prompt="": book(prompt))
    monkeypatch.setattr(c.getpass, "getpass", _boom)
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 1
    assert token_asked["v"] is False, "must abort before asking for the token"
    assert not (tmp_path / ".mcp.json").exists()
    book.assert_consumed()


def test_main_neither_aborts_before_token_in_clone_mode(monkeypatch, tmp_path: Path) -> None:
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    token_asked = {"v": False}

    def _boom(_prompt=""):
        token_asked["v"] = True
        return "opapi-x"

    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: False)
    monkeypatch.setattr(c, "_find_uv", lambda: "uv")
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: [claude])
    monkeypatch.chdir(tmp_path)
    book = _AnswerBook({"Configure globally": "n", "Configure project-scoped": "n"})
    monkeypatch.setattr("builtins.input", lambda prompt="": book(prompt))
    monkeypatch.setattr(c.getpass, "getpass", _boom)
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 1
    assert token_asked["v"] is False, "must abort before asking for the token"
    assert not (tmp_path / ".mcp.json").exists()
    book.assert_consumed()


def test_main_can_remove_existing_global_without_collecting_credentials(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"openproject": {"command": "old", "env": ENV}}}))
    claude = _json_client(target, project_target=tmp_path / ".mcp.json")
    token_asked = {"v": False}

    def _boom(_prompt=""):
        token_asked["v"] = True
        return "opapi-x"

    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: [claude])
    monkeypatch.chdir(tmp_path)
    # no global config, remove existing global, no project config
    book = _AnswerBook(
        {
            "Configure globally": "n",
            "Remove existing global Claude Code": "y",
            "Configure project-scoped": "n",
        }
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": book(prompt))
    monkeypatch.setattr(c.getpass, "getpass", _boom)

    c.main([])

    assert token_asked["v"] is False, "removal-only flow must not ask for credentials"
    data = json.loads(target.read_text())
    assert "mcpServers" not in data
    book.assert_consumed()


def test_main_project_prefill_does_not_use_global_values(monkeypatch, tmp_path: Path) -> None:
    global_target = tmp_path / ".claude.json"
    project_target = tmp_path / ".mcp.json"
    global_target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://global.example.com",
                            "OPENPROJECT_API_TOKEN": "global-token",
                        },
                    }
                }
            }
        )
    )
    project_target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://project.example.com",
                            "OPENPROJECT_API_TOKEN": "project-token",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(global_target, project_target=project_target)

    # Skip global, keep existing global, configure project. Empty base/token keep
    # the selected project's values, not the global ones.
    answers = {
        "Configure globally": "n",
        "Remove existing global Claude Code": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(project_target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_BASE_URL"] == "https://project.example.com"
    assert env["OPENPROJECT_API_TOKEN"] == "project-token"


def test_main_project_non_claude_writes_generic_mcp_json(monkeypatch, tmp_path: Path) -> None:
    # Project scope with ONLY a non-Claude client (codex) → generic .mcp.json IS written.
    codex = _codex_client(tmp_path / "g.toml", project_target=tmp_path / ".codex" / "config.toml")
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Codex?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [codex], answers)
    assert (tmp_path / ".codex" / "config.toml").exists()
    assert (tmp_path / ".mcp.json").exists(), "generic .mcp.json written when no Claude Code project"


def test_main_project_claude_no_duplicate_mcp_json(monkeypatch, tmp_path: Path) -> None:
    # Project scope WITH Claude Code → .mcp.json is Claude's project file, written once,
    # and the generic write is skipped (no double write / no extra backup).
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)
    assert (tmp_path / ".mcp.json").exists()
    # exactly one .mcp.json, no stray backup from a second write
    backups = list(tmp_path.glob(".mcp.json.bak.*"))
    assert backups == [], "Claude Code project write must not double-write .mcp.json"


def test_main_basic_setup_safe_advanced_defaults(monkeypatch, tmp_path: Path) -> None:
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    # global n, project y, claude y, base/default scopes, write access default
    # false, advanced default false.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)

    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_TOOLS"] == c._DEFAULT_TOOL_GROUPS_CSV
    assert env["OPENPROJECT_PERSONAL_WRITE"] == "false"
    assert env["OPENPROJECT_ATTACHMENT_ROOT"] == ""
    assert env["OPENPROJECT_MAX_RETRIES"] == "3"
    assert env["OPENPROJECT_RETRY_BASE_DELAY"] == "1.0"
    assert env["OPENPROJECT_RETRY_MAX_DELAY"] == "60.0"


def test_main_fresh_setup_defaults_read_projects_to_empty_not_wildcard(monkeypatch, tmp_path: Path) -> None:
    # OPM-125: a brand-new setup (no prefill, no legacy keys) must start
    # fail-closed like the runtime default, not silently suggest "*".
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)

    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == ""


def test_main_write_access_no_disables_write_flags(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "TST",
                            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
                            "OPENPROJECT_ENABLE_PROJECT_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # The explicit write-access answer disables project-scoped writes. The next
    # answer is consumed by the advanced gate; write flags are not prompted.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "*",
        "Enable write access?": "n",
        "Configure advanced options?": "n",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_WRITE_PROJECTS"] == ""
    assert env["OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"] == "false"
    assert env["OPENPROJECT_ENABLE_PROJECT_WRITE"] == "false"
    assert env["OPENPROJECT_ENABLE_MEMBERSHIP_WRITE"] == "false"
    assert env["OPENPROJECT_ENABLE_VERSION_WRITE"] == "false"
    assert env["OPENPROJECT_ENABLE_BOARD_WRITE"] == "false"


def test_main_write_access_enter_keeps_existing_scope(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM, TST",
                            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "TST",
                            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # Enter on every prompt: write access defaults on (existing write scope is
    # non-empty), so the "Writable projects" prompt fires too, then advanced
    # defaults off (its default is hardcoded False, not derived from existing
    # config) — nothing beyond these 5 credentials-phase prompts is ever asked.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Writable projects": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == "OPM, TST"
    assert env["OPENPROJECT_WRITE_PROJECTS"] == "TST"
    assert env["OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"] == "true"


def test_main_migrates_legacy_only_project_scope_keys(monkeypatch, tmp_path: Path) -> None:
    # OPM-125: an existing config with ONLY the old ALLOWED_PROJECTS_* keys must
    # still prefill correctly (not silently fall back to "*") and the output must
    # use only the new key names.
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM,TST",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == "OPM,TST"
    assert "OPENPROJECT_ALLOWED_PROJECTS_READ" not in env


def test_main_explicit_empty_new_key_overrides_nonempty_legacy_key(monkeypatch, tmp_path: Path) -> None:
    # OPM-125: presence, not truthiness, decides the prefill — a deliberately
    # empty OPENPROJECT_READ_PROJECTS/_WRITE_PROJECTS must win over a nonempty
    # legacy value, not silently resurrect it.
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_READ_PROJECTS": "",
                            "OPENPROJECT_ALLOWED_PROJECTS_READ": "OPM",
                            "OPENPROJECT_WRITE_PROJECTS": "",
                            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "TST",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == ""
    assert env["OPENPROJECT_WRITE_PROJECTS"] == ""


def test_main_write_access_yes_defaults_write_controls_on(monkeypatch, tmp_path: Path) -> None:
    # Write-group flags (project/membership/work_package/version/board) still
    # default on unprompted once write access is enabled. There is no
    # auto-confirm prompt anymore (OPM-124): every write/delete always
    # requires explicit confirm=true, no operator-level bypass exists.
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")

    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "OPM, TST",
        "Enable write access?": "y",
        "Writable projects": "TST",
        "Configure advanced options?": "n",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)

    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == "OPM, TST"
    assert env["OPENPROJECT_WRITE_PROJECTS"] == "TST"
    assert env["OPENPROJECT_ENABLE_PROJECT_WRITE"] == "true"
    assert env["OPENPROJECT_ENABLE_MEMBERSHIP_WRITE"] == "true"
    assert env["OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"] == "true"
    assert env["OPENPROJECT_ENABLE_VERSION_WRITE"] == "true"
    assert env["OPENPROJECT_ENABLE_BOARD_WRITE"] == "true"


def test_main_skipping_advanced_preserves_existing_advanced_values(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_HIDE_PROJECT_FIELDS": "description",
                            "OPENPROJECT_TOOLS": "projects,work-packages,memberships,versions,boards,extended",
                            "OPENPROJECT_ATTACHMENT_ROOT": "/tmp/uploads",
                            "OPENPROJECT_MAX_RETRIES": "7",
                            "OPENPROJECT_RETRY_BASE_DELAY": "2.5",
                            "OPENPROJECT_RETRY_MAX_DELAY": "30",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)

    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_HIDE_PROJECT_FIELDS"] == "description"
    assert env["OPENPROJECT_TOOLS"] == "projects,work-packages,memberships,versions,boards,extended"
    assert env["OPENPROJECT_ATTACHMENT_ROOT"] == "/tmp/uploads"
    assert env["OPENPROJECT_MAX_RETRIES"] == "7"
    assert env["OPENPROJECT_RETRY_BASE_DELAY"] == "2.5"
    assert env["OPENPROJECT_RETRY_MAX_DELAY"] == "30"


def test_main_advanced_setup_prompts_for_optional_values(monkeypatch, tmp_path: Path) -> None:
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "OPM",
        "Enable write access?": "y",
        "Writable projects": "TST",
        "Configure advanced options?": "y",
        "Enabled tool groups": "projects,work-packages,memberships,versions,boards,personal,extended",
        "Enable personal-data writes": "y",
        "Enable work-package writes": "y",
        "Enable project writes": "n",
        "Enable membership writes": "n",
        "Enable version writes": "n",
        "Enable board writes": "n",
        "Hidden project fields": "status_explanation",
        "Hidden work-package fields": "description",
        "Hidden activity fields": "comment",
        "Hidden custom fields": "budget",
        "Enable admin writes": "n",
        "Attachment upload root": "/tmp/uploads",
        "Default page size": "5",
        "Max page size": "25",
        "Max total results": "50",
        "List text preview char limit": "250",
        "Request timeout seconds": "20",
        "Verify TLS certificates?": "y",
        "Max retries for 429": "4",
        "Retry base delay seconds": "0.5",
        "Retry max delay seconds": "10",
        "Log level": "INFO",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)

    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert env["OPENPROJECT_READ_PROJECTS"] == "OPM"
    assert env["OPENPROJECT_WRITE_PROJECTS"] == "TST"
    assert env["OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"] == "true"
    assert env["OPENPROJECT_HIDE_PROJECT_FIELDS"] == "status_explanation"
    tool_groups = env["OPENPROJECT_TOOLS"].split(",")
    assert "extended" in tool_groups
    assert "personal" in tool_groups
    assert env["OPENPROJECT_PERSONAL_WRITE"] == "true"
    assert env["OPENPROJECT_ATTACHMENT_ROOT"] == "/tmp/uploads"
    assert env["OPENPROJECT_DEFAULT_PAGE_SIZE"] == "5"
    assert env["OPENPROJECT_MAX_RETRIES"] == "4"
    assert env["OPENPROJECT_RETRY_BASE_DELAY"] == "0.5"


# ── Wizard reconciliation + validation (OPM-126 review rounds 3-7) ─────────────


def test_main_advanced_deselecting_group_disables_existing_write_flag(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_WRITE_PROJECTS": "*",
                            "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # advanced + write access both on → the wizard also asks the 5 write-control
    # toggles and the 16 always-asked advanced-only fields; none of those are
    # asserted on here, so they're left at their kept/default answers.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "y",
        "Writable projects": "",  # keep existing "*"
        "Configure advanced options?": "y",
        "Enabled tool groups": "projects,work-packages,memberships,versions",  # groups WITHOUT boards
        **_WRITE_CONTROL_DEFAULTS,
        **_ADVANCED_ONLY_DEFAULTS,
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert "boards" not in env["OPENPROJECT_TOOLS"].split(",")
    assert env["OPENPROJECT_ENABLE_BOARD_WRITE"] == "false"
    c.Settings.from_env(env)  # must still parse cleanly


def test_main_personal_write_forced_false_when_personal_group_absent_in_advanced(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_PERSONAL_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # write access off → no write-control toggles; advanced on → the 16
    # always-asked advanced-only fields still fire, left at their defaults.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "n",
        "Configure advanced options?": "y",
        "Enabled tool groups": "projects,work-packages",  # groups WITHOUT personal — no personal_write slot needed
        **_ADVANCED_ONLY_DEFAULTS,
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert "personal" not in env["OPENPROJECT_TOOLS"].split(",")
    assert env["OPENPROJECT_PERSONAL_WRITE"] == "false"


def test_main_legacy_migration_reconciles_read_off_write_on_same_scope(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_WRITE_PROJECTS": "*",
                            "OPENPROJECT_ENABLE_BOARD_READ": "false",
                            "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # Advanced entirely skipped: the migrated OPENPROJECT_TOOLS excludes "boards"
    # (board read was false), while OPENPROJECT_ENABLE_BOARD_WRITE stayed true from
    # the same legacy config — the reconciliation must fire even in this
    # non-advanced/migration-only path, not just when the user types groups by hand.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "y",
        "Writable projects": "",
        "Configure advanced options?": "",
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert "boards" not in env["OPENPROJECT_TOOLS"].split(",")
    assert env["OPENPROJECT_ENABLE_BOARD_WRITE"] == "false"


def test_main_advanced_invalid_group_reprompts_then_succeeds(monkeypatch, tmp_path: Path) -> None:
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    # "Enabled tool groups" gets a 2-item queue: the initial typo'd answer, then
    # the corrected one on reprompt — the reprompt's label
    # ("Enabled tool groups — comma-separated, check spelling") is a strict
    # extension of the initial one, so this one key covers both asks.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "n",
        "Configure advanced options?": "y",
        "Enabled tool groups": [
            "projects,work-packages,personl",  # typo: should be "personal"
            "projects,work-packages,personal",  # corrected on reprompt
        ],
        "Enable personal-data writes": "y",  # personal now present + advanced
        **_ADVANCED_ONLY_DEFAULTS,
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)

    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    groups = env["OPENPROJECT_TOOLS"].split(",")
    assert "personal" in groups
    assert env["OPENPROJECT_PERSONAL_WRITE"] == "true"


def test_main_typo_in_group_list_does_not_clobber_unrelated_personal_write(monkeypatch, tmp_path: Path) -> None:
    # OPM-126 review round 5 regression: a typo in ONE group must not permanently
    # disable an unrelated, already-correct write flag once corrected.
    target = tmp_path / ".mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openproject": {
                        "command": "old",
                        "env": {
                            "OPENPROJECT_BASE_URL": "https://old.example.com",
                            "OPENPROJECT_API_TOKEN": "old-token",
                            "OPENPROJECT_TOOLS": "projects,personal",
                            "OPENPROJECT_PERSONAL_WRITE": "true",
                        },
                    }
                }
            }
        )
    )
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "n",
        "Configure advanced options?": "y",
        "Enabled tool groups": [
            "projects,personl",  # typo drops "personal"
            "projects,personal",  # corrected — "personal" is back
        ],
        "Enable personal-data writes": "",  # keep existing (true) default
        **_ADVANCED_ONLY_DEFAULTS,
    }
    _run_main(monkeypatch, tmp_path, [claude], answers, secret="")

    data = json.loads(target.read_text())
    env = data["mcpServers"]["openproject"]["env"]
    assert "personal" in env["OPENPROJECT_TOOLS"].split(",")
    assert env["OPENPROJECT_PERSONAL_WRITE"] == "true"


def test_main_advanced_permanently_invalid_group_aborts_without_writing(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    claude = _json_client(tmp_path / ".claude.json", project_target=target)
    # 3 input() calls total for tool groups: the initial ask plus 2 reprompts
    # (the 3rd failure aborts immediately, with no 3rd reprompt) — all under one
    # queued key, since every reprompt's label extends the initial one.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "",
        "Enable write access?": "n",
        "Configure advanced options?": "y",
        "Enabled tool groups": ["bogus1", "bogus2", "bogus3"],  # 3 attempts, all invalid
    }
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path, [claude], answers)
    assert exc.value.code == 1
    assert not target.exists()


def test_wizard_invariant_generated_config_always_parses_with_settings_from_env(monkeypatch, tmp_path: Path) -> None:
    """The generated env must always parse via Settings.from_env — enforced
    structurally inside main() itself; this test is a regression guard, not the
    mechanism that creates the guarantee."""
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    # Only 4 of the 5 write-control toggles are explicitly answered "y" here
    # (matching the original list, which ran out after 4) — "Enable board
    # writes" is left at its merged "" (kept-default) answer. Not asserted on
    # either way; this test only checks the generated config parses cleanly.
    answers = {
        "Configure globally": "n",
        "Configure project-scoped": "y",
        "Configure Claude Code?": "y",
        "OpenProject base URL": "",
        "Readable projects": "OPM",
        "Enable write access?": "y",
        "Writable projects": "TST",
        "Configure advanced options?": "y",
        "Enabled tool groups": "projects,work-packages,memberships,versions,boards,personal,extended",
        "Enable personal-data writes": "y",
        **_WRITE_CONTROL_DEFAULTS,
        "Enable work-package writes": "y",
        "Enable project writes": "y",
        "Enable membership writes": "y",
        "Enable version writes": "y",
        **_ADVANCED_ONLY_DEFAULTS,
    }
    _run_main(monkeypatch, tmp_path, [claude], answers)
    data = json.loads((tmp_path / ".mcp.json").read_text())
    env = data["mcpServers"]["openproject"]["env"]
    c.Settings.from_env(env)  # must not raise


def test_main_ctrl_c_exits_130_no_traceback(monkeypatch, capsys) -> None:
    # Ctrl+C during a prompt → clean "Cancelled" message + exit 130, no traceback.
    # This is the one deliberate, documented exception to the "no direct
    # builtins.input patch outside _AnswerBook" rule (see OPM-132): raising an
    # exception isn't an "answer" _AnswerBook's string/string-queue API can
    # express, and it isn't the positional-fragility class OPM-132 targets.
    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: [])

    def raise_keyboard_interrupt(_prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_keyboard_interrupt)
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 130
    assert "Cancelled" in capsys.readouterr().err
