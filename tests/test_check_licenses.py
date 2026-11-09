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


# The License value pip-licenses prints for tiktoken 0.13.0: the whole license text, no SPDX expression.
TIKTOKEN_LICENSE = (
    "MIT License\n\nCopyright (c) 2022 OpenAI, Shantanu Jain\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    'of this software and associated documentation files (the "Software"), to deal\n'
    "in the Software without restriction, including without limitation the rights\n"
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
    "copies of the Software, and to permit persons to whom the Software is\n"
    "furnished to do so, subject to the following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included in all\n"
    "copies or substantial portions of the Software.\n\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n'
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
    "SOFTWARE.\n"
)
_TITLE_AND_NOTICE = "MIT License\n\nCopyright (c) 2022 OpenAI, Shantanu Jain\n\n"
MIT_TERMS = TIKTOKEN_LICENSE.removeprefix(_TITLE_AND_NOTICE)


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
        "Apache-2.0 AND CNRI-Python",
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
        "GPL-2.0 AND CNRI-Python",
    ],
)
def test_every_license_named_in_an_expression_must_be_allowed(license_text: str) -> None:
    assert check_licenses.problems([_package(license_text)]) != []


ACCEPTED_TEXTS = {
    "as published": TIKTOKEN_LICENSE,
    "terms only": MIT_TERMS,
    "notice without title": "Copyright (c) 2022 OpenAI, Shantanu Jain\n\n" + MIT_TERMS,
    "other holders, lower-case title": "mit\n\nCopyright 1999 Someone Else\nCopyright (c) 2024 Another Holder\n\n"
    + MIT_TERMS,
    "holders with abbreviations": "Copyright (c) 2010-2020 Foo Inc., Bar Ltd.\n\n" + MIT_TERMS,
    "windows line ends": TIKTOKEN_LICENSE.replace("\n", "\r\n"),
    "upper case": TIKTOKEN_LICENSE.upper(),
}
REFUSED_TEXTS = {
    "gpl title": "GPL-3.0-only\n" + MIT_TERMS,
    "other allowed title": "Apache-2.0\n\n" + MIT_TERMS,
    "sentence as title": "Dual licensed: GPL-3.0 applies to commercial use; the MIT terms below apply otherwise.\n"
    + MIT_TERMS,
    "license named on the notice line": TIKTOKEN_LICENSE.replace("Shantanu Jain", "Shantanu Jain, licensed to you"),
    "second sentence on the notice line": TIKTOKEN_LICENSE.replace(
        "Shantanu Jain", "Shantanu Jain. Also offered under GPL-2.0-or-later"
    ),
    "copyright line inside the terms": TIKTOKEN_LICENSE.replace(
        "THE SOFTWARE IS PROVIDED", "Copyright holders additionally require GPL-3.0 terms.\nTHE SOFTWARE IS PROVIDED"
    ),
    "second license appended": TIKTOKEN_LICENSE + "\nAlternatively, this software is available under the GPL-2.0.\n",
    "one word changed": TIKTOKEN_LICENSE.replace("without restriction", "with restriction"),
    "title and notice only": "MIT License\n\nCopyright (c) 2022 OpenAI\n",
    "other license under an MIT title": "MIT License\n\nGNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n",
}


@pytest.mark.parametrize("license_text", ACCEPTED_TEXTS.values(), ids=ACCEPTED_TEXTS.keys())
def test_the_canonical_mit_text_passes(license_text: str) -> None:
    assert check_licenses.problems([_package(license_text)]) == []


@pytest.mark.parametrize("license_text", REFUSED_TEXTS.values(), ids=REFUSED_TEXTS.keys())
def test_a_license_text_that_is_not_the_canonical_mit_text_is_reported(license_text: str) -> None:
    found = check_licenses.problems([_package(license_text, name="texty", version="3.4")])
    assert len(found) == 1
    assert "texty" in found[0] and "3.4" in found[0]
    assert "not a recognised license text" in found[0]


def test_the_report_for_a_license_text_names_its_first_line_and_stays_short() -> None:
    found = check_licenses.problems([_package("GPL-3.0-only\n" + MIT_TERMS)])
    assert "'GPL-3.0-only'" in found[0]
    assert f"license text of {len(MIT_TERMS.splitlines()) + 1} lines" in found[0]
    assert len(found[0]) < 200


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
    assert dev.count("lint_tool pip-licenses") == 1
    assert "pip-licenses" not in workflow
    assert "run: ./dev licenses" in workflow
    lint = dev.split("\nlint() {")[1].split("\n}\n")[0]
    assert "licenses" in lint


def test_the_license_gate_checks_a_fresh_environment_with_every_extra() -> None:
    dev = (ROOT / "dev").read_text(encoding="utf-8")
    licenses = dev.split("\nlicenses() {")[1].split("\n}\n")[0]

    assert "UV_PROJECT_ENVIRONMENT" in licenses
    assert "uv sync --locked --all-extras --all-groups" in licenses
    assert '--python "$licenses_dir/venv/bin/python3"' in licenses
    assert "trap 'rm -rf" in licenses
    assert "uv run" not in licenses
    assert ".venv" not in licenses
