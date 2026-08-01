"""Static architecture-boundary checks for the app/ layered tree (ADR 0001).

First static-boundary test in this repo -- no existing pattern to copy (confirmed by
searching the whole tree for `ast.parse`/"boundary"/"layering" before writing this).
A general, directory-based layer-dependency check, not a narrow "these two specific
files don't import each other" test -- the narrow version would have missed a real
layering violation caught during an earlier design review (a shared helper placed
under app/services/ that a Resolver depended on).

This was later generalized from the Versions-only pilot to cover future domains.
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

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "openproject_ce_mcp"
APP = SRC / "app"

# Pre-existing httpx importers not migrated to the layered app/ tree: client.py still does raw HTTP
# for ~50 unmigrated domains; retry_transport.py is wrapped-not-replaced per the ADR;
# doctor.py/setup_cli.py are the ADR's own named, pre-existing exceptions.
_PRE_EXISTING_HTTPX_IMPORTERS = {"client.py", "retry_transport.py", "doctor.py", "setup_cli.py"}
_HTTPX_TRANSPORT_FILE = Path("transport") / "httpx_transport.py"

# Layer dependency rules (ADR 0001): which app/<layer> dirs a given layer may import
# from, besides itself and the shared kernel (app/errors.py, app/pagination.py,
# app/api_href.py, app/form_result.py, config.py, models.py -- always allowed,
# excluded from this check entirely).
_LAYER_DEPENDENCIES: dict[str, set[str]] = {
    "policies": set(),
    "transport": set(),
    "ports": set(),
    "adapters": {"ports", "transport"},
    "resolvers": {"ports", "policies"},
    "services": {"ports", "policies", "resolvers"},
}
_SHARED_KERNEL = {"errors", "pagination", "api_href", "form_result"}  # module names directly under app/, not layer dirs


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
    Python allows: absolute `ast.ImportFrom`, relative `ast.ImportFrom`
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


_HAL_ALLOWED_ABSOLUTE_ROOTS = {"__future__", "typing"}


def _hal_import_violations(source: str) -> list[str]:
    """Allowlist, not a denylist (an earlier denylist version -- `client`/
    `openproject_ce_mcp.app`/`app`/`httpx` prefixes -- missed several real
    forms: it compared only `alias.name.split(".")[0]`, i.e. the leading
    `openproject_ce_mcp` component, against the full `openproject_ce_mcp.app`
    prefix, so `import openproject_ce_mcp.app.foo`/`import
    openproject_ce_mcp.client`/`from openproject_ce_mcp import client` all
    passed uncaught; and `from . import client` has its target in
    `node.names`, not `node.module`, which the denylist never inspected).
    hal.py's actual invariant is narrower and simpler to state correctly as
    an allowlist: it may import ONLY `__future__`/`typing` (the only two
    names it currently needs) plus, implicitly, nothing else -- so ANY
    relative import (necessarily reaching back into this package) and ANY
    absolute import whose top-level root isn't in the allowlist is a
    violation, with no prefix-matching required.
    """
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in _HAL_ALLOWED_ABSOLUTE_ROOTS:
                    violations.append(ast.dump(node))
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                # Any relative import reaches back into this package -- never allowed.
                violations.append(ast.dump(node))
            elif (node.module or "").split(".")[0] not in _HAL_ALLOWED_ABSOLUTE_ROOTS:
                violations.append(ast.dump(node))
    return violations


def test_hal_module_stays_neutral() -> None:
    """hal.py (introduced as an architecture follow-up) is a shared-kernel module imported by
    both client.py and app/transport/httpx_transport.py -- neither of which
    may import from the other. It only stays a valid shared dependency for
    both sides as long as it imports nothing from either. This guards against
    the module silently regaining a dependency that would recreate the exact
    duplication this refactor removed.
    """
    violations = _hal_import_violations((SRC / "hal.py").read_text())
    assert violations == [], f"hal.py must only import from {_HAL_ALLOWED_ABSOLUTE_ROOTS}: {violations}"


@pytest.mark.parametrize(
    "source",
    [
        "from . import client\n",
        "from .client import X\n",
        "import openproject_ce_mcp.client\n",
        "from openproject_ce_mcp import client\n",
        "import openproject_ce_mcp.app.foo\n",
        "from openproject_ce_mcp.app import foo\n",
        "import httpx\n",
        "from httpx import Response\n",
    ],
)
def test_hal_import_violation_detector_catches_every_disallowed_form(source: str) -> None:
    assert _hal_import_violations(source)


def test_hal_import_violation_detector_allows_future_and_typing() -> None:
    source = "from __future__ import annotations\nfrom typing import Any\n"
    assert _hal_import_violations(source) == []


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
    """Generalizes an earlier Versions-only check (which named VersionService/
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


def test_project_service_and_resolver_bind_the_api_param_to_project_api_specifically() -> None:
    """Non-generalized regression test for the Projects domain's exact
    guarantee, sibling to the Versions-only check above (that one is not
    generalized further -- this is a new, separate test, not an edit to it):
    the api param is ProjectApi exactly, not just "some Protocol"."""
    from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
    from openproject_ce_mcp.app.ports.project_api import ProjectApi
    from openproject_ce_mcp.app.resolvers.project_resolver import ProjectResolver
    from openproject_ce_mcp.app.services.project_service import ProjectAdminService, ProjectService

    for cls in (ProjectService, ProjectAdminService, ProjectResolver):
        hints = typing.get_type_hints(cls.__init__)
        assert hints["api"] is ProjectApi, f"{cls.__name__}.__init__'s api param must be typed ProjectApi"
        assert hints["api"] is not HttpxProjectApi, (
            f"{cls.__name__}.__init__'s api param must not be the concrete adapter"
        )


def test_membership_service_binds_the_api_param_to_membership_api_specifically() -> None:
    """Non-generalized regression test for the Memberships domain's exact
    guarantee, sibling to the Versions-only and Projects-only checks above:
    the api param is MembershipApi exactly, not just "some Protocol". No
    MembershipResolver exists (unlike Versions/Projects) -- membership_id is
    always a numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_membership_api import HttpxMembershipApi
    from openproject_ce_mcp.app.ports.membership_api import MembershipApi
    from openproject_ce_mcp.app.services.membership_service import MembershipService

    hints = typing.get_type_hints(MembershipService.__init__)
    assert hints["api"] is MembershipApi, "MembershipService.__init__'s api param must be typed MembershipApi"
    assert hints["api"] is not HttpxMembershipApi, (
        "MembershipService.__init__'s api param must not be the concrete adapter"
    )


def test_news_service_binds_the_api_param_to_news_api_specifically() -> None:
    """Non-generalized regression test for the News domain's exact guarantee,
    sibling to the checks above: the api param is NewsApi exactly, not just
    "some Protocol". No NewsResolver exists (like Memberships) -- news_id is
    always a numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_news_api import HttpxNewsApi
    from openproject_ce_mcp.app.ports.news_api import NewsApi
    from openproject_ce_mcp.app.services.news_service import NewsService

    hints = typing.get_type_hints(NewsService.__init__)
    assert hints["api"] is NewsApi, "NewsService.__init__'s api param must be typed NewsApi"
    assert hints["api"] is not HttpxNewsApi, "NewsService.__init__'s api param must not be the concrete adapter"


def test_document_service_binds_the_api_param_to_document_api_specifically() -> None:
    """Non-generalized regression test for the Documents domain's exact
    guarantee, sibling to the checks above: the api param is DocumentApi
    exactly, not just "some Protocol". No DocumentResolver exists (like
    Memberships/News) -- document_id is always a numeric value already
    validated by tools.py, so there is no semantic-reference resolution for
    this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_document_api import HttpxDocumentApi
    from openproject_ce_mcp.app.ports.document_api import DocumentApi
    from openproject_ce_mcp.app.services.document_service import DocumentService

    hints = typing.get_type_hints(DocumentService.__init__)
    assert hints["api"] is DocumentApi, "DocumentService.__init__'s api param must be typed DocumentApi"
    assert hints["api"] is not HttpxDocumentApi, "DocumentService.__init__'s api param must not be the concrete adapter"


def test_wiki_page_service_binds_the_api_param_to_wiki_page_api_specifically() -> None:
    """Non-generalized regression test for the Wiki Pages domain's exact
    guarantee, sibling to the checks above: the api param is WikiPageApi
    exactly, not just "some Protocol". No WikiPageResolver exists (like
    Memberships/News/Documents) -- wiki_page_id is always a numeric value
    already validated by tools.py, so there is no semantic-reference
    resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_wiki_page_api import HttpxWikiPageApi
    from openproject_ce_mcp.app.ports.wiki_page_api import WikiPageApi
    from openproject_ce_mcp.app.services.wiki_page_service import WikiPageService

    hints = typing.get_type_hints(WikiPageService.__init__)
    assert hints["api"] is WikiPageApi, "WikiPageService.__init__'s api param must be typed WikiPageApi"
    assert hints["api"] is not HttpxWikiPageApi, "WikiPageService.__init__'s api param must not be the concrete adapter"


def test_category_service_binds_the_api_param_to_category_api_specifically() -> None:
    """Non-generalized regression test for the Categories domain's exact
    guarantee, sibling to the checks above: the api param is CategoryApi
    exactly, not just "some Protocol". No CategoryResolver exists (like
    Memberships/News/Documents/Wiki Pages) -- category_id is always a numeric
    value already validated by tools.py, so there is no semantic-reference
    resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_category_api import HttpxCategoryApi
    from openproject_ce_mcp.app.ports.category_api import CategoryApi
    from openproject_ce_mcp.app.services.category_service import CategoryService

    hints = typing.get_type_hints(CategoryService.__init__)
    assert hints["api"] is CategoryApi, "CategoryService.__init__'s api param must be typed CategoryApi"
    assert hints["api"] is not HttpxCategoryApi, "CategoryService.__init__'s api param must not be the concrete adapter"


def test_view_service_binds_the_api_param_to_view_api_specifically() -> None:
    """Non-generalized regression test for the Views domain's exact
    guarantee, sibling to the checks above: the api param is ViewApi
    exactly, not just "some Protocol". No ViewResolver exists (like
    Memberships/News/Documents/Wiki Pages/Categories) -- view_id is always a
    numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_view_api import HttpxViewApi
    from openproject_ce_mcp.app.ports.view_api import ViewApi
    from openproject_ce_mcp.app.services.view_service import ViewService

    hints = typing.get_type_hints(ViewService.__init__)
    assert hints["api"] is ViewApi, "ViewService.__init__'s api param must be typed ViewApi"
    assert hints["api"] is not HttpxViewApi, "ViewService.__init__'s api param must not be the concrete adapter"


def test_grid_service_binds_the_api_param_to_grid_api_specifically() -> None:
    """Non-generalized regression test for the Grids domain's exact
    guarantee, sibling to the checks above: the api param is GridApi
    exactly, not just "some Protocol". No GridResolver exists -- grid_id is
    always a numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_grid_api import HttpxGridApi
    from openproject_ce_mcp.app.ports.grid_api import GridApi
    from openproject_ce_mcp.app.services.grid_service import GridService

    hints = typing.get_type_hints(GridService.__init__)
    assert hints["api"] is GridApi, "GridService.__init__'s api param must be typed GridApi"
    assert hints["api"] is not HttpxGridApi, "GridService.__init__'s api param must not be the concrete adapter"


def test_sprint_service_binds_the_api_param_to_sprint_api_specifically() -> None:
    """Non-generalized regression test for the Sprints domain's exact
    guarantee, sibling to the checks above: the api param is SprintApi
    exactly, not just "some Protocol". No SprintResolver exists -- sprint_id
    is always a numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver
    (client.py's own `_resolve_sprint_id`, which resolves a *name* to an id
    for work-package writes, stays client.py-side machinery consuming
    SprintApi/sprint_policy directly, not a Service-layer Resolver)."""
    from openproject_ce_mcp.app.adapters.httpx_sprint_api import HttpxSprintApi
    from openproject_ce_mcp.app.ports.sprint_api import SprintApi
    from openproject_ce_mcp.app.services.sprint_service import SprintService

    hints = typing.get_type_hints(SprintService.__init__)
    assert hints["api"] is SprintApi, "SprintService.__init__'s api param must be typed SprintApi"
    assert hints["api"] is not HttpxSprintApi, "SprintService.__init__'s api param must not be the concrete adapter"


def test_board_service_binds_the_api_param_to_board_api_specifically() -> None:
    """Non-generalized regression test for the Boards domain's exact
    guarantee, sibling to the checks above: the api param is BoardApi
    exactly, not just "some Protocol". No BoardResolver exists -- board_id is
    always a numeric value already validated by tools.py, so there is no
    semantic-reference resolution for this domain to warrant a Resolver."""
    from openproject_ce_mcp.app.adapters.httpx_board_api import HttpxBoardApi
    from openproject_ce_mcp.app.ports.board_api import BoardApi
    from openproject_ce_mcp.app.services.board_service import BoardService

    hints = typing.get_type_hints(BoardService.__init__)
    assert hints["api"] is BoardApi, "BoardService.__init__'s api param must be typed BoardApi"
    assert hints["api"] is not HttpxBoardApi, "BoardService.__init__'s api param must not be the concrete adapter"


def test_action_capability_service_binds_the_api_param_to_action_capability_api_specifically() -> None:
    """Non-generalized regression test for the Actions & Capabilities domain's
    exact guarantee, sibling to the checks above: the api param is
    ActionCapabilityApi exactly, not just "some Protocol". No dedicated
    Resolver exists -- capability_id is an opaque filter string, not a
    semantic reference needing lookup."""
    from openproject_ce_mcp.app.adapters.httpx_action_capability_api import HttpxActionCapabilityApi
    from openproject_ce_mcp.app.ports.action_capability_api import ActionCapabilityApi
    from openproject_ce_mcp.app.services.action_capability_service import ActionCapabilityService

    hints = typing.get_type_hints(ActionCapabilityService.__init__)
    assert hints["api"] is ActionCapabilityApi, (
        "ActionCapabilityService.__init__'s api param must be typed ActionCapabilityApi"
    )
    assert hints["api"] is not HttpxActionCapabilityApi, (
        "ActionCapabilityService.__init__'s api param must not be the concrete adapter"
    )


def test_role_service_binds_the_api_param_to_role_api_specifically() -> None:
    """Non-generalized regression test for the Roles domain's exact guarantee,
    sibling to the checks above: the api param is RoleApi exactly, not just
    "some Protocol". No dedicated Resolver exists -- list_roles has no
    semantic reference to resolve."""
    from openproject_ce_mcp.app.adapters.httpx_role_api import HttpxRoleApi
    from openproject_ce_mcp.app.ports.role_api import RoleApi
    from openproject_ce_mcp.app.services.role_service import RoleService

    hints = typing.get_type_hints(RoleService.__init__)
    assert hints["api"] is RoleApi, "RoleService.__init__'s api param must be typed RoleApi"
    assert hints["api"] is not HttpxRoleApi, "RoleService.__init__'s api param must not be the concrete adapter"


def test_instance_configuration_service_binds_the_api_param_to_instance_configuration_api_specifically() -> None:
    """Non-generalized regression test for the Instance Configuration domain's
    exact guarantee, sibling to the checks above: the api param is
    InstanceConfigurationApi exactly, not just "some Protocol". No dedicated
    Resolver exists -- get_instance_configuration has no semantic reference
    to resolve, and no project link/allowlist concept at all."""
    from openproject_ce_mcp.app.adapters.httpx_instance_configuration_api import HttpxInstanceConfigurationApi
    from openproject_ce_mcp.app.ports.instance_configuration_api import InstanceConfigurationApi
    from openproject_ce_mcp.app.services.instance_configuration_service import InstanceConfigurationService

    hints = typing.get_type_hints(InstanceConfigurationService.__init__)
    assert hints["api"] is InstanceConfigurationApi, (
        "InstanceConfigurationService.__init__'s api param must be typed InstanceConfigurationApi"
    )
    assert hints["api"] is not HttpxInstanceConfigurationApi, (
        "InstanceConfigurationService.__init__'s api param must not be the concrete adapter"
    )


def test_current_user_service_binds_the_api_param_to_current_user_api_specifically() -> None:
    """Non-generalized regression test for the Current User domain's exact
    guarantee, sibling to the checks above: the api param is CurrentUserApi
    exactly, not just "some Protocol". No dedicated Resolver exists --
    get_current_user has no semantic reference to resolve, and no project
    link/allowlist concept at all. Not to be confused with the pre-existing
    CurrentUserLookup seam Protocol (app/ports/current_user.py), a different,
    unrelated bare-callable seam this migration does not touch."""
    from openproject_ce_mcp.app.adapters.httpx_current_user_api import HttpxCurrentUserApi
    from openproject_ce_mcp.app.ports.current_user_api import CurrentUserApi
    from openproject_ce_mcp.app.services.current_user_service import CurrentUserService

    hints = typing.get_type_hints(CurrentUserService.__init__)
    assert hints["api"] is CurrentUserApi, "CurrentUserService.__init__'s api param must be typed CurrentUserApi"
    assert hints["api"] is not HttpxCurrentUserApi, (
        "CurrentUserService.__init__'s api param must not be the concrete adapter"
    )


def test_principal_service_binds_the_api_param_to_principal_api_specifically() -> None:
    """Non-generalized regression test for the Principals domain's exact
    guarantee, sibling to the checks above: the api param is PrincipalApi
    exactly, not just "some Protocol". No dedicated Resolver dependency on
    this Service -- the internal name/id lookup lives on PrincipalResolver
    instead, tested separately, since PrincipalService itself deliberately
    has only one public, gated method."""
    from openproject_ce_mcp.app.adapters.httpx_principal_api import HttpxPrincipalApi
    from openproject_ce_mcp.app.ports.principal_api import PrincipalApi
    from openproject_ce_mcp.app.services.principal_service import PrincipalService

    hints = typing.get_type_hints(PrincipalService.__init__)
    assert hints["api"] is PrincipalApi, "PrincipalService.__init__'s api param must be typed PrincipalApi"
    assert hints["api"] is not HttpxPrincipalApi, (
        "PrincipalService.__init__'s api param must not be the concrete adapter"
    )


def test_principal_resolver_binds_the_api_param_to_principal_api_specifically() -> None:
    """Sibling check for PrincipalResolver (not a Service, but follows the
    same Port-binding discipline): the api param is PrincipalApi exactly,
    not just "some Protocol", and not the concrete adapter."""
    from openproject_ce_mcp.app.adapters.httpx_principal_api import HttpxPrincipalApi
    from openproject_ce_mcp.app.ports.principal_api import PrincipalApi
    from openproject_ce_mcp.app.resolvers.principal_resolver import PrincipalResolver

    hints = typing.get_type_hints(PrincipalResolver.__init__)
    assert hints["api"] is PrincipalApi, "PrincipalResolver.__init__'s api param must be typed PrincipalApi"
    assert hints["api"] is not HttpxPrincipalApi, (
        "PrincipalResolver.__init__'s api param must not be the concrete adapter"
    )


def test_status_priority_type_resolver_binds_the_api_param_to_status_priority_type_api_specifically() -> None:
    """Sibling check for StatusPriorityTypeResolver (OPM-371): the api param
    is StatusPriorityTypeApi exactly, not just "some Protocol", and not the
    concrete adapter."""
    from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
    from openproject_ce_mcp.app.ports.status_priority_type_api import StatusPriorityTypeApi
    from openproject_ce_mcp.app.resolvers.status_priority_type_resolver import StatusPriorityTypeResolver

    hints = typing.get_type_hints(StatusPriorityTypeResolver.__init__)
    assert hints["api"] is StatusPriorityTypeApi, (
        "StatusPriorityTypeResolver.__init__'s api param must be typed StatusPriorityTypeApi"
    )
    assert hints["api"] is not HttpxStatusPriorityTypeApi, (
        "StatusPriorityTypeResolver.__init__'s api param must not be the concrete adapter"
    )


def test_type_resolver_binds_the_api_param_to_status_priority_type_api_specifically() -> None:
    """Sibling check for TypeResolver (OPM-371): the api param is
    StatusPriorityTypeApi exactly, not just "some Protocol", and not the
    concrete adapter."""
    from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
    from openproject_ce_mcp.app.ports.status_priority_type_api import StatusPriorityTypeApi
    from openproject_ce_mcp.app.resolvers.type_resolver import TypeResolver

    hints = typing.get_type_hints(TypeResolver.__init__)
    assert hints["api"] is StatusPriorityTypeApi, (
        "TypeResolver.__init__'s api param must be typed StatusPriorityTypeApi"
    )
    assert hints["api"] is not HttpxStatusPriorityTypeApi, (
        "TypeResolver.__init__'s api param must not be the concrete adapter"
    )


def test_user_preferences_service_binds_the_api_param_to_user_preferences_api_specifically() -> None:
    """Non-generalized regression test for the User Preferences domain's
    exact guarantee, sibling to the checks above: the api param is
    UserPreferencesApi exactly, not just "some Protocol". No dedicated
    Resolver exists -- get()/update() operate on the token owner's own
    singleton resource, with no id or semantic reference to resolve at all."""
    from openproject_ce_mcp.app.adapters.httpx_user_preferences_api import HttpxUserPreferencesApi
    from openproject_ce_mcp.app.ports.user_preferences_api import UserPreferencesApi
    from openproject_ce_mcp.app.services.user_preferences_service import UserPreferencesService

    hints = typing.get_type_hints(UserPreferencesService.__init__)
    assert hints["api"] is UserPreferencesApi, (
        "UserPreferencesService.__init__'s api param must be typed UserPreferencesApi"
    )
    assert hints["api"] is not HttpxUserPreferencesApi, (
        "UserPreferencesService.__init__'s api param must not be the concrete adapter"
    )


def test_extended_metadata_service_binds_the_api_param_to_extended_metadata_api_specifically() -> None:
    """Non-generalized regression test for the Extended Metadata domain's
    exact guarantee, sibling to the checks above: the api param is
    ExtendedMetadataApi exactly, not just "some Protocol". No dedicated
    Resolver exists -- none of the five bundled lookups has a project or
    semantic reference to resolve."""
    from openproject_ce_mcp.app.adapters.httpx_extended_metadata_api import HttpxExtendedMetadataApi
    from openproject_ce_mcp.app.ports.extended_metadata_api import ExtendedMetadataApi
    from openproject_ce_mcp.app.services.extended_metadata_service import ExtendedMetadataService

    hints = typing.get_type_hints(ExtendedMetadataService.__init__)
    assert hints["api"] is ExtendedMetadataApi, (
        "ExtendedMetadataService.__init__'s api param must be typed ExtendedMetadataApi"
    )
    assert hints["api"] is not HttpxExtendedMetadataApi, (
        "ExtendedMetadataService.__init__'s api param must not be the concrete adapter"
    )


def test_user_service_binds_the_api_param_to_user_api_specifically() -> None:
    """Non-generalized regression test for the Users domain's exact guarantee,
    sibling to the checks above: the api param is UserApi exactly, not just
    "some Protocol". No dedicated Resolver exists -- Users have no project
    concept and no semantic reference to resolve, following RoleService's
    zero-Resolver template."""
    from openproject_ce_mcp.app.adapters.httpx_user_api import HttpxUserApi
    from openproject_ce_mcp.app.ports.user_api import UserApi
    from openproject_ce_mcp.app.services.user_service import UserService

    hints = typing.get_type_hints(UserService.__init__)
    assert hints["api"] is UserApi, "UserService.__init__'s api param must be typed UserApi"
    assert hints["api"] is not HttpxUserApi, "UserService.__init__'s api param must not be the concrete adapter"


def test_group_service_binds_the_api_param_to_group_api_specifically() -> None:
    """Non-generalized regression test for the Groups domain's exact guarantee,
    sibling to the checks above: the api param is GroupApi exactly, not just
    "some Protocol". No dedicated Resolver exists -- Groups have no project
    concept and no semantic reference to resolve, following RoleService's/
    UserService's zero-Resolver template."""
    from openproject_ce_mcp.app.adapters.httpx_group_api import HttpxGroupApi
    from openproject_ce_mcp.app.ports.group_api import GroupApi
    from openproject_ce_mcp.app.services.group_service import GroupService

    hints = typing.get_type_hints(GroupService.__init__)
    assert hints["api"] is GroupApi, "GroupService.__init__'s api param must be typed GroupApi"
    assert hints["api"] is not HttpxGroupApi, "GroupService.__init__'s api param must not be the concrete adapter"


def test_status_priority_type_service_binds_the_api_param_to_status_priority_type_api_specifically() -> None:
    """Non-generalized regression test for the Statuses/Priorities/Types
    domain's exact guarantee, sibling to the checks above: the api param is
    StatusPriorityTypeApi exactly, not just "some Protocol". No dedicated
    Resolver exists for status_id/priority_id/type_id -- all three are always
    numeric values already validated by tools.py. `list_types`' optional
    `project` filter uses the pre-existing ProjectRefResolver seam instead
    (a request-shaping parameter, not a semantic reference needing a
    dedicated Resolver)."""
    from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
    from openproject_ce_mcp.app.ports.status_priority_type_api import StatusPriorityTypeApi
    from openproject_ce_mcp.app.services.status_priority_type_service import StatusPriorityTypeService

    hints = typing.get_type_hints(StatusPriorityTypeService.__init__)
    assert hints["api"] is StatusPriorityTypeApi, (
        "StatusPriorityTypeService.__init__'s api param must be typed StatusPriorityTypeApi"
    )
    assert hints["api"] is not HttpxStatusPriorityTypeApi, (
        "StatusPriorityTypeService.__init__'s api param must not be the concrete adapter"
    )


def test_query_metadata_service_binds_the_api_param_to_query_metadata_api_specifically() -> None:
    """Non-generalized regression test for the Query Metadata domain's exact
    guarantee, sibling to the checks above: the api param is
    QueryMetadataApi exactly, not just "some Protocol". No dedicated
    Resolver exists for filter/column/operator/sort_by/schema ids -- all are
    opaque strings, not semantic references needing lookup.
    `list_filter_instance_schemas`' optional `project` filter uses the
    pre-existing ProjectRefResolver seam instead (a request-shaping
    parameter, not a semantic reference needing a dedicated Resolver)."""
    from openproject_ce_mcp.app.adapters.httpx_query_metadata_api import HttpxQueryMetadataApi
    from openproject_ce_mcp.app.ports.query_metadata_api import QueryMetadataApi
    from openproject_ce_mcp.app.services.query_metadata_service import QueryMetadataService

    hints = typing.get_type_hints(QueryMetadataService.__init__)
    assert hints["api"] is QueryMetadataApi, "QueryMetadataService.__init__'s api param must be typed QueryMetadataApi"
    assert hints["api"] is not HttpxQueryMetadataApi, (
        "QueryMetadataService.__init__'s api param must not be the concrete adapter"
    )


def test_job_status_service_binds_the_api_param_to_job_status_api_specifically() -> None:
    """Non-generalized regression test for the Job Status domain's exact
    guarantee, sibling to the checks above: the api param is JobStatusApi
    exactly, not just "some Protocol". No dedicated Resolver: job_status_id
    is a plain numeric id already validated by tools.py, not a semantic
    reference needing lookup."""
    from openproject_ce_mcp.app.adapters.httpx_job_status_api import HttpxJobStatusApi
    from openproject_ce_mcp.app.ports.job_status_api import JobStatusApi
    from openproject_ce_mcp.app.services.job_status_service import JobStatusService

    hints = typing.get_type_hints(JobStatusService.__init__)
    assert hints["api"] is JobStatusApi, "JobStatusService.__init__'s api param must be typed JobStatusApi"
    assert hints["api"] is not HttpxJobStatusApi, (
        "JobStatusService.__init__'s api param must not be the concrete adapter"
    )


# Names that once lived in app/ports/project_api.py (HAL->model normalize_*
# translation functions and their private text/href helpers) before they moved
# to app/adapters/httpx_project_api.py, matching the Versions domain's
# convention. Kept as a literal list so this test independently pins the exact
# set that moved, in addition to (not instead of) a generic "normalize_*"
# prefix check below that also catches any *new* normalizer added to the port
# in the future under a name not in this historical list.
_FORMER_PROJECT_API_PORT_NORMALIZER_NAMES = {
    "normalize_project",
    "normalize_project_detail",
    "normalize_option_value",
    "normalize_project_field_schema",
    "normalize_project_phase_definition",
    "normalize_project_phase",
    "_trim_text",
    "_normalize_text",
    "_trim_text_with_meta",
    "_extract_formattable_text_with_meta",
    "_link_title",
    "_id_from_href",
    "_slug_from_href",
    "_delimit_user_content",
}


def test_project_api_port_defines_no_normalize_functions() -> None:
    """Positive proof that app/ports/project_api.py is narrow again: HAL->model
    mapping must live in HttpxProjectApi (the adapter), not the port. Checks
    module-level FunctionDef/AsyncFunctionDef nodes via AST (not a text/rg
    match) so the surviving module docstring and comments can freely mention
    these names without tripping the check."""
    path = APP / "ports" / "project_api.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    defined_names = {
        node.name for node in ast.iter_child_nodes(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    offenders = defined_names & _FORMER_PROJECT_API_PORT_NORMALIZER_NAMES
    assert not offenders, f"app/ports/project_api.py must not define {offenders} -- move to the adapter"
    new_normalizers = {name for name in defined_names if name.startswith("normalize_")}
    assert not new_normalizers, (
        f"app/ports/project_api.py must not define {new_normalizers} -- normalize_* HAL->model "
        "mapping belongs in HttpxProjectApi (the adapter), not the port"
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


# Added during the Statuses/Priorities/Types migration (16th domain),
# after a broader audit found FOUR real, silent hidden-field-masking gaps that
# no existing test caught: normalize_priority/normalize_notification/
# normalize_emoji_reaction never called _apply_hidden_fields at all, and
# normalize_file_link called it but "file_link" had no entry in config.py's
# HIDE_FIELD_ENV_BY_ENTITY map (a permanent, silent no-op). Every
# tests/unit/test_hidden_fields.py test constructs Settings directly with
# hidden_fields={...} pre-populated, bypassing HIDE_FIELD_ENV_BY_ENTITY
# entirely -- none of them would have caught a missing map entry. This test
# closes that structural gap: it extracts every literal entity string passed
# to an _apply_hidden_fields/apply_hidden_fields call (in client.py's still-flat
# normalize_* methods, and in every migrated domain's Service), and asserts
# each one has a HIDE_FIELD_ENV_BY_ENTITY entry -- so a future domain that
# repeats this exact mistake fails a test immediately instead of shipping a
# silently-broken OPENPROJECT_HIDE_<X>_FIELDS env var.
def _hidden_field_entity_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    entities: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # client.py's call sites are all self._apply_hidden_fields(...) (leading
        # underscore); app/services/*.py's are hidden_fields.apply_hidden_fields(...)
        # (no underscore) -- both attribute names must be matched, or this check
        # silently contributes nothing from client.py (confirmed during this
        # migration's own self-audit: the underscore-less version alone returns an
        # EMPTY set for client.py, despite the module docstring above claiming
        # client.py's still-flat normalize_* methods are covered).
        is_apply_hidden_fields_call = (
            isinstance(func, ast.Attribute) and func.attr in ("apply_hidden_fields", "_apply_hidden_fields")
        ) or (isinstance(func, ast.Name) and func.id in ("apply_hidden_fields", "_apply_hidden_fields"))
        if not is_apply_hidden_fields_call or not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            entities.add(first_arg.value)
    return entities


def test_every_apply_hidden_fields_entity_is_registered_in_config() -> None:
    from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY

    entities: set[str] = set()
    entities |= _hidden_field_entity_literals(SRC / "client.py")
    for path in APP.rglob("*.py"):
        entities |= _hidden_field_entity_literals(path)

    unregistered = sorted(entities - HIDE_FIELD_ENV_BY_ENTITY.keys())
    assert unregistered == [], (
        f"Entities passed to apply_hidden_fields/_apply_hidden_fields with no "
        f"HIDE_FIELD_ENV_BY_ENTITY entry (their OPENPROJECT_HIDE_<X>_FIELDS env "
        f"var can never work): {unregistered}"
    )


def test_work_package_resolver_methods_structurally_satisfy_the_seam_protocols() -> None:
    """WorkPackageResolver.resolve_id/.project_link_allowed are the
    concrete methods future migrations bind `WorkPackageIdResolver`/
    `WorkPackageProjectAllowedCheck` seam parameters to (bound methods
    `self._work_package_resolver.resolve_id`/`.project_link_allowed`,
    structural typing, no wrapper class -- mirrors how `ProjectRefResolver`
    is bound to `self._get_project_payload`). No Service consumes these seams
    yet (declared for future use only), so there is no existing "api param
    typed as the Protocol" call site to check statically the way
    test_project_service_and_resolver_bind_the_api_param_to_project_api_specifically
    does; instead this proves structural compatibility directly by comparing
    each bound method's runtime signature (param names, kinds, and defaults)
    against the corresponding Protocol's `__call__` signature.
    """
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver

    def _bound_params(func: object) -> list[inspect.Parameter]:
        return [p for p in inspect.signature(func).parameters.values() if p.name != "self"]

    def _comparable(p: inspect.Parameter) -> tuple[object, ...]:
        # mypy's own structural-typing rule for Protocol.__call__ technically
        # excludes positional-or-keyword param NAMES (satisfied by any callable
        # with a compatible positional signature, regardless of that param's
        # internal name). This codebase's convention is stricter, though (see
        # ProjectResolver.resolve_id/ProjectRefResolver.__call__, both named
        # `project_ref`): a resolver method's param name matches its seam
        # Protocol's exactly, so a keyword call works identically through
        # either the bound method or the Protocol-typed seam -- a real bug a
        # Codex review caught in an earlier version of WorkPackageResolver
        # (its `resolve_id` param was named `ref`, not `work_package_ref` as
        # in `WorkPackageIdResolver`, silently breaking a hypothetical keyword
        # call). Comparing the name here, not just kind/default, enforces the
        # convention rather than just mypy's more permissive minimum.
        return (p.name, p.kind, p.default)

    resolve_id_params = _bound_params(WorkPackageResolver.resolve_id)
    protocol_params = _bound_params(WorkPackageIdResolver.__call__)
    assert [_comparable(p) for p in resolve_id_params] == [_comparable(p) for p in protocol_params], (
        "WorkPackageResolver.resolve_id no longer structurally satisfies WorkPackageIdResolver"
    )

    allowed_params = _bound_params(WorkPackageResolver.project_link_allowed)
    protocol_params = _bound_params(WorkPackageProjectAllowedCheck.__call__)
    assert [_comparable(p) for p in allowed_params] == [_comparable(p) for p in protocol_params], (
        "WorkPackageResolver.project_link_allowed no longer structurally satisfies WorkPackageProjectAllowedCheck"
    )


def test_file_link_service_binds_its_three_dependencies_to_the_right_protocols() -> None:
    """FileLinkService has THREE Protocol dependencies, not the usual one --
    FileLinkApi (its own domain Port), WorkPackageLookupApi (a second domain
    Port, used directly for delete()'s raw work-package-payload fetch rather
    than through the resolver), and WorkPackageIdResolver (used by
    list_for_work_package()'s anchor resolution). All three
    must be pinned to their Protocol, not the concrete adapter/resolver
    method, or a caller could accidentally depend on adapter-specific
    behavior that isn't part of the Protocol contract."""
    from openproject_ce_mcp.app.adapters.httpx_file_link_api import HttpxFileLinkApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.file_link_api import FileLinkApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.file_link_service import FileLinkService

    hints = typing.get_type_hints(FileLinkService.__init__)
    assert hints["api"] is FileLinkApi, "FileLinkService.__init__'s api param must be typed FileLinkApi"
    assert hints["api"] is not HttpxFileLinkApi, "FileLinkService.__init__'s api param must not be the concrete adapter"

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "FileLinkService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "FileLinkService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "FileLinkService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "FileLinkService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )


def test_watcher_service_binds_the_api_and_resolver_params_to_the_right_protocols() -> None:
    """Watchers is the second domain to consume the
    WorkPackageIdResolver seam -- a cleaner fit than File Links had, since
    add()/remove() resolve a genuine caller-supplied work-package reference
    (via WorkPackageIdResolver(ref, write=True)) rather than an
    already-known numeric id. Only two Protocol dependencies here (WatcherApi,
    WorkPackageIdResolver) -- no second WorkPackageLookupApi dependency,
    since neither add() nor remove() needs a raw work-package payload fetch
    outside the resolver."""
    from openproject_ce_mcp.app.adapters.httpx_watcher_api import HttpxWatcherApi
    from openproject_ce_mcp.app.ports.watcher_api import WatcherApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.watcher_service import WatcherService

    hints = typing.get_type_hints(WatcherService.__init__)
    assert hints["api"] is WatcherApi, "WatcherService.__init__'s api param must be typed WatcherApi"
    assert hints["api"] is not HttpxWatcherApi, "WatcherService.__init__'s api param must not be the concrete adapter"

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "WatcherService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "WatcherService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )


def test_emoji_reaction_service_binds_its_three_dependencies_to_the_right_protocols() -> None:
    """Emoji Reactions is the third domain to consume these seams,
    matching File Links' three-Protocol shape (not Watchers' two): toggle()'s
    work-package id is already a concrete int derived from the activity's own
    link (not a caller-supplied reference), so it uses WorkPackageLookupApi
    directly rather than WorkPackageIdResolver/WorkPackageProjectAllowedCheck
    -- the same reasoning as FileLinkService.delete()."""
    from openproject_ce_mcp.app.adapters.httpx_emoji_reaction_api import HttpxEmojiReactionApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.emoji_reaction_api import EmojiReactionApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.emoji_reaction_service import EmojiReactionService

    hints = typing.get_type_hints(EmojiReactionService.__init__)
    assert hints["api"] is EmojiReactionApi, "EmojiReactionService.__init__'s api param must be typed EmojiReactionApi"
    assert hints["api"] is not HttpxEmojiReactionApi, (
        "EmojiReactionService.__init__'s api param must not be the concrete adapter"
    )

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "EmojiReactionService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "EmojiReactionService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "EmojiReactionService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "EmojiReactionService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )


