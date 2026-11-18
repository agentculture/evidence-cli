"""Wording of the two result commands, and their registration on the real entry point.

``evidence check`` is counts of checked quotes and backed conclusions; ``evidence grade``
is a match against recorded expected values. Both carry one line, and neither prints the
two forbidden words.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence.cli import main
from tests.test_check_command import make_export

NOTE = "a complete trail does not mean the work is correct"
FORBIDDEN = ("quality score", "accuracy")
FIXTURES = Path(__file__).parent / "fixtures" / "answer"
QUOTE = "the first quoted line is here"


def _mask(text: str, tmp_path: Path) -> str:
    return text.replace(str(tmp_path), "<tmp>")  # pytest's path holds the test name


def _call(capsys, argv):
    rc = main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def export(tmp_path):
    return make_export(tmp_path / "runs" / "a" / "export", [QUOTE])


def _check(capsys, tmp_path, export, json_mode):
    argv = ["check", str(export), "--no-flags"] + (["--json"] if json_mode else [])
    rc, out, err = _call(capsys, argv)
    assert rc == 0 and err == ""
    return _mask(out, tmp_path)


def _grade(capsys, task, json_mode, wrong=False):
    answer = FIXTURES / task / ("wrong.txt" if wrong else "answer.txt")
    argv = [
        "grade",
        "--answer-file",
        str(answer),
        "--expected",
        str(FIXTURES / task / "expected.json"),
    ]
    rc, out, err = _call(capsys, argv + (["--json"] if json_mode else []))
    assert rc == 0 and err == ""
    return out


def _task() -> str:
    return sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())[0]


def _assert_clean(text: str) -> None:
    low = text.lower()
    assert not any(word in low for word in FORBIDDEN)


def test_check_text_wording(capsys, tmp_path, export):
    text = _check(capsys, tmp_path, export, False)
    assert NOTE in text
    assert "quote found" in text
    _assert_clean(text)


def test_check_json_wording(capsys, tmp_path, export):
    text = _check(capsys, tmp_path, export, True)
    assert json.loads(text)["note"] == NOTE
    _assert_clean(text)


def test_grade_text_wording(capsys):
    text = _grade(capsys, _task(), False)
    assert NOTE in text
    _assert_clean(text)


def test_grade_json_wording(capsys):
    text = _grade(capsys, _task(), True)
    data = json.loads(text)
    assert data["note"] == NOTE and data["verdict"] == "matches"
    _assert_clean(text)


def test_grade_exit_zero_for_each_result(capsys, tmp_path):
    task = _task()
    assert json.loads(_grade(capsys, task, True))["verdict"] == "matches"
    assert json.loads(_grade(capsys, task, True, wrong=True))["verdict"] == "does_not_match"
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    argv = [
        "grade",
        "--answer-file",
        str(empty),
        "--expected",
        str(FIXTURES / task / "expected.json"),
        "--json",
    ]
    rc, out, _ = _call(capsys, argv)
    assert rc == 0 and json.loads(out)["verdict"] == "cannot_tell"


def test_grade_refused_expected_file_is_exit_one_on_stderr(capsys, tmp_path):
    bad = tmp_path / "expected.json"
    bad.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    answer = FIXTURES / _task() / "answer.txt"
    rc, out, err = _call(capsys, ["grade", "--answer-file", str(answer), "--expected", str(bad)])
    assert rc == 1 and out == "" and "refused" in err


@pytest.mark.parametrize("path", [["check"], ["grade"]])
def test_explain_describes_each_command(capsys, path):
    rc, out, err = _call(capsys, ["explain", *path])
    assert rc == 0 and err == ""
    assert f"evidence-cli {path[0]}" in out
    assert NOTE in out.lower()
    _assert_clean(out)


def test_learn_lists_both_commands(capsys):
    _, text, _ = _call(capsys, ["learn"])
    _, js, _ = _call(capsys, ["learn", "--json"])
    paths = [c["path"] for c in json.loads(js)["commands"]]
    assert ["check"] in paths and ["grade"] in paths
    assert "evidence-cli check" in text and "evidence-cli grade" in text
    _assert_clean(text + js)
