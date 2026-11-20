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
)
from evidence.accuracy.strict_export import (
    is_strict_export,
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
    assert {"id": None, "field": "facts", "recorded": 1, "recheck": 2} in got["disagreements"]


def test_an_export_without_a_strict_record_is_an_export_error(tmp_path):
    export = copy_fixture(tmp_path)
    (export / "check.json").unlink()
    with pytest.raises(ExportError):
        recheck_strict_export(export, SETTINGS)
    with pytest.raises(ExportError):
        strict_export_input(export, SETTINGS)


# --- the settings ------------------------------------------------------------------------------


def test_settings_without_a_strict_block_take_the_shared_contract():
    chosen = strict_settings(SETTINGS)
    assert chosen["strict_source"] == "shared cases"
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


def write_export(tmp_path: Path, case: dict[str, Any]) -> tuple[Path, Any]:
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
