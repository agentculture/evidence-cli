"""End-to-end tests through the console entry point, one test per part of the success signal.

Every test here goes through ``evidence.cli.main`` (or ``python -m evidence`` in a
subprocess), never through a command module. The five success-signal tests are named
so each can be cited alone:

* ``test_every_shared_vector_passes_through_the_entry_point``
* ``test_counts_over_the_fixture_exports_equal_a_hand_count``
* ``test_a_second_run_prints_a_byte_identical_report``
* ``test_every_export_file_is_byte_identical_after_both_commands``
* ``test_each_fixture_answer_matches_and_a_wrong_one_does_not``

Below them are the tests the plan's gaps asked for: the ``--continue-from`` option, the
flags file content, and symlinks inside an export directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evidence.accuracy.vectors import load_matcher_vectors
from evidence.cli import main
from tests.test_check_command import QUOTE_1, QUOTE_2, make_export

VECTORS = load_matcher_vectors()
ANSWER_FIXTURES = Path(__file__).parent / "fixtures" / "answer"
TASKS = sorted(p.name for p in ANSWER_FIXTURES.iterdir() if p.is_dir())
FORMAT_LINE = {"format": {"name": "associate-walk", "version": 2}}
CHILD_LABEL = re.compile(r"c[1-9]\d*", re.ASCII)
REPORT_KEYS = ("facts", "conclusions", "statements", "by_source_kind", "flags")


def call(capsys, argv: list[str]) -> tuple[int, str, str]:
    """Run the real entry point and return its exit code, stdout and stderr."""
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def checksums(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- 1. every shared vector passes -------------------------------------------------


def write_export(
    root: Path, run: dict[str, Any], *, links: list[tuple[str, Path]] | None = None
) -> Path:
    """An export directory holding a format-2 walk, saved results and facts payload."""
    (root / "results").mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, Any]] = [FORMAT_LINE, *run.get("entries", [])]
    lines += [{"child": {"id": label, "child_walk": str(walk)}} for label, walk in links or []]
    (root / "walk.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), "utf-8")
    for walk_id, text in run.get("results", {}).items():
        (root / "results" / f"{walk_id}.txt").write_text(text, encoding="utf-8")
    if run.get("payload") is not None:
        (root / "facts.json").write_text(json.dumps(run["payload"]), encoding="utf-8")
    return root


def materialise_children(base: Path, children: list[Any]) -> list[tuple[str, Path]]:
    """Each child the walk can link (a ``cN`` label, an object); the rest cannot be on disk."""
    links = []
    for child in children:
        label = child.get("label") if isinstance(child, dict) else None
        if isinstance(label, str) and CHILD_LABEL.fullmatch(label):
            walk = write_export(base / label / "export", child) / "walk.jsonl"
            links.append((label, walk))
    return links


def on_disk_labels(case_input: dict[str, Any]) -> dict[str, Any]:
    """The vector with its ``child-N`` labels spelled ``cN``, the only form a walk can link."""
    text = re.sub(r"\bchild-([1-9]\d*)", r"c\1", json.dumps(case_input), flags=re.ASCII)
    return json.loads(text)


def materialise_case(base: Path, raw_input: dict[str, Any]) -> tuple[Path, list[str]]:
    """The export for a hand-back vector and the extra arguments its prior run needs."""
    case_input = on_disk_labels(raw_input)
    children = materialise_children(base / "children", case_input.get("children", []))
    export = write_export(base / "run" / "export", case_input, links=children)
    extra: list[str] = []
    prior = case_input.get("prior_runs", {}).get("prior")
    if prior is not None:
        prior_dir = write_export(base / "prior" / "export", prior)
        extra = ["--continue-from", str(prior_dir)]
    return export, extra


@pytest.mark.parametrize("case", VECTORS["handback_cases"], ids=lambda c: c["name"][:50])
def test_every_shared_vector_passes_through_the_entry_point_handback(capsys, tmp_path, case):
    export, extra = materialise_case(tmp_path, case["input"])
    code, out, _ = call(capsys, ["check", str(export), "--no-flags", "--json", *extra])
    assert code == 0
    got = json.loads(out)["runs"][0]
    expect = case["expect"]["report"]
    assert {k: got[k] for k in REPORT_KEYS} == {k: expect[k] for k in REPORT_KEYS}


def matcher_case_export(base: Path, case: dict[str, Any]) -> tuple[Path, Path]:
    """One fact quoting ``case['quote']`` against the saved text, and a settings file."""
    entry = {"id": "w1", "ts": "t", "tool": "read", "args": {}, "result": {}, "truncated": False}
    results: dict[str, str] = {}
    if case["saved_text"] is not None:
        entry["saved_result"] = "results/w1.txt"
        results["w1"] = case["saved_text"]
    value = case["literal"] if case["literal"] is not None else ""
    fact = {"id": "f1", "value": value, "source": "w1", "quote": case["quote"]}
    run = {"entries": [entry], "results": results, "payload": {"facts": [fact]}}
    settings = json.loads(json.dumps(load_default_settings()))
    settings["min_quote_length"] = case["min_quote_length"]
    settings_path = base / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return write_export(base / "run" / "export", run), settings_path


def load_default_settings() -> dict[str, Any]:
    from evidence.accuracy.check import load_default_settings as load

    return load()[0]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"][:50])
def test_every_shared_vector_passes_through_the_entry_point_matcher(capsys, tmp_path, case):
    export, settings = matcher_case_export(tmp_path, case)
    argv = ["check", str(export), "--no-flags", "--json", "--settings", str(settings)]
    code, out, _ = call(capsys, argv)
    assert code == 0
    facts = json.loads(out)["runs"][0]["facts"]
    expected = {"passed": 0, "refused": 0, "unchecked": 0}
    expected[case["expect"]["verdict"]] = 1
    assert {k: facts[k] for k in expected} == expected
    assert facts["made"] == 1


# --- 2. counts equal a hand count --------------------------------------------------


@pytest.fixture
def two_runs(tmp_path: Path) -> tuple[Path, Path]:
    """Run A: three facts, two quotes found in w1 and one not. Run B: one fact, found."""
    run_a = make_export(tmp_path / "runs" / "a", [QUOTE_1, QUOTE_2, "not in the result"])
    run_b = make_export(tmp_path / "runs" / "b", [QUOTE_1])
    return run_a, run_b


def test_counts_over_the_fixture_exports_equal_a_hand_count(capsys, two_runs):
    code, out, _ = call(capsys, ["check", *map(str, two_runs), "--no-flags", "--json"])
    assert code == 0
    report = json.loads(out)
    by_export = {Path(r["export"]).name: r["facts"] for r in report["runs"]}
    assert by_export["a"] == {"made": 3, "checked": 3, "passed": 2, "refused": 1, "unchecked": 0}
    assert by_export["b"] == {"made": 1, "checked": 1, "passed": 1, "refused": 0, "unchecked": 0}
    assert report["sums"]["facts"] == {
        "made": 4,
        "checked": 4,
        "passed": 3,
        "refused": 1,
        "unchecked": 0,
    }
    assert all(r["by_source_kind"]["file"] == r["facts"] for r in report["runs"])


# --- 3. a second run prints a byte-identical report --------------------------------


def run_in_process(*argv: str) -> subprocess.CompletedProcess:
    # B603: fixed argv of our own interpreter running our own package.
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "evidence", *argv], capture_output=True, check=False
    )


@pytest.mark.parametrize("json_mode", [False, True])
def test_a_second_run_prints_a_byte_identical_report(two_runs, json_mode):
    argv = ["check", *map(str, two_runs)] + (["--json"] if json_mode else [])
    first, second = run_in_process(*argv), run_in_process(*argv)
    assert first.returncode == second.returncode == 0
    assert first.stdout
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr


@pytest.mark.parametrize("task", TASKS)
def test_a_second_run_prints_a_byte_identical_grade(task):
    argv = ["grade", "--answer-file", str(ANSWER_FIXTURES / task / "answer.txt")]
    argv += ["--expected", str(ANSWER_FIXTURES / task / "expected.json"), "--json"]
    first, second = run_in_process(*argv), run_in_process(*argv)
    assert first.stdout
    assert first.stdout == second.stdout


# --- 4. no export file changes -----------------------------------------------------


def test_every_export_file_is_byte_identical_after_both_commands(capsys, two_runs, tmp_path):
    before = [checksums(r) for r in two_runs]
    fixture_before = checksums(ANSWER_FIXTURES)
    assert call(capsys, ["check", *map(str, two_runs)])[0] == 0
    assert call(capsys, ["check", *map(str, two_runs), "--json"])[0] == 0
    for task in TASKS:
        grade = ["grade", "--answer-file", str(ANSWER_FIXTURES / task / "answer.txt")]
        grade += ["--expected", str(ANSWER_FIXTURES / task / "expected.json")]
        assert call(capsys, grade)[0] == 0
    assert [checksums(r) for r in two_runs] == before
    assert checksums(ANSWER_FIXTURES) == fixture_before
    # the flags file went beside each export, never inside it
    assert all((r.parent / "evidence" / "flags.json").is_file() for r in two_runs)


# --- 5. recorded answers match, a wrong one does not -------------------------------


def grade_verdict(capsys, task: str, name: str) -> str:
    argv = ["grade", "--answer-file", str(ANSWER_FIXTURES / task / name)]
    argv += ["--expected", str(ANSWER_FIXTURES / task / "expected.json"), "--json"]
    code, out, _ = call(capsys, argv)
    assert code == 0
    return json.loads(out)["verdict"]


def test_each_fixture_answer_matches_and_a_wrong_one_does_not(capsys):
    assert len(TASKS) >= 3
    for task in TASKS:
        assert grade_verdict(capsys, task, "answer.txt") == "matches", task
        assert grade_verdict(capsys, task, "wrong.txt") == "does_not_match", task


# --- gap tests: --continue-from, the flags file, symlinks ---------------------------


def prior_run(tmp_path: Path) -> Path:
    return write_export(
        tmp_path / "prior" / "export",
        {
            "entries": [
                {
                    "id": "w1",
                    "ts": "t",
                    "tool": "read",
                    "args": {},
                    "result": {},
                    "truncated": False,
                    "saved_result": "results/w1.txt",
                }
            ],
            "results": {"w1": "prior text, quotable line\n"},
        },
    )


def prior_citing_run(tmp_path: Path) -> Path:
    fact = {"id": "f1", "value": "", "source": "prior:w1", "quote": "prior text, quotable line"}
    return write_export(tmp_path / "current" / "export", {"payload": {"facts": [fact]}})


def test_continue_from_is_needed_for_a_prior_fact_to_pass_through_the_entry_point(capsys, tmp_path):
    prior, current = prior_run(tmp_path), prior_citing_run(tmp_path)
    base = ["check", str(current), "--no-flags", "--json"]
    without = json.loads(call(capsys, base)[1])["runs"][0]["facts"]
    with_prior = json.loads(call(capsys, [*base, "--continue-from", str(prior)])[1])
    assert (without["passed"], without["unchecked"] + without["refused"]) == (0, 1)
    assert with_prior["runs"][0]["facts"]["passed"] == 1
    assert with_prior["sums"]["facts"]["passed"] == 1


def test_the_flags_file_holds_a_reviewer_flag_with_the_export_path(capsys, tmp_path):
    export = make_export(tmp_path / "runs" / "a" / "export", ["a quote absent from the result"])
    code, out, _ = call(capsys, ["check", str(export), "--json"])
    assert code == 0
    flags_path = export.parent / "evidence" / "flags.json"
    assert json.loads(out)["flags_file"]["path"] == str(flags_path)
    content = json.loads(flags_path.read_text(encoding="utf-8"))
    (run,) = content["runs"]
    assert run["export"] == str(export)
    assert [f["check"] for f in run["flags"]] == ["quote_not_in_result"]
    assert run["flags"][0]["ref"] == "w1"


OUTSIDE_QUOTE = "a line that only the outside file holds"


def test_a_symlinked_result_pointing_outside_the_export_is_not_read(capsys, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text(OUTSIDE_QUOTE + "\n", encoding="utf-8")
    export = make_export(tmp_path / "runs" / "a" / "export", [OUTSIDE_QUOTE])
    (export / "results" / "w1.txt").unlink()
    (export / "results" / "w1.txt").symlink_to(outside)
    code, out, _ = call(capsys, ["check", str(export), "--no-flags", "--json"])
    assert code == 0
    facts = json.loads(out)["runs"][0]["facts"]
    assert facts["passed"] == 0
    assert facts["unchecked"] == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT in evidence/accuracy/check.py _read_payload: facts.json is opened with "
        "is_file()/read_text(), which follow a symlink, so a facts.json that links to a file "
        "outside the export is read and counted as the run's facts (results/wN.txt links are "
        "refused by _read_results, facts.json is not)."
    ),
)
def test_a_symlinked_facts_file_pointing_outside_the_export_is_not_read(capsys, tmp_path):
    outside = tmp_path / "outside-facts.json"
    fact = {"id": "f1", "value": "", "source": "w1", "quote": QUOTE_1}
    outside.write_text(json.dumps({"facts": [fact]}), encoding="utf-8")
    export = make_export(tmp_path / "runs" / "a" / "export", None)
    (export / "facts.json").symlink_to(outside)
    code, out, _ = call(capsys, ["check", str(export), "--no-flags", "--json"])
    run = json.loads(out)["runs"][0]
    assert code == 0
    assert run["applicable"] is False
    assert run["facts"] == []