def test_reminder_service_binds_its_four_dependencies_to_the_right_protocols() -> None:
    """Reminders is the fourth domain to consume these seams
    and the widest seam surface of any domain in this migration: list()
    fans out across N different work packages (one per reminder, not a
    single anchor), so it needs WorkPackageProjectAllowedCheck +
    WorkPackageAllowedContext (not used by File Links/Watchers/Emoji
    Reactions, whose list() methods each scope to one already-resolved
    anchor); create() resolves a genuine caller-supplied reference via
    WorkPackageIdResolver(ref, write=True) (Watchers' shape); update()/
    delete() derive an already-concrete work-package id from the reminder's
    own remindable link via WorkPackageLookupApi directly (Emoji Reactions'/
    File Links' shape). All four Protocol dependencies must be pinned."""
    from openproject_ce_mcp.app.adapters.httpx_reminder_api import HttpxReminderApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.reminder_api import ReminderApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.reminder_service import ReminderService

    hints = typing.get_type_hints(ReminderService.__init__)
    assert hints["api"] is ReminderApi, "ReminderService.__init__'s api param must be typed ReminderApi"
    assert hints["api"] is not HttpxReminderApi, "ReminderService.__init__'s api param must not be the concrete adapter"

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "ReminderService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "ReminderService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "ReminderService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "ReminderService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )

    assert hints["work_package_project_allowed"] is WorkPackageProjectAllowedCheck, (
        "ReminderService.__init__'s work_package_project_allowed param must be typed WorkPackageProjectAllowedCheck"
    )
    assert hints["work_package_project_allowed"] is not WorkPackageResolver, (
        "ReminderService.__init__'s work_package_project_allowed param must not be the concrete resolver class"
    )


