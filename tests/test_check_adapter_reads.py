"""The representer snapshot: its format, its header against the pinned versions, and its regeneration."""

from __future__ import annotations

import json
from pathlib import Path

import check_adapter_reads as snapshot_tool
import pytest
from op_sources import checkout_problems, pinned_versions

PINS = ["16.0", "16.1", "17.0", "17.1"]


def test_version_ranges_join_consecutive_pinned_versions_and_keep_gaps() -> None:
    assert snapshot_tool.version_ranges(["16.0", "16.1", "17.0", "17.1"], PINS) == "16.0-17.1"
    assert snapshot_tool.version_ranges(["16.0", "17.0"], PINS) == "16.0,17.0"
    assert snapshot_tool.version_ranges(["16.1", "17.0"], PINS) == "16.1-17.0"
    assert snapshot_tool.version_ranges(["17.1"], PINS) == "17.1"


@pytest.mark.parametrize("present", [["16.0"], ["16.0", "17.0"], ["16.1", "17.0", "17.1"], PINS])
def test_version_ranges_expand_back_to_the_versions(present: list[str]) -> None:
    assert snapshot_tool.expand_ranges(snapshot_tool.version_ranges(present, PINS), PINS) == present


def test_a_basename_that_continues_at_another_path_is_a_move_and_a_representer_that_ends_is_gone() -> None:
    pins = {"16.0": "a", "16.1": "b", "17.0": "c"}
    snap = {
        "pinned": pins,
        "paths": {
            "lib/old/thing_representer.rb": {"versions": "16.0-16.1", "fields": {}},
            "lib/new/thing_representer.rb": {"versions": "17.0", "fields": {}},
            "lib/stays/other_representer.rb": {"versions": "16.0-17.0", "fields": {}},
        },
    }

    moved, gone = snapshot_tool.moves_and_disappearances(snap)

    assert moved == ["lib/old/thing_representer.rb -> lib/new/thing_representer.rb"]
    assert gone == ["lib/old/thing_representer.rb"]


def _fake_sources(root: Path, label: str, representer: str, patch: str | None) -> None:
    base = root / label
    (base / "lib/api/v3/things").mkdir(parents=True)
    (base / "lib/api/v3/things/thing_representer.rb").write_text(representer)
    engine_dir = base / "modules/demo/lib/open_project/demo"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.rb").write_text(
        "extend_api_response(:v3, :things, :thing,\n"
        "                    &::OpenProject::Demo::Patches::API::ThingRepresenter.extension)\n"
    )
    if patch is not None:
        (engine_dir / "patches/api").mkdir(parents=True)
        (engine_dir / "patches/api/thing_representer.rb").write_text(patch)


def test_build_records_the_versions_per_field_and_resolves_a_patch_module(tmp_path: Path, monkeypatch) -> None:
    pins = {"16.0": "v16", "16.1": "v16.1"}
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: pins)
    _fake_sources(tmp_path, "16.0", "property :id\nproperty :old\n", "link :extra\n")
    _fake_sources(tmp_path, "16.1", "property :id\nproperty :newer\n", "link :extra\n")

    built = snapshot_tool.build(tmp_path)
    fields = built["paths"]["lib/api/v3/things/thing_representer.rb"]["fields"]
    patched = built["paths"][
        "modules/demo/lib/open_project/demo/engine.rb#extend_api_response:lib/api/v3/things/thing_representer.rb"
    ]["fields"]

    assert fields["property|id"] == {"versions": "16.0-16.1"}
    assert fields["property|old"] == {"versions": "16.0"} and fields["property|newer"] == {"versions": "16.1"}
    assert patched["link|extra"] == {"versions": "16.0-16.1"}
    assert patched["link-member:extra|*"] == {"versions": "16.0-16.1"}


def test_a_patch_constant_that_resolves_to_no_file_is_an_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    _fake_sources(tmp_path, "16.0", "property :id\n", None)

    with pytest.raises(ValueError, match="is not at"):
        snapshot_tool.build(tmp_path)


def test_unrelated_representers_with_one_basename_that_overlap_are_no_move() -> None:
    pins = {"16.0": "a", "16.1": "b", "17.0": "c"}
    snap = {
        "pinned": pins,
        "paths": {
            "lib/a/form_representer.rb": {"versions": "16.0-17.0", "fields": {}},
            "lib/b/form_representer.rb": {"versions": "16.0-17.0", "fields": {}},
            "modules/x/lib/engine.rb#extend_api_response:lib/a/form_representer.rb": {"versions": "16.0", "fields": {}},
            "modules/y/lib/engine.rb#extend_api_response:lib/a/form_representer.rb": {"versions": "17.0", "fields": {}},
        },
    }

    moved, gone = snapshot_tool.moves_and_disappearances(snap)

    assert moved == [] and gone == []


def test_an_engine_extension_whose_target_does_not_exist_is_an_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    base = tmp_path / "16.0"
    engine_dir = base / "modules/demo/lib/open_project/demo"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.rb").write_text("extend_api_response(:v3, :nope, :missing) do\n  property :x\nend\n")

    with pytest.raises(ValueError, match="which does not exist in this version"):
        snapshot_tool.build(tmp_path)


