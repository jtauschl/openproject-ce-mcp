from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / "tests" / "integration" / "_live_cleanup.py"
_spec = importlib.util.spec_from_file_location("live_cleanup_under_test", _PATH)
live_cleanup = importlib.util.module_from_spec(_spec)
sys.modules["live_cleanup_under_test"] = live_cleanup
_spec.loader.exec_module(live_cleanup)

from openproject_ce_mcp.client import NotFoundError, PermissionDeniedError  # noqa: E402


class _Recorder:
    def __init__(self, outcomes: dict | None = None):
        self.outcomes = outcomes or {}
        self.called: list = []

    async def __call__(self, item):
        self.called.append(item)
        outcome = self.outcomes.get(item)
        if isinstance(outcome, Exception):
            raise outcome


async def test_every_item_is_deleted():
    delete = _Recorder()

    await live_cleanup.delete_all("work package", [1, 2, 3], delete)

    assert delete.called == [1, 2, 3]


async def test_an_item_that_is_already_gone_is_tolerated():
    delete = _Recorder({2: NotFoundError("gone")})

    await live_cleanup.delete_all("work package", [1, 2, 3], delete)

    assert delete.called == [1, 2, 3]


async def test_other_failures_do_not_stop_the_rest_and_are_all_reported_with_item_and_error():
    delete = _Recorder({1: PermissionDeniedError("forbidden"), 3: RuntimeError("boom")})

    with pytest.raises(live_cleanup.LiveCleanupFailed) as failed:
        await live_cleanup.delete_all("version", [1, 2, 3, 4], delete)

    assert delete.called == [1, 2, 3, 4]
    message = str(failed.value)
    assert "version 1: PermissionDeniedError: forbidden" in message
    assert "version 3: RuntimeError: boom" in message
    assert "version 2" not in message and "version 4" not in message


async def test_a_failure_is_an_assertion_failure_so_pytest_names_the_test():
    with pytest.raises(AssertionError):
        await live_cleanup.delete_all("grid", [1], _Recorder({1: RuntimeError("x")}))


class _Client:
    def __init__(self, name: str, log: list, *, fail_initialize=False, fail_close=False):
        self.name, self.log = name, log
        self.fail_initialize, self.fail_close = fail_initialize, fail_close

    async def initialize(self):
        self.log.append(f"init {self.name}")
        if self.fail_initialize:
            raise RuntimeError(f"{self.name} cannot initialize")

    async def aclose(self):
        self.log.append(f"close {self.name}")
        if self.fail_close:
            raise RuntimeError(f"{self.name} cannot close")


def _registry(log: list, **per_client):
    names = iter(["a", "b", "c"])

    def factory(settings):
        name = next(names)
        return _Client(name, log, **per_client.get(name, {}))

    return live_cleanup.ClientRegistry(factory)


async def test_every_client_is_closed_in_reverse_order():
    log: list = []
    registry = _registry(log)
    await registry.open(object())
    await registry.open(object())

    await registry.close()

    assert log == ["init a", "init b", "close b", "close a"]


async def test_a_client_that_fails_to_initialize_is_still_closed():
    log: list = []
    registry = _registry(log, a={"fail_initialize": True})

    with pytest.raises(RuntimeError, match="a cannot initialize"):
        await registry.open(object())
    await registry.close()

    assert log == ["init a", "close a"]


async def test_a_failing_close_does_not_stop_the_others_and_is_reported():
    log: list = []
    registry = _registry(log, b={"fail_close": True})
    for _ in range(3):
        await registry.open(object())

    with pytest.raises(live_cleanup.LiveCleanupFailed, match="b cannot close"):
        await registry.close()

    assert log[-3:] == ["close c", "close b", "close a"]


async def test_closing_twice_closes_each_client_once():
    log: list = []
    registry = _registry(log)
    await registry.open(object())

    await registry.close()
    await registry.close()

    assert log.count("close a") == 1


# ── A client that may write outside the test project needs an admin token ──


class _Settings:
    def __init__(self, write_projects: tuple[str, ...]):
        self.write_projects = write_projects


def _is_admin(answer: bool, asked: list):
    async def is_admin(settings):
        asked.append(settings)
        return answer

    return is_admin


@pytest.mark.parametrize(
    ("write_projects", "outside"),
    [
        ((), False),
        (("TST",), False),
        (("tst",), False),
        (("*",), True),
        (("TST", "OTHER"), True),
        (("it*",), True),
    ],
)
def test_a_client_writes_outside_the_test_project_when_a_pattern_covers_more_than_it(write_projects, outside):
    assert live_cleanup.writes_outside("TST", _Settings(write_projects)) is outside


