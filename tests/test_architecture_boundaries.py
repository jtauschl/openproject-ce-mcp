"""Static architecture-boundary checks for the app/ layered tree (ADR 0001, OPM-153/OPM-209).

First static-boundary test in this repo -- no existing pattern to copy (confirmed by
searching the whole tree for `ast.parse`/"boundary"/"layering" before writing this).
A general, directory-based layer-dependency check, not a narrow "these two specific
files don't import each other" test -- the narrow version would have missed a real
layering violation caught during OPM-153's design review (a shared helper placed
under app/services/ that a Resolver depended on).

OPM-209 generalized this from the Versions-only pilot to cover future domains.
Four of the five original checks were already directory-generic (they walk app/
by layer, not by domain name) and needed no changes; only the Service/Resolver-
depends-on-the-port-Protocol check named VersionService/VersionResolver/VersionApi/
HttpxVersionApi directly and has been rewritten to discover classes by directory,
plus two entirely new static rules (no FastMCP import, no direct env-var reads)
were added under app/.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import typing
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent / "src" / "openproject_ce_mcp"
APP = SRC / "app"

# Pre-existing httpx importers NOT touched by OPM-153: client.py still does raw HTTP
# for ~50 unmigrated domains; retry_transport.py is wrapped-not-replaced per the ADR;
# doctor.py/setup_cli.py are the ADR's own named, pre-existing exceptions.
_PRE_EXISTING_HTTPX_IMPORTERS = {"client.py", "retry_transport.py", "doctor.py", "setup_cli.py"}
_HTTPX_TRANSPORT_FILE = Path("transport") / "httpx_transport.py"

# Layer dependency rules (ADR 0001): which app/<layer> dirs a given layer may import
# from, besides itself and the shared kernel (app/errors.py, app/pagination.py,
# config.py, models.py -- always allowed, excluded from this check entirely).
_LAYER_DEPENDENCIES: dict[str, set[str]] = {
    "policies": set(),
    "transport": set(),
    "ports": set(),
    "adapters": {"ports", "transport"},
    "resolvers": {"ports", "policies"},
    "services": {"ports", "policies", "resolvers"},
}
_SHARED_KERNEL = {"errors", "pagination"}  # module names directly under app/, not layer dirs


def _imports_httpx(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "httpx" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "httpx":
            return True
    return False


def _app_layers_imported(path: Path) -> set[str]:
    """Which app/<layer> subdirectories this file imports from, excluding the shared
    kernel and the file's own layer. Handles both `ast.Import` (bare
    `import openproject_ce_mcp.app.services.version_service`) and `ast.ImportFrom`
    (relative `from .foo import bar` / `from ..foo import bar`, or absolute
    `from openproject_ce_mcp.app.foo import bar`).
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    own_layer = path.relative_to(APP).parts[0]
    layers: set[str] = set()

    def _record(dotted: str) -> None:
        top = dotted.split(".")[0]
        if top in _LAYER_DEPENDENCIES and top != own_layer and top not in _SHARED_KERNEL:
            layers.add(top)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("openproject_ce_mcp.app."):
                    _record(alias.name[len("openproject_ce_mcp.app.") :])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("openproject_ce_mcp.app."):
                _record(node.module[len("openproject_ce_mcp.app.") :])
            elif node.level == 2 and node.module:
                # from app/<own_layer>/<file>.py: level=2 ("..X") reaches app/, so
                # module's first component is either another layer dir or shared kernel.
                _record(node.module)
            # level == 1 ("from .X import Y") is a same-layer sibling import -- never
            # cross-layer, intentionally not recorded. level == 3 ("from ...X import Y")
            # reaches the root package (config, models) -- never a layer, not recorded.
    return layers


def test_httpx_confined_to_one_file_within_the_app_tree() -> None:
    offenders = [p for p in APP.rglob("*.py") if p.relative_to(APP) != _HTTPX_TRANSPORT_FILE and _imports_httpx(p)]
    assert offenders == []


def test_httpx_importers_outside_app_match_the_known_allow_list() -> None:
    offenders = {p.name for p in SRC.glob("*.py") if p.name not in _PRE_EXISTING_HTTPX_IMPORTERS and _imports_httpx(p)}
    assert offenders == set()


