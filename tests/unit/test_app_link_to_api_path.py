"""A link's href becomes a request path only when it names the instance's own API.

Every adapter that follows an href of a server response (an allowed-values link, a memberships link, a collection
link) reads it through `link_to_api_path`, so a foreign or manipulated href is refused before any request is made
and a dot segment cannot step out of `/api/v3`.
"""

from __future__ import annotations

from typing import Any

import pytest

from openproject_ce_mcp.app.adapters._text import link_to_api_path
from openproject_ce_mcp.app.adapters.httpx_membership_api import HttpxMembershipApi
from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
from openproject_ce_mcp.app.adapters.httpx_time_entry_api import HttpxTimeEntryApi
from openproject_ce_mcp.app.adapters.httpx_work_package_api import HttpxWorkPackageApi
from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
from openproject_ce_mcp.app.errors import OpenProjectServerError

BASE = "https://op.example.com"
PREFIX = "/api/v3/"

_ACCEPTED = [
    ("/api/v3/projects/7/available_parent_projects", "projects/7/available_parent_projects"),
    (f"{BASE}/api/v3/projects/7", "projects/7"),
    ("https://OP.example.com:443/api/v3/projects/7", "projects/7"),
    ("projects/7", "projects/7"),
    ("/projects/7", "projects/7"),
    ("/api/v3/projects?offset=1&pageSize=100", "projects?offset=1&pageSize=100"),
    (
        '/api/v3/projects?filters=[{"project":{"operator":"=","values":["7"]}}]',
        'projects?filters=[{"project":{"operator":"=","values":["7"]}}]',
    ),
    ("/api/v3/projects?filters=%5B%5D", "projects?filters=%5B%5D"),
    ('/api/v3/projects?filters=[{"name": "a b"}]', 'projects?filters=[{"name": "a b"}]'),
    ("/api/v3/a.b/c..d", "a.b/c..d"),
    ("?page=2", "?page=2"),
]
_FOREIGN = [
    "https://evil.example/api/v3/projects/7",
    "http://op.example.com/api/v3/projects/7",
    "https://op.example.com:8443/api/v3/projects/7",
    "https://op.example.com.evil.example/api/v3/projects/7",
    "https://user:pw@op.example.com/api/v3/projects/7",
    "https://op.example.com@evil.example/api/v3/projects/7",
    "//op.example.com/api/v3/projects/7",
    "//evil.example/api/v3/projects/7",
    "https:\\\\evil.example\\api\\v3\\projects",
    "mailto:a@op.example.com",
    "projects:1",
]
_TRAVERSAL = [
    "/api/v3/../../admin/users",
    "/api/v3/projects/../../admin",
    f"{BASE}/api/v3/../admin",
    "/api/v3/%2e%2e/admin",
    "/api/v3/%2E%2E/%2e%2e/admin",
    "/api/v3/..%2fadmin",
    "/api/v3/projects/%2e",
    "/api/v3/..\\admin",
    "/api/v3/./projects",
    "../../admin",
]
_ABSOLUTE_INSIDE = [
    "/api/v3/https://evil.example/x",
    "/https://evil.example/x",
    "https://evil.example/x",
    "/api/v3/projects:1",
]
_CONTROL = ["/api/v3/projects\n/7", "/api/v3/\tprojects", "/api/v3/projects\r", "\x00/api/v3/projects"]


@pytest.mark.parametrize(("href", "expected"), _ACCEPTED)
def test_an_href_of_the_instance_becomes_an_api_relative_path_with_its_query(href: str, expected: str) -> None:
    assert link_to_api_path(href, base_url=BASE, api_prefix=PREFIX) == expected


@pytest.mark.parametrize("href", _FOREIGN)
def test_an_href_on_another_origin_is_refused(href: str) -> None:
    with pytest.raises(OpenProjectServerError, match="unexpected link host"):
        link_to_api_path(href, base_url=BASE, api_prefix=PREFIX)


