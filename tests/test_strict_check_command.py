"""``evidence check`` on a strict export: the strict re-check, its counts and its agreement.

A strict export (``check.json`` ``mode`` is ``strict``) gets the strict re-check;
any other export gets the quote check exactly as before, and the two are not
summed together.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evidence.cli import main
from tests.test_check_command import QUOTE_1, make_export

FIXTURE = Path(__file__).parent / "fixtures" / "strict_export"
FORBIDDEN = ("accuracy", "quality score", "verified")


def run(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def strict_copy(tmp_path: Path) -> Path:
    target = tmp_path / "strict" / "export"
    shutil.copytree(FIXTURE, target)
    return target


def test_text_prints_each_fact_the_counts_and_the_agreement(capsys):
    code, out, err = run(capsys, ["check", "--no-flags", str(FIXTURE)])
    assert (code, err) == (0, "")
    assert "strict re-check (check.json mode strict)" in out
    assert "  fact f1 (source w1): checked direct, outcome pass\n" in out
    assert "  fact f2 (source w1): checked llm, outcome dropped, drop reason decider_drop" in out
    assert "  counts: pass 1  keep_marked 0  returned 0  dropped 1  not_judged 0" in out
    assert "  drop reasons: decider_drop 1" in out
    assert "agrees with the export's own check.json" in out
    assert "1 strict, not summed here" in out
    assert "a complete trail does not mean the work is correct" in out
    assert not any(word in out.lower() for word in FORBIDDEN)


def test_json_carries_the_same(capsys):
    code, out, _ = run(capsys, ["check", "--no-flags", "--json", str(FIXTURE)])
    assert code == 0
    report = json.loads(out)
    (entry,) = report["runs"]
    assert entry["check"] == "strict"
    assert entry["facts"] == [
        {
            "id": "f1",
            "source": "w1",
            "kind_checked": "direct",
            "outcome": "pass",
            "drop_reason": None,
            "agrees_with_record": True,
        },
        {
            "id": "f2",
            "source": "w1",
            "kind_checked": "llm",
            "outcome": "dropped",
            "drop_reason": "decider_drop",
            "agrees_with_record": True,
        },
    ]
    assert entry["counts"]["dropped"] == 1
    assert entry["drop_reasons"] == {"decider_drop": 1}
    assert (entry["agrees"], entry["disagreements"]) == (True, [])
    assert report["sums"]["runs"]["strict"] == 1
    assert "copied from a saved result" in report["strict_note"]
    assert not any(word in out.lower() for word in FORBIDDEN)


def test_each_disagreement_is_listed(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["facts"][0]["kind_checked"] = "llm"
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    code, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert code == 0
    assert "disagrees with the export's own check.json (1):" in out
    assert "  disagreement f1 kind_checked: check.json 'llm', re-check 'direct'" in out
    _, js, _ = run(capsys, ["check", "--no-flags", "--json", str(export)])
    (entry,) = json.loads(js)["runs"]
    assert entry["disagreements"] == [
        {"id": "f1", "field": "kind_checked", "recorded": "llm", "recheck": "direct"}
    ]
    assert entry["facts"][0]["agrees_with_record"] is False


def test_a_count_disagreement_names_no_fact(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["strict"]["counts"]["pass"] = 2
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "  disagreement counts.pass: check.json 2, re-check 1" in out


def test_verdicts_and_open_items_are_printed(capsys, tmp_path):
    export = strict_copy(tmp_path)
    facts = json.loads((export / "facts.json").read_text(encoding="utf-8"))
    facts["verdicts"] = [{"id": "v1", "text": "t", "verdict": "supported", "basis": ["f2"]}]
    facts["open_items"] = [{"id": "o1", "text": "?", "check": "look", "basis": ["f1"]}]
    (export / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "  verdict v1: dropped, drop reason basis_dropped" in out
    assert "  open item o1: pass" in out
    assert "  drop reasons: decider_drop 1  basis_dropped 1" in out


def test_a_strict_and_a_plain_export_are_reported_apart(capsys, tmp_path):
    plain = make_export(tmp_path / "runs" / "a" / "export", [QUOTE_1])
    code, out, _ = run(capsys, ["check", "--no-flags", "--json", str(plain), str(FIXTURE)])
    assert code == 0
    report = json.loads(out)
    assert report["sums"]["runs"] == {
        "given": 2,
        "applicable": 1,
        "not_applicable": 0,
        "unsupported": 0,
        "strict": 1,
    }
    assert report["sums"]["facts"]["made"] == 1
    plain_entry = next(e for e in report["runs"] if "check" not in e)
    assert plain_entry["facts"]["passed"] == 1


def test_a_plain_export_alone_has_no_strict_keys(capsys, tmp_path):
    plain = make_export(tmp_path / "runs" / "a" / "export", [QUOTE_1])
    _, out, _ = run(capsys, ["check", "--no-flags", "--json", str(plain)])
    report = json.loads(out)
    assert "strict" not in report["sums"]["runs"]
    assert "strict_note" not in report
    _, text, _ = run(capsys, ["check", "--no-flags", str(plain)])
    assert "strict" not in text


@pytest.mark.parametrize("json_mode", [False, True])
def test_the_flags_file_holds_the_strict_run_with_no_flags(capsys, tmp_path, json_mode):
    export = strict_copy(tmp_path)
    flags_dir = tmp_path / "flags"
    argv = ["check", "--flags-dir", str(flags_dir), str(export)] + (["--json"] if json_mode else [])
    code, _, _ = run(capsys, argv)
    assert code == 0
    written = json.loads((flags_dir / "flags.json").read_text(encoding="utf-8"))
    assert written == {"runs": [{"export": str(export), "flags": []}]}


def test_explain_and_learn_describe_the_strict_re_check(capsys):
    _, explained, _ = run(capsys, ["explain", "check"])
    assert "strict" in explained
    _, learned, _ = run(capsys, ["learn"])
    _, learned_json, _ = run(capsys, ["learn", "--json"])
    assert "strict" in learned
    check = next(c for c in json.loads(learned_json)["commands"] if c["path"] == ["check"])
    assert "strict" in check["summary"]


# --- review findings -------------------------------------------------------------------------


def test_each_disagreement_is_a_flag_and_counted_in_the_sums(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["facts"][1]["strict_outcome"] = "pass"
    record["accepted"] = False
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    flags_dir = tmp_path / "flags"
    code, out, err = run(capsys, ["check", "--flags-dir", str(flags_dir), str(export)])
    assert (code, err) == (0, "")
    flags = json.loads((flags_dir / "flags.json").read_text(encoding="utf-8"))["runs"][0]["flags"]
    assert flags == [
        {
            "check": "strict_record_disagrees",
            "detail": "f2 strict_outcome: check.json 'pass', re-check 'dropped'",
            "ref": "w1",
        },
        {
            "check": "strict_record_disagrees",
            "detail": "accepted: check.json False, re-check True",
        },
    ]
    assert out.rstrip("\n").splitlines()[-1] == (
        "strict re-check: 2 disagreement(s) with the exports' own check.json"
    )
    _, js, _ = run(capsys, ["check", "--no-flags", "--json", str(export)])
    assert json.loads(js)["sums"]["strict_disagreements"] == 2


def test_an_agreeing_strict_run_writes_an_empty_flags_list_like_a_plain_run(capsys, tmp_path):
    export = strict_copy(tmp_path)
    flags_dir = tmp_path / "flags"
    run(capsys, ["check", "--flags-dir", str(flags_dir), str(export)])
    written = json.loads((flags_dir / "flags.json").read_text(encoding="utf-8"))
    assert written == {"runs": [{"export": str(export), "flags": []}]}
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert out.rstrip("\n").splitlines()[-1] == (
        "strict re-check: 0 disagreement(s) with the exports' own check.json"
    )


def test_the_agreement_line_names_what_was_compared(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["strict"].pop("judge_counts")
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert (
        "  agrees with the export's own check.json on: facts, verdicts, open_items, accepted, "
        "counts, drop_reasons" in out
    )
    assert "  not compared (absent from check.json): judge_counts" in out


def test_a_malformed_record_is_a_user_error(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["facts"][0].pop("id")
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    code, out, err = run(capsys, ["check", "--no-flags", str(export)])
    assert code == 1
    assert out == ""
    assert "check.json fact record 1" in err
    assert "Traceback" not in err


# --- issue 8: a record that holds nothing to compare ----------------------------------------


def reduced_copy(tmp_path: Path) -> Path:
    export = strict_copy(tmp_path)
    (export / "check.json").write_text('{"mode": "strict", "strict": []}', encoding="utf-8")
    return export


def test_text_says_plainly_when_nothing_could_be_compared(capsys, tmp_path):
    code, out, _ = run(capsys, ["check", "--no-flags", str(reduced_copy(tmp_path))])
    assert code == 0
    assert "  neither agrees nor disagrees: nothing in check.json could be compared" in out
    assert "agrees with the export's own check.json on" not in out
    assert "disagreement f" not in out
    assert "  not compared (absent from check.json): facts," in out
    assert "1 strict run(s) with an incomplete check.json record" in out
    assert "  flag strict_record_incomplete: check.json not compared: facts, verdicts" in out


def test_json_reports_the_third_state_as_null(capsys, tmp_path):
    _, js, _ = run(capsys, ["check", "--no-flags", "--json", str(reduced_copy(tmp_path))])
    report = json.loads(js)
    (entry,) = report["runs"]
    assert entry["agrees"] is None
    assert entry["agrees_reason"] == "nothing in check.json could be compared"
    assert entry["disagreements"] == []
    assert [flag["check"] for flag in entry["flags"]] == ["strict_record_incomplete"]
    assert entry["incomplete"] is True
    assert [fact["agrees_with_record"] for fact in entry["facts"]] == [None, None]
    assert report["sums"]["strict_disagreements"] == 0
    assert report["sums"]["strict_not_compared"] == 1


def test_an_agreeing_run_counts_no_uncompared_run(capsys):
    _, js, _ = run(capsys, ["check", "--no-flags", "--json", str(FIXTURE)])
    report = json.loads(js)
    assert report["runs"][0]["agrees_reason"] is None
    assert report["runs"][0]["incomplete"] is False
    assert report["runs"][0]["flags"] == []
    assert report["runs"][0]["returned_before_source"] == "inferred from keep_marked"
    assert report["sums"]["strict_not_compared"] == 0


def test_text_says_when_returned_before_was_read_from_the_record(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["strict"]["returned_before"] = []
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "returned_before read from check.json" in out
    _, plain, _ = run(capsys, ["check", "--no-flags", str(FIXTURE)])
    assert "returned_before not recorded in check.json" in plain


# --- review of PR 9: a truncated record is never a clean run ---------------------------------

INCOMPLETE = "strict_record_incomplete"


def written_flags(capsys, tmp_path: Path, export: Path) -> list[dict]:
    flags_dir = tmp_path / "flags"
    code, _, err = run(capsys, ["check", "--flags-dir", str(flags_dir), str(export)])
    assert (code, err) == (0, "")
    return json.loads((flags_dir / "flags.json").read_text(encoding="utf-8"))["runs"][0]["flags"]


@pytest.mark.parametrize(
    "text", ['{"mode": "strict"}', '{"mode": "strict", "accepted": true}'], ids=["bare", "accepted"]
)
def test_a_stripped_record_is_flagged_and_does_not_agree(capsys, tmp_path, text):
    export = strict_copy(tmp_path)
    (export / "check.json").write_text(text, encoding="utf-8")
    (flag,) = written_flags(capsys, tmp_path, export)
    assert flag["check"] == INCOMPLETE
    assert "facts" in flag["detail"]
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "agrees with the export's own check.json on" not in out
    assert "neither agrees nor disagrees" in out
    _, js, _ = run(capsys, ["check", "--no-flags", "--json", str(export)])
    assert json.loads(js)["sums"]["strict_not_compared"] == 1


def test_a_record_without_its_last_fact_is_flagged_twice(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["facts"].pop()
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    flags = written_flags(capsys, tmp_path, export)
    assert [flag["check"] for flag in flags] == ["strict_record_disagrees", INCOMPLETE]
    assert "facts without a record: f2" in flags[0]["detail"]
    assert "facts without a record: f2" in flags[1]["detail"]
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "disagrees with the export's own check.json (1)" in out
    assert "facts without a record: f2" in out


def test_a_record_missing_one_part_agrees_and_is_still_flagged(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    del record["strict"]["judge_counts"]
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    (flag,) = written_flags(capsys, tmp_path, export)
    assert flag == {"check": INCOMPLETE, "detail": "check.json not compared: judge_counts"}
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "  agrees with the export's own check.json on:" in out


def test_a_full_record_writes_no_flag(capsys, tmp_path):
    assert written_flags(capsys, tmp_path, strict_copy(tmp_path)) == []


def test_a_record_of_no_fact_is_named_in_the_text(capsys, tmp_path):
    export = strict_copy(tmp_path)
    record = json.loads((export / "check.json").read_text(encoding="utf-8"))
    record["facts"].append({"id": "zz"})
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    _, out, _ = run(capsys, ["check", "--no-flags", str(export)])
    assert "  disagreement facts: check.json 3, re-check 2; records of no fact: zz" in out
    assert "strict_record_incomplete" not in out