def test_notification_service_binds_the_api_param_to_notification_api_specifically() -> None:
    """Notifications mirrors Reminders' list()
    shape exactly: list_all() fans out across N different work packages (one
    per notification with a work-package resource link but no project link
    of its own), so it needs WorkPackageProjectAllowedCheck, not a full
    WorkPackageIdResolver (Notifications has no create/update/delete method
    that resolves a caller-supplied work-package reference)."""
    from openproject_ce_mcp.app.adapters.httpx_notification_api import HttpxNotificationApi
    from openproject_ce_mcp.app.ports.notification_api import NotificationApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageProjectAllowedCheck
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.notification_service import NotificationService

    hints = typing.get_type_hints(NotificationService.__init__)
    assert hints["api"] is NotificationApi, "NotificationService.__init__'s api param must be typed NotificationApi"
    assert hints["api"] is not HttpxNotificationApi, (
        "NotificationService.__init__'s api param must not be the concrete adapter"
    )

    assert hints["work_package_project_allowed"] is WorkPackageProjectAllowedCheck, (
        "NotificationService.__init__'s work_package_project_allowed param must be typed WorkPackageProjectAllowedCheck"
    )
    assert hints["work_package_project_allowed"] is not WorkPackageResolver, (
        "NotificationService.__init__'s work_package_project_allowed param must not be the concrete resolver class"
    )


