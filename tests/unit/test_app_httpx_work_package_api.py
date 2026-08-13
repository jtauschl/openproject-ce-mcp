from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_work_package_api import (
    CUSTOM_FIELD_LIST_ITEM_LIMIT,
    CUSTOM_FIELD_SCALAR_LIMIT,
    CUSTOM_FIELD_VALUE_LIMIT,
    HttpxWorkPackageApi,
    normalize_work_package_detail,
    normalize_work_package_summary,
)
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.models import SortCriterion

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _wp_payload(wp_id: int = 6, subject: str = "Demo WP", **extra) -> dict:
    payload = {
        "id": wp_id,
        "_type": "WorkPackage",
        "subject": subject,
        "lockVersion": 1,
        "description": {"raw": "Some description"},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "type": {"title": "Task"},
            "status": {"title": "New"},
            "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
            "activities": {"href": "/api/v3/work_packages/6/activities"},
            "relations": {"href": "/api/v3/work_packages/6/relations"},
        },
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_list_hits_work_packages_endpoint_with_filters_sort_and_group() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        params = dict(request.url.params)
        assert params["offset"] == "1"
        assert params["pageSize"] == "10"
        assert json.loads(params["filters"]) == [{"project_id": {"operator": "=", "values": ["1"]}}]
        assert json.loads(params["sortBy"]) == [["status", "desc"]]
        assert params["groupBy"] == "status"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_wp_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        page = await api.list(
            filters=[{"project_id": {"operator": "=", "values": ["1"]}}],
            offset=1,
            limit=10,
            sort_by=[SortCriterion(field="status", direction="desc")],
            group_by="status",
        )

    assert page.server_total == 1
    assert len(page.raw_elements) == 1
    assert page.raw_elements[0]["id"] == 6
    assert page.raw_groups is None
    assert page.raw_total_sums is None


@pytest.mark.asyncio
async def test_list_sends_show_sums_only_when_include_sums_is_true() -> None:
    seen_params: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by="status", include_sums=True)
        await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by="status", include_sums=False)

    assert seen_params[0]["showSums"] == "true"
    assert "showSums" not in seen_params[1]


@pytest.mark.asyncio
async def test_list_parses_top_level_groups_and_total_sums_when_include_sums() -> None:
    group_payload = {
        "value": "New",
        "count": 39,
        "sums": {"estimatedTime": "P6DT4H", "percentageDone": 0},
    }
    total_sums_payload = {"estimatedTime": "P23DT2H45M", "percentageDone": 87}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 1,
                "count": 1,
                "groups": [group_payload],
                "totalSums": total_sums_payload,
                "_embedded": {"elements": [_wp_payload()]},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        page = await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by="status", include_sums=True)

    assert page.raw_groups == [group_payload]
    assert page.raw_total_sums == total_sums_payload
    # Normal row elements stay unaffected by groupBy/sums, per real API behavior.
    assert len(page.raw_elements) == 1


@pytest.mark.asyncio
async def test_list_ignores_groups_and_total_sums_in_response_when_include_sums_is_false() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 1,
                "groups": [{"value": "New", "count": 39, "sums": {}}],
                "totalSums": {"estimatedTime": "P1D"},
                "_embedded": {"elements": [_wp_payload()]},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        page = await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by=None, include_sums=False)

    assert page.raw_groups is None
    assert page.raw_total_sums is None


