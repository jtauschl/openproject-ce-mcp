from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.work_package_ref import work_package_ref


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (42, "42"),
        ("42", "42"),
        (" 42 ", "42"),
        ("007", "7"),
        ("0" + "9" * 4400, "9" * 4400),
        ("PROJ-123", "PROJ-123"),
        ("P2_X-7", "P2_X-7"),
        ("proj-42", "proj-42"),
        ("my-proj-42", "my-proj-42"),
        ("2024_plan-3", "2024_plan-3"),
        ("2026-10-15", "2026-10-15"),
        ("ABCDEFGHIJ-1", "ABCDEFGHIJ-1"),
        ("a" * 100 + "-1", "a" * 100 + "-1"),
    ],
)
def test_work_package_ref_accepts_the_shapes_openproject_resolves(ref, expected: str) -> None:
    assert work_package_ref(ref) == expected


@pytest.mark.parametrize(
    "ref",
    [
        "garbage text",
        "context token catalog",
        "PROJ",
        "PROJ-",
        "-42",
        "Proj-42",
        "0",
        "000",
        "PROJ-0",
        "PROJ-007",
        "12-34",
        "ABCDEFGHIJK-1",
        "a" * 101 + "-1",
        "١٢٣",
        "OPM-١",
        "42/attachments",
        "PROJ-42?x=1",
        "PROJ-42#x",
        "../projects/42",
        ".",
        "%2e%2e",
        "",
    ],
)
def test_work_package_ref_rejects_anything_else_before_a_request(ref) -> None:
    with pytest.raises(InvalidInputError, match="work_package_id"):
        work_package_ref(ref)
