"""Tests for the run check command module, evidence.cli._commands.check.

Fixture exports are built in ``tmp_path``; every expected number is a hand count.
Run A has three facts (two quotes found in w1, one not): made 3, checked 3,
passed 2, refused 1, all from a ``read`` call (source kind file). Run B has one
fact whose quote is found: made 1, checked 1, passed 1. Run C has no facts file
(not applicable). Run D has a walk format newer than supported (unsupported).
The sums over A and B are made 4, checked 4, passed 3, refused 1, unchecked 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evidence.cli._commands import check as cmd
from evidence.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError

QUOTE_1 = "the first quoted line is here"
QUOTE_2 = "the second quoted line is here"
RESULT_TEXT = QUOTE_1 + "\n" + QUOTE_2 + "\n"


def _walk(root: Path, version: int) -> None:
    lines: list[dict[str, Any]] = [
        {"format": {"name": "associate-walk", "version": version}},
        {
            "id": "w1",
            "ts": "2026-11-18T00:00:00+00:00",
            "tool": "read",
            "args": {},
            "result": {},
            "truncated": False,
            "saved_result": "results/w1.txt",
        },
        {"run": {"duration_ms": 1, "tool_calls": 1, "outcome": "ok", "truncated": False}},
    ]
    (root / "walk.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def _fact(fid: str, quote: str) -> dict[str, Any]:
    return {"id": fid, "value": quote.split()[-1], "source": "w1", "quote": quote}


def make_export(
    root: Path,
    quotes: list[str] | None,
    *,
    version: int = 2,
    own_report: dict[str, Any] | None = None,
) -> Path:
    root.mkdir(parents=True)
    (root / "results").mkdir()
    (root / "results" / "w1.txt").write_text(RESULT_TEXT, encoding="utf-8")
    _walk(root, version)
    if quotes is not None:
        facts = [_fact(f"f{i}", q) for i, q in enumerate(quotes, 1)]
        (root / "facts.json").write_text(json.dumps({"facts": facts}), encoding="utf-8")
    if own_report is not None:
        (root / "report.json").write_text(json.dumps(own_report), encoding="utf-8")
    return root


def own(made: int, passed: int, refused: int) -> dict[str, Any]:
    facts = {
        "made": made,
        "checked": passed + refused,
        "passed": passed,
        "refused": refused,
        "unchecked": made - passed - refused,
    }
    return {"facts": facts}


@pytest.fixture
def runs(tmp_path: Path) -> dict[str, Path]:
    base = tmp_path / "runs"
    return {
        "a": make_export(
            base / "a", [QUOTE_1, QUOTE_2, "not in the result"], own_report=own(3, 2, 1)
        ),
        "b": make_export(base / "b", [QUOTE_1], own_report=own(1, 1, 0)),
        "c": make_export(base / "c", None),
        "d": make_export(base / "d", [QUOTE_1], version=99),
    }


def ns(exports, **kw) -> argparse.Namespace:
    values = dict(
        exports=[str(e) for e in exports],
        settings=None,
        continue_from=None,
        flags_dir=None,
        no_flags=False,
        json=True,
    )
    values.update(kw)
    return argparse.Namespace(**values)


def run(capsys, args) -> tuple[int, str, str]:
    code = cmd.cmd_check(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def checksums(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_per_run_counts_and_sums_equal_hand_count(capsys, runs):
    code, out, _ = run(capsys, ns([runs["a"], runs["b"]]))
    data = json.loads(out)
    assert code == 0
    by_path = {r["export"]: r for r in data["runs"]}
    a = by_path[str(runs["a"])]
    assert a["facts"] == {"made": 3, "checked": 3, "passed": 2, "refused": 1, "unchecked": 0}
    assert a["by_source_kind"]["file"] == a["facts"]
    assert a["by_source_kind"]["web"]["made"] == 0
    b = by_path[str(runs["b"])]
    assert b["facts"] == {"made": 1, "checked": 1, "passed": 1, "refused": 0, "unchecked": 0}
    assert data["sums"]["facts"] == {
        "made": 4,
        "checked": 4,
        "passed": 3,
        "refused": 1,
        "unchecked": 0,
    }
    assert data["sums"]["by_source_kind"]["file"]["passed"] == 3
    assert data["sums"]["runs"] == {
        "given": 2,
        "applicable": 2,
        "not_applicable": 0,
        "unsupported": 0,
    }
    assert a["disagreements"] == []
    assert b["disagreements"] == []


def test_wrong_report_count_is_a_disagreement_with_both_values(capsys, tmp_path):
    export = make_export(tmp_path / "w" / "x", [QUOTE_1, "absent"], own_report=own(2, 2, 0))
    _, out, _ = run(capsys, ns([export]))
    run_data = json.loads(out)["runs"][0]
    assert run_data["disagreements"] == [
        {"key": "facts.passed", "report_json": 2, "recheck": 1},
        {"key": "facts.refused", "report_json": 0, "recheck": 1},
    ]
    code, text, _ = run(capsys, ns([export], json=False))
    assert "facts.passed" in text
    assert "report.json 2" in text
    assert "re-check 1" in text


def test_no_facts_run_is_not_applicable_and_adds_nothing(capsys, runs):
    _, out, _ = run(capsys, ns([runs["a"], runs["c"]]))
    data = json.loads(out)
    c = next(r for r in data["runs"] if r["export"] == str(runs["c"]))
    assert c["applicable"] is False
    assert c["not_applicable_reason"]
    assert "facts" not in c
    assert data["sums"]["facts"]["made"] == 3
    assert data["sums"]["runs"] == {
        "given": 2,
        "applicable": 1,
        "not_applicable": 1,
        "unsupported": 0,
    }


def test_newer_walk_format_is_unsupported_and_adds_nothing(capsys, runs):
    _, out, _ = run(capsys, ns([runs["a"], runs["d"]]))
    data = json.loads(out)
    d = next(r for r in data["runs"] if r["export"] == str(runs["d"]))
    assert d["unsupported"] is True
    assert d["walk_format"] == 99
    assert d["applicable"] is False
    assert data["sums"]["facts"]["made"] == 3
    assert data["sums"]["runs"]["unsupported"] == 1
    _, text, _ = run(capsys, ns([runs["d"]], json=False))
    assert "unsupported" in text


def test_flags_file_beside_export_dir_and_export_untouched(capsys, runs):
    before = checksums(runs["a"])
    code, out, _ = run(capsys, ns([runs["a"]]))
    assert code == 0
    flags_path = runs["a"].parent / "evidence" / "flags.json"
    assert flags_path.is_file()
    assert json.loads(out)["flags_file"] == {"written": True, "path": str(flags_path)}
    content = json.loads(flags_path.read_text(encoding="utf-8"))
    assert content["runs"][0]["export"] == str(runs["a"])
    assert isinstance(content["runs"][0]["flags"], list)
    assert checksums(runs["a"]) == before
    assert not (runs["a"] / "evidence").exists()


def test_unwritable_location_prints_report_and_exits_env_error(capsys, runs):
    (runs["a"].parent / "evidence").write_text("a file, not a directory", encoding="utf-8")
    code, out, err = run(capsys, ns([runs["a"]], json=False))
    assert code == EXIT_ENV_ERROR
    assert "quote found 2" in out
    assert "flags file was not written" in out
    assert "flags file was not written" in err
    code, out, _ = run(capsys, ns([runs["a"]]))
    assert code == EXIT_ENV_ERROR
    assert json.loads(out)["flags_file"]["written"] is False
    assert json.loads(out)["sums"]["facts"]["made"] == 3


def test_flags_dir_and_no_flags_exit_zero(capsys, runs, tmp_path):
    (runs["a"].parent / "evidence").write_text("blocker", encoding="utf-8")
    target = tmp_path / "elsewhere"
    code, out, _ = run(capsys, ns([runs["a"]], flags_dir=str(target)))
    assert code == 0
    assert (target / "flags.json").is_file()
    assert json.loads(out)["flags_file"]["path"] == str(target / "flags.json")
    code, out, _ = run(capsys, ns([runs["a"]], no_flags=True))
    assert code == 0
    assert json.loads(out)["flags_file"] == {"written": False, "reason": "--no-flags"}


def test_settings_named_in_output(capsys, runs, tmp_path):
    from evidence.accuracy.check import load_default_settings

    settings, version = load_default_settings()
    _, out, _ = run(capsys, ns([runs["a"]], no_flags=True))
    assert json.loads(out)["settings"] == {"source": "bundled default", "version": version}
    _, text, _ = run(capsys, ns([runs["a"]], no_flags=True, json=False))
    assert f"bundled default settings, version {version}" in text
    custom = tmp_path / "mine.json"
    custom.write_text(json.dumps(settings), encoding="utf-8")
    _, out, _ = run(capsys, ns([runs["a"]], no_flags=True, settings=str(custom)))
    assert json.loads(out)["settings"] == {
        "source": "file",
        "path": str(custom),
        "version": version,
    }
    _, text, _ = run(capsys, ns([runs["a"]], no_flags=True, settings=str(custom), json=False))
    assert f"settings file: {custom}" in text


@pytest.mark.parametrize("json_mode", [True, False])
def test_two_runs_print_identical_output(capsys, runs, json_mode):
    args = ns([runs["b"], runs["a"], runs["c"]], json=json_mode)
    first = run(capsys, args)
    second = run(capsys, args)
    assert first == second
    paths = [r["export"] for r in json.loads(first[1])["runs"]] if json_mode else []
    assert paths == sorted(paths)


def test_text_never_says_accuracy_or_quality_score(capsys, runs):
    _, text, _ = run(capsys, ns([runs["a"], runs["c"], runs["d"]], json=False, no_flags=True))
    text = text.replace(str(runs["a"].parent), "<runs>")  # the pytest temp path names this test
    assert "accuracy" not in text.lower()
    assert "quality score" not in text.lower()
    assert "quote found" in text


def test_bad_inputs_are_user_errors(runs, tmp_path):
    missing_args = ns([tmp_path / "missing"])
    with pytest.raises(CliError) as err:
        cmd.cmd_check(missing_args)
    assert err.value.code == EXIT_USER_ERROR
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    bad_args = ns([runs["a"]], settings=str(bad))
    with pytest.raises(CliError) as err:
        cmd.cmd_check(bad_args)
    assert err.value.code == EXIT_USER_ERROR
    nope_args = ns([runs["a"]], settings=str(tmp_path / "nope.json"))
    with pytest.raises(CliError) as err:
        cmd.cmd_check(nope_args)
    assert err.value.code == EXIT_USER_ERROR


def test_register_adds_check_verb():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    cmd.register(sub)
    parsed = parser.parse_args(["check", "x", "y", "--no-flags", "--json"])
    assert parsed.exports == ["x", "y"]
    assert parsed.no_flags
    assert parsed.func is cmd.cmd_check


def test_conclusions_are_shown_as_stated_and_as_backed_or_refused(capsys, tmp_path):
    """A stated 'supported' is not a backed conclusion when the fact under it was refused.

    Seen in a live worker run (2026-11-18): five conclusions stated as supported, four of
    them resting on refused facts. Here f1's quote is found and f2's is not, so v1 is
    backed and v2 is refused, while the run states both as supported.
    """
    export = make_export(tmp_path / "runs" / "v", [QUOTE_1, "not in the result"])
    payload = json.loads((export / "facts.json").read_text(encoding="utf-8"))
    payload["verdicts"] = [
        {"id": "v1", "claim": "the first line is there", "verdict": "supported", "basis": ["f1"]},
        {"id": "v2", "claim": "the other line is there", "verdict": "supported", "basis": ["f2"]},
    ]
    (export / "facts.json").write_text(json.dumps(payload), encoding="utf-8")
    code, out, _ = run(capsys, ns([export], no_flags=True))
    data = json.loads(out)
    assert code == 0
    assert data["runs"][0]["conclusions"] == {"made": 2, "supported": 2, "refuted": 0, "open": 0}
    assert data["runs"][0]["conclusion_outcomes"] == {"backed": 1, "open": 0, "refused": 1}
    assert data["sums"]["conclusion_outcomes"] == {"backed": 1, "open": 0, "refused": 1}
    code, out, _ = run(capsys, ns([export], no_flags=True, json=False))
    lines = [line.strip() for line in out.splitlines() if "conclusions as the run stated" in line]
    assert len(lines) == 2
    assert all(line.endswith("backed 1, left open 0, refused 1") for line in lines)


# --- review findings ------------------------------------------------------------------


def _with_verdicts(export: Path, verdicts: list[dict[str, Any]]) -> Path:
    payload = json.loads((export / "facts.json").read_text(encoding="utf-8"))
    payload["verdicts"] = verdicts
    (export / "facts.json").write_text(json.dumps(payload), encoding="utf-8")
    return export


def test_a_verdict_left_open_is_counted_open_not_backed(capsys, tmp_path):
    export = _with_verdicts(
        make_export(tmp_path / "runs" / "v", [QUOTE_1, "not in the result"]),
        [
            {"id": "v1", "claim": "c", "verdict": "supported", "basis": ["f1"]},
            {"id": "v2", "claim": "c", "verdict": "supported", "basis": ["f2"]},
            {"id": "v3", "claim": "c", "verdict": "open", "basis": ["f1"], "check": "run it"},
            {"id": "v4", "claim": "c", "verdict": "cannot_tell", "basis": [], "check": "ask"},
        ],
    )
    _, out, _ = run(capsys, ns([export], no_flags=True))
    data = json.loads(out)
    assert data["runs"][0]["conclusion_outcomes"] == {"backed": 1, "open": 2, "refused": 1}
    assert data["sums"]["conclusion_outcomes"] == {"backed": 1, "open": 2, "refused": 1}
    _, text, _ = run(capsys, ns([export], no_flags=True, json=False))
    assert "backed 1, left open 2, refused 1" in text


def test_a_refuted_verdict_that_is_accepted_is_backed(capsys, tmp_path):
    export = _with_verdicts(
        make_export(tmp_path / "runs" / "v", [QUOTE_1]),
        [{"id": "v1", "claim": "c", "verdict": "refuted", "basis": ["f1"]}],
    )
    _, out, _ = run(capsys, ns([export], no_flags=True))
    assert json.loads(out)["runs"][0]["conclusion_outcomes"] == {
        "backed": 1,
        "open": 0,
        "refused": 0,
    }


def test_flags_file_is_not_written_inside_the_export_when_run_from_inside_it(
    capsys, runs, monkeypatch
):
    monkeypatch.chdir(runs["a"])
    before = checksums(runs["a"])
    code, out, _ = run(capsys, ns(["."]))
    assert code == 0
    assert not (runs["a"] / "evidence").exists()
    assert checksums(runs["a"]) == before
    assert (runs["a"].parent / "evidence" / "flags.json").is_file()
    assert json.loads(out)["runs"][0]["export"] == "."


def test_flags_file_for_a_path_ending_in_dotdot_goes_beside_the_export(capsys, runs):
    code, _, _ = run(capsys, ns([runs["a"] / "results" / ".."]))
    assert code == 0
    assert not (runs["a"] / "evidence").exists()
    assert (runs["a"].parent / "evidence" / "flags.json").is_file()


def test_the_same_export_spelled_three_ways_is_one_run(capsys, runs):
    a = str(runs["a"])
    spellings = [a, a + "/", str(runs["a"].parent / "." / "a")]
    _, out, _ = run(capsys, ns(spellings, no_flags=True))
    data = json.loads(out)
    assert data["sums"]["runs"]["given"] == 1
    assert data["sums"]["facts"]["made"] == 3
    assert [r["export"] for r in data["runs"]] == [a]


def test_runs_are_ordered_by_resolved_path(capsys, runs):
    (runs["a"].parent / "zz").mkdir()
    spelled = [str(runs["b"]), str(runs["a"].parent / "zz" / ".." / "a")]
    _, out, _ = run(capsys, ns(spelled, no_flags=True))
    assert [r["export"] for r in json.loads(out)["runs"]] == [spelled[1], spelled[0]]


def test_continue_from_with_two_exports_is_a_user_error(runs, tmp_path):
    args = ns([runs["a"], runs["b"]], continue_from=str(runs["c"]))
    with pytest.raises(CliError) as err:
        cmd.cmd_check(args)
    assert err.value.code == EXIT_USER_ERROR
    assert "on its own" in err.value.remediation


@pytest.mark.parametrize("name", ["missing", "empty"])
def test_continue_from_with_no_walk_is_a_user_error(runs, tmp_path, name):
    (tmp_path / "empty").mkdir()
    args = ns([runs["a"]], continue_from=str(tmp_path / name))
    with pytest.raises(CliError) as err:
        cmd.cmd_check(args)
    assert err.value.code == EXIT_USER_ERROR
    assert "walk.jsonl" in err.value.message


def test_continue_from_may_name_the_session_directory(capsys, runs):
    session = runs["c"].parent / "session"
    make_export(session / "export", None)
    code, _, _ = run(capsys, ns([runs["a"]], continue_from=str(session), no_flags=True))
    assert code == 0


def test_flags_file_failure_under_json_is_one_json_error_on_stderr(capsys, runs):
    (runs["a"].parent / "evidence").write_text("a file, not a directory", encoding="utf-8")
    code, out, err = run(capsys, ns([runs["a"]]))
    assert code == EXIT_ENV_ERROR
    assert json.loads(out)["flags_file"]["written"] is False
    error = json.loads(err)
    assert error["code"] == EXIT_ENV_ERROR
    assert "flags file was not written" in error["message"]
    assert "--flags-dir" in error["remediation"]


def _settings_with(tmp_path: Path, **changes: Any) -> str:
    from evidence.accuracy.check import load_default_settings

    settings = load_default_settings()[0]
    for key, value in changes.items():
        if value is KeyError:
            del settings[key]
        else:
            settings[key] = value
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "key, value",
    [
        ("source_kinds", "read"),
        ("refusal_checks", []),
        ("min_quote_length", "8"),
        ("min_quote_length", True),
        ("source_kinds", {"read": 5}),
        ("refusal_checks", {"quote_absent": None}),
        ("checks", ["not an object"]),
        ("source_kinds", KeyError),
    ],
)
def test_a_settings_file_of_the_wrong_shape_is_a_user_error_naming_the_key(
    runs, tmp_path, key, value
):
    args = ns([runs["a"]], settings=_settings_with(tmp_path, **{key: value}), no_flags=True)
    with pytest.raises(CliError) as err:
        cmd.cmd_check(args)
    assert err.value.code == EXIT_USER_ERROR
    assert key in err.value.message


def test_a_settings_file_may_use_a_broken_min_quote_length_number(capsys, runs, tmp_path):
    """0 is a number of the right type; the library refuses every fact with it (fails closed)."""
    args = ns([runs["a"]], settings=_settings_with(tmp_path, min_quote_length=0), no_flags=True)
    code, out, _ = run(capsys, args)
    assert code == 0
    assert json.loads(out)["runs"][0]["facts"]["refused"] == 3


def test_a_newer_format_child_is_named_in_text_and_json(capsys, tmp_path):
    child = make_export(tmp_path / "runs" / "child" / "export", [QUOTE_1], version=3)
    export = make_export(tmp_path / "runs" / "p" / "export", [QUOTE_1])
    with (export / "walk.jsonl").open("a", encoding="utf-8") as handle:
        link = {"child": {"id": "c1", "child_walk": str(child / "walk.jsonl")}}
        handle.write(json.dumps(link) + "\n")
    _, out, _ = run(capsys, ns([export], no_flags=True))
    assert json.loads(out)["runs"][0]["unsupported_runs"] == [{"label": "c1", "walk_format": 3}]
    _, text, _ = run(capsys, ns([export], no_flags=True, json=False))
    lines = [line for line in text.splitlines() if "c1" in line]
    assert len(lines) == 1
    assert "not loaded" in lines[0]
    assert "walk format 3" in lines[0]


# --- review sweep: malformed input files ---------------------------------------------

DEEP = "[" * 100000 + "]" * 100000


@pytest.mark.parametrize(
    "content", [DEEP.encode(), b"\xff\xfe{", None], ids=["deep", "not-utf8", "directory"]
)
def test_a_settings_file_that_cannot_be_parsed_is_a_user_error(runs, tmp_path, content):
    path = tmp_path / "settings.json"
    if content is None:
        path.mkdir()
    else:
        path.write_bytes(content)
    args = ns([runs["a"]], settings=str(path), no_flags=True)
    with pytest.raises(CliError) as err:
        cmd.cmd_check(args)
    assert err.value.code == EXIT_USER_ERROR


def test_a_report_file_nested_too_deeply_is_not_compared(capsys, tmp_path):
    export = make_export(tmp_path / "runs" / "a", [QUOTE_1])
    (export / "report.json").write_text(DEEP, encoding="utf-8")
    code, out, _ = run(capsys, ns([export], no_flags=True))
    assert code == 0
    assert json.loads(out)["runs"][0]["own_report_found"] is False
