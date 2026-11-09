"""`tools/verify_dist.py` accepts exactly the recorded wheel and sdist, and nothing it cannot account for."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "verify_dist.py"
_spec = importlib.util.spec_from_file_location("verify_dist", _PATH)
assert _spec is not None and _spec.loader is not None
verify_dist = importlib.util.module_from_spec(_spec)
sys.modules["verify_dist"] = verify_dist
_spec.loader.exec_module(verify_dist)

VERSION = "1.2.3"
WHEEL = f"openproject_ce_mcp-{VERSION}-py3-none-any.whl"
SDIST = f"openproject_ce_mcp-{VERSION}.tar.gz"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dist(tmp_path: Path) -> tuple[Path, str]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / WHEEL).write_bytes(b"wheel")
    (dist / SDIST).write_bytes(b"sdist")
    return dist, f"{_sha(b'wheel')}  {WHEEL}\n{_sha(b'sdist')}  {SDIST}\n"


def _run(dist: Path, digests: str, tmp_path: Path, version: str = VERSION) -> int:
    digests_file = tmp_path / "digests.txt"
    digests_file.write_text(digests, encoding="utf-8")
    return verify_dist.main(["verify_dist.py", str(dist), version, str(digests_file)])


def test_the_recorded_wheel_and_sdist_pass_and_are_listed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)

    assert _run(dist, digests, tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [f"{_sha(b'wheel')}  {WHEEL}", f"{_sha(b'sdist')}  {SDIST}"]


def _fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], message: str, dist: Path, digests: str, **kw: str
) -> None:
    assert _run(dist, digests, tmp_path, **kw) == 1
    assert message in capsys.readouterr().err


def test_an_extra_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)
    (dist / "SHA256SUMS").write_text("x")

    _fails(tmp_path, capsys, "SHA256SUMS", dist, digests)


def test_a_hidden_extra_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)
    (dist / ".gitignore").write_text("*")

    _fails(tmp_path, capsys, ".gitignore", dist, digests)


def test_a_different_version_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)

    _fails(tmp_path, capsys, "the digest records name", dist, digests, version="1.2.4")


@pytest.mark.parametrize("missing", [WHEEL, SDIST])
def test_a_missing_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str) -> None:
    dist, digests = _dist(tmp_path)
    (dist / missing).unlink()

    _fails(tmp_path, capsys, "holds", dist, digests)


def test_a_file_with_another_digest_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)
    (dist / WHEEL).write_bytes(b"tampered")

    _fails(tmp_path, capsys, f"{WHEEL} has digest {_sha(b'tampered')}", dist, digests)


@pytest.mark.parametrize(
    ("digests", "message"),
    [
        ("", "the digests are empty"),
        ("\n\n", "the digests are empty"),
        (f"{'a' * 64}  {WHEEL}\n", "the digest records name"),
        (f"{'a' * 64}  {WHEEL}\n{'b' * 64}  {SDIST}\n{'c' * 64}  other.whl\n", "the digest records name"),
        (f"{'a' * 64}  {WHEEL}\n{'a' * 64}  {WHEEL}\n{'b' * 64}  {SDIST}\n", f"duplicate digest record for {WHEEL}"),
        (f"{'A' * 64}  {WHEEL}\n{'b' * 64}  {SDIST}\n", "malformed digest record"),
        (f"{'a' * 63}  {WHEEL}\n{'b' * 64}  {SDIST}\n", "malformed digest record"),
        (f"{'a' * 64} {WHEEL}\n{'b' * 64}  {SDIST}\n", "malformed digest record"),
    ],
)
def test_digest_records_must_be_exactly_one_well_formed_line_per_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], digests: str, message: str
) -> None:
    dist, _ = _dist(tmp_path)

    _fails(tmp_path, capsys, message, dist, digests)


def test_an_empty_directory_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, digests = _dist(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()

    _fails(tmp_path, capsys, "holds []", empty, digests)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlink_in_place_of_a_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)
    target = tmp_path / "real.whl"
    target.write_bytes(b"wheel")
    (dist / WHEEL).unlink()
    (dist / WHEEL).symlink_to(target)

    _fails(tmp_path, capsys, f"{WHEEL} is not a regular file", dist, digests)


def test_a_directory_in_place_of_a_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist, digests = _dist(tmp_path)
    (dist / SDIST).unlink()
    (dist / SDIST).mkdir()

    _fails(tmp_path, capsys, f"{SDIST} is not a regular file", dist, digests)


def test_a_missing_directory_or_digests_file_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verify_dist.main(["verify_dist.py", str(tmp_path / "nope"), VERSION, str(tmp_path / "none.txt")]) == 1
    assert "verify_dist:" in capsys.readouterr().err


def test_wrong_arguments_print_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_dist.main(["verify_dist.py"]) == 2
    assert "Usage: python tools/verify_dist.py" in capsys.readouterr().err
