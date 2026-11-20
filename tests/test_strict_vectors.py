"""The strict re-check against every shared case in ``strict_vectors.json``.

Each case's whole result is compared with its ``expect``, field by field, so a
mismatch names the case and the field. The file is a byte copy of associate's
``associate/contract/strict_vectors.json``; it is never edited here.
"""

from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from evidence.accuracy.strict import strict_recheck
from evidence.accuracy.vectors import load_strict_vectors

VECTORS = load_strict_vectors()
CASES = VECTORS["cases"]

#: sha256 of associate's associate/contract/strict_vectors.json at associate commit 7c8db4c.
STRICT_VECTORS_SHA256 = "58c999fb3f42a2d0d0beb0658295b9ddbf4711c9dcc6d91d0ede6c8d71a4faa6"


def differences(got: Any, want: Any, path: str = "") -> list[str]:
    """Every place where *got* and *want* differ, as readable lines naming the field."""
    if isinstance(want, dict) and isinstance(got, dict):
        out: list[str] = []
        for key in want.keys() | got.keys():
            where = f"{path}.{key}" if path else str(key)
            if key not in got:
                out.append(f"{where}: missing (expected {want[key]!r})")
            elif key not in want:
                out.append(f"{where}: unexpected {got[key]!r}")
            else:
                out.extend(differences(got[key], want[key], where))
        return out
    if isinstance(want, list) and isinstance(got, list) and len(want) == len(got):
        out = []
        for index, (g, w) in enumerate(zip(got, want)):
            out.extend(differences(g, w, f"{path}[{index}]"))
        return out
    if got != want or type(got) is not type(want):
        return [f"{path}: got {got!r}, expected {want!r}"]
    return []


def test_the_file_holds_45_named_cases():
    assert VECTORS["version"] == 1
    assert len(CASES) == 45
    assert len({case["name"] for case in CASES}) == len(CASES)


def test_the_file_is_the_byte_copy_of_associate():
    data = resources.files("evidence").joinpath("data/strict_vectors.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == STRICT_VECTORS_SHA256


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_strict_recheck_reproduces_the_case(case):
    got = strict_recheck(case["input"], VECTORS["redaction"])
    found = differences(got, case["expect"])
    assert not found, f"case {case['name']}:\n  " + "\n  ".join(sorted(found))


def test_the_difference_helper_names_the_field():
    got = {"facts": [{"id": "f1", "status": "passed"}], "extra": 1}
    want = {"facts": [{"id": "f1", "status": "failed"}], "counts": {}}
    found = sorted(differences(got, want))
    assert found == [
        "counts: missing (expected {})",
        "extra: unexpected 1",
        "facts[0].status: got 'passed', expected 'failed'",
    ]


def test_the_recheck_is_pure_same_input_same_result():
    case = CASES[0]
    assert strict_recheck(case["input"], VECTORS["redaction"]) == strict_recheck(
        case["input"], VECTORS["redaction"]
    )


def test_the_recheck_does_not_change_its_input():
    for case in CASES:
        before = copy.deepcopy(case["input"])
        strict_recheck(case["input"], VECTORS["redaction"])
        assert case["input"] == before, case["name"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not available to build the wheel")
def test_the_built_wheel_carries_the_strict_vectors():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as out:
        # B603/B607: fixed argv; uv is the project's own build tool.
        build = subprocess.run(  # noqa: S603  # nosec B603 B607
            ["uv", "build", "--wheel", "-o", out, str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert build.returncode == 0, build.stderr
        (wheel,) = Path(out).glob("*.whl")
        with zipfile.ZipFile(wheel) as zf:
            assert "evidence/data/strict_vectors.json" in zf.namelist()
            shipped = zf.read("evidence/data/strict_vectors.json")
    assert hashlib.sha256(shipped).hexdigest() == STRICT_VECTORS_SHA256
