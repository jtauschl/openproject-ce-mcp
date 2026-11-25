"""The filters a saved query can carry (`tools/api-check/query_filter_keys.json`) against the policy tables.

`query_filter_keys.py` reads the pinned OpenProject sources and writes a snapshot of every work package filter a
`Query` registers, by the API name the server stores in a saved query. `stored_query_policy` judges a stored filter by
that name, so each name of the snapshot is owned, listed as not hideable with a reason, or the dynamic custom field
pattern; the tool's own docstring states what it does not read. The snapshot is compared with the sources only where
they are checked out (`op-sources/`, `tools/api-check/fetch-sources.sh`); the proof against a running instance is
`tests/integration/test_stored_query_filter_names.py`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import op_sources
import pytest

from openproject_ce_mcp.app.policies.stored_query_policy import (
    NOT_HIDEABLE_FILTERS,
    STATE_OPERATOR_OWNERS,
    STORED_FILTER_OWNERS,
)

_PATH = Path(__file__).resolve().parents[1] / "tools" / "api-check" / "query_filter_keys.py"
_spec = importlib.util.spec_from_file_location("query_filter_keys", _PATH)
qfk = importlib.util.module_from_spec(_spec)
sys.modules["query_filter_keys"] = qfk
_spec.loader.exec_module(qfk)

SNAPSHOT = json.loads(qfk.SNAPSHOT.read_text())
FILTERS = SNAPSHOT["filters"]
# The filters whose class or a mixin decides its operators itself, instead of the type's default list. Of these only
# the ones that name a state of a record (`o`, `c`, `l`) need an operator owner; the manual sort filter has one
# operator that names no field.
OPERATOR_OVERRIDES = {"manualSort", "observedInVersion", "status", "targetVersion", "version"}
OVERRIDES_WITHOUT_STATE = {"manualSort": "its one operator orders by the dragged position, which no field shows"}


def test_every_filter_of_the_snapshot_is_owned_or_not_hideable() -> None:
    classified = set(STORED_FILTER_OWNERS) | set(NOT_HIDEABLE_FILTERS) | {qfk.CUSTOM_FIELD_PATTERN}

    assert sorted(set(FILTERS) - classified) == []


def test_no_row_of_the_tables_names_a_filter_the_sources_do_not_have() -> None:
    assert sorted((set(STORED_FILTER_OWNERS) | set(NOT_HIDEABLE_FILTERS)) - set(FILTERS)) == []


def test_the_custom_field_filter_is_the_only_pattern() -> None:
    assert [name for name in FILTERS if "<" in name] == [qfk.CUSTOM_FIELD_PATTERN]
    assert FILTERS[qfk.CUSTOM_FIELD_PATTERN]["ar_key"] is None


def test_the_snapshot_resolved_every_registered_class() -> None:
    assert SNAPSHOT["unresolved"] == {}
    assert SNAPSHOT["unresolved_ancestors"] == {}
    assert all(entry["class"] and entry["versions"] for entry in FILTERS.values())


def test_the_filters_that_decide_their_operators_are_the_ones_listed_here() -> None:
    assert {name for name, entry in FILTERS.items() if entry["operator_override"]} == OPERATOR_OVERRIDES


def test_every_operator_that_names_a_state_belongs_to_a_filter_that_decides_its_operators() -> None:
    owned = {key for key, _ in STATE_OPERATOR_OWNERS}

    assert owned <= OPERATOR_OVERRIDES
    assert OPERATOR_OVERRIDES - owned == set(OVERRIDES_WITHOUT_STATE)


def _conversion_keys_of_filters(added: set[str], ar_keys: set[str]) -> set[str]:
    """The runtime conversion keys that name a filter, with or without the `_id` the converter drops first."""
    return added & (ar_keys | {key.removesuffix("_id") for key in ar_keys})


def test_the_runtime_additions_to_the_conversion_table_touch_no_filter_key() -> None:
    added = {key for per_version in SNAPSHOT["runtime_conversions"].values() for key in per_version}
    ar_keys = {entry["ar_key"] for entry in FILTERS.values() if entry["ar_key"]}

    assert added and not _conversion_keys_of_filters(added, ar_keys)


def test_a_conversion_key_without_the_id_suffix_still_names_the_filter_of_that_key() -> None:
    assert _conversion_keys_of_filters({"assigned_to", "grids"}, {"assigned_to_id"}) == {"assigned_to"}
    assert _conversion_keys_of_filters({"assigned_to_id"}, {"assigned_to_id"}) == {"assigned_to_id"}
    assert not _conversion_keys_of_filters({"grids"}, {"assigned_to_id"})


# --- the extractor on a small checkout ------------------------------------------------------------------------------


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "config/constants/ar_to_api_conversions.rb",
        'WELL_KNOWN_CONVERSIONS = {\n  assigned_to: "assignee",\n  done_ratio: "percentageDone"\n}.freeze\n',
    )
    _write(tmp_path, "config/initializers/inflections.rb", 'inflect.acronym "API"\n')
    _write(
        tmp_path,
        "app/models/queries/work_packages.rb",
        "module Queries::WorkPackages\n"
        "  ::Queries::Register.register(Query) do\n"
        "    filter Filter::AssignedToFilter\n"
        "    filter Filter::ApiKeyFilter\n"
        "    filter Filter::DoneRatioFilter\n"
        "    filter Filter::CustomFieldFilter\n"
        "    filter Filter::HiddenFilter\n"
        "    # filter Filter::CommentedFilter\n"
        "    exclude Filter::HiddenFilter\n"
        "  end\n"
        "end\n",
    )
    base = "app/models/queries/work_packages/filter"
    _write(
        tmp_path,
        f"{base}/assigned_to_filter.rb",
        "class Queries::WorkPackages::Filter::AssignedToFilter\n  def self.key\n    :assigned_to_id\n  end\n\n  def type\n    :list_optional\n  end\nend\n",
    )
    _write(
        tmp_path,
        f"{base}/api_key_filter.rb",
        "class Queries::WorkPackages::Filter::ApiKeyFilter < Queries::WorkPackages::Filter::BaseFilter\n  include Queries::WorkPackages::Filter::StateMixin\nend\n",
    )
    _write(
        tmp_path, f"{base}/base_filter.rb", "class Queries::WorkPackages::Filter::BaseFilter\n  def type = :text\nend\n"
    )
    _write(
        tmp_path,
        f"{base}/state_mixin.rb",
        "module Queries::WorkPackages::Filter::StateMixin\n  def available_operators\n    []\n  end\nend\n",
    )
    _write(
        tmp_path,
        f"{base}/done_ratio_filter.rb",
        "class Queries::WorkPackages::Filter::DoneRatioFilter\n  def self.key = :done_ratio\nend\n",
    )
    _write(tmp_path, f"{base}/custom_field_filter.rb", "class Queries::WorkPackages::Filter::CustomFieldFilter\nend\n")
    _write(tmp_path, f"{base}/hidden_filter.rb", "class Queries::WorkPackages::Filter::HiddenFilter\nend\n")
    return tmp_path


def test_the_extractor_names_filters_by_the_api_name_the_server_stores(checkout: Path) -> None:
    filters = qfk.read_filters(checkout)["filters"]

    assert sorted(filters) == ["apiKey", "assignee", "customField<N>", "hidden", "percentageDone"]
    assert filters["assignee"]["ar_key"] == "assigned_to_id" and filters["assignee"]["type"] == "list_optional"
    assert filters["apiKey"]["ar_key"] == "api_key"
    assert filters["customField<N>"]["ar_key"] is None


def test_the_extractor_reads_type_and_operators_through_superclass_and_mixin(checkout: Path) -> None:
    filters = qfk.read_filters(checkout)["filters"]

    assert filters["apiKey"]["type"] == "text" and filters["apiKey"]["operator_override"] is True
    assert filters["assignee"]["operator_override"] is False


def test_the_extractor_marks_an_excluded_filter_and_skips_a_commented_one(checkout: Path) -> None:
    registered, _ = qfk.registrations(checkout / "app/models/queries/work_packages.rb")

    assert registered["Filter::HiddenFilter"] is True and registered["Filter::AssignedToFilter"] is False
    assert "Filter::CommentedFilter" not in registered


def test_the_extractor_skips_a_registration_of_another_query_nested_in_the_block(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        "::Queries::Register.register(::Query) do\n"
        "  filter ::M::OneFilter\n"
        "  ::Queries::Register.register(::ProjectQuery) do\n"
        "    filter ::M::ProjectOnlyFilter\n"
        "  end\n"
        "  filter ::M::TwoFilter\n"
        "end\n",
    )

    registered, _ = qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")

    assert sorted(registered) == ["::M::OneFilter", "::M::TwoFilter"]


def test_the_extractor_reads_a_loop_over_a_list_of_classes_and_its_exclusion(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        "::Queries::Register.register(::Query) do\n"
        "  filter ::M::OneFilter\n"
        "  [\n"
        "    ::M::LoopedFilter,\n"
        "    ::M::OtherLoopedFilter\n"
        "  ].each do |filter|\n"
        "    filter filter\n"
        "    exclude filter\n"
        "  end\n"
        "end\n",
    )

    registered, _ = qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")

    assert registered == {"::M::OneFilter": False, "::M::LoopedFilter": True, "::M::OtherLoopedFilter": True}


def test_a_loop_over_a_list_written_on_one_line_excludes_only_its_own_classes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        "::Queries::Register.register(::Query) do\n"
        "  filter ::M::OneFilter\n"
        "  [::M::LoopedFilter, ::M::OtherLoopedFilter].each do |filter|\n"
        "    filter filter\n"
        "    exclude filter\n"
        "  end\n"
        "end\n",
    )

    registered, _ = qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")

    assert registered == {"::M::OneFilter": False, "::M::LoopedFilter": True, "::M::OtherLoopedFilter": True}


def test_a_comment_inside_a_loop_list_neither_resets_the_list_nor_adds_a_class(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        "::Queries::Register.register(::Query) do\n"
        "  [\n"
        "    ::M::LoopedFilter,\n"
        "    # [legacy] ::M::RetiredFilter\n"
        "    ::M::OtherLoopedFilter\n"
        "  ].each do |filter|\n"
        "    filter filter\n"
        "    exclude filter\n"
        "  end\n"
        "end\n",
    )

    registered, _ = qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")

    assert registered == {"::M::LoopedFilter": True, "::M::OtherLoopedFilter": True}


def test_the_snapshot_records_the_tags_the_fetch_script_pins() -> None:
    assert SNAPSHOT["pins"] == op_sources.pinned_versions()


def test_a_loop_variable_without_a_loop_in_the_block_is_an_error(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        "::Queries::Register.register(::Query) do\n  filter ::M::OneFilter\n  filter filter\nend\n",
    )

    with pytest.raises(qfk.UnreadableRegistrationError, match="engine.rb"):
        qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")


@pytest.mark.parametrize(
    "line", ["filter some_filter_class", "filter ::M::OneFilter, ::M::TwoFilter", "filter", "filter(filter_class)"]
)
def test_a_filter_line_that_names_no_single_class_is_an_error_not_a_dropped_filter(tmp_path: Path, line: str) -> None:
    _write(
        tmp_path,
        "modules/m/lib/m/engine.rb",
        f"::Queries::Register.register(::Query) do\n  filter ::M::OneFilter\n  {line}\nend\n",
    )

    with pytest.raises(qfk.UnreadableRegistrationError, match="engine.rb"):
        qfk.registrations(tmp_path / "modules/m/lib/m/engine.rb")


def test_the_extractor_reads_a_runtime_addition_to_the_conversion_table(checkout: Path) -> None:
    _write(checkout, "modules/m/lib/m/engine.rb", 'Constants::ARToAPIConversions.add("grids/my_page": "grid")\n')

    assert qfk.read_filters(checkout)["runtime_conversions"] == {"grids/my_page": "grid"}


def test_the_extractor_lists_a_class_it_cannot_find_instead_of_dropping_it(checkout: Path) -> None:
    (checkout / "app/models/queries/work_packages/filter/api_key_filter.rb").unlink()

    result = qfk.read_filters(checkout)

    assert "apiKey" not in result["filters"]
    assert len(result["unresolved"]) == 1 and "ApiKeyFilter: no file" in result["unresolved"][0]


def test_a_name_is_looked_up_under_its_enclosing_namespace_innermost_first_and_must_be_unique(tmp_path: Path) -> None:
    _write(tmp_path, "app/models/a/b/thing_filter.rb", "class A::B::ThingFilter\nend\n")
    _write(tmp_path, "app/models/a/thing_filter.rb", "class A::ThingFilter\nend\n")
    _write(tmp_path, "modules/m/app/models/c/dup_filter.rb", "class C::DupFilter\nend\n")
    _write(tmp_path, "app/models/c/dup_filter.rb", "class C::DupFilter\nend\n")
    checkout = qfk.Checkout(tmp_path)

    assert checkout.resolve("ThingFilter", namespaces=("A::B", "A")).name == "thing_filter.rb"
    assert checkout.resolve("ThingFilter", namespaces=("A::B", "A")).parent.name == "b"
    assert checkout.resolve("::A::ThingFilter").parent.name == "a"
    with pytest.raises(qfk.UnresolvedConstantError, match="dup_filter.rb"):
        checkout.resolve("C::DupFilter")


@pytest.mark.parametrize(
    ("ar_key", "api"),
    [
        ("assigned_to_id", "assignee"),
        ("subject_or_id", "subjectOr"),
        ("is_milestone", "isMilestone"),
        ("project_phase_definition_id", "projectPhaseDefinition"),
        ("done_ratio", "percentageDone"),
        ("estimated_hours", "estimatedTime"),
        ("member_of_group", "memberOfGroup"),
        ("observed_in_version_id", "observedInVersion"),
    ],
)
def test_the_converted_names_are_the_ones_a_running_server_lists(ar_key: str, api: str) -> None:
    assert api in FILTERS
    assert FILTERS[api]["ar_key"] == ar_key


needs_sources = pytest.mark.skipif(
    bool(op_sources.checkout_problems(dict(SNAPSHOT["pins"]), op_sources.SOURCES)),
    reason="the snapshot's source checkouts are not under op-sources/",
)


@needs_sources
def test_the_snapshot_is_what_the_sources_say() -> None:
    assert qfk.build(SNAPSHOT["pins"]) == SNAPSHOT