def test_a_base_class_under_an_api_subtree_is_in_the_snapshot_and_a_grape_api_file_is_not(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    base = tmp_path / "16.0/lib/api/decorators"
    base.mkdir(parents=True)
    (base / "collection.rb").write_text("property :total\ncollection :elements, embedded: true\n")
    (tmp_path / "16.0/lib/api/v3").mkdir(parents=True)
    (tmp_path / "16.0/lib/api/v3/things_api.rb").write_text("resource :things do\nend\n")

    paths = snapshot_tool.build(tmp_path)["paths"]

    assert set(paths) == {"lib/api/decorators/collection.rb"}
    assert paths["lib/api/decorators/collection.rb"]["fields"]["embedded|elements"] == {"versions": "16.0"}


def test_a_computed_property_name_is_recorded_as_unparsed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    base = tmp_path / "16.0/lib/api/v3/things"
    base.mkdir(parents=True)
    (base / "thing_representer.rb").write_text("property setting,\n         getter: 1\nproperty :id\n")

    entry = snapshot_tool.build(tmp_path)["paths"]["lib/api/v3/things/thing_representer.rb"]

    assert entry["unparsed"] == ["property setting,"]


def test_the_committed_snapshot_carries_the_member_constants_and_the_base_classes() -> None:
    committed = json.loads(snapshot_tool.SNAPSHOT.read_text())

    assert committed["link_object_members"] == list(snapshot_tool.LINK_OBJECT_MEMBERS)
    assert committed["value_members"] == list(snapshot_tool.FORMATTABLE_MEMBERS)
    assert "lib/api/decorators/collection.rb" in committed["paths"]


def _one_representer(root: Path, body: str, label: str = "16.0") -> None:
    base = root / label / "lib/api/v3/things"
    base.mkdir(parents=True)
    (base / "thing_representer.rb").write_text(body)


def test_the_enterprise_flag_and_unreadable_members_are_stored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    _one_representer(
        tmp_path,
        "property :readonly,\n         if: ->(*) { ::EnterpriseToken.allows_to?(:x) }\nresource_link :scope, getter: g, setter: s\n",
    )

    fields = snapshot_tool.build(tmp_path)["paths"]["lib/api/v3/things/thing_representer.rb"]["fields"]

    assert fields["property|readonly"] == {"versions": "16.0", "enterprise": True}
    assert fields["link|scope"] == {"versions": "16.0"}
    assert fields["link-member:scope|*"] == {"versions": "16.0"}


def test_an_acronym_of_the_checkout_is_applied_to_the_names(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    _one_representer(tmp_path, "property :page_api_size\n")
    (tmp_path / "16.0/config/initializers").mkdir(parents=True)
    (tmp_path / "16.0/config/initializers/inflections.rb").write_text('inflect.acronym "API"\n')

    fields = snapshot_tool.build(tmp_path)["paths"]["lib/api/v3/things/thing_representer.rb"]["fields"]

    assert "property|pageAPISize" in fields


def test_an_acronym_is_applied_to_the_fields_of_an_engine_body_too(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    _one_representer(tmp_path, "property :id\n")
    (tmp_path / "16.0/config/initializers").mkdir(parents=True)
    (tmp_path / "16.0/config/initializers/inflections.rb").write_text('inflect.acronym "API"\n')
    engine_dir = tmp_path / "16.0/modules/demo/lib/open_project/demo"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.rb").write_text(
        "extend_api_response(:v3, :things, :thing) do\n  property :page_api_size\nend\n"
    )

    pseudo = "modules/demo/lib/open_project/demo/engine.rb#extend_api_response:lib/api/v3/things/thing_representer.rb"

    assert "property|pageAPISize" in snapshot_tool.build(tmp_path)["paths"][pseudo]["fields"]


def test_the_bcf_api_is_not_part_of_the_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    bcf = tmp_path / "16.0/modules/bim/app/representers/bim/bcf/api/v2_1/topics"
    bcf.mkdir(parents=True)
    (bcf / "topic_representer.rb").write_text("property :topic_type\n")
    _one_representer(tmp_path, "property :id\n")

    assert set(snapshot_tool.build(tmp_path)["paths"]) == {"lib/api/v3/things/thing_representer.rb"}


def test_two_extensions_of_one_target_in_one_engine_are_merged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    _one_representer(tmp_path, "property :id\n")
    engine_dir = tmp_path / "16.0/modules/demo/lib/open_project/demo"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.rb").write_text(
        "extend_api_response(:v3, :things, :thing) do\n  property :first\nend\n"
        "extend_api_response(:v3, :things, :thing) do\n  property :second\nend\n"
    )

    pseudo = "modules/demo/lib/open_project/demo/engine.rb#extend_api_response:lib/api/v3/things/thing_representer.rb"

    assert set(snapshot_tool.build(tmp_path)["paths"][pseudo]["fields"]) == {"property|first", "property|second"}


def test_a_move_needs_the_old_path_to_end_before_the_newest_version_and_the_new_one_to_start_later() -> None:
    pins = {"16.0": "a", "16.1": "b", "17.0": "c"}

    def snap(old: str, new: str) -> dict:
        return {
            "pinned": pins,
            "paths": {
                "lib/old/x_representer.rb": {"versions": old, "fields": {}},
                "lib/new/x_representer.rb": {"versions": new, "fields": {}},
            },
        }

    assert snapshot_tool.moves_and_disappearances(snap("16.0", "16.1-17.0"))[0] != []
    assert snapshot_tool.moves_and_disappearances(snap("16.0-17.0", "16.1-17.0"))[0] == []
    assert snapshot_tool.moves_and_disappearances(snap("16.0-16.1", "17.0"))[0] != []
    assert snapshot_tool.moves_and_disappearances(snap("17.0", "16.0-16.1"))[0] == [
        "lib/new/x_representer.rb -> lib/old/x_representer.rb"
    ]


def _fake_tool(tmp_path: Path, monkeypatch, body: str = "property :id\n") -> Path:
    monkeypatch.setattr(snapshot_tool, "pinned_versions", lambda: {"16.0": "v16"})
    monkeypatch.setattr(snapshot_tool, "SOURCES", tmp_path)
    monkeypatch.setattr(snapshot_tool, "require_checkouts", lambda pins, sources: None)
    monkeypatch.setattr(snapshot_tool, "SNAPSHOT", tmp_path / "snapshot.json")
    _one_representer(tmp_path, body)
    return tmp_path / "snapshot.json"


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["check_adapter_reads.py", *argv])
    return snapshot_tool.main()