def test_relation_service_binds_its_dependencies_to_the_right_protocols() -> None:
    """Relations mirrors Reminders' widest seam surface: list_all()/
    list_for_work_package() each check TWO work packages per relation (from
    AND to, not a single anchor) via WorkPackageProjectAllowedCheck +
    WorkPackageAllowedContext; create() resolves a genuine caller-supplied
    target reference via WorkPackageIdResolver(ref, write=True); update()/
    delete() derive an already-concrete work package from the relation's own
    from link via WorkPackageLookupApi directly. All four Protocol
    dependencies must be pinned."""
    from openproject_ce_mcp.app.adapters.httpx_relation_api import HttpxRelationApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.relation_api import RelationApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.relation_service import RelationService

    hints = typing.get_type_hints(RelationService.__init__)
    assert hints["api"] is RelationApi, "RelationService.__init__'s api param must be typed RelationApi"
    assert hints["api"] is not HttpxRelationApi, "RelationService.__init__'s api param must not be the concrete adapter"

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "RelationService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "RelationService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "RelationService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "RelationService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )

    assert hints["work_package_project_allowed"] is WorkPackageProjectAllowedCheck, (
        "RelationService.__init__'s work_package_project_allowed param must be typed WorkPackageProjectAllowedCheck"
    )
    assert hints["work_package_project_allowed"] is not WorkPackageResolver, (
        "RelationService.__init__'s work_package_project_allowed param must not be the concrete resolver class"
    )


