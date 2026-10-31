from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_licenses", ROOT / "tools" / "check_licenses.py")
assert _spec is not None and _spec.loader is not None
check_licenses = importlib.util.module_from_spec(_spec)
sys.modules["check_licenses"] = check_licenses
_spec.loader.exec_module(check_licenses)


def _package(license_text: str, name: str = "pkg", version: str = "1.0") -> dict[str, str]:
    return {"Name": name, "Version": version, "License": license_text}


@pytest.mark.parametrize(
    "license_text",
    [
        "MIT",
        "MIT License",
        "BSD License",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "Apache Software License",
        "PSF-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "MPL-2.0",
        "mit license",
        "Apache Software License; MIT License",
        "Apache-2.0 OR BSD-3-Clause",
        "Apache-2.0 OR BSD-2-Clause",
        "(MIT OR BSD-3-Clause) AND Apache-2.0",
    ],
)
def test_licenses_on_the_allow_list_pass(license_text: str) -> None:
    assert check_licenses.problems([_package(license_text)]) == []


@pytest.mark.parametrize(
    "license_text",
    [
        "GPL-3.0-or-later",
        "GPL-2.0",
        "GNU General Public License v3 (GPLv3)",
        "GNU Lesser General Public License v2 or later (LGPLv2+)",
        "LGPL-2.1",
        "AGPL-3.0",
        "Proprietary",
        "UNKNOWN",
        "",
        "   ",
    ],
)
def test_licenses_off_the_allow_list_are_reported(license_text: str) -> None:
    found = check_licenses.problems([_package(license_text, name="bad", version="2.1")])
    assert len(found) == 1
    assert "bad" in found[0] and "2.1" in found[0]


@pytest.mark.parametrize(
    "license_text",
    [
        "MIT; GPL-2.0",
        "MIT AND GPL-3.0",
        "GPL-2.0 OR MIT",
        "(MIT OR GPL-2.0) AND BSD-3-Clause",
        "GPL-2.0 WITH Classpath-exception-2.0",
        "MIT OR",
        "MIT;;",
        "MIT OR  OR BSD-3-Clause",
    ],
)
def test_every_license_named_in_an_expression_must_be_allowed(license_text: str) -> None:
    assert check_licenses.problems([_package(license_text)]) != []


def test_a_mixed_set_reports_only_the_offending_packages() -> None:
    found = check_licenses.problems(
        [_package("MIT", name="a"), _package("GPL-3.0-or-later", name="b"), _package("Apache-2.0", name="c")]
    )
    assert [line.split()[0] for line in found] == ["b"]


def test_main_sets_the_exit_code_and_names_the_package(tmp_path: Path, capsys) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps([_package("MIT")]), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([_package("GPL-3.0-or-later", name="copyleft")]), encoding="utf-8")

    assert check_licenses.main([str(good)]) == 0
    assert capsys.readouterr().err == ""
    assert check_licenses.main([str(bad)]) == 1
    assert "copyleft" in capsys.readouterr().err


def test_the_license_gate_has_one_home() -> None:
    dev = (ROOT / "dev").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

    assert "--fail-on" not in dev and "--fail-on" not in workflow
    assert dev.count("uvx pip-licenses") == 1
    assert "pip-licenses" not in workflow
    assert "run: ./dev licenses" in workflow
    lint = dev.split("\nlint() {")[1].split("\n}\n")[0]
    assert "licenses" in lint