def test_write_then_check_is_clean_and_a_changed_source_fails_the_check(tmp_path: Path, monkeypatch) -> None:
    snapshot = _fake_tool(tmp_path, monkeypatch)

    assert _run(monkeypatch, "--check") == 1  # no snapshot yet
    assert _run(monkeypatch, "--write") == 0 and snapshot.is_file()
    assert _run(monkeypatch, "--check") == 0
    (tmp_path / "16.0/lib/api/v3/things/thing_representer.rb").write_text("property :id\nproperty :added\n")
    assert _run(monkeypatch, "--check") == 1


def test_a_source_that_cannot_be_parsed_and_a_missing_checkout_are_failures(tmp_path: Path, monkeypatch) -> None:
    _fake_tool(tmp_path, monkeypatch)
    engine_dir = tmp_path / "16.0/modules/demo/lib/open_project/demo"
    engine_dir.mkdir(parents=True)
    (engine_dir / "engine.rb").write_text("extend_api_response(dynamic)\n")

    assert _run(monkeypatch, "--write") == 1

    def missing(pins, sources):
        raise snapshot_tool.MissingCheckoutError("no checkout")

    monkeypatch.setattr(snapshot_tool, "require_checkouts", missing)
    assert _run(monkeypatch, "--write") == 2


def test_dumps_is_deterministic_and_valid_json() -> None:
    snap = {
        "format": 1,
        "pinned": {"16.0": "v16.0.1"},
        "link_object_members": ["href"],
        "value_members": ["raw"],
        "paths": {
            "b.rb": {"versions": "16.0", "fields": {"property|b": {"versions": "16.0"}}},
            "a.rb": {"versions": "16.0", "fields": {}},
        },
    }

    text = snapshot_tool.dumps(snap)

    assert json.loads(text) == snap
    assert text == snapshot_tool.dumps(json.loads(text))


def test_the_committed_snapshot_header_names_the_pinned_versions_and_tags() -> None:
    committed = json.loads(snapshot_tool.SNAPSHOT.read_text())

    assert committed["format"] == snapshot_tool.FORMAT
    assert committed["pinned"] == pinned_versions(), (
        "a pinned version or tag changed: run check_adapter_reads.py --write"
    )


def test_every_snapshot_entry_names_a_known_location_and_versions_of_the_pinned_list() -> None:
    committed = json.loads(snapshot_tool.SNAPSHOT.read_text())
    pins = list(committed["pinned"])
    kinds = ("property", "link", "embedded", "link-member:", "value-member:")

    for path, value in committed["paths"].items():
        assert set(snapshot_tool.expand_ranges(value["versions"], pins)) <= set(pins), path
        for key, field in value["fields"].items():
            location, _, wire = key.partition("|")
            assert location.startswith(kinds) and wire, (path, key)
            assert set(snapshot_tool.expand_ranges(field["versions"], pins)) <= set(pins), (path, key)


needs_sources = pytest.mark.skipif(
    bool(checkout_problems(pinned_versions())),
    reason="the pinned OpenProject sources are not checked out",
)


@needs_sources
def test_the_committed_snapshot_equals_a_regeneration_from_the_sources() -> None:
    assert json.loads(snapshot_tool.SNAPSHOT.read_text()) == snapshot_tool.build()
