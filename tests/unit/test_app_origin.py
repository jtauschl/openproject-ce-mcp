from __future__ import annotations

import pytest

from openproject_ce_mcp.app.origin import api_prefix_from_url, root_path_from_url, strict_origin


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://op.example.com", ("https", "op.example.com", 443)),
        ("https://OP.Example.com:443/x", ("https", "op.example.com", 443)),
        ("HTTP://op.example.com", ("http", "op.example.com", 80)),
        ("https://op.example.com:8443", ("https", "op.example.com", 8443)),
        ("https://[::1]:23/x", ("https", "::1", 23)),
    ],
)
def test_strict_origin_normalizes_equivalent_spellings(url: str, expected: tuple[str, str, int]) -> None:
    assert strict_origin(url) == expected


def test_strict_origin_keeps_ipv6_hosts_and_ports_apart() -> None:
    assert strict_origin("https://[::1]:23") != strict_origin("https://[::1:23]")


@pytest.mark.parametrize(
    "url",
    [
        "https://user@op.example.com",
        "https://user:pw@op.example.com",
        "https://op.example.com:abc",
        "https://op.example.com:99999",
        "https://[::1",
        "//op.example.com/api/v3",
        "/api/v3/projects/7",
        "ftp://op.example.com",
        "https://",
    ],
)
def test_strict_origin_never_matches_what_it_cannot_read_unambiguously(url: str) -> None:
    assert strict_origin(url) is None


@pytest.mark.parametrize(
    ("base_url", "root", "api_prefix"),
    [
        ("https://op.example.com", "/", "/api/v3/"),
        ("https://op.example.com/openproject", "/openproject/", "/openproject/api/v3/"),
        ("https://op.example.com/openproject/", "/openproject/", "/openproject/api/v3/"),
    ],
)
def test_root_path_and_api_prefix_follow_the_base_url(base_url: str, root: str, api_prefix: str) -> None:
    assert root_path_from_url(base_url) == root
    assert api_prefix_from_url(base_url) == api_prefix