def test_time_entry_service_binds_its_dependencies_to_the_right_protocols() -> None:
    """Unlike Relations, no Time Entries path dereferences an already-known
    work-package link the way Relations' from/to sides do -- list_all() only
    resolves a caller-supplied work-package reference to a numeric id
    (WorkPackageIdResolver), and create()/update()/delete() check the time
    entry's own or its work package's project link directly via
    WorkPackageLookupApi/ProjectRefResolver, never via
    WorkPackageProjectAllowedCheck. All 8 Protocol dependencies must be
    pinned."""
    from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
    from openproject_ce_mcp.app.adapters.httpx_time_entry_api import HttpxTimeEntryApi
    from openproject_ce_mcp.app.adapters.httpx_user_api import HttpxUserApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.current_user import CurrentUserLookup
    from openproject_ce_mcp.app.ports.principal_ref import PrincipalRefResolver
    from openproject_ce_mcp.app.ports.project_api import ProjectApi
    from openproject_ce_mcp.app.ports.project_ref import ProjectIdResolver, ProjectRefResolver
    from openproject_ce_mcp.app.ports.time_entry_api import TimeEntryApi
    from openproject_ce_mcp.app.ports.user_api import UserApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.project_resolver import ProjectResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.time_entry_service import TimeEntryService

    hints = typing.get_type_hints(TimeEntryService.__init__)

    assert hints["api"] is TimeEntryApi, "TimeEntryService.__init__'s api param must be typed TimeEntryApi"
    assert hints["api"] is not HttpxTimeEntryApi, (
        "TimeEntryService.__init__'s api param must not be the concrete adapter"
    )

    assert hints["project_api"] is ProjectApi, "TimeEntryService.__init__'s project_api param must be typed ProjectApi"
    assert hints["project_api"] is not HttpxProjectApi, (
        "TimeEntryService.__init__'s project_api param must not be the concrete adapter"
    )

    assert hints["user_api"] is UserApi, "TimeEntryService.__init__'s user_api param must be typed UserApi"
    assert hints["user_api"] is not HttpxUserApi, (
        "TimeEntryService.__init__'s user_api param must not be the concrete adapter"
    )

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "TimeEntryService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "TimeEntryService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "TimeEntryService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "TimeEntryService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )

    assert hints["resolve_project_ref"] is ProjectRefResolver, (
        "TimeEntryService.__init__'s resolve_project_ref param must be typed ProjectRefResolver"
    )
    assert hints["resolve_project_ref"] is not ProjectResolver, (
        "TimeEntryService.__init__'s resolve_project_ref param must not be the concrete resolver class"
    )

    assert hints["resolve_project_id"] is ProjectIdResolver, (
        "TimeEntryService.__init__'s resolve_project_id param must be typed ProjectIdResolver"
    )
    assert hints["resolve_project_id"] is not ProjectResolver, (
        "TimeEntryService.__init__'s resolve_project_id param must not be the concrete resolver class"
    )

    assert hints["resolve_principal_id"] is PrincipalRefResolver, (
        "TimeEntryService.__init__'s resolve_principal_id param must be typed PrincipalRefResolver"
    )

    assert hints["get_current_user"] is CurrentUserLookup, (
        "TimeEntryService.__init__'s get_current_user param must be typed CurrentUserLookup"
    )


