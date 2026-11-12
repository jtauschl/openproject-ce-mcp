"""The doctor and `OPENPROJECT_API_TOKEN_VAR`: the variable it names is the one that must hold the token.

Every finding calls that variable "the variable that OPENPROJECT_API_TOKEN_VAR names" and never prints its name or
a value: a token pasted into `OPENPROJECT_API_TOKEN_VAR` by mistake would otherwise reach output that people share.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doctor_test_helpers import BASE_URL, FakeCodex, Sandbox, listed, listing, server

from openproject_ce_mcp.doctor.checks import Evaluation, probe_key
from openproject_ce_mcp.doctor.codex import CodexCli
from openproject_ce_mcp.doctor.environment import EffectiveEnv, EnvMap
from openproject_ce_mcp.doctor.hosts import CursorHost, Subject
from openproject_ce_mcp.doctor.run import EXIT_FAILURE, EXIT_SUCCESS

NAMED = "TOKEN_OP_EXAMPLE_USER"
SECRET = "secret-value-via-the-named-variable"
PASTED_INVALID = "opapi-0a1b2c3d4e5f-pasted-token"
PASTED_VALID_SHAPE = "a3f9" * 16
LABEL = "the variable that OPENPROJECT_API_TOKEN_VAR names"
CLAUDE_USER = "Claude Code openproject (~/.claude.json, user scope)"
CODEX = "Codex openproject (this directory and user level)"


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    return Sandbox(tmp_path, monkeypatch)


def _claude(box: Sandbox, env: dict[str, str]) -> None:
    box.write(box.claude_state, {"mcpServers": {"openproject": server(env)}})


def _codex(env: dict[str, str], env_vars: list[str]) -> FakeCodex:
    return FakeCodex(listing(listed(env=env, env_vars=env_vars)))


def _levels(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(("[FAIL]", "[WARN]", "[ OK ]", "[ok]"))]


def _no_secrets(out: str) -> None:
    assert SECRET not in out
    assert PASTED_INVALID not in out
    assert PASTED_VALID_SHAPE not in out


# ── Claude Code: the host passes its own environment on ─────────────────────────


def test_the_named_variable_set_in_the_entry_is_the_token(box, capsys):
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: SECRET})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert any("API: connected" in line for line in run.lines(CLAUDE_USER))
    assert box.probe.calls[0].get(NAMED) == SECRET
    _no_secrets(run.out)


def test_the_named_variable_mapped_from_the_shell_is_the_token(box, capsys, monkeypatch):
    monkeypatch.setenv(NAMED, SECRET)
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: f"${{{NAMED}}}"})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert box.probe.calls[0].get(NAMED) == SECRET
    _no_secrets(run.out)


def test_the_named_variable_missing_from_a_host_that_inherits_is_unverified_not_a_fail(box, capsys):
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    assert any(LABEL in line and "is not set in the entry" in line for line in run.lines(CLAUDE_USER))
    assert NAMED not in run.out
    assert box.probe.calls == []


def test_a_token_pasted_as_the_name_is_never_printed_on_the_unverified_path(box, capsys):
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": PASTED_VALID_SHAPE})

    run = box.run(capsys)

    assert LABEL in run.out
    _no_secrets(run.out)


def test_a_token_pasted_as_the_name_is_never_printed_on_the_fail_path(box, capsys):
    codex = _codex({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": PASTED_VALID_SHAPE}, [])

    run = box.run(capsys, codex=codex)

    assert run.exit_code == EXIT_FAILURE
    assert any(LABEL in line for line in run.lines(CODEX) if line.startswith("[FAIL]"))
    _no_secrets(run.out)


def test_the_named_variable_is_the_token_on_vs_code_and_on_claude_desktop(box, capsys):
    env = {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: SECRET}
    box.write(box.vscode_workspace_mcp, {"servers": {"openproject": server(env)}})
    box.write(box.desktop_config, {"mcpServers": {"openproject": server(env)}})

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    assert {call.get(NAMED) for call in box.probe.calls} == {SECRET}
    _no_secrets(run.out)


def test_the_named_variable_missing_on_a_host_that_passes_only_the_entry_fails(box, capsys):
    box.write(
        box.desktop_config,
        {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED})}},
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any(f"{LABEL} is not set, and Claude Desktop cannot get it" in line for line in run.out.splitlines())
    assert NAMED not in run.out


def test_a_token_pasted_as_an_invalid_name_fails_with_the_loaders_text_and_prints_nothing(box, capsys):
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": PASTED_INVALID})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any(
        "OPENPROJECT_API_TOKEN_VAR must be an environment variable name" in line for line in run.lines(CLAUDE_USER)
    )
    _no_secrets(run.out)


def test_both_sources_set_in_the_entry_fail(box, capsys):
    _claude(
        box,
        {
            "OPENPROJECT_BASE_URL": BASE_URL,
            "OPENPROJECT_API_TOKEN": SECRET,
            "OPENPROJECT_API_TOKEN_VAR": NAMED,
            NAMED: SECRET,
        },
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("both set" in line for line in run.lines(CLAUDE_USER) if line.startswith("[FAIL]"))
    _no_secrets(run.out)


def test_a_token_exported_in_the_shell_conflicts_with_the_named_variable_on_a_host_that_passes_its_environment(
    box, capsys, monkeypatch
):
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", SECRET)
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: SECRET})

    run = box.run(capsys)

    assert run.exit_code == EXIT_FAILURE
    assert any("both set" in line for line in run.lines(CLAUDE_USER) if line.startswith("[FAIL]"))
    assert "an entry can clear an inherited OPENPROJECT_API_TOKEN" in run.out
    _no_secrets(run.out)


def test_an_unresolvable_placeholder_on_the_named_variable_is_unverified(box, capsys):
    _claude(
        box,
        {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: "${UNKNOWN_SOURCE}"},
    )

    run = box.run(capsys)

    assert "[FAIL]" not in run.out
    assert any(LABEL in line and "placeholder" in line for line in run.lines(CLAUDE_USER))
    assert NAMED not in run.out
    assert box.probe.calls == []


def test_an_unresolvable_placeholder_on_the_variable_name_is_unverified(box, capsys):
    _claude(box, {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": "${UNKNOWN_SOURCE}"})

    run = box.run(capsys)

    assert "[FAIL]" not in run.out
    assert any("OPENPROJECT_API_TOKEN_VAR uses a placeholder" in line for line in run.lines(CLAUDE_USER))
    assert box.probe.calls == []


# ── Codex: forwards a variable only under its own name ──────────────────────────


def test_codex_with_the_named_variable_in_env_vars_and_in_the_shell_is_valid(box, capsys, monkeypatch):
    monkeypatch.setenv(NAMED, SECRET)
    codex = _codex({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED}, [NAMED])

    run = box.run(capsys, codex=codex)

    assert run.exit_code == EXIT_SUCCESS
    assert box.probe.calls[0].get(NAMED) == SECRET
    _no_secrets(run.out)


def test_codex_with_the_named_variable_listed_but_absent_from_the_shell_is_unverified(box, capsys):
    codex = _codex({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED}, [NAMED])

    run = box.run(capsys, codex=codex)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    assert any("Codex passes it from its own environment (env_vars)" in line for line in run.lines(CODEX))
    assert NAMED not in run.out
    assert box.probe.calls == []


def test_codex_with_the_named_variable_not_in_env_vars_fails_even_if_the_shell_has_it(box, capsys, monkeypatch):
    monkeypatch.setenv(NAMED, SECRET)
    codex = _codex({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED}, [])

    run = box.run(capsys, codex=codex)

    assert run.exit_code == EXIT_FAILURE
    assert any(
        f"{LABEL} is not set, and Codex cannot get it" in line for line in run.lines(CODEX) if line.startswith("[FAIL]")
    )
    _no_secrets(run.out)
    assert NAMED not in run.out


def test_a_codex_fragment_that_sets_only_the_variable_name_is_not_a_failure(box, capsys):
    box.write(
        box.codex_config,
        '[mcp_servers.openproject]\ncommand = "openproject-ce-mcp"\n[mcp_servers.openproject.env]\n'
        f'OPENPROJECT_API_TOKEN_VAR = "{NAMED}"\n',
    )

    run = box.run(capsys, codex=CodexCli(None))

    assert "[FAIL]" not in run.out


def test_a_codex_fragment_that_sets_a_name_that_is_not_a_variable_name_fails(box, capsys):
    box.write(
        box.codex_config,
        '[mcp_servers.openproject]\ncommand = "openproject-ce-mcp"\n[mcp_servers.openproject.env]\n'
        f'OPENPROJECT_API_TOKEN_VAR = "{PASTED_INVALID}"\n',
    )

    run = box.run(capsys, codex=CodexCli(None))

    assert run.exit_code == EXIT_FAILURE
    assert any(
        "OPENPROJECT_API_TOKEN_VAR must be an environment variable name" in line
        for line in run.out.splitlines()
        if line.startswith("[FAIL]")
    )
    _no_secrets(run.out)


# ── Cursor: how it builds the environment is not known ──────────────────────────


def test_cursor_with_the_named_variable_only_in_the_shell_is_unverified(box, capsys, monkeypatch):
    monkeypatch.setenv(NAMED, SECRET)
    box.write(
        box.home / ".cursor" / "mcp.json",
        {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED})}},
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    assert "works only if Cursor inherits this shell's variables" in run.out
    assert box.probe.calls == []
    _no_secrets(run.out)


def test_cursor_notes_a_shell_token_that_would_conflict_with_the_named_variable(box, capsys, monkeypatch):
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", SECRET)
    box.write(
        box.home / ".cursor" / "mcp.json",
        {
            "mcpServers": {
                "openproject": server(
                    {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: SECRET}
                )
            }
        },
    )

    run = box.run(capsys)

    assert "OPENPROJECT_API_TOKEN is set in this shell but not in the entry" in run.out
    _no_secrets(run.out)


def test_cursor_with_no_token_in_the_entry_but_the_name_and_the_variable_in_the_shell_is_unverified(
    box, capsys, monkeypatch
):
    monkeypatch.setenv("OPENPROJECT_API_TOKEN_VAR", NAMED)
    monkeypatch.setenv(NAMED, SECRET)
    box.write(
        box.home / ".cursor" / "mcp.json", {"mcpServers": {"openproject": server({"OPENPROJECT_BASE_URL": BASE_URL})}}
    )

    run = box.run(capsys)

    assert run.exit_code == EXIT_SUCCESS
    assert "[FAIL]" not in run.out
    assert box.probe.calls == []
    _no_secrets(run.out)


# ── the connection check is shared only by entries that would connect the same way ──


def _evaluation(token: str) -> Evaluation:
    env = EnvMap(
        {"OPENPROJECT_BASE_URL": BASE_URL, "OPENPROJECT_API_TOKEN_VAR": NAMED, NAMED: token}, case_insensitive=False
    )
    return Evaluation(Subject(CursorHost(), "x", effective=EffectiveEnv(env=env)), probe_env=env)


def test_two_entries_that_differ_only_in_the_token_variable_are_probed_separately():
    assert probe_key(_evaluation("one")) != probe_key(_evaluation("two"))
    assert probe_key(_evaluation("one")) == probe_key(_evaluation("one"))