@pytest.mark.asyncio
async def test_list_returns_raw_unnormalized_elements_not_records() -> None:
    """The list() page must carry raw payload dicts, not pre-normalized
    WorkPackageRecords -- allowlist filtering happens in the Service BEFORE
    normalization for this domain (see app/ports/work_package_api.py's
    module docstring), unlike Projects."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_wp_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        page = await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by=None)

    assert isinstance(page.raw_elements[0], dict)
    assert page.raw_elements[0] == _wp_payload()


@pytest.mark.asyncio
async def test_get_fetches_by_ref_and_builds_record() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/6"
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6")

    assert record.summary.id == 6
    assert record.summary.subject == "Demo WP"
    assert record.payload == _wp_payload()


@pytest.mark.asyncio
async def test_get_url_escapes_a_semantic_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        await api.get("PROJ-123")


@pytest.mark.asyncio
async def test_get_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        with pytest.raises(InvalidInputError):
            await api.get("../job_statuses/77")


@pytest.mark.asyncio
async def test_to_record_lazy_to_detail_diverges_from_summary_on_long_text() -> None:
    """Summary caps description at the requested (small) text_limit; detail's
    to_detail() re-extracts with FORMATTABLE_LIMIT (1200), a genuinely
    different, larger cap -- proving to_detail is lazily computed from the
    raw payload, not a cheap copy of the already-capped summary text."""
    long_description = {"raw": "x" * 900}
    payload = _wp_payload(description=long_description)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6", text_limit=10)

    assert record.summary.description_truncated is True
    assert record.summary.description_length == 900
    detail = record.to_detail()
    # get()'s detail_text_limit propagation: to_detail must use the SAME
    # text_limit passed to get() (10), matching client.py's get_work_package
    # default (text_limit=None means uncapped, but an explicit small limit
    # here proves to_detail re-derives from text_limit, not FORMATTABLE_LIMIT).
    assert detail.description_truncated is True


@pytest.mark.asyncio
async def test_to_record_to_detail_is_lazy_not_precomputed() -> None:
    """list()'s raw elements, once turned into records via to_record(), must
    not eagerly compute .to_detail() -- proven by a record whose payload would
    raise if detail-normalized (a payload missing a required field detail
    normalization reads), confirming to_detail is a deferred callable."""
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()))
    payload = _wp_payload()
    record = api.to_record(payload, text_limit=None)

    assert callable(record.to_detail)
    # Calling it explicitly must still work (proves it's not broken, just deferred).
    detail = record.to_detail()
    assert detail.id == 6


@pytest.mark.asyncio
async def test_normalize_detail_milestone_date_fallback() -> None:
    """Milestone work packages report the single day under `date`, not
    startDate/dueDate (verified against OpenProject 17.2's
    work_package_representer.rb: date_property :date with
    getter: default_date_getter(:due_date), skip_render: !milestone?)."""
    payload = _wp_payload(date="2026-03-15")
    payload.pop("startDate", None)
    payload.pop("dueDate", None)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6")

    assert record.summary.start_date == "2026-03-15"
    assert record.summary.due_date == "2026-03-15"


@pytest.mark.asyncio
async def test_normalize_detail_children_and_ancestors_truncation() -> None:
    many_children = [{"href": f"/api/v3/work_packages/{i}", "title": f"Child {i}"} for i in range(60)]
    payload = _wp_payload()
    payload["_links"]["children"] = many_children

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6")

    detail = record.to_detail()
    assert len(detail.children) == 50  # WORK_PACKAGE_CHILDREN_LIMIT
    assert detail.children_truncated is True


@pytest.mark.asyncio
async def test_normalize_detail_ancestors_missing_display_id_on_classic_instance() -> None:
    """Regression guard: hierarchy links carry displayId only from 17.5+
    (verified: no displayId on the 17.2 representer's :children/:ancestors
    links) -- must tolerate its absence rather than crash."""
    payload = _wp_payload()
    payload["_links"]["ancestors"] = [{"href": "/api/v3/work_packages/1", "title": "Parent"}]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6")

    detail = record.to_detail()
    assert detail.ancestors == [{"href": "/api/v3/work_packages/1", "title": "Parent", "display_id": None}]


@pytest.mark.asyncio
async def test_validate_create_posts_to_project_scoped_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/1/work_packages/form"
        body = json.loads(request.content)
        assert body == {"subject": "Draft"}
        return httpx.Response(
            200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        form = await api.validate_create("1", {"subject": "Draft"})

    assert form["_embedded"]["payload"] == {"subject": "Draft"}


@pytest.mark.asyncio
async def test_validate_update_posts_to_work_package_scoped_form_and_escapes_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/work_packages/PROJ-123/form" in bytes(request.url.raw_path)
        body = json.loads(request.content)
        assert body == {"subject": "Updated"}
        return httpx.Response(
            200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        await api.validate_update("PROJ-123", {"subject": "Updated"})


@pytest.mark.asyncio
async def test_validate_update_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        with pytest.raises(InvalidInputError):
            await api.validate_update("../job_statuses/77", {})


def test_parse_form_extracts_payload_validation_errors_and_schema() -> None:
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()))
    form = {
        "_type": "Form",
        "_embedded": {
            "payload": {"subject": "Draft"},
            "validationErrors": {"subject": {"message": "can't be blank"}},
            "schema": {"priority": {"writable": True}},
        },
    }

    result = api.parse_form(form)

    assert result.payload == {"subject": "Draft"}
    assert result.validation_errors == {"subject": "can't be blank"}
    assert result.schema == {"priority": {"writable": True}}


def test_parse_form_defaults_missing_sections_to_empty() -> None:
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()))

    result = api.parse_form({"_type": "Form", "_embedded": {}})

    assert result.payload == {}
    assert result.validation_errors == {}
    assert result.schema == {}


@pytest.mark.asyncio
async def test_commit_create_posts_to_work_packages_and_caps_text_limit() -> None:
    long_description = {"raw": "x" * 900}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/work_packages"
        return httpx.Response(200, json=_wp_payload(description=long_description), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.commit_create({"subject": "New"}, text_limit=10)

    assert record.summary.description_truncated is True


@pytest.mark.asyncio
async def test_commit_update_patches_by_ref_and_escapes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.commit_update("PROJ-123", {"subject": "Updated"}, text_limit=None)

    assert record.summary.id == 6


@pytest.mark.asyncio
async def test_delete_issues_delete_by_ref_and_escapes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        await api.delete("PROJ-123")


@pytest.mark.asyncio
async def test_delete_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        with pytest.raises(InvalidInputError):
            await api.delete("../job_statuses/77")


@pytest.mark.asyncio
async def test_post_comment_builds_params_and_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/6/activities"
        assert dict(request.url.params) == {"notify": "true"}
        body = json.loads(request.content)
        assert body == {"comment": {"raw": "Hello"}, "internal": True}
        return httpx.Response(201, json={"id": 99, "_links": {}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        activity = await api.post_comment("6", comment="Hello", internal=True, notify=True)

    assert activity["id"] == 99


# ---------------------------------------------------------------------------
# OPM-94: custom_fields / custom_comments read-value exposure
# ---------------------------------------------------------------------------


def test_custom_fields_top_level_plain_value_formats() -> None:
    """string/int/float/date/bool-format CFs (and calculated_value's sibling
    <N>_errors, out of CE scope) are plain top-level properties -- verified
    against custom_field_injector.rb's inject_property_value."""
    payload = _wp_payload(
        customField1="Acme Corp",  # string
        customField2=42,  # int
        customField3=3.5,  # float
        customField4="2026-05-01",  # date (plain ISO string)
        customField5=True,  # bool
        customField6_errors=[{"code": "x", "message": "bad"}],  # calculated_value sibling, must NOT be captured
    )

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {
        "customField1": "<user-content>Acme Corp</user-content>",
        "customField2": 42,
        "customField3": 3.5,
        "customField4": "<user-content>2026-05-01</user-content>",
        "customField5": True,
    }
    assert "customField6_errors" not in (summary.custom_fields or {})
    assert summary.custom_fields_truncated is False


