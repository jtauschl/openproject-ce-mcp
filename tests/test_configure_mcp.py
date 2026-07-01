from __future__ import annotations

import importlib.util
import json
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


def test_choose_targets_both_gates_no(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate no, project gate no → nothing.
    _answers(monkeypatch, ["", ""])
    assert c._choose_targets([codex]) == ([], [])


def test_choose_targets_global_only(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate yes, per-client yes; project gate no.
    _answers(monkeypatch, ["y", "y", ""])
    global_clients, project_clients = c._choose_targets([codex])
    assert global_clients == [codex]
    assert project_clients == []


def test_choose_targets_project_only(monkeypatch, tmp_path: Path) -> None:
    codex = _codex_client(tmp_path / "config.toml", project_target=tmp_path / ".codex" / "config.toml")
    # global gate no; project gate yes, per-client yes.
    _answers(monkeypatch, ["", "y", "y"])
    global_clients, project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == [codex]


def test_choose_targets_project_offers_undetected(monkeypatch, tmp_path: Path) -> None:
    # A client NOT detected still gets offered in the project gate (default n),
    # answer y anyway → it is selected. It is NOT offered in the global gate.
    codex = _codex_client(
        tmp_path / "config.toml", detect=False, project_target=tmp_path / ".codex" / "config.toml"
    )
    _answers(monkeypatch, ["y", "y"])  # project gate yes (global gate skipped: no detected), per-client yes
    global_clients, project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == [codex]


def test_choose_targets_claude_code_default_yes_when_alone(monkeypatch, tmp_path: Path) -> None:
    # Claude Code undetected + no other project client detected → project default y,
    # so pressing Enter selects it.
    claude = _json_client(
        tmp_path / ".claude.json", detect=False, project_target=tmp_path / ".mcp.json"
    )
    _answers(monkeypatch, ["y", ""])  # project gate yes, then Enter (default y) for claude
    global_clients, project_clients = c._choose_targets([claude])
    assert project_clients == [claude]


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


def test_resolve_mcp_json_clone_uses_repo_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(c, "_REPO_ROOT", tmp_path)
    assert c._resolve_mcp_json(None, installed=False) == tmp_path / ".mcp.json"


def test_resolve_mcp_json_installed_project_dir_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    assert c._resolve_mcp_json(None, installed=True) == tmp_path / ".mcp.json"


def test_resolve_mcp_json_installed_bare_dir_is_global(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no project markers
    assert c._resolve_mcp_json(None, installed=True) is None


def test_resolve_mcp_json_local_forces_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
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
    client = c.Client("claude-code", "Claude Code", target, "json", lambda: True, "docs/claude.md", root_key="mcpServers")
    assert c._read_client_env(client) == {"OPENPROJECT_BASE_URL": "https://op.x"}


def test_read_client_env_missing_file_returns_empty(tmp_path: Path) -> None:
    client = c.Client("claude-code", "Claude Code", tmp_path / "nope.json", "json", lambda: True, "docs/claude.md", root_key="mcpServers")
    assert c._read_client_env(client) == {}


def test_merge_prefill_field_wise_priority(tmp_path: Path) -> None:
    # Global config has a full entry; a project config has only the base URL.
    # Field-wise merge: project URL wins, global token survives (not discarded).
    global_f = tmp_path / "global.json"
    global_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": {
        "OPENPROJECT_BASE_URL": "https://global.example",
        "OPENPROJECT_API_TOKEN": "gtok",
    }}}}))
    project_f = tmp_path / "project.json"
    project_f.write_text(json.dumps({"mcpServers": {"openproject": {"env": {
        "OPENPROJECT_BASE_URL": "https://project.example",
    }}}}))
    gclient = c.Client("g", "G", global_f, "json", lambda: True, "d", root_key="mcpServers")
    pclient = c.Client("p", "P", tmp_path / "unused", "json", lambda: True, "d", root_key="mcpServers")
    merged = c._merge_prefill([(gclient, global_f), (pclient, project_f)])
    assert merged["OPENPROJECT_BASE_URL"] == "https://project.example"  # project overrides
    assert merged["OPENPROJECT_API_TOKEN"] == "gtok"  # global token preserved


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
    codex = _codex_client(
        tmp_path / "config.toml", detect=False, project_target=tmp_path / ".codex" / "config.toml"
    )
    # Only the project gate consumes an answer here (global gate skipped). Say no.
    _answers(monkeypatch, [""])
    global_clients, project_clients = c._choose_targets([codex])
    assert global_clients == []
    assert project_clients == []


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
    client = c.Client("vscode", "VS Code", tmp_path / "g.json", "json", lambda: True,
                      "docs/github.md", root_key="servers", stdio=True, project_target=target)
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
    target.write_text(json.dumps({"mcpServers": {
        "github": {"command": "x"},
        "openproject": {"command": CMD},
    }}))
    client = _json_client(tmp_path / ".claude.json", project_target=target)
    assert c._remove_client_config(client, target=target) is True
    data = json.loads(target.read_text())
    assert "openproject" not in data["mcpServers"]
    assert "github" in data["mcpServers"]


