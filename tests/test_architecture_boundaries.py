"""Static architecture-boundary checks for the app/ layered tree (ADR 0001, OPM-153).

First static-boundary test in this repo -- no existing pattern to copy (confirmed by
searching the whole tree for `ast.parse`/"boundary"/"layering" before writing this).
A general, directory-based layer-dependency check, not a narrow "these two specific
files don't import each other" test -- the narrow version would have missed a real
layering violation caught during OPM-153's design review (a shared helper placed
under app/services/ that a Resolver depended on).
"""

from __future__ import annotations

import ast
import typing
from pathlib import Path

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


def test_tools_module_never_imports_from_app_directly() -> None:
    tree = ast.parse((SRC / "tools.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("openproject_ce_mcp.app"):
            raise AssertionError(f"tools.py must not import from app/ directly: {ast.dump(node)}")


def test_app_layer_dependencies_are_one_directional() -> None:
    for layer, allowed in _LAYER_DEPENDENCIES.items():
        layer_dir = APP / layer
        if not layer_dir.exists():
            continue
        for path in layer_dir.rglob("*.py"):
            disallowed = _app_layers_imported(path) - allowed
            assert not disallowed, f"{path} imports from disallowed layer(s): {disallowed}"


def test_version_service_and_resolver_depend_on_the_version_api_protocol_not_the_concrete_adapter() -> None:
    # Covers BOTH VersionService and VersionResolver -- the ADR decision (Resolver
    # depends only on the port, never the Service) applies to both constructors.
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