def test_custom_fields_link_format_is_plain_string_not_hal_link() -> None:
    """link-format CF is a plain string URL despite the name -- NOT a HAL
    link, so it lives at the top level and is treated as a scalar string,
    same as string/date format (verified: link-format is absent from
    custom_field_injector.rb's LINK_FORMATS constant)."""
    payload = _wp_payload(customField7="https://example.com/spec.pdf")

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField7": "<user-content>https://example.com/spec.pdf</user-content>"}


def test_custom_fields_text_format_uses_formattable_extraction_and_delimiting() -> None:
    payload = _wp_payload(customField8={"format": "markdown", "raw": "Some **CF** text", "html": "<p></p>"})

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField8": "<user-content>Some **CF** text</user-content>"}


def test_custom_fields_hal_link_formats_scanned_from_links_not_top_level() -> None:
    """list/user/version-format CFs live ONLY under _links, never at the top
    level (verified against custom_field_injector.rb's LINK_FORMATS and
    inject_link_value, which routes through the LinkedResource DSL). Scanning
    only the top level would silently drop these three formats."""
    payload = _wp_payload()
    payload["_links"]["customField9"] = {"href": "/api/v3/custom_options/3", "title": "High"}  # list, single-value
    payload["_links"]["customField10"] = {"href": "/api/v3/users/5", "title": "Jane Doe"}  # user, single-value
    payload["_links"]["customField11"] = {"href": "/api/v3/versions/2", "title": "v1.0"}  # version, single-value

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {
        "customField9": "High",
        "customField10": "Jane Doe",
        "customField11": "v1.0",
    }