@pytest.mark.parametrize("href", [*_TRAVERSAL, *_CONTROL, *_ABSOLUTE_INSIDE[:2], *_ABSOLUTE_INSIDE[3:]])
def test_an_href_that_steps_out_of_the_api_path_or_hides_a_control_character_is_refused(href: str) -> None:
    with pytest.raises(OpenProjectServerError, match="unexpected link path"):
        link_to_api_path(href, base_url=BASE, api_prefix=PREFIX)


def test_an_instance_under_a_root_path_reads_its_own_prefix() -> None:
    base_url, prefix = "https://op.example.com/OP", "/OP/api/v3/"

    assert link_to_api_path("/OP/api/v3/projects/7", base_url=base_url, api_prefix=prefix) == "projects/7"
    assert link_to_api_path(f"{base_url}/api/v3/projects/7", base_url=base_url, api_prefix=prefix) == "projects/7"


def test_an_href_the_parser_cannot_read_is_refused() -> None:
    with pytest.raises(OpenProjectServerError, match="unexpected link path"):
        link_to_api_path("http://[::1/api/v3/projects", base_url=BASE, api_prefix=PREFIX)


class _NoRequestTransport:
    async def get_json(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the transport must not be reached")


_ADAPTERS = [
    HttpxProjectApi,
    HttpxWorkPackageApi,
    HttpxWorkPackageLookupApi,
    HttpxTimeEntryApi,
    HttpxMembershipApi,
]


@pytest.mark.parametrize("adapter_class", _ADAPTERS, ids=lambda cls: cls.__name__)
@pytest.mark.parametrize("href", [*_FOREIGN, *_TRAVERSAL, *_CONTROL, *_ABSOLUTE_INSIDE])
def test_every_adapter_that_follows_an_href_refuses_what_the_shared_function_refuses(
    adapter_class: type, href: str
) -> None:
    adapter = adapter_class(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX)

    with pytest.raises(OpenProjectServerError):
        adapter._link_to_api_path(href)


@pytest.mark.parametrize("href", ["https://evil.example/api/v3/projects/7", "/api/v3/../admin"])
@pytest.mark.asyncio
async def test_the_lookup_and_the_memberships_adapter_refuse_before_any_request(href: str) -> None:
    with pytest.raises(OpenProjectServerError):
        await HttpxWorkPackageLookupApi(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX).get_by_href(href)
    with pytest.raises(OpenProjectServerError):
        await HttpxMembershipApi(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX).list_for_project(
            href, offset=1, page_size=10
        )


_FOREIGN_LINK = {"_links": {"allowedValues": {"href": "https://evil.example/api/v3/principals"}}}


@pytest.mark.asyncio
async def test_the_project_adapter_refuses_a_foreign_allowed_values_link_before_any_request() -> None:
    adapter = HttpxProjectApi(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX)

    with pytest.raises(OpenProjectServerError, match="unexpected link host"):
        await adapter.list_available_parent_projects(5, schema={"parent": _FOREIGN_LINK})
    with pytest.raises(OpenProjectServerError, match="unexpected link host"):
        await adapter._with_custom_field_options({"customField3": _FOREIGN_LINK})


@pytest.mark.asyncio
async def test_the_work_package_adapter_refuses_a_foreign_allowed_values_link_before_any_request() -> None:
    adapter = HttpxWorkPackageApi(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX)

    with pytest.raises(OpenProjectServerError, match="unexpected link host"):
        await adapter._resolve_linked_allowed_values({"assignee": _FOREIGN_LINK}, cache=None)


@pytest.mark.asyncio
async def test_the_time_entry_adapter_refuses_a_foreign_link_before_any_request() -> None:
    adapter = HttpxTimeEntryApi(_NoRequestTransport(), base_url=BASE, api_prefix=PREFIX)

    with pytest.raises(OpenProjectServerError, match="unexpected link host"):
        await adapter.fetch_page_by_href("https://evil.example/api/v3/time_entries", offset=1, page_size=10)