def _app_import_violations(source: str) -> list[str]:
    """Find imports of the `app/` package in `source`, in any of the three forms
    Python allows (OPM-219): absolute `ast.ImportFrom`, relative `ast.ImportFrom`
    (as used from a package-root file like tools.py, so level == 1), and bare
    `ast.Import`. An earlier version of this check only inspected absolute
    `ast.ImportFrom` nodes, so `from .app.presentation import x` or
    `import openproject_ce_mcp.app.presentation` silently passed.
    """
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openproject_ce_mcp.app" or alias.name.startswith("openproject_ce_mcp.app."):
                    violations.append(ast.dump(node))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("openproject_ce_mcp.app"):
                violations.append(ast.dump(node))
            elif node.level == 1 and (
                (node.module and (node.module == "app" or node.module.startswith("app.")))
                or (node.module is None and any(alias.name == "app" for alias in node.names))
            ):
                violations.append(ast.dump(node))
    return violations


def test_tools_module_never_imports_from_app_directly() -> None:
    violations = _app_import_violations((SRC / "tools.py").read_text())
    assert violations == [], f"tools.py must not import from app/ directly: {violations}"


def test_app_import_violation_detector_catches_absolute_import_from() -> None:
    assert _app_import_violations("from openproject_ce_mcp.app.presentation import _to_payload\n")


def test_app_import_violation_detector_catches_relative_import_from() -> None:
    assert _app_import_violations("from .app.presentation import _to_payload\n")


def test_app_import_violation_detector_catches_relative_bare_app_import() -> None:
    assert _app_import_violations("from . import app\n")


def test_app_import_violation_detector_catches_bare_import() -> None:
    assert _app_import_violations("import openproject_ce_mcp.app.presentation\n")


def test_app_import_violation_detector_ignores_unrelated_imports() -> None:
    source = "from .models import ProjectSummary\nimport json\nfrom . import presentation\n"
    assert _app_import_violations(source) == []


def test_app_layer_dependencies_are_one_directional() -> None:
    for layer, allowed in _LAYER_DEPENDENCIES.items():
        layer_dir = APP / layer
        if not layer_dir.exists():
            continue
        for path in layer_dir.rglob("*.py"):
            disallowed = _app_layers_imported(path) - allowed
            assert not disallowed, f"{path} imports from disallowed layer(s): {disallowed}"


_LAYER_CLASS_SUFFIX: dict[str, str] = {"services": "Service", "resolvers": "Resolver"}


def _public_classes_defined_in(module: Any) -> list[tuple[str, type]]:
    return [
        (name, cls)
        for name, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__ and not name.startswith("_")
    ]


def _iter_leaf_types(hint: Any) -> Iterator[type]:
    """Recursively unwrap Optional/Union/generic-collection type hints down to their
    leaf types, so a concrete adapter type nested inside e.g. `X | None` or
    `list[X]` is still found rather than only checking the top-level hint.
    `typing.get_type_hints` (without `include_extras=True`) already strips
    `Annotated` metadata before this ever runs.
    """
    origin = typing.get_origin(hint)
    if origin is None:
        if isinstance(hint, type):
            yield hint
        return
    for arg in typing.get_args(hint):
        if arg is type(None):
            continue
        yield from _iter_leaf_types(arg)


def _protocol_classes_under_ports() -> set[type]:
    ports_dir = APP / "ports"
    protocols: set[type] = set()
    if not ports_dir.exists():
        return protocols
    for path in sorted(ports_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"openproject_ce_mcp.app.ports.{path.stem}")
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and getattr(cls, "_is_protocol", False):
                protocols.add(cls)
    return protocols