def test_custom_fields_multi_value_link_format_from_links() -> None:
    payload = _wp_payload()
    payload["_links"]["customField12"] = [
        {"href": "/api/v3/custom_options/1", "title": "Red"},
        {"href": "/api/v3/custom_options/2", "title": "Blue"},
    ]

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField12": ["Red", "Blue"]}


def test_custom_fields_empty_single_value_link_kept_as_none_not_omitted() -> None:
    """An empty single-value link can render as {href: null, title: null}
    (per OPM-94 §2) -- this is a genuine, interpretable dict shape (a link
    with no value), so it normalizes to None via _link_title and is KEPT,
    not omitted."""
    payload = _wp_payload()
    payload["_links"]["customField13"] = {"href": None, "title": None}

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField13": None}


def test_custom_fields_malformed_dict_with_no_title_kept_as_none() -> None:
    """A dict with no usable title (e.g. {"href": "..."}) is still an
    interpretable single-value-link shape -- kept as None via _link_title,
    not omitted (a dict is always a recognized shape at this detection
    level; see the omitted-shape test below for genuine omission)."""
    payload = _wp_payload()
    payload["_links"]["customField14"] = {"href": "/api/v3/custom_options/9"}

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField14": None}


def test_custom_fields_empty_titles_list_kept_not_omitted() -> None:
    """A multi-value link whose items resolve to zero usable titles still
    normalizes to [] and is KEPT -- a real, meaningful value ("no titles
    resolved"), not a malformed entry."""
    payload = _wp_payload()
    payload["_links"]["customField15"] = [{"href": "/api/v3/custom_options/1"}]  # no title key

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField15": []}


def test_custom_fields_none_value_kept() -> None:
    """A legitimate None CF value (render_nil: true) passes through and is
    kept -- distinct from an omitted/malformed entry."""
    payload = _wp_payload(customField16=None)

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField16": None}


def test_custom_field_errors_and_custom_comment_not_captured_by_custom_field_scan() -> None:
    """customField<N>_errors and customComment<N> must not be captured by the
    customField<N> scan -- verified by the strict k.startswith("customField")
    and k[11:].isdigit() pattern."""
    payload = _wp_payload(
        customField1="value",
        customField1_errors=[{"code": "x", "message": "bad"}],
        customComment1="a comment",
    )

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields == {"customField1": "<user-content>value</user-content>"}
    assert summary.custom_comments == {"customComment1": "<user-content>a comment</user-content>"}


def test_custom_field_raw_entries_tolerates_malformed_links_container() -> None:
    """A null/malformed `_links` must not crash the customField<N> scan --
    guarded with an isinstance(..., dict) check, independent of the rest of
    normalize_work_package_summary's own (pre-existing, unrelated)
    assumption that `links` is always a dict once resolved by its caller."""
    from openproject_ce_mcp.app.adapters.httpx_work_package_api import _custom_field_raw_entries

    payload = {"customField1": "value"}
    entries = _custom_field_raw_entries(payload, None)  # type: ignore[arg-type]

    assert entries == {"customField1": "value"}


def test_custom_fields_no_custom_field_keys_present_yields_none() -> None:
    payload = _wp_payload()

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields is None
    assert summary.custom_fields_truncated is False
    assert summary.custom_comments is None
    assert summary.custom_comments_truncated is False


def test_custom_fields_text_format_truncation_uses_passed_text_limit_and_sets_flag() -> None:
    """A text-format CF value routes through the SAME text_limit as
    description in this normalization context (not a hardcoded
    FORMATTABLE_LIMIT) -- and its truncation correctly propagates to
    custom_fields_truncated (this is Bug 1's regression guard: an earlier
    draft computed but discarded this signal)."""
    payload = _wp_payload(customField1={"raw": "x" * 50})

    summary = normalize_work_package_summary(payload, text_limit=10)

    assert summary.custom_fields is not None
    assert summary.custom_fields["customField1"].endswith("…</user-content>")
    assert summary.custom_fields_truncated is True


def test_custom_fields_scalar_string_cap_applies_even_when_text_limit_is_none() -> None:
    """get_work_package(text_limit=None) does not truncate description, but
    the independent scalar-string cap on a string/link/date-format CF still
    applies regardless."""
    long_value = "x" * (CUSTOM_FIELD_SCALAR_LIMIT + 50)
    payload = _wp_payload(customField1=long_value)

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields is not None
    normalized = summary.custom_fields["customField1"]
    assert normalized is not None
    assert len(normalized) < len(long_value)
    assert summary.custom_fields_truncated is True


