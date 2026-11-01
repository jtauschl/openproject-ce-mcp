"""The pure decisions of the display id guard: which combination of reference, record and expectation passes."""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies import work_package_target_policy as policy
from openproject_ce_mcp.work_package_reference import canonical_display_id, has_semantic_display_id

SETTINGS = make_settings()
DISPLAY_ID_HIDDEN = dataclasses.replace(SETTINGS, hide_work_package_fields=("display_id",))


class TestDecide:
    @pytest.mark.parametrize(
        ("reference", "record_display_id", "expect", "outcome"),
        [
            ("436", "A-1", None, policy.GuardOutcome.EXPECTATION_REQUIRED),
            ("A-1", "A-1", None, policy.GuardOutcome.PASS),
            ("436", "436", None, policy.GuardOutcome.PASS),
            ("436", None, None, policy.GuardOutcome.PASS),
            ("436", "A-1", "A-1", policy.GuardOutcome.PASS),
            ("436", "A-1", "B-2", policy.Lookup("B-2")),
            ("A-1", "A-1", "A-1", policy.GuardOutcome.PASS),
            ("A-1", "A-1", "B-2", policy.Lookup("B-2")),
            ("436", "436", "A-1", policy.GuardOutcome.NO_SEMANTIC_DISPLAY_ID),
            ("436", None, "A-1", policy.GuardOutcome.NO_SEMANTIC_DISPLAY_ID),
            ("A-1", "", "A-1", policy.GuardOutcome.NO_SEMANTIC_DISPLAY_ID),
        ],
    )
    def test_the_outcome_follows_reference_record_and_expectation(
        self, reference: str, record_display_id: str | None, expect: str | None, outcome: policy.Decision
    ) -> None:
        decided = policy.decide(
            reference=reference, record_display_id=record_display_id, expect_display_id=expect, settings=SETTINGS
        )

        assert decided == outcome

    def test_a_hidden_display_id_drops_the_requirement(self) -> None:
        decided = policy.decide(
            reference="436", record_display_id="A-1", expect_display_id=None, settings=DISPLAY_ID_HIDDEN
        )

        assert decided is policy.GuardOutcome.PASS


class TestExpectationUsable:
    def test_a_given_expectation_is_refused_while_display_id_is_hidden(self) -> None:
        with pytest.raises(InvalidInputError, match="display_id field is hidden"):
            policy.ensure_expectation_usable("A-1", settings=DISPLAY_ID_HIDDEN)

    @pytest.mark.parametrize("bad", ["436", "A-007", " A-1", "A 1", ""])
    def test_an_expectation_that_is_not_a_canonical_display_id_is_refused(self, bad: str) -> None:
        with pytest.raises(InvalidInputError, match="expect_display_id must be a display id like 'PROJ-51'"):
            policy.ensure_expectation_usable(bad, settings=SETTINGS)

    def test_no_expectation_is_never_refused(self) -> None:
        policy.ensure_expectation_usable(None, settings=DISPLAY_ID_HIDDEN)
        policy.ensure_expectation_usable("A-1", settings=SETTINGS)


class TestNamedTicket:
    @pytest.mark.parametrize(
        ("hidden", "named"),
        [
            ((), "A-1 (Project A)"),
            (("project",), "A-1"),
            (("display_id",), "work package 436 (Project A)"),
            (("display_id", "project"), "work package 436"),
            (("subject",), "A-1 (Project A)"),
        ],
    )
    def test_only_fields_the_settings_show_are_named(self, hidden: tuple[str, ...], named: str) -> None:
        settings = dataclasses.replace(SETTINGS, hide_work_package_fields=hidden)

        ticket = policy.named_ticket(display_id="A-1", project="Project A", work_package_id=436, settings=settings)

        assert ticket == named


class TestSharedRules:
    @pytest.mark.parametrize("value", ["A-1", "PROJ-42", "my-proj-3"])
    def test_a_display_id_is_canonical(self, value: str) -> None:
        assert canonical_display_id(value) == value

    @pytest.mark.parametrize("value", ["42", "007", "A-007", "A 1", "", "A-0"])
    def test_a_number_or_malformed_value_is_not_a_display_id(self, value: str) -> None:
        assert canonical_display_id(value) is None

    @pytest.mark.parametrize(("value", "semantic"), [("A-1", True), ("436", False), ("", False), (None, False)])
    def test_only_a_display_id_with_a_project_is_semantic(self, value: str | None, semantic: bool) -> None:
        assert has_semantic_display_id(value) is semantic
