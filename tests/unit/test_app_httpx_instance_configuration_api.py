from __future__ import annotations

from openproject_ce_mcp.app.adapters.httpx_instance_configuration_api import normalize_instance_configuration


def test_normalize_instance_configuration_maps_fields() -> None:
    config = normalize_instance_configuration(
        {
            "hostName": "op.example.com",
            "maximumAttachmentFileSize": 1024,
            "maximumAPIV3PageSize": 100,
            "perPageOptions": [10, 25, 50],
            "durationFormat": "hours_only",
            "hoursPerDay": 8,
            "daysPerMonth": 20,
            "activeFeatureFlags": ["beta_feature"],
            "availableFeatures": ["feature_a"],
            "triallingFeatures": ["trial_feature"],
        }
    )
    assert config.host_name == "op.example.com"
    assert config.maximum_attachment_file_size == 1024
    assert config.per_page_options == [10, 25, 50]
    assert config.active_feature_flags == ["beta_feature"]


def test_normalize_instance_configuration_per_page_options_keeps_only_ints_without_coercion() -> None:
    """per_page_options is filtered via isinstance(item, int), not coerced --
    non-int entries (including plain strings) are dropped entirely, not
    str-to-int-parsed. A bool entry passes the isinstance check (bool is an
    int subclass in Python) and survives as 1/0, matching the original
    behavior exactly rather than being special-cased out."""
    config = normalize_instance_configuration({"perPageOptions": [10, "25", None, True, False, 50]})
    assert config.per_page_options == [10, 1, 0, 50]


def test_normalize_instance_configuration_feature_flags_are_coerced_deduped_by_sort_and_blank_filtered() -> None:
    """The three feature-flag lists use a DIFFERENT strategy than
    per_page_options: every entry is str()-coerced (so a non-string survives,
    unlike per_page_options), blank/whitespace-only entries are dropped, and
    the result is sorted alphabetically -- not preserved in payload order."""
    config = normalize_instance_configuration(
        {
            "activeFeatureFlags": ["zeta", "", "  ", "alpha", 42],
            "availableFeatures": [],
            "triallingFeatures": ["only_one"],
        }
    )
    assert config.active_feature_flags == ["42", "alpha", "zeta"]
    assert config.available_features == []
    assert config.trialling_features == ["only_one"]