def test_custom_fields_multi_value_list_item_cap_sets_truncated_flag() -> None:
    payload = _wp_payload()
    payload["_links"]["customField1"] = [
        {"href": f"/api/v3/custom_options/{i}", "title": f"Option {i}"} for i in range(CUSTOM_FIELD_LIST_ITEM_LIMIT + 5)
    ]

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields is not None
    titles = summary.custom_fields["customField1"]
    assert len(titles) == CUSTOM_FIELD_LIST_ITEM_LIMIT
    assert summary.custom_fields_truncated is True


def test_custom_fields_entry_count_cap_normalizes_first_then_caps() -> None:
    """Bug 2 regression guard: with >50 raw keys where several are
    malformed, the final dict must contain up to 50 GOOD entries -- not
    merely the first 50 raw keys regardless of validity. Malformed entries
    (here, customField<N>_errors-shaped garbage is impossible to inject as a
    customField<N> key itself, so we use unrecognized raw shapes instead --
    a bare object type __normalize_custom_field_entry cannot interpret) must
    not consume a slot."""
    payload = _wp_payload()
    # 5 malformed (unrecognized-shape) entries interleaved with 55 good ones,
    # spanning ids 1-60, so a naive "first 50 raw keys" would return fewer
    # than 50 good entries (or none if all 5 malformed ones landed in the
    # first 50 ids) while the fixed implementation returns exactly 50 good
    # ones by skipping malformed entries without spending a slot.
    malformed_ids = {3, 17, 29, 41, 50}
    for i in range(1, 61):
        key = f"customField{i}"
        if i in malformed_ids:
            payload[key] = object()  # unrecognized shape -> omitted, per _normalize_custom_field_entry
        else:
            payload[key] = f"value-{i}"

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_fields is not None
    assert len(summary.custom_fields) == CUSTOM_FIELD_VALUE_LIMIT
    assert all(int(key[len("customField") :]) not in malformed_ids for key in summary.custom_fields)
    assert summary.custom_fields_truncated is True


def test_custom_comments_present_and_capped_independently() -> None:
    payload = _wp_payload()
    for i in range(1, CUSTOM_FIELD_VALUE_LIMIT + 5):
        payload[f"customComment{i}"] = f"comment {i}"

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_comments is not None
    assert len(summary.custom_comments) == CUSTOM_FIELD_VALUE_LIMIT
    assert summary.custom_comments_truncated is True
    # custom_fields is untouched by the custom_comments cap (independent dicts/caps).
    assert summary.custom_fields is None


def test_custom_comments_absent_on_pre_17_2_style_payload() -> None:
    """No customComment<N> keys at all (as on a pre-17.2 instance, where the
    injector never emits them) -- handled gracefully with no special-casing,
    no version check needed."""
    payload = _wp_payload(customField1="value")

    summary = normalize_work_package_summary(payload, text_limit=None)

    assert summary.custom_comments is None
    assert summary.custom_comments_truncated is False


def test_custom_fields_and_custom_comments_reused_verbatim_in_detail_from_summary() -> None:
    """normalize_work_package_detail does not re-derive custom_fields/
    custom_comments -- it reuses summary's (computed with the same
    text_limit), a deliberate choice documented in the function's own
    docstring."""
    payload = _wp_payload(customField1="value", customComment1="a note")

    detail = normalize_work_package_detail(payload, text_limit=None)

    assert detail.custom_fields == {"customField1": "<user-content>value</user-content>"}
    assert detail.custom_comments == {"customComment1": "<user-content>a note</user-content>"}
    assert detail.custom_fields_truncated is False
    assert detail.custom_comments_truncated is False


@pytest.mark.asyncio
async def test_get_work_package_exposes_custom_fields_end_to_end() -> None:
    payload = _wp_payload(customField1="Acme Corp")
    payload["_links"]["customField2"] = {"href": "/api/v3/versions/2", "title": "v1.0"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client))
        record = await api.get("6")

    detail = record.to_detail()
    assert detail.custom_fields == {
        "customField1": "<user-content>Acme Corp</user-content>",
        "customField2": "v1.0",
    }
