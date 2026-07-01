from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# configure_mcp.py lives at the repo root, not inside the installed package, so it
# is not importable by name under every pytest runner (e.g. `uv run pytest` does
# not put the repo root on sys.path). Load it explicitly by file path.
_SPEC = importlib.util.spec_from_file_location(
    "configure_mcp", Path(__file__).resolve().parent.parent / "configure_mcp.py"
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

_needs_tomllib = pytest.mark.skipif(
    tomllib is None, reason="tomllib requires Python 3.11+"
)

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
    existing = json.dumps(
        {"mcpServers": {"openproject": {"command": "/old/path", "env": {"X": "1"}}}}
    )
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
    existing = (
        '[some_setting]\nkey = "value"\n\n'
        '[mcp_servers.other]\ncommand = "/bin/other"\n'
    )
    merged = c._merge_codex_toml(existing, CMD, ENV)
    data = tomllib.loads(merged)
    assert data["some_setting"]["key"] == "value"
    assert data["mcp_servers"]["other"]["command"] == "/bin/other"
    assert data["mcp_servers"]["openproject"]["command"] == CMD


@_needs_tomllib
def test_merge_codex_toml_replaces_existing_openproject() -> None:
    existing = (
        "[mcp_servers.openproject]\ncommand = \"/old\"\n\n"
        "[mcp_servers.openproject.env]\nOLD = \"1\"\n\n"
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
    monkeypatch.setattr(
        c.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    assert c._detect_claude_code() is True


def test_clients_only_offers_detected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_home", lambda: tmp_path)
    monkeypatch.setattr(c.shutil, "which", lambda _name: None)
    # No client artifacts present → nothing detected.
    assert [cl for cl in c._clients() if cl.detected()] == []


# ── write + backup ──────────────────────────────────────────────────────────────


def _codex_client(target: Path) -> c.Client:
    return c.Client(
        "codex",
        "Codex",
        target,
        "toml",
        lambda: True,
        "docs/codex.md",
    )


def _json_client(target: Path) -> c.Client:
    return c.Client(
        "claude-code",
        "Claude Code",
        target,
        "json",
        lambda: True,
        "docs/claude.md",
        root_key="mcpServers",
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
    monkeypatch.setattr(
        c, "_backup", lambda p: p.rename(p.with_name(f"{p.name}.bak.fixed"))
    )
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


# ── registration mode (asked up front, non-interactive) ─────────────────────────


def _answers(monkeypatch, seq: list[str]) -> None:
    it = iter(seq)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it, ""))


def test_choose_mode_no_clients_returns_empty(monkeypatch, capsys) -> None:
    monkeypatch.setattr(c, "_clients", lambda: [])
    assert c._choose_registration_mode() == []
    assert "Detected MCP clients" not in capsys.readouterr().out


def test_choose_mode_gate_no_skips_per_client_prompts(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml")
    monkeypatch.setattr(c, "_clients", lambda: [codex])
    # Only one answer is consumed (the gate); default No → no per-client prompt.
    _answers(monkeypatch, [""])
    assert c._choose_registration_mode() == []


def test_choose_mode_gate_yes_then_per_client(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml")
    monkeypatch.setattr(c, "_clients", lambda: [codex])
    # Gate yes, then yes for the one client.
    _answers(monkeypatch, ["y", "y"])
    chosen = c._choose_registration_mode()
    assert chosen == [codex]


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
    existing = (
        "[mcp_servers.other]\n"
        'command = "/bin/other"\n'
        "args = [\n"
        '  "--flag",\n'
        '  "--another",\n'
        "]\n"
    )
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
    existing = json.dumps({
        "mcpServers": {"openproject": {"command": "/x"}, "github": {"command": "/gh"}},
        "theme": "dark",
    })
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
    client = c.Client("claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers")
    assert c._remove_client_config(client) is True
    assert (tmp_path / ".claude.json.bak.fixed").exists()
    result = json.loads(target.read_text())
    assert "openproject" not in result["mcpServers"]
    assert "gh" in result["mcpServers"]


def test_remove_client_config_noop_when_no_entry(tmp_path) -> None:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({"mcpServers": {"gh": {"command": "/gh"}}}))
    client = c.Client("claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers")
    assert c._remove_client_config(client) is False
