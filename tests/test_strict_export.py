"""The strict re-check of a stored export, and its comparison with the export's own record.

``fixtures/strict_export`` is copied from associate's
``tests/fixtures/strict_export`` (its ``ready.json`` machine paths replaced).
Further exports are built here from the shared strict cases, so the rebuild of
the input is tested against every case that the export layout can hold.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from evidence.accuracy import strict_export
from evidence.accuracy.check import (
    ExportError,
    accuracy_result,
    inspect_export,
    load_default_settings,
    load_export,
    load_handback_input,
)
from evidence.accuracy.strict_export import (
    is_strict_export,
    load_strict_defaults,
    recheck_strict_export,
    strict_export_input,
    strict_settings,
)
from evidence.accuracy.vectors import load_strict_vectors

FIXTURE = Path(__file__).parent / "fixtures" / "strict_export"
SETTINGS, _ = load_default_settings()
VECTORS = load_strict_vectors()


def copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "export"
    shutil.copytree(FIXTURE, target)
    return target


def edit_check(export: Path, change) -> None:
    path = export / "check.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(json.dumps(record), encoding="utf-8")


# --- the copied fixture ---------------------------------------------------------------------


def test_the_copied_fixture_holds_no_machine_path():
    for path in FIXTURE.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/home/" not in text, path.name
            assert "/Users/" not in text, path.name


def test_the_copied_fixture_is_a_strict_export_and_a_plain_one_is_not(tmp_path):
    assert is_strict_export(FIXTURE)
    plain = copy_fixture(tmp_path)
    edit_check(plain, lambda r: r.update(mode="report"))
    assert not is_strict_export(plain)
    (plain / "check.json").unlink()
    assert not is_strict_export(plain)


def test_the_copied_fixture_agrees_with_its_own_record():
    got = recheck_strict_export(FIXTURE, SETTINGS)
    assert got["check"] == "strict"
    assert got["comparison"]["agrees"] is True
    assert got["comparison"]["disagreements"] == []
    rows = got["comparison"]["facts"]
    assert [(r["id"], r["source"], r["agrees"]) for r in rows] == [
        ("f1", "w1", True),
        ("f2", "w1", True),
    ]
    assert got["recheck"]["counts"] == got["recorded"]["counts"]
    assert got["accepted"] is True
    assert got["recorded"]["accepted"] is True


def test_the_copied_fixture_copies_the_same_evidence_as_its_record():
    got = recheck_strict_export(FIXTURE, SETTINGS)["recheck"]["facts"]
    recorded = json.loads((FIXTURE / "check.json").read_text(encoding="utf-8"))["facts"]
    for mine, theirs in zip(got, recorded):
        assert mine["evidence"] == theirs["evidence"]
    assert got[0]["judge"] is None
    assert recorded[0]["judge"] is None
    assert got[1]["judge"]["option"] == recorded[1]["judge"]["option"] == "none"


def test_the_input_is_rebuilt_from_the_saved_files():
    data = strict_export_input(FIXTURE, SETTINGS)
    assert [e["id"] for e in data["walk"]] == ["w1", "w2", "w3", "w4"]
    assert set(data["results"]) == {f"results/w{n}.txt" for n in range(1, 5)}
    assert [f["id"] for f in data["finish"]["facts"]] == ["f1", "f2"]
    assert data["decider"] == {"f2": {"question": "support", "option": "none"}}
    # retry_rounds 2, rounds_used 2, round_open false: no round was left.
    assert (data["rounds_left"], data["returned_before"]) == (0, [])


def test_a_changed_record_is_reported_field_by_field(tmp_path):
    export = copy_fixture(tmp_path)

    def change(record: dict[str, Any]) -> None:
        record["facts"][1]["strict_outcome"] = "pass"
        record["facts"][1]["drop_reason"] = None
        record["strict"]["counts"]["dropped"] = 0

    edit_check(export, change)
    got = recheck_strict_export(export, SETTINGS)["comparison"]
    assert got["agrees"] is False
    assert got["facts"][1]["agrees"] is False
    assert got["disagreements"] == [
        {"id": "f2", "field": "strict_outcome", "recorded": "pass", "recheck": "dropped"},
        {"id": "f2", "field": "drop_reason", "recorded": None, "recheck": "decider_drop"},
        {"id": None, "field": "counts.dropped", "recorded": 0, "recheck": 1},
    ]


def test_a_record_with_fewer_facts_is_a_disagreement(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r["facts"].pop())
    got = recheck_strict_export(export, SETTINGS)["comparison"]
    assert got["facts"][1]["recorded_found"] is False
    # The fact with no record gives no field rows: the count row is the disagreement.
    assert got["facts"][1]["agrees"] is None
    assert {"id": None, "field": "facts", "recorded": 1, "recheck": 2} in got["disagreements"]
    assert "f2" not in [row["id"] for row in got["disagreements"]]
    assert got["agrees"] is False


def test_an_export_without_a_strict_record_is_an_export_error(tmp_path):
    export = copy_fixture(tmp_path)
    (export / "check.json").unlink()
    with pytest.raises(ExportError):
        recheck_strict_export(export, SETTINGS)
    with pytest.raises(ExportError):
        strict_export_input(export, SETTINGS)


# --- the settings ------------------------------------------------------------------------------


def test_settings_without_a_strict_block_take_the_bundled_defaults():
    chosen = strict_settings(SETTINGS)
    assert chosen["strict_source"] == "bundled defaults"
    shared = VECTORS["cases"][0]["input"]["contract"]
    assert chosen["contract"]["strict"] == shared["strict"]
    assert chosen["contract"]["support_passes"] == shared["support_passes"]
    assert chosen["contract"]["min_quote_length"] == SETTINGS["min_quote_length"]
    assert chosen["redaction"] == VECTORS["redaction"]


def test_settings_shaped_like_associate_accuracy_version_2_are_used():
    settings = {
        **SETTINGS,
        "support_score": {"passes": ["all"]},
        "strict": {"keep_marked": ["part"], "drop": ["none", "little"], "mark_text": "m"},
        "redaction": {"replacement": "X", "patterns": []},
    }
    chosen = strict_settings(settings)
    assert chosen["strict_source"] == "settings"
    assert chosen["contract"]["strict"]["drop"] == ["none", "little"]
    assert chosen["contract"]["strict"]["derived_decides_drops"] is False
    assert chosen["contract"]["strict"]["derived_passes"] == []
    assert chosen["contract"]["support_passes"] == ["all"]
    assert chosen["redaction"]["replacement"] == "X"


def test_the_contract_values_change_the_outcome():
    settings = {**SETTINGS, "support_passes": ["none"], "strict": {"keep_marked": [], "drop": []}}
    got = recheck_strict_export(FIXTURE, settings)
    assert got["recheck"]["facts"][1]["strict_outcome"] == "pass"
    assert got["comparison"]["agrees"] is False


# --- exports built from the shared cases ------------------------------------------------------


def write_run(directory: Path, walk: list[dict], results: dict[str, str], extra=()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [{"format": {"name": "associate-walk", "version": 2}}, *walk, *extra]
    (directory / "walk.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    for name, text in results.items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text, encoding="utf-8")


def recorded_judge(fact: dict[str, Any]) -> Any:
    judge = fact["judge"]
    if judge is None:
        return None
    return {**judge, "judged": judge["option"] is not None, "confidence": None}


def write_export(
    tmp_path: Path, case: dict[str, Any], returned_before: bool = True
) -> tuple[Path, Any]:
    """An export holding the case; ``strict.returned_before`` is written unless told not to."""
    data, expect = case["input"], case["expect"]
    export = tmp_path / "run" / "export"
    child_lines = []
    for child in data["children"]:
        child_dir = tmp_path / "children" / child["label"]
        write_run(child_dir, child["walk"], child["results"])
        child_lines.append(
            {"child": {"id": child["label"], "child_walk": str(child_dir / "walk.jsonl")}}
        )
    write_run(export, data["walk"], data["results"], child_lines)
    prior = None
    if data["prior_runs"]:
        (label, run), *_ = data["prior_runs"].items()
        assert label == "prior"
        prior = tmp_path / "prior"
        write_run(prior, run["walk"], run["results"])
    (export / "facts.json").write_text(json.dumps(data["finish"]), encoding="utf-8")
    retry = data["contract"]["retry_rounds"]
    record = {
        "mode": "strict",
        "facts": [{**f, "judge": recorded_judge(f)} for f in expect["facts"]],
        "strict": {
            "retry_rounds": retry,
            "rounds_used": retry - data["rounds_left"],
            "round_open": False,
            "counts": expect["counts"],
            "drop_reasons": expect["drop_reasons"],
        },
    }
    if returned_before:
        record["strict"]["returned_before"] = sorted(data["returned_before"])
    (export / "check.json").write_text(json.dumps(record), encoding="utf-8")
    return export, prior


def case_settings(case: dict[str, Any]) -> dict[str, Any]:
    contract = case["input"]["contract"]
    return {
        **contract,
        "redaction": VECTORS["redaction"],
    }


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_an_export_built_from_a_shared_case_gives_the_case_result(tmp_path, case):
    export, prior = write_export(tmp_path, case)
    got = recheck_strict_export(
        export,
        case_settings(case),
        checkout_root=case["input"]["checkout_root"],
        continue_from=prior,
    )
    assert got["comparison"]["agrees"] is True, got["comparison"]["disagreements"]
    assert got["recheck"] == case["expect"]
    assert got["returned_before"] == case["input"]["returned_before"]
    assert got["returned_before_source"] == "check.json"


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_an_export_without_returned_before_still_gives_the_case_result(tmp_path, case):
    export, prior = write_export(tmp_path, case, returned_before=False)
    got = recheck_strict_export(
        export,
        case_settings(case),
        checkout_root=case["input"]["checkout_root"],
        continue_from=prior,
    )
    assert got["comparison"]["agrees"] is True, got["comparison"]["disagreements"]
    assert got["recheck"] == case["expect"]
    assert got["returned_before_source"] == "inferred from keep_marked"


# --- returned_before ---------------------------------------------------------------------


def kept_marked_export(tmp_path: Path, returned_before: Any) -> Path:
    """A fact recorded keep_marked while a round was left; the record names *returned_before*."""
    case = named_case("604_part_returned_before_kept_marked")
    assert case["input"]["rounds_left"] > 0
    export, _ = write_export(tmp_path, case, returned_before=False)
    if returned_before is not None:
        edit_check(export, lambda r: r["strict"].update(returned_before=returned_before))
    return export


def named_case(name: str) -> dict[str, Any]:
    return next(c for c in VECTORS["cases"] if c["name"] == name)


def recheck_case(export: Path, name: str) -> dict[str, Any]:
    return recheck_strict_export(export, case_settings(named_case(name)))


def test_a_recorded_returned_before_is_used_and_named(tmp_path):
    case = named_case("604_part_returned_before_kept_marked")
    export = kept_marked_export(tmp_path, case["input"]["returned_before"])
    got = recheck_case(export, case["name"])
    assert got["returned_before"] == case["input"]["returned_before"]
    assert got["returned_before_source"] == "check.json"
    assert got["comparison"]["agrees"] is True


def test_a_recorded_returned_before_can_disagree_on_keep_marked(tmp_path):
    # The record says keep_marked, a round was left, and the fact was not returned before.
    export = kept_marked_export(tmp_path, [])
    got = recheck_case(export, "604_part_returned_before_kept_marked")
    assert got["returned_before"] == []
    assert got["comparison"]["agrees"] is False
    (row,) = [d for d in got["comparison"]["disagreements"] if d["field"] == "strict_outcome"]
    assert (row["recorded"], row["recheck"]) == ("keep_marked", "returned")


def test_without_returned_before_keep_marked_cannot_disagree(tmp_path):
    export = kept_marked_export(tmp_path, None)
    got = recheck_case(export, "604_part_returned_before_kept_marked")
    assert got["returned_before_source"] == "inferred from keep_marked"
    assert got["returned_before"] == ["f1"]
    assert got["comparison"]["agrees"] is True


@pytest.mark.parametrize("bad", ["f1", [1], {"f1": True}, None], ids=repr)
def test_a_malformed_returned_before_counts_as_not_recorded(tmp_path, bad):
    export = kept_marked_export(tmp_path, [])
    edit_check(export, lambda r: r["strict"].update(returned_before=bad))
    got = recheck_case(export, "604_part_returned_before_kept_marked")
    assert got["returned_before_source"] == "inferred from keep_marked"
    assert got["comparison"]["agrees"] is True


def test_the_input_names_where_returned_before_came_from(tmp_path):
    export = kept_marked_export(tmp_path, ["f1", "f9"])
    settings = case_settings(named_case("604_part_returned_before_kept_marked"))
    assert strict_export_input(export, settings)["returned_before"] == ["f1", "f9"]


# --- a saved result under the entry's own name ---------------------------------------------


def test_an_own_result_file_is_not_read_through_a_link_outside_the_export(tmp_path):
    case = named_case("saved_result_file_read")
    export, _ = write_export(tmp_path, case)
    outside = tmp_path / "outside.txt"
    outside.write_text(case["input"]["results"]["results/w4.txt"], encoding="utf-8")
    (export / "results" / "w4.txt").unlink()
    (export / "results" / "w4.txt").symlink_to(outside)
    got = recheck_strict_export(export, case_settings(case))["recheck"]["facts"]
    by_id = {fact["id"]: fact["drop_reason"] for fact in got}
    assert by_id["f8"] == "no_saved_text"


def test_the_loader_names_the_saved_files_it_read(tmp_path):
    case = named_case("saved_result_file_read")
    export, _ = write_export(tmp_path, case)
    loaded = load_export(export)
    assert set(loaded["result_files"]) == {"results/w1.txt", "results/w4.txt"}
    # ``results`` is unchanged: walk id to the text of the file its entry names.
    assert set(loaded["results"]) == {"w3"}


# --- the routing -----------------------------------------------------------------------


def test_inspect_export_routes_a_strict_export_and_says_so():
    got = inspect_export(FIXTURE, SETTINGS)
    assert got["check"] == "strict"
    assert got["applicable"] is True
    assert [f["drop_reason"] for f in got["facts"]] == [None, "decider_drop"]
    assert got["report"]["dropped"]["by_reason"] == {"decider_drop": 1}
    assert got["strict"]["comparison"]["agrees"] is True
    assert len(got["calls"]) == 4


def test_a_non_strict_export_has_no_check_key(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r.update(mode="report"))
    got = inspect_export(export, SETTINGS)
    assert "check" not in got
    assert "strict" not in got
    # Read by the quote check, a strict fact (``at``, no quote) has an empty quote.
    assert {f["reason"] for f in got["facts"]} == {"quote_short"}


def test_accuracy_result_names_the_strict_check():
    got = accuracy_result(FIXTURE, SETTINGS)["accuracy"]
    assert got["check"] == "strict"
    assert got["python_recheck_verdict"] == "accepted"
    assert got["report"]["unchecked_text"] == {"summary_sentences": 1, "final_message_sentences": 0}


def test_the_compared_fields_are_named():
    assert strict_export.STRICT_MODE == "strict"
    assert strict_export.COMPARED_FIELDS == ("kind_checked", "strict_outcome", "drop_reason")


# --- review findings -------------------------------------------------------------------------


def test_verdicts_open_items_accepted_and_judge_counts_are_compared(tmp_path):
    case = next(c for c in VECTORS["cases"] if c["name"] == "verdicts_on_dropped_facts")
    export, prior = write_export(tmp_path, case)
    path = export / "check.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["verdicts"] = [dict(v) for v in case["expect"]["verdicts"]]
    record["open_items"] = [dict(v) for v in case["expect"]["open_items"]]
    record["accepted"] = False  # v1 is refused by the checker
    record["strict"]["judge_counts"] = dict(case["expect"]["judge_counts"])
    path.write_text(json.dumps(record), encoding="utf-8")
    settings = case_settings(case)
    got = recheck_strict_export(export, settings)["comparison"]
    assert got["agrees"] is True, got["disagreements"]
    assert got["not_compared"] == []
    assert set(got["compared"]) >= {"facts", "verdicts", "open_items", "accepted", "judge_counts"}

    record["verdicts"][3]["strict_outcome"] = "dropped"
    record["open_items"][0]["strict_reason"] = None
    record["accepted"] = True
    record["strict"]["judge_counts"]["llm_judged"] = 0
    path.write_text(json.dumps(record), encoding="utf-8")
    found = recheck_strict_export(export, settings)["comparison"]["disagreements"]
    assert {
        "id": "v4",
        "field": "verdicts.strict_outcome",
        "recorded": "dropped",
        "recheck": "pass",
    } in found
    assert {
        "id": "o1",
        "field": "open_items.strict_reason",
        "recorded": None,
        "recheck": "basis_dropped",
    } in found
    assert {"id": None, "field": "accepted", "recorded": True, "recheck": False} in found
    assert {"id": None, "field": "judge_counts.llm_judged", "recorded": 0, "recheck": 2} in found


def test_parts_absent_from_the_record_are_named_as_not_compared(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: (r["strict"].pop("judge_counts"), r.pop("open_items")))
    got = recheck_strict_export(export, SETTINGS)["comparison"]
    assert got["agrees"] is True
    assert got["not_compared"] == ["open_items", "judge_counts"]
    assert "open_items" not in got["compared"]


@pytest.mark.parametrize(
    "bad",
    [{"strict_outcome": "pass"}, {"id": 7}, "not an object"],
    ids=["no id", "id not a string", "not an object"],
)
def test_a_malformed_fact_record_is_an_export_error(tmp_path, bad):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r["facts"].append(bad))
    with pytest.raises(ExportError, match="check.json fact record 3"):
        recheck_strict_export(export, SETTINGS)


def test_a_facts_value_that_is_not_a_list_is_an_export_error(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r.update(facts={"f1": {}}))
    with pytest.raises(ExportError, match="facts is not a list"):
        recheck_strict_export(export, SETTINGS)


def test_a_strict_block_is_used_without_a_support_pass_list():
    settings = {**SETTINGS, "strict": {"keep_marked": [], "drop": ["part"]}}
    chosen = strict_settings(settings)
    assert chosen["strict_source"] == "settings"
    assert chosen["contract"]["strict"]["drop"] == ["part"]


#: The two shared cases that set their own strict block (see associate's rules note).
OWN_STRICT_BLOCK = ("derived_decides_drops_true", "derived_passes_absent_fails_closed")


def test_the_two_cases_with_their_own_strict_block_differ_from_the_defaults():
    defaults = load_strict_defaults()
    for name in OWN_STRICT_BLOCK:
        assert named_case(name)["input"]["contract"]["strict"] != defaults["strict"], name


def test_the_bundled_strict_defaults_are_what_every_other_shared_case_uses():
    defaults = load_strict_defaults()
    for case in VECTORS["cases"]:
        if case["name"] in OWN_STRICT_BLOCK:
            continue
        contract = case["input"]["contract"]
        assert defaults["strict"] == contract["strict"], case["name"]
        assert defaults["support_passes"] == contract["support_passes"], case["name"]
    assert defaults["redaction"] == VECTORS["redaction"]
    assert strict_settings(SETTINGS)["strict_source"] == "bundled defaults"


def test_the_export_path_does_not_load_the_shared_cases(monkeypatch):
    def refuse():
        raise AssertionError("the shared cases were loaded")

    monkeypatch.setattr(strict_export, "load_strict_vectors", refuse, raising=False)
    monkeypatch.setattr("evidence.accuracy.vectors.load_strict_vectors", refuse)
    assert recheck_strict_export(FIXTURE, SETTINGS)["comparison"]["agrees"] is True


def test_check_json_is_read_once_per_export(monkeypatch):
    calls = []
    original = strict_export.read_check_record

    def counting(export_dir):
        calls.append(export_dir)
        return original(export_dir)

    monkeypatch.setattr(strict_export, "read_check_record", counting)
    recheck_strict_export(FIXTURE, SETTINGS)
    assert len(calls) == 1
    calls.clear()
    inspect_export(FIXTURE, SETTINGS)
    assert len(calls) == 1


def test_a_redaction_pattern_python_cannot_compile_is_an_export_error():
    settings = {**SETTINGS, "redaction": {"replacement": "X", "patterns": ["(?<name>secret)"]}}
    with pytest.raises(ExportError, match=r"\(\?<name>secret\)"):
        recheck_strict_export(FIXTURE, settings)


def test_two_facts_with_one_id_keep_their_own_stored_answers(tmp_path):
    export = copy_fixture(tmp_path)
    facts = json.loads((export / "facts.json").read_text(encoding="utf-8"))
    second = {**facts["facts"][1], "id": "f2", "at": {"lines": [3, 3]}, "value": "the intake role"}
    facts["facts"].append(second)
    (export / "facts.json").write_text(json.dumps(facts), encoding="utf-8")

    def change(record):
        twin = json.loads(json.dumps(record["facts"][1]))
        twin["judge"]["option"] = "all"
        twin["strict_outcome"], twin["drop_reason"], twin["status"] = "pass", None, "judged"
        record["facts"].append(twin)
        record["strict"]["counts"]["pass"] = 2
        record["strict"]["judge_counts"]["llm_judged"] = 2

    edit_check(export, change)
    got = recheck_strict_export(export, SETTINGS)
    outcomes = [f["strict_outcome"] for f in got["recheck"]["facts"]]
    assert outcomes == ["pass", "dropped", "pass"]
    assert got["comparison"]["agrees"] is True, got["comparison"]["disagreements"]


def test_answers_fall_back_to_ids_when_positions_do_not_align(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r["facts"].reverse())
    got = recheck_strict_export(export, SETTINGS)
    assert [f["strict_outcome"] for f in got["recheck"]["facts"]] == ["pass", "dropped"]


# --- issue 8: absent parts, no facts file, the comparison from accuracy_result ---------------

NOTHING_COMPARED = "nothing in check.json could be compared"
ALL_PARTS = list(strict_export.PARTS)


def reduced_export(tmp_path: Path) -> Path:
    export = copy_fixture(tmp_path)
    (export / "check.json").write_text('{"mode": "strict", "strict": []}', encoding="utf-8")
    return export


def test_a_record_holding_no_part_is_neither_agreement_nor_disagreement(tmp_path):
    got = recheck_strict_export(reduced_export(tmp_path), SETTINGS)["comparison"]
    assert got["agrees"] is None
    assert got["agrees_reason"] == NOTHING_COMPARED
    assert got["disagreements"] == []
    assert got["compared"] == []
    assert got["not_compared"] == ALL_PARTS


def test_a_fact_with_no_record_has_no_verdict_of_its_own(tmp_path):
    rows = recheck_strict_export(reduced_export(tmp_path), SETTINGS)["comparison"]["facts"]
    assert [row["id"] for row in rows] == ["f1", "f2"]
    assert [row["agrees"] for row in rows] == [None, None]
    assert {field["agree"] for row in rows for field in row["fields"].values()} == {None}


def test_an_absent_facts_part_gives_no_rows_while_other_parts_are_compared(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r.pop("facts"))
    got = recheck_strict_export(export, SETTINGS)["comparison"]
    # The stored answers went with the facts part: only the checker's verdict is compared.
    assert got["compared"] == ["accepted"]
    assert got["not_compared"] == [part for part in ALL_PARTS if part != "accepted"]
    assert got["disagreements"] == []
    assert got["agrees"] is True
    assert got["agrees_reason"] is None


def test_a_compared_part_still_disagrees_when_facts_are_absent(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: (r.pop("facts"), r.update(accepted=False)))
    got = recheck_strict_export(export, SETTINGS)["comparison"]
    assert got["agrees"] is False
    assert got["disagreements"] == [
        {"id": None, "field": "accepted", "recorded": False, "recheck": True}
    ]


def test_a_compared_record_has_no_reason(tmp_path):
    got = recheck_strict_export(FIXTURE, SETTINGS)
    assert got["comparison"]["agrees_reason"] is None
    assert got["applicable"] is True
    assert got["not_applicable_reason"] is None


def test_no_disagreement_row_holds_two_equal_values(tmp_path):
    export = copy_fixture(tmp_path)

    def change(record: dict[str, Any]) -> None:
        record["facts"][0] = {"id": "f1"}
        record["strict"]["counts"]["pass"] = 5

    edit_check(export, change)
    found = recheck_strict_export(export, SETTINGS)["comparison"]["disagreements"]
    assert found
    assert all(row["recorded"] != row["recheck"] for row in found)
    assert "drop_reason" not in [row["field"] for row in found]


def test_a_strict_export_without_facts_is_not_applicable_from_both(tmp_path):
    export = copy_fixture(tmp_path)
    (export / "facts.json").unlink()
    inspected = inspect_export(export, SETTINGS)
    rechecked = recheck_strict_export(export, SETTINGS)
    assert inspected["applicable"] is False
    assert rechecked["applicable"] is False
    assert rechecked["not_applicable_reason"] == inspected["not_applicable_reason"]
    assert "facts.json" in rechecked["not_applicable_reason"]


def test_a_not_applicable_recheck_compares_nothing(tmp_path):
    export = copy_fixture(tmp_path)
    (export / "facts.json").unlink()
    got = recheck_strict_export(export, SETTINGS)
    assert got["check"] == "strict"
    assert got["recheck"] is None
    assert got["accepted"] is None
    comparison = got["comparison"]
    assert comparison["agrees"] is None
    assert comparison["agrees_reason"] == got["not_applicable_reason"]
    assert (comparison["compared"], comparison["not_compared"]) == ([], ALL_PARTS)
    assert (comparison["facts"], comparison["disagreements"]) == ([], [])


def test_loaded_data_without_file_names_is_still_re_checked():
    loaded = dict(load_handback_input(FIXTURE))
    del loaded["result_files"]
    got = strict_export.recheck_loaded(FIXTURE, loaded, SETTINGS)
    assert got["comparison"]["agrees"] is True
    assert got == recheck_strict_export(FIXTURE, SETTINGS)


def test_accuracy_result_is_unchanged_by_default():
    got = accuracy_result(FIXTURE, SETTINGS)
    assert sorted(got) == ["accuracy", "answer", "answer_path", "check_mode", "handback_outcome"]


def test_accuracy_result_can_carry_the_strict_re_check(monkeypatch):
    runs = []
    real = strict_export.recheck_with_checker

    def counting(case_input, redaction):
        runs.append(1)
        return real(case_input, redaction)

    monkeypatch.setattr(strict_export, "recheck_with_checker", counting)
    got = accuracy_result(FIXTURE, SETTINGS, with_strict=True)
    assert len(runs) == 1
    assert got["strict"]["comparison"]["agrees"] is True
    assert got["strict"] == recheck_strict_export(FIXTURE, SETTINGS)
    assert got["accuracy"] == accuracy_result(FIXTURE, SETTINGS)["accuracy"]


def test_accuracy_result_with_strict_is_none_for_a_plain_export(tmp_path):
    export = copy_fixture(tmp_path)
    edit_check(export, lambda r: r.update(mode="report"))
    got = accuracy_result(export, SETTINGS, with_strict=True)
    assert got["strict"] is None


def test_accuracy_result_with_strict_is_none_without_facts(tmp_path):
    export = copy_fixture(tmp_path)
    (export / "facts.json").unlink()
    got = accuracy_result(export, SETTINGS, with_strict=True)
    assert got["strict"] is None
    assert "facts.json" in got["accuracy"]["not_applicable_reason"]
