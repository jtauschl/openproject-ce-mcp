"""Edits of a stored work package description are computed against the stored text, not a read of it."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import httpx
import pytest
from _client_test_helpers import _make_wp_form_response, make_settings
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.client import ConflictError, InvalidInputError, OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolInputError
from openproject_ce_mcp.tools import bulk_update_work_packages, update_work_package

_LONG = "x" * 400


class _Server:
    """A work package store: GET, the update form and PATCH, keyed by id; every PATCH body is recorded."""

    def __init__(self, stored: dict[int, Any]) -> None:
        self.stored = dict(stored)
        self.patches: list[dict[str, Any]] = []
        self.requests: list[str] = []
        self.patch_status = 200

    def description_field(self, work_package_id: int) -> dict[str, Any] | None:
        raw = self.stored[work_package_id]
        if raw is _ABSENT:
            return None
        return {"format": "markdown", "raw": raw, "html": "<p>ignored</p>"}

    def record(self, work_package_id: int) -> dict[str, Any]:
        record: dict[str, Any] = {
            "_type": "WorkPackage",
            "id": work_package_id,
            "subject": f"WP {work_package_id}",
            "lockVersion": 3,
            "_links": {
                "self": {"href": f"/api/v3/work_packages/{work_package_id}"},
                "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                "status": {"title": "New"},
                "type": {"title": "Task"},
                "activities": {"href": f"/api/v3/work_packages/{work_package_id}/activities"},
                "relations": {"href": f"/api/v3/work_packages/{work_package_id}/relations"},
            },
        }
        description = self.description_field(work_package_id)
        if description is not None:
            record["description"] = description
        return record

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append(f"{method} {path}")
        parts = path.split("/")
        if len(parts) >= 5 and parts[:4] == ["", "api", "v3", "work_packages"] and parts[4].isdigit():
            work_package_id = int(parts[4])
            if len(parts) == 5 and method == "GET":
                return httpx.Response(200, json=self.record(work_package_id), request=request)
            if len(parts) == 6 and parts[5] == "form" and method == "POST":
                return _make_wp_form_response(request, json.loads(request.content))
            if len(parts) == 5 and method == "PATCH":
                body = json.loads(request.content)
                if self.patch_status != 200:
                    return httpx.Response(
                        self.patch_status,
                        json={
                            "_type": "Error",
                            "errorIdentifier": "urn:openproject-org:api:v3:errors:UpdateConflict",
                            "message": "Couldn't update the resource because someone else altered it.",
                        },
                        request=request,
                    )
                self.patches.append(body)
                if "description" in body:
                    self.stored[work_package_id] = body["description"]["raw"]
                return httpx.Response(200, json=self.record(work_package_id), request=request)
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    def client(self, settings: Settings | None = None) -> OpenProjectClient:
        base = settings or dataclasses.replace(make_settings(), enable_work_package_write=True)
        return OpenProjectClient(base, transport=httpx.MockTransport(self.handler))


_ABSENT = object()


def _server(stored: Any = "Stored text.") -> _Server:
    return _Server({1: stored})


def _hidden_description_settings() -> Settings:
    return dataclasses.replace(
        make_settings(), enable_work_package_write=True, hide_work_package_fields=("description",)
    )


def _written(server: _Server) -> str:
    assert len(server.patches) == 1
    return server.patches[0]["description"]["raw"]


@pytest.mark.parametrize(
    ("stored", "text", "expected"),
    [
        ("Intro.", "More.", "Intro.\n\nMore."),
        ("Intro.\n\n\n", "More.", "Intro.\n\nMore."),
        ("Line one\r\nLine two\r\n", "More.", "Line one\r\nLine two\n\nMore."),
        ("", "More.", "More."),
        ("  \n ", "More.", "More."),
        (None, "More.", "More."),
        (_ABSENT, "More.", "More."),
        ("  indented\n\n    code\n", "More.", "  indented\n\n    code\n\nMore."),
        ("Hard break  ", "More.", "Hard break  \n\nMore."),
    ],
    ids=[
        "plain",
        "trailing-newlines",
        "crlf",
        "empty",
        "blank",
        "raw-null",
        "no-field",
        "leading-indent-kept",
        "trailing-spaces-kept",
    ],
)
@pytest.mark.asyncio
async def test_append_adds_a_paragraph_and_keeps_the_stored_text(stored: Any, text: str, expected: str) -> None:
    server = _server(stored)
    client = server.client()
    result = await client.work_package.update(work_package_id=1, description_append=text, confirm=True)
    assert result.state == "confirmed"
    assert _written(server) == expected
    await client.aclose()


@pytest.mark.parametrize(
    ("stored", "old", "new", "expected"),
    [
        ("Alpha beta gamma.", "beta", "BETA", "Alpha BETA gamma."),
        ("Alpha\n    beta\n\n\ngamma", "Alpha beta gamma", "ALL", "ALL"),
        ("Alpha\r\nbeta\r\ngamma tail", "Alpha beta", "AB", "AB\r\ngamma tail"),
        ("Keep\n\n- one\n- two\n\nKeep", "- one - two", "- three", "Keep\n\n- three\n\nKeep"),
        ("Alpha beta gamma.", "beta ", "", "Alpha  gamma."),
        ("a\tb  c", "a b c", "z", "z"),
    ],
    ids=["simple", "indent-and-blank-lines", "crlf", "list", "delete-keeps-both-spaces", "tab-and-spaces"],
)
@pytest.mark.asyncio
async def test_replace_matches_across_whitespace_and_keeps_the_rest(
    stored: str, old: str, new: str, expected: str
) -> None:
    server = _server(stored)
    client = server.client()
    await client.work_package.update(work_package_id=1, description_replace={"old": old, "new": new}, confirm=True)
    assert _written(server) == expected
    await client.aclose()


@pytest.mark.asyncio
async def test_replace_does_not_touch_the_whitespace_around_the_passage() -> None:
    server = _server("head\n\n   mid   \n\ntail\n")
    client = server.client()
    await client.work_package.update(work_package_id=1, description_replace={"old": "mid", "new": "MID"}, confirm=True)
    assert _written(server) == "head\n\n   MID   \n\ntail\n"
    await client.aclose()


@pytest.mark.asyncio
async def test_replace_without_a_match_names_the_problem_and_not_the_stored_text() -> None:
    server = _server("Secret stored text.")
    client = server.client()
    with pytest.raises(InvalidInputError) as raised:
        await client.work_package.update(
            work_package_id=1, description_replace={"old": "absent passage", "new": "x"}, confirm=True
        )
    assert "was not found" in str(raised.value)
    assert "Secret" not in str(raised.value)
    assert server.patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_replace_with_an_escaped_look_alike_in_old_is_not_found_and_hints_at_the_escape() -> None:
    server = _server("keep <user-content> as written")
    client = server.client()
    with pytest.raises(InvalidInputError) as raised:
        await client.work_package.update(
            work_package_id=1, description_replace={"old": "keep &lt;user-content> as", "new": "x"}, confirm=True
        )
    assert "&lt;" in str(raised.value)
    await client.aclose()


@pytest.mark.parametrize(
    ("stored", "old"),
    [("one two one", "one"), ("a a a", "a a"), ("x\n\nx", "x")],
    ids=["twice", "overlapping-pair", "across-blank-line"],
)
@pytest.mark.asyncio
async def test_replace_refuses_an_ambiguous_passage(stored: str, old: str) -> None:
    server = _server(stored)
    client = server.client()
    with pytest.raises(InvalidInputError, match="matches 2 passages|matches 3 passages|matches 2"):
        await client.work_package.update(work_package_id=1, description_replace={"old": old, "new": "z"}, confirm=True)
    assert server.patches == []
    await client.aclose()


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
@pytest.mark.asyncio
async def test_append_rejects_blank_text_in_the_service(text: str) -> None:
    server = _server("text")
    client = server.client()
    with pytest.raises(InvalidInputError, match="description_append must not be blank"):
        await client.work_package.update(work_package_id=1, description_append=text, confirm=True)
    assert server.requests == []
    await client.aclose()


@pytest.mark.parametrize("old", ["", "   ", "\n\t"])
@pytest.mark.asyncio
async def test_replace_rejects_a_blank_old(old: str) -> None:
    server = _server("text")
    client = server.client()
    with pytest.raises(InvalidInputError, match="must not be blank"):
        await client.work_package.update(work_package_id=1, description_replace={"old": old, "new": "z"})
    await client.aclose()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"description": "a", "description_append": "b"},
        {"description": "a", "description_replace": {"old": "x", "new": "y"}},
        {"description_append": "b", "description_replace": {"old": "x", "new": "y"}},
        {"description": "a", "description_append": "b", "description_replace": {"old": "x", "new": "y"}},
    ],
)
@pytest.mark.asyncio
async def test_the_three_description_inputs_exclude_each_other_in_the_service(kwargs: dict[str, Any]) -> None:
    server = _server("x")
    client = server.client()
    with pytest.raises(InvalidInputError, match="cannot be combined"):
        await client.work_package.update(work_package_id=1, **kwargs)
    assert server.requests == []
    await client.aclose()


@pytest.mark.parametrize(
    "replace",
    [{"old": "x"}, {"new": "y"}, {"old": "x", "new": "y", "extra": "z"}, {"old": "x", "new": 3}],
)
@pytest.mark.asyncio
async def test_description_replace_takes_exactly_two_string_keys_in_the_service(replace: dict[str, Any]) -> None:
    server = _server("x")
    client = server.client()
    with pytest.raises(InvalidInputError, match="exactly the string keys"):
        await client.work_package.update(work_package_id=1, description_replace=replace)
    await client.aclose()


@pytest.mark.parametrize(
    "call",
    [
        {"description_append": "added"},
        {"description_replace": {"old": "does not match", "new": "x"}},
        {"description": "Stored text… cut"},
    ],
    ids=["append", "replace-without-match", "cut-copy"],
)
@pytest.mark.asyncio
async def test_hidden_description_field_refuses_before_any_edit_logic_runs(call: dict[str, Any]) -> None:
    server = _server("Stored text that is long enough.")
    client = server.client(_hidden_description_settings())
    with pytest.raises(InvalidInputError) as raised:
        await client.work_package.update(work_package_id=1, **call, confirm=True)
    assert "'description' is hidden by" in str(raised.value)
    assert "not found" not in str(raised.value)
    assert "truncated" not in str(raised.value)
    assert server.patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_description_field_leaves_an_update_without_description_unchanged() -> None:
    server = _server("Stored text.")
    client = server.client(_hidden_description_settings())
    result = await client.work_package.update(work_package_id=1, subject="New subject", confirm=True)
    assert result.state == "confirmed"
    assert "description" not in server.patches[0]
    await client.aclose()


_STORED = "First paragraph with detail.\n\nSecond paragraph with more detail.\n\n- item one\n- item two\n"


@pytest.mark.parametrize(
    "text",
    [
        "First paragraph with detail. Second paragraph…",
        "First paragraph with detail. Second paragraph… A new sentence.",
        "First paragraph with detail. Second paragraph… Appended sentence…",
        "First paragraph with detail.\n\nSecond paragraph…",
        "First paragraph with detail. Second paragraph… rewrite",
    ],
    ids=[
        "pure-cut",
        "cut-plus-appended-sentence",
        "two-ellipses",
        "multiline-cut",
        "known-false-positive",
    ],
)
@pytest.mark.asyncio
async def test_a_full_description_holding_a_cut_copy_is_refused(text: str) -> None:
    server = _server(_STORED)
    client = server.client()
    with pytest.raises(InvalidInputError, match="truncated read"):
        await client.work_package.update(work_package_id=1, description=text, confirm=True)
    assert server.patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_a_cut_copy_with_an_escaped_look_alike_before_the_cut_is_refused() -> None:
    stored = "Use <user-content> carefully in the long text that follows after this point."
    server = _server(stored)
    client = server.client()
    with pytest.raises(InvalidInputError, match="truncated read"):
        await client.work_package.update(
            work_package_id=1, description="Use &lt;user-content> carefully in the long text…", confirm=True
        )
    await client.aclose()


@pytest.mark.parametrize(
    "text",
    [
        _STORED,
        "First paragraph with detail. Second paragraph with more detail. - item one - item two…",
        "Entirely different, shorter text.",
        "…starts with an ellipsis",
        "First paragraph with detail. A rewrite before the mark… and more",
        "",
    ],
    ids=["unchanged", "full-text-plus-ellipsis", "unrelated", "leading-ellipsis", "rewrite-before-mark", "clear"],
)
@pytest.mark.asyncio
async def test_other_full_descriptions_are_written(text: str) -> None:
    server = _server(_STORED)
    client = server.client()
    await client.work_package.update(work_package_id=1, description=text, confirm=True)
    assert _written(server) == text
    await client.aclose()


@pytest.mark.asyncio
async def test_a_stored_text_with_the_ellipsis_at_that_position_is_not_a_cut_copy() -> None:
    stored = "First paragraph… and the rest of a deliberately elided sentence."
    server = _server(stored)
    client = server.client()
    await client.work_package.update(work_package_id=1, description="First paragraph… changed tail", confirm=True)
    assert _written(server) == "First paragraph… changed tail"
    await client.aclose()


@pytest.mark.asyncio
async def test_a_space_before_the_stored_ellipsis_is_not_a_cut_copy() -> None:
    server = _server("word … rest of a deliberately elided sentence.")
    client = server.client()
    await client.work_package.update(work_package_id=1, description="word… x", confirm=True)
    assert _written(server) == "word… x"
    await client.aclose()


@pytest.mark.asyncio
async def test_a_cut_copy_of_a_stored_literal_escape_is_refused() -> None:
    stored = "Write &lt;b> to escape, in a text that goes on for a while after this point."
    server = _server(stored)
    client = server.client()
    with pytest.raises(InvalidInputError, match="truncated read"):
        await client.work_package.update(
            work_package_id=1, description="Write &lt;b> to escape, in a text…", confirm=True
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_a_harmless_first_ellipsis_does_not_hide_a_true_cut_after_it() -> None:
    server = _server("A… B C D long stored tail")
    client = server.client()
    with pytest.raises(InvalidInputError, match="truncated read"):
        await client.work_package.update(work_package_id=1, description="A… B…", confirm=True)
    await client.aclose()


@pytest.mark.asyncio
async def test_preview_and_success_message_carry_the_length_change() -> None:
    server = _server("Intro.")
    client = server.client()
    preview = await client.work_package.update(work_package_id=1, description_append="More.", confirm=False)
    assert preview.message is not None
    assert preview.message.endswith("The description changes from 6 to 13 characters.")
    assert server.patches == []
    confirmed = await client.work_package.update(work_package_id=1, description_append="More.", confirm=True)
    assert confirmed.message == "Work package updated successfully. The description changes from 6 to 13 characters."
    await client.aclose()


@pytest.mark.parametrize(
    ("stored_length", "new", "shrink_sentence"),
    [
        (400, "y" * 200, True),
        (400, "y" * 201, False),
        (398, "y" * 199, False),
        (400, "y" * 199, True),
        (150, "", False),
    ],
    ids=["half-and-200", "just-over-half", "loss-199", "loss-201", "small-text"],
)
@pytest.mark.asyncio
async def test_the_shrink_sentence_needs_half_and_two_hundred_characters(
    stored_length: int, new: str, shrink_sentence: bool
) -> None:
    server = _server("x" * stored_length)
    client = server.client()
    result = await client.work_package.update(work_package_id=1, description=new, confirm=False)
    assert result.message is not None
    assert (" It shrinks by " in result.message) is shrink_sentence
    if shrink_sentence:
        assert result.message.endswith(f"It shrinks by {stored_length - len(new)} characters.")
    await client.aclose()


@pytest.mark.asyncio
async def test_messages_are_unchanged_when_the_description_is_not_part_of_the_change() -> None:
    server = _server(_LONG)
    client = server.client()
    preview = await client.work_package.update(work_package_id=1, subject="New", confirm=False)
    assert preview.message == (
        "OpenProject validated the change. Ask for confirmation, then call again with confirm=true to write it."
    )
    confirmed = await client.work_package.update(work_package_id=1, subject="New", confirm=True)
    assert confirmed.message == "Work package updated successfully."
    await client.aclose()


@pytest.mark.asyncio
async def test_a_stale_lock_version_surfaces_as_the_conflict_error() -> None:
    server = _server("Intro.")
    server.patch_status = 409
    client = server.client()
    with pytest.raises(ConflictError, match="someone else altered it"):
        await client.work_package.update(work_package_id=1, description_append="More.", confirm=True)
    assert server.stored[1] == "Intro."
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_items_edit_their_own_stored_text_and_a_failing_item_is_isolated() -> None:
    server = _Server({1: "One.", 2: "Two two.", 3: "Three."})
    client = server.client()
    result = await client.work_package.bulk_update(
        items=[
            {"work_package_id": 1, "description_append": "Added."},
            {"work_package_id": 2, "description_replace": {"old": "Two two", "new": "2"}},
            {"work_package_id": 3, "description_replace": {"old": "missing", "new": "x"}},
        ],
        confirm=True,
    )
    assert (result.succeeded, result.failed) == (2, 1)
    assert server.stored[1] == "One.\n\nAdded."
    assert server.stored[2] == "2."
    assert server.stored[3] == "Three."
    failed = result.items[2]
    assert failed.error is not None and "was not found" in failed.error
    await client.aclose()


@pytest.mark.asyncio
async def test_a_confirmed_bulk_item_stays_lean() -> None:
    server = _server("Intro.")
    client = server.client()
    result = await client.work_package.bulk_update(
        items=[{"work_package_id": 1, "description_append": "Added."}], confirm=True
    )
    assert "The description changes" in (result.items[0].result.message or "")
    assert "The description changes" not in json.dumps(_to_payload(result))
    await client.aclose()


def _ctx(server: _Server) -> FakeContext:
    return FakeContext(server.client())


@pytest.mark.asyncio
async def test_the_tool_rejects_two_description_inputs_in_one_call() -> None:
    server = _server("x")
    ctx = _ctx(server)
    with pytest.raises(ToolInputError, match="cannot be combined"):
        await update_work_package(ctx, 1, description="a", description_append="b")
    assert server.requests == []


@pytest.mark.parametrize(
    "replace",
    [
        {"old": "x"},
        {"new": "y"},
        {"old": "x", "new": "y", "extra": "z"},
        {"old": "x", "new": 3},
        {"old": 3, "new": "y"},
    ],
)
@pytest.mark.asyncio
async def test_the_tool_rejects_a_malformed_description_replace(replace: dict[str, Any]) -> None:
    server = _server("x")
    ctx = _ctx(server)
    with pytest.raises(ValueError, match="exactly the string keys"):
        await update_work_package(ctx, 1, description_replace=replace)  # type: ignore[arg-type]
    assert server.requests == []


@pytest.mark.asyncio
async def test_the_tool_rejects_a_blank_append_and_a_blank_old() -> None:
    server = _server("x")
    ctx = _ctx(server)
    with pytest.raises(ValueError, match="description_append must not be blank"):
        await update_work_package(ctx, 1, description_append="   ")
    with pytest.raises(ValueError, match="description_append must not be blank"):
        await update_work_package(ctx, 1, subject="New", description_append="<user-content> </user-content>")
    with pytest.raises(ValueError, match="description_replace.old is required"):
        await update_work_package(ctx, 1, description_replace={"old": "  ", "new": "y"})
    assert server.requests == []


@pytest.mark.asyncio
async def test_the_tool_strips_the_read_wrapper_from_append_old_and_new() -> None:
    server = _server("Stored passage here.")
    ctx = _ctx(server)
    await update_work_package(
        ctx,
        1,
        description_replace={
            "old": "<user-content>passage</user-content>",
            "new": "<user-content>section</user-content>",
        },
        confirm=True,
    )
    assert server.stored[1] == "Stored section here."
    await update_work_package(ctx, 1, description_append="<user-content>Tail.</user-content>", confirm=True)
    assert server.stored[1] == "Stored section here.\n\nTail."


@pytest.mark.asyncio
async def test_the_tool_accepts_an_empty_new_to_delete_a_passage() -> None:
    server = _server("Keep this, drop that.")
    ctx = _ctx(server)
    await update_work_package(ctx, 1, description_replace={"old": ", drop that", "new": ""}, confirm=True)
    assert server.stored[1] == "Keep this."


@pytest.mark.asyncio
async def test_bulk_tool_forwards_both_edit_keys_and_rejects_a_malformed_item() -> None:
    server = _Server({1: "One.", 2: "Two two."})
    ctx = _ctx(server)
    await bulk_update_work_packages(
        ctx,
        [
            {"work_package_id": 1, "description_append": "Added."},
            {"work_package_id": 2, "description_replace": {"old": "Two two", "new": "2"}},
        ],
        confirm=True,
    )
    assert server.stored == {1: "One.\n\nAdded.", 2: "2."}
    with pytest.raises(ValueError, match=r"items\[0\].description_replace takes exactly"):
        await bulk_update_work_packages(
            ctx,
            [{"work_package_id": 1, "description_replace": {"old": "x"}}],  # type: ignore[typeddict-item]
        )