def test_services_and_resolvers_are_named_by_convention_and_depend_on_port_protocols() -> None:
    """Generalizes OPM-153's Versions-only check (which named VersionService/
    VersionResolver/VersionApi/HttpxVersionApi directly) by discovering classes
    by directory instead, so a second domain's Service/Resolver needs no edit
    here. Two things are proven, not just "isn't the adapter" alone:

    1. The Service/Resolver naming convention itself is enforced, not assumed --
       a misnamed public class fails immediately rather than silently escaping
       the dependency check below (this closes what would otherwise be a blind
       spot: a naive "no adapter type" check alone would also pass for a class
       typed `Any`, `object`, an unrelated type, or with a missing annotation,
       none of which prove dependency inversion actually holds).
    2. Every such class's __init__ has no missing parameter annotations, no
       adapter type anywhere in its parameter types (even nested inside
       Optional/Union/a generic collection), and depends on at least one
       Protocol class defined under app/ports/ -- a positive proof of
       dependency inversion, not merely the absence of the concrete adapter.
    """
    protocol_classes = _protocol_classes_under_ports()
    assert protocol_classes, "expected at least one Protocol class under app/ports/"

    for layer, suffix in _LAYER_CLASS_SUFFIX.items():
        layer_dir = APP / layer
        if not layer_dir.exists():
            continue
        for path in sorted(layer_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            module = importlib.import_module(f"openproject_ce_mcp.app.{layer}.{path.stem}")
            for name, cls in _public_classes_defined_in(module):
                assert name.endswith(suffix), (
                    f"{module.__name__}.{name} is a public class under app/{layer}/ and "
                    f"must be named *{suffix} by convention (matching VersionService/"
                    f"VersionResolver)"
                )
                # Deliberately NOT skipped when the class has no __init__ of its own --
                # inspect.signature/typing.get_type_hints resolve an inherited __init__
                # via the MRO just as well as an own one, and a class with no
                # constructor at all (or one that inherits object.__init__ unchanged)
                # has zero real params either way, so it correctly falls through to
                # fail has_port_dependency below rather than silently passing.
                sig_params = [
                    p.name
                    for p in inspect.signature(cls.__init__).parameters.values()
                    if p.name != "self"
                    and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                ]
                hints = typing.get_type_hints(cls.__init__)
                missing = [p for p in sig_params if p not in hints]
                assert not missing, f"{cls.__qualname__}.__init__ has unannotated params: {missing}"

                has_port_dependency = False
                for pname in sig_params:
                    for leaf in _iter_leaf_types(hints[pname]):
                        leaf_module = getattr(leaf, "__module__", "")
                        assert not leaf_module.startswith("openproject_ce_mcp.app.adapters"), (
                            f"{cls.__qualname__}.__init__ param {pname!r} references the "
                            f"concrete adapter {leaf!r} (possibly nested in Optional/Union/a "
                            f"collection) instead of a port Protocol"
                        )
                        if leaf in protocol_classes:
                            has_port_dependency = True
                assert has_port_dependency, (
                    f"{cls.__qualname__}.__init__ has no parameter typed as a port Protocol from app/ports/"
                )


def test_version_service_and_resolver_bind_the_api_param_to_version_api_specifically() -> None:
    """Non-generalized regression test for the pilot domain's exact original
    guarantee, kept alongside the generic check above so the generic test can
    never silently substitute for this specific one: the api param is VersionApi
    exactly, not just "some Protocol"."""
    from openproject_ce_mcp.app.adapters.httpx_version_api import HttpxVersionApi
    from openproject_ce_mcp.app.ports.version_api import VersionApi
    from openproject_ce_mcp.app.resolvers.version_resolver import VersionResolver
    from openproject_ce_mcp.app.services.version_service import VersionService

    for cls in (VersionService, VersionResolver):
        hints = typing.get_type_hints(cls.__init__)
        assert hints["api"] is VersionApi, f"{cls.__name__}.__init__'s api param must be typed VersionApi"
        assert hints["api"] is not HttpxVersionApi, (
            f"{cls.__name__}.__init__'s api param must not be the concrete adapter"
        )


def _imports_module_named(path: Path, module_name: str) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == module_name for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == module_name:
            return True
    return False


def test_app_tree_never_imports_fastmcp() -> None:
    offenders = [p for p in APP.rglob("*.py") if _imports_module_named(p, "fastmcp")]
    assert offenders == []


_BARE_ENV_ACCESS_NAMES = {"environ", "getenv"}


def _reads_env_vars_directly(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    # Track every local name the `os` module itself is bound to (`import os`,
    # `import os as host_os`, ...), not just the literal name "os" -- an aliased
    # import must be caught too, since it's the same module underneath.
    os_module_names: set[str] = set()
    bare_imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_module_names.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            bare_imported.update(
                alias.asname or alias.name for alias in node.names if alias.name in _BARE_ENV_ACCESS_NAMES
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id in os_module_names
        ):
            return True
        if isinstance(node, ast.Name) and node.id in bare_imported:
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in os_module_names
        ):
            return True
    return False


def test_app_tree_never_reads_environment_variables_directly() -> None:
    offenders = [p for p in APP.rglob("*.py") if _reads_env_vars_directly(p)]
    assert offenders == []