def test_attachment_service_binds_its_three_dependencies_to_the_right_protocols() -> None:
    """Attachments follows File Links' three-Protocol shape: its own Port,
    WorkPackageLookupApi (get()/delete()'s container-derived id), and
    WorkPackageIdResolver (list()'s anchor, create()'s caller-supplied
    reference)."""
    from openproject_ce_mcp.app.adapters.httpx_attachment_api import HttpxAttachmentApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
    from openproject_ce_mcp.app.ports.attachment_api import AttachmentApi
    from openproject_ce_mcp.app.ports.work_package_lookup_api import WorkPackageLookupApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.attachment_service import AttachmentService

    hints = typing.get_type_hints(AttachmentService.__init__)
    assert hints["api"] is AttachmentApi, "AttachmentService.__init__'s api param must be typed AttachmentApi"
    assert hints["api"] is not HttpxAttachmentApi, (
        "AttachmentService.__init__'s api param must not be the concrete adapter"
    )

    assert hints["work_package_lookup_api"] is WorkPackageLookupApi, (
        "AttachmentService.__init__'s work_package_lookup_api param must be typed WorkPackageLookupApi"
    )
    assert hints["work_package_lookup_api"] is not HttpxWorkPackageLookupApi, (
        "AttachmentService.__init__'s work_package_lookup_api param must not be the concrete adapter"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "AttachmentService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "AttachmentService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )


