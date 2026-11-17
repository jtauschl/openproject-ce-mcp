"""Normalizers read the keys their representer renders and no alternative the server never sends.

Each case names the representer fact it rests on. The rendered key alone must map, and the key only an older client
guessed must not.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from openproject_ce_mcp.app.adapters.httpx_board_api import normalize_board
from openproject_ce_mcp.app.adapters.httpx_document_api import normalize_document
from openproject_ce_mcp.app.adapters.httpx_extended_metadata_api import normalize_help_text
from openproject_ce_mcp.app.adapters.httpx_group_api import normalize_group
from openproject_ce_mcp.app.adapters.httpx_news_api import normalize_news
from openproject_ce_mcp.app.adapters.httpx_notification_api import normalize_notification
from openproject_ce_mcp.app.adapters.httpx_query_metadata_api import normalize_query_filter

BASE_URL = "https://op.example.com"
_LINK = {"href": "/api/v3/x"}

# (normalizer, minimal payload, link rels the representer renders when the user may update)
_UPDATE_CASES: list[tuple[str, Callable[[dict[str, Any]], Any], dict[str, Any], tuple[str, ...]]] = [
    # group_representer.rb and news_representer.rb: `link :updateImmediately` only, 16.0 to 17.9.
    ("group", normalize_group, {"id": 1, "name": "G"}, ("updateImmediately",)),
    ("news", normalize_news, {"id": 1, "title": "N"}, ("updateImmediately",)),
    # document_representer.rb: `link :update` from 17.0 (16.0 to 16.6 render no update link at all).
    ("document", normalize_document, {"id": 1, "title": "D"}, ("update",)),
    # grid_representer.rb: both `link :updateImmediately` and `link :update`.
    ("board", normalize_board, {"id": 1, "name": "B"}, ("update", "updateImmediately")),
]


@pytest.mark.parametrize(("name", "normalize", "payload", "rendered"), _UPDATE_CASES, ids=[c[0] for c in _UPDATE_CASES])
def test_can_update_follows_the_rel_the_representer_renders(
    name: str, normalize: Callable[[dict[str, Any]], Any], payload: dict[str, Any], rendered: tuple[str, ...]
) -> None:
    for rel in rendered:
        assert normalize({**payload, "_links": {rel: _LINK}}).can_update is True, rel

    for rel in {"update", "updateImmediately"} - set(rendered):
        assert normalize({**payload, "_links": {rel: _LINK}}).can_update is False, rel

    assert normalize({**payload, "_links": {}}).can_update is False


def test_a_notification_is_read_when_read_ian_says_so_and_a_read_key_is_ignored() -> None:
    # notification_representer.rb renders `property :read_ian, as: :readIAN` and no `read`.
    assert normalize_notification({"id": 1, "readIAN": True}).read is True
    assert normalize_notification({"id": 1, "readIAN": False}).read is False
    assert normalize_notification({"id": 1, "read": True}).read is False


def test_a_help_text_attribute_is_the_attribute_key_and_an_attribute_name_key_is_ignored() -> None:
    # help_text_representer.rb: `property :attribute_name, as: :attribute`.
    assert normalize_help_text({"id": 1, "attribute": "subject"}).attribute_name == "subject"
    assert normalize_help_text({"id": 1, "attributeName": "subject"}).attribute_name is None


def test_a_query_filter_is_named_by_its_self_title_and_a_name_key_is_ignored() -> None:
    # query_filter_representer.rb: the human name is the title of `self`; no `name` property is rendered.
    named = {"id": "assignee", "_links": {"self": {"href": "/api/v3/queries/filters/assignee", "title": "Assignee"}}}

    assert normalize_query_filter(named, base_url=BASE_URL, origin=BASE_URL).name == "Assignee"
    assert normalize_query_filter({**named, "name": "Phantom"}, base_url=BASE_URL, origin=BASE_URL).name == "Assignee"
    unnamed = {"id": "assignee", "name": "Phantom", "_links": {"self": {"href": "/api/v3/queries/filters/assignee"}}}
    assert normalize_query_filter(unnamed, base_url=BASE_URL, origin=BASE_URL).name is None