# ── main() orchestration (happy paths + abort), prompts fully patched ───────────


def _run_main(monkeypatch, tmp_path: Path, clients, answers: list[str], secret: str = "opapi-tok"):
    """Drive main() with patched infra + a shared answer iterator for input/getpass.

    ``answers`` feeds both the gate/bool/text prompts (input) in order; the token
    (getpass) returns ``secret``. Returns nothing — assert on written files.
    """
    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)  # installed: no uv sync, cwd paths
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: clients)
    monkeypatch.chdir(tmp_path)
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it, ""))
    monkeypatch.setattr(c.getpass, "getpass", lambda _prompt="": secret)
    c.main([])


def test_main_global_only_writes_no_mcp_json(monkeypatch, tmp_path: Path) -> None:
    gtarget = tmp_path / ".claude.json"
    claude = _json_client(gtarget, project_target=tmp_path / ".mcp.json")
    # global gate y, per-client y; project gate n; then all creds default (Enter).
    _run_main(monkeypatch, tmp_path, [claude], ["y", "y", "n"] + [""] * 30)
    assert gtarget.exists(), "global claude config should be written"
    assert not (tmp_path / ".mcp.json").exists(), "no project .mcp.json for global-only"


def test_main_project_cursor_writes_cursor_file(monkeypatch, tmp_path: Path) -> None:
    ctarget = tmp_path / ".cursor" / "mcp.json"
    cursor = c.Client("cursor", "Cursor", tmp_path / "g.json", "json", lambda: True,
                      "docs/cursor.md", root_key="mcpServers", project_target=ctarget,
                      restart_hint="reload")
    # global gate n; project gate y, cursor y; then creds default.
    _run_main(monkeypatch, tmp_path, [cursor], ["n", "y", "y"] + [""] * 30)
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
    it = iter(["n", "n"])  # both gates no
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it, ""))
    monkeypatch.setattr(c.getpass, "getpass", _boom)
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 1
    assert token_asked["v"] is False, "must abort before asking for the token"
    assert not (tmp_path / ".mcp.json").exists()


def test_main_project_non_claude_writes_generic_mcp_json(monkeypatch, tmp_path: Path) -> None:
    # Project scope with ONLY a non-Claude client (codex) → generic .mcp.json IS written.
    codex = _codex_client(tmp_path / "g.toml", project_target=tmp_path / ".codex" / "config.toml")
    _run_main(monkeypatch, tmp_path, [codex], ["n", "y", "y"] + [""] * 30)
    assert (tmp_path / ".codex" / "config.toml").exists()
    assert (tmp_path / ".mcp.json").exists(), "generic .mcp.json written when no Claude Code project"


def test_main_project_claude_no_duplicate_mcp_json(monkeypatch, tmp_path: Path) -> None:
    # Project scope WITH Claude Code → .mcp.json is Claude's project file, written once,
    # and the generic write is skipped (no double write / no extra backup).
    claude = _json_client(tmp_path / ".claude.json", project_target=tmp_path / ".mcp.json")
    _run_main(monkeypatch, tmp_path, [claude], ["n", "y", "y"] + [""] * 30)
    assert (tmp_path / ".mcp.json").exists()
    # exactly one .mcp.json, no stray backup from a second write
    backups = list(tmp_path.glob(".mcp.json.bak.*"))
    assert backups == [], "Claude Code project write must not double-write .mcp.json"


def test_main_ctrl_c_exits_130_no_traceback(monkeypatch, capsys) -> None:
    # Ctrl+C during a prompt → clean "Cancelled" message + exit 130, no traceback.
    monkeypatch.setattr(c, "_check_python", lambda: None)
    monkeypatch.setattr(c, "_installed_mode", lambda: True)
    monkeypatch.setattr(c, "_install_deps", lambda *a, **k: None)
    monkeypatch.setattr(c, "_server_command", lambda installed: ("openproject-ce-mcp", True))
    monkeypatch.setattr(c, "_clients", lambda: [])
    def _interrupt(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _interrupt)
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 130
    assert "Cancelled" in capsys.readouterr().err
