"""Tests for the answer check command module, evidence.cli._commands.grade."""

import argparse
import io
import json
from pathlib import Path

import pytest

from evidence.cli._commands import grade as cmd
from evidence.cli._errors import EXIT_USER_ERROR, CliError

FIXTURES = Path(__file__).parent / "fixtures" / "answer"
TASKS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def ns(answer, expected, json_mode=False):
    return argparse.Namespace(answer_file=str(answer), expected=str(expected), json=json_mode)


def run(capsys, args):
    cmd.cmd_grade(args)
    return capsys.readouterr()


def test_fixture_set_has_three_tasks():
    assert len(TASKS) >= 3


@pytest.mark.parametrize("task", TASKS)
def test_recorded_answer_matches_and_wrong_does_not(capsys, task):
    exp = FIXTURES / task / "expected.json"
    good = json.loads(run(capsys, ns(FIXTURES / task / "answer.txt", exp, True)).out)
    bad = json.loads(run(capsys, ns(FIXTURES / task / "wrong.txt", exp, True)).out)
    assert good["verdict"] == "matches"
    assert bad["verdict"] == "does_not_match"


def test_text_output_states_verdict_in_plain_words(capsys):
    exp = FIXTURES / TASKS[0] / "expected.json"
    out = run(capsys, ns(FIXTURES / TASKS[0] / "answer.txt", exp)).out
    assert "result: matches" in out
    out = run(capsys, ns(FIXTURES / TASKS[0] / "wrong.txt", exp)).out
    assert "result: does not match" in out
    for word in ("accuracy", "quality score", "grade"):
        assert word not in out.lower()


def test_empty_answer_is_cannot_tell(capsys, tmp_path):
    empty = tmp_path / "a.txt"
    empty.write_text("  \n")
    out = run(capsys, ns(empty, FIXTURES / TASKS[0] / "expected.json")).out
    assert "result: cannot tell" in out


@pytest.mark.parametrize("json_mode", [False, True])
def test_stdin_and_file_give_identical_output(capsys, monkeypatch, json_mode):
    exp = FIXTURES / "find-file" / "expected.json"
    path = FIXTURES / "find-file" / "answer.txt"
    from_file = run(capsys, ns(path, exp, json_mode)).out
    monkeypatch.setattr("sys.stdin", io.StringIO(path.read_text(encoding="utf-8")))
    from_stdin = run(capsys, ns("-", exp, json_mode)).out
    assert from_file == from_stdin


@pytest.mark.parametrize(
    "body", ['{"schema_version": 2}', '{"schema_version": 1, "extra": 1}', "not json", "[]"]
)
def test_refused_expected_file_is_user_error_with_remediation(tmp_path, body):
    bad = tmp_path / "e.json"
    bad.write_text(body)
    args = ns(FIXTURES / TASKS[0] / "answer.txt", bad)
    with pytest.raises(CliError) as info:
        cmd.cmd_grade(args)
    assert info.value.code == EXIT_USER_ERROR
    assert info.value.remediation


def test_unreadable_inputs_are_user_errors(tmp_path):
    good = FIXTURES / TASKS[0]
    for answer, exp in (
        (tmp_path / "none", good / "expected.json"),
        (good / "answer.txt", tmp_path / "none"),
    ):
        args = ns(answer, exp)
        with pytest.raises(CliError) as info:
            cmd.cmd_grade(args)
        assert info.value.code == EXIT_USER_ERROR
        assert info.value.remediation


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("name", ["answer.txt", "wrong.txt"])
def test_two_runs_are_byte_identical(capsys, json_mode, name):
    exp = FIXTURES / "find-file" / "expected.json"
    args = ns(FIXTURES / "find-file" / name, exp, json_mode)
    first = run(capsys, args).out
    second = run(capsys, args).out
    assert first == second


def test_text_lists_found_missing_and_schema_version(capsys):
    exp = FIXTURES / "stack-version" / "expected.json"
    out = run(capsys, ns(FIXTURES / "stack-version" / "wrong.txt", exp)).out
    assert "schema version: 1" in out
    assert "found:" in out
    assert "missing:" in out
    assert "forbidden present:" in out
    assert "Deno" in out


def test_register_adds_parser_with_options():
    p = argparse.ArgumentParser()
    cmd.register(p.add_subparsers())
    a = p.parse_args(["grade", "--answer-file", "-", "--expected", "e.json", "--json"])
    assert a.func is cmd.cmd_grade
    assert a.json
    assert a.answer_file == "-"


def test_an_answer_with_every_required_value_and_a_forbidden_one_does_not_match(capsys):
    """Guards the forbidden-value path: nothing is missing, yet the result is does_not_match."""
    task = FIXTURES / "count-tests"
    out = run(capsys, ns(task / "forbidden.txt", task / "expected.json", json_mode=True))
    payload = json.loads(out.out)
    assert payload["verdict"] == "does_not_match"
    assert payload["missing"] == []
    assert [item["text"] for item in payload["forbidden_present"]] == ["41"]