async def test_a_non_admin_token_skips_the_client_that_could_create_disposable_projects():
    log: list = []
    asked: list = []
    registry = live_cleanup.ClientRegistry(
        lambda settings: _Client("a", log),
        before_open=live_cleanup.require_admin_for_wide_writes("TST", _is_admin(False, asked)),
    )

    with pytest.raises(pytest.skip.Exception, match="not an admin"):
        await registry.open(_Settings(("*",)))

    assert log == []
    assert len(asked) == 1


async def test_an_admin_token_opens_the_client_with_wide_writes():
    log: list = []
    registry = live_cleanup.ClientRegistry(
        lambda settings: _Client("a", log),
        before_open=live_cleanup.require_admin_for_wide_writes("TST", _is_admin(True, [])),
    )

    await registry.open(_Settings(("*",)))

    assert log == ["init a"]


async def test_a_client_confined_to_the_test_project_never_asks_whether_the_token_is_admin():
    log: list = []
    asked: list = []
    registry = live_cleanup.ClientRegistry(
        lambda settings: _Client("a", log),
        before_open=live_cleanup.require_admin_for_wide_writes("TST", _is_admin(False, asked)),
    )

    await registry.open(_Settings(("TST",)))
    await registry.open(_Settings(()))

    assert log == ["init a", "init a"]
    assert asked == []


def test_the_integration_suite_opens_every_client_through_the_admin_check():
    conftest = (_ROOT / "tests" / "integration" / "conftest.py").read_text(encoding="utf-8")

    assert conftest.count("ClientRegistry(") == 1
    assert "before_open=require_admin_for_wide_writes(" in conftest


async def test_the_token_is_admin_only_when_users_me_says_so(monkeypatch):
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Http:
        payload: dict = {}

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url):
            assert url == "https://op.example/api/v3/users/me"
            return _Response(self.payload)

    monkeypatch.setattr(live_cleanup.httpx, "AsyncClient", _Http)
    settings = type("S", (), {"base_url": "https://op.example/", "api_token": SecretStr("t"), "timeout": 5})()

    _Http.payload = {"admin": True}
    assert await live_cleanup.token_is_admin(settings) is True
    _Http.payload = {"admin": False}
    assert await live_cleanup.token_is_admin(settings) is False
    _Http.payload = {"login": "member"}
    assert await live_cleanup.token_is_admin(settings) is False


# ── Structural guard for code written later ────────────────────────────────

_LIVE_FILES = sorted((_ROOT / "tests" / "integration").glob("*.py")) + [_ROOT / "tools" / "measure-context.py"]


def _silent_broad_handlers(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        broad = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        )
        silent = all(isinstance(stmt, (ast.Pass, ast.Continue)) for stmt in node.body)
        if broad and silent:
            lines.append(node.lineno)
    return lines


def _direct_client_constructions(tree: ast.AST) -> list[int]:
    """Calls of OpenProjectClient by its name, by an import alias, or through a module attribute."""
    names = {"OpenProjectClient"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name == "OpenProjectClient" and alias.asname}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in names) or (
            isinstance(func, ast.Attribute) and func.attr == "OpenProjectClient"
        ):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("path", _LIVE_FILES, ids=lambda path: path.name)
def test_no_live_file_swallows_an_error_silently(path: Path):
    assert _silent_broad_handlers(ast.parse(path.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("path", _LIVE_FILES, ids=lambda path: path.name)
def test_no_test_builds_its_own_live_client(path: Path):
    # The registry in _live_cleanup.py and the benchmark's workspace own every client's lifetime.
    allowed = {"_live_cleanup.py", "measure-context.py"}
    constructions = _direct_client_constructions(ast.parse(path.read_text(encoding="utf-8")))
    assert path.name in allowed or constructions == []


def test_the_guard_sees_a_planted_silent_handler_and_a_planted_construction():
    planted = ast.parse(
        "def f():\n    try:\n        pass\n    except Exception:\n        pass\n    OpenProjectClient(settings)\n"
    )
    assert _silent_broad_handlers(planted) == [4]
    assert _direct_client_constructions(planted) == [6]


@pytest.mark.parametrize(
    "source",
    [
        "from openproject_ce_mcp.client import OpenProjectClient as Client\nClient(settings)\n",
        "import openproject_ce_mcp.client as module\nmodule.OpenProjectClient(settings)\n",
        "from openproject_ce_mcp import client\nclient.OpenProjectClient(settings)\n",
    ],
    ids=["alias", "module attribute", "package attribute"],
)
def test_the_guard_sees_an_aliased_or_attribute_construction(source: str):
    assert _direct_client_constructions(ast.parse(source)) != []
