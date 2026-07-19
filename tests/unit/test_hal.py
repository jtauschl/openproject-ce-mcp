from __future__ import annotations

from openproject_ce_mcp.hal import normalize_links


def test_normalize_links_replaces_explicit_null_at_top_level() -> None:
    payload = {"id": 1, "_links": None}
    assert normalize_links(payload) == {"id": 1, "_links": {}}


def test_normalize_links_leaves_absent_links_absent() -> None:
    # Must NOT introduce a `_links` key that wasn't there -- the existing
    # `payload.get("_links", {})` absent-key default already handles this
    # case correctly; only an explicit null needs fixing.
    payload = {"id": 1}
    assert normalize_links(payload) == {"id": 1}


def test_normalize_links_leaves_populated_links_untouched() -> None:
    payload = {"id": 1, "_links": {"project": {"title": "Demo"}}}
    result = normalize_links(payload)
    assert result["_links"] == {"project": {"title": "Demo"}}


def test_normalize_links_recurses_into_nested_dicts_and_lists() -> None:
    payload = {
        "_links": None,
        "_embedded": {
            "elements": [
                {"id": 1, "_links": None},
                {"id": 2, "_links": {"project": {"title": "Demo"}}},
                {"id": 3},
            ]
        },
    }
    result = normalize_links(payload)
    assert result["_links"] == {}
    elements = result["_embedded"]["elements"]
    assert elements[0]["_links"] == {}
    assert elements[1]["_links"] == {"project": {"title": "Demo"}}
    assert "_links" not in elements[2]


def test_normalize_links_leaves_unrelated_null_fields_alone() -> None:
    payload = {"id": 1, "description": None, "_links": None}
    result = normalize_links(payload)
    assert result["description"] is None
    assert result["_links"] == {}