def test_activity_service_binds_the_api_param_to_activity_api_specifically() -> None:
    """Activities is the simplest work-package-reference-dependent domain
    this session: no WorkPackageLookupApi at all, only its own Port plus
    WorkPackageIdResolver -- the caller-supplied work_package_id is the only
    input, nothing here derives an id from another resource's own link."""
    from openproject_ce_mcp.app.adapters.httpx_activity_api import HttpxActivityApi
    from openproject_ce_mcp.app.ports.activity_api import ActivityApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.activity_service import ActivityService

    hints = typing.get_type_hints(ActivityService.__init__)
    assert hints["api"] is ActivityApi, "ActivityService.__init__'s api param must be typed ActivityApi"
    assert hints["api"] is not HttpxActivityApi, "ActivityService.__init__'s api param must not be the concrete adapter"

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "ActivityService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "ActivityService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )


def test_work_package_service_binds_the_api_param_to_work_package_api_specifically() -> None:
    """Work Packages' Service (now covering both the READ slice and the
    write-path migration, OPM-286's second sub-step) depends on its own
    WorkPackageApi Port (not the pre-existing, deliberately minimal
    WorkPackageLookupApi that 8 other domains' resolvers use), on the
    existing WorkPackageProjectAllowedCheck seam for hierarchy-allowlist
    filtering, and -- new for the write path -- WorkPackageIdResolver (parent
    resolution), AssigneeRefResolver (deliberately narrower than
    PrincipalRefResolver: "me"/numeric-only), SprintIdResolver
    (project-required, unlike VersionIdResolver's optional project),
    StatusPriorityTypeApi (the auto-derivation's is_closed lookup, injected
    directly rather than via StatusPriorityTypeService since that would
    incorrectly gate on read-enablement), and ActivityApi (comment
    normalization, reusing the already-migrated Activities Port instead of
    duplicating it) -- none of these may bind to their concrete
    adapter/resolver class instead of the Protocol."""
    from openproject_ce_mcp.app.adapters.httpx_activity_api import HttpxActivityApi
    from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
    from openproject_ce_mcp.app.adapters.httpx_work_package_api import HttpxWorkPackageApi
    from openproject_ce_mcp.app.ports.activity_api import ActivityApi
    from openproject_ce_mcp.app.ports.assignee_ref import AssigneeRefResolver
    from openproject_ce_mcp.app.ports.principal_ref import PrincipalRefResolver
    from openproject_ce_mcp.app.ports.sprint_ref import SprintIdResolver
    from openproject_ce_mcp.app.ports.status_priority_type_api import StatusPriorityTypeApi
    from openproject_ce_mcp.app.ports.version_ref import VersionIdResolver
    from openproject_ce_mcp.app.ports.work_package_api import WorkPackageApi
    from openproject_ce_mcp.app.ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
    from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
    from openproject_ce_mcp.app.services.work_package_service import WorkPackageService

    hints = typing.get_type_hints(WorkPackageService.__init__)
    assert hints["api"] is WorkPackageApi, "WorkPackageService.__init__'s api param must be typed WorkPackageApi"
    assert hints["api"] is not HttpxWorkPackageApi, (
        "WorkPackageService.__init__'s api param must not be the concrete adapter"
    )

    assert hints["work_package_project_allowed"] is WorkPackageProjectAllowedCheck, (
        "WorkPackageService.__init__'s work_package_project_allowed param must be typed WorkPackageProjectAllowedCheck"
    )
    assert hints["work_package_project_allowed"] is not WorkPackageResolver, (
        "WorkPackageService.__init__'s work_package_project_allowed param must not be the concrete resolver class"
    )

    assert hints["resolve_work_package_id"] is WorkPackageIdResolver, (
        "WorkPackageService.__init__'s resolve_work_package_id param must be typed WorkPackageIdResolver"
    )
    assert hints["resolve_work_package_id"] is not WorkPackageResolver, (
        "WorkPackageService.__init__'s resolve_work_package_id param must not be the concrete resolver class"
    )

    assert hints["resolve_assignee_id"] is AssigneeRefResolver, (
        "WorkPackageService.__init__'s resolve_assignee_id param must be typed AssigneeRefResolver"
    )
    assert hints["resolve_assignee_id"] is not PrincipalRefResolver, (
        "WorkPackageService.__init__'s resolve_assignee_id param must not be PrincipalRefResolver -- assignee "
        "resolution is deliberately narrower (me/numeric-only), reusing PrincipalRefResolver here would silently "
        "broaden what create/update accept for assignee"
    )

    assert hints["resolve_sprint_id"] is SprintIdResolver, (
        "WorkPackageService.__init__'s resolve_sprint_id param must be typed SprintIdResolver"
    )
    assert hints["resolve_sprint_id"] is not VersionIdResolver, (
        "WorkPackageService.__init__'s resolve_sprint_id param must not be VersionIdResolver -- sprint resolution "
        "requires a project (VersionIdResolver's project param is optional)"
    )

    assert hints["status_api"] is StatusPriorityTypeApi, (
        "WorkPackageService.__init__'s status_api param must be typed StatusPriorityTypeApi"
    )
    assert hints["status_api"] is not HttpxStatusPriorityTypeApi, (
        "WorkPackageService.__init__'s status_api param must not be the concrete adapter"
    )

    assert hints["activity_api"] is ActivityApi, (
        "WorkPackageService.__init__'s activity_api param must be typed ActivityApi"
    )
    assert hints["activity_api"] is not HttpxActivityApi, (
        "WorkPackageService.__init__'s activity_api param must not be the concrete adapter"
    )
