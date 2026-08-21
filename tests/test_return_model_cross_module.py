"""Regression test: _return_model must resolve a tool's return annotation
against the tool's OWN defining module, not tools.py's module.

`from __future__ import annotations` turns every return annotation into a
plain string. `_return_model` looks that string up as a class name to decide
whether a tool's result is a trimmable dataclass. Before this fix it looked
the name up in tools.py's own `globals()` -- correct only because every tool
function currently lives in tools.py itself. Once tools.py is eventually
split into per-domain files (OPM-395), a tool defined elsewhere would still
carry a correct annotation string, but the old code would search the wrong
module and silently return None instead of the real model.

`ExampleModel` and `example_tool` are deliberately defined here, in this
test module's own namespace -- not in tools.py -- so this test fails against
the pre-fix globals()-based lookup (ExampleModel doesn't exist in tools.py's
namespace) and passes against the fn.__globals__-based fix (which resolves
against this module's namespace instead, regardless of which module calls
_return_model).
"""

from __future__ import annotations

from dataclasses import dataclass

from openproject_ce_mcp.tools import _return_model, _returns_dataclass


@dataclass
class ExampleModel:
    value: int


async def example_tool() -> ExampleModel:
    return ExampleModel(value=1)


def not_a_dataclass() -> int:
    return 1


def test_return_model_resolves_against_the_function_s_own_module() -> None:
    assert _return_model(example_tool) is ExampleModel


def test_returns_dataclass_true_for_cross_module_dataclass_return() -> None:
    assert _returns_dataclass(example_tool) is True


def test_returns_dataclass_false_for_non_dataclass_return() -> None:
    assert _returns_dataclass(not_a_dataclass) is False
