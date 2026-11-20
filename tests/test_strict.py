"""The strict re-check beyond the shared cases: behaviour the extension has that no case shows.

Each test starts from a shared case's input and changes one thing. Where the
note (associate's ``docs/notes/strict-vectors.md``) does not say what happens,
the expectation here is what associate's TypeScript does (``lib/strict.ts``,
``lib/facts.ts``, ``lib/evidence.ts``, ``lib/judge.ts``).
"""

from __future__ import annotations

import copy
from typing import Any

from evidence.accuracy.command import js_items, js_trim, render_command
from evidence.accuracy.pointer import SAVED_NAME, number_tokens, resolve, split_lines
from evidence.accuracy.strict import strict_recheck
from evidence.accuracy.vectors import load_strict_vectors

VECTORS = load_strict_vectors()
REDACTION = VECTORS["redaction"]
ROOT = "/srv/someone/git/proj"


def case_input(name: str) -> dict[str, Any]:
    return copy.deepcopy(next(c["input"] for c in VECTORS["cases"] if c["name"] == name))


def facts_of(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in result["facts"]}


def run(data: dict[str, Any]) -> dict[str, Any]:
    return strict_recheck(data, REDACTION)


# --- the decider step ----------------------------------------------------------------------


def test_a_derived_fact_whose_listed_facts_hold_nothing_is_not_judged_with_no_inputs():
    data = case_input("derived_each_answer")
    data["finish"]["facts"] = [
        {"id": "f1", "source": "w1", "at": {"lines": [1, 1]}},
        {
            "id": "f2",
            "kind": "derived",
            "source": "w1",
            "at": {"lines": [1, 1]},
            "value": "big",
            "based_on": ["f1"],
        },
    ]
    data["results"]["results/w1.txt"] = " \n"
    data["decider"] = {}
    f2 = facts_of(run(data))["f2"]
    assert f2["status"] == "not_judged"
    assert f2["judge"] == {"question": "derived", "option": None, "reason": "no_inputs"}
    assert f2["sent"] is None


def test_a_worded_fact_whose_copied_lines_are_blank_is_not_judged_with_no_evidence():
    data = case_input("worded_all_pass")
    data["results"]["results/w1.txt"] = "alpha\n\nbeta\n"
    data["finish"]["facts"] = [{"id": "f1", "source": "w1", "at": {"lines": [2, 2]}, "value": "x"}]
    data["decider"] = {"f1": {"question": "support", "option": "all"}}
    f1 = facts_of(run(data))["f1"]
    assert f1["worded"] is True
    assert f1["judge"] == {"question": "support", "option": None, "reason": "no_evidence"}
    assert f1["strict_outcome"] == "not_judged"


def test_a_sent_fact_with_no_stored_answer_is_not_judged():
    data = case_input("worded_all_pass")
    data["decider"] = {}
    f1 = facts_of(run(data))["f1"]
    assert f1["judge"]["reason"] == "no_stored_answer"
    assert f1["sent"] is not None
    assert f1["strict_outcome"] == "not_judged"


def test_derived_decides_drops_true_passes_only_the_derived_passes():
    data = case_input("derived_each_answer")
    data["contract"]["strict"]["derived_decides_drops"] = True
    by_id = facts_of(run(data))
    assert by_id["f2"]["strict_outcome"] == by_id["f5"]["strict_outcome"] == "pass"  # yes, mostly
    for fid in ("f3", "f4", "f6"):  # partly, no, little
        assert by_id[fid]["drop_reason"] == "decider_drop"


def test_derived_decides_drops_true_without_derived_passes_fails_closed():
    data = case_input("derived_each_answer")
    data["contract"]["strict"]["derived_decides_drops"] = True
    del data["contract"]["strict"]["derived_passes"]
    by_id = facts_of(run(data))
    assert {by_id[f]["drop_reason"] for f in ("f2", "f3", "f4", "f5", "f6")} == {"decider_drop"}


def test_a_support_answer_in_no_list_passes():
    data = case_input("worded_all_pass")
    data["decider"] = {"f1": {"question": "support", "option": "something else"}}
    assert facts_of(run(data))["f1"]["strict_outcome"] == "pass"


# --- unchecked facts and the cascade ---------------------------------------------------------


def test_an_unchecked_fact_resting_on_a_failed_fact_is_dropped_by_the_cascade():
    data = case_input("old_shape_found_direct")
    data["finish"]["facts"] = [
        {"id": "f1", "source": "w1", "at": {"lines": [9, 9]}},
        {"id": "f2", "source": "w9", "quote": "anything at all", "value": "a", "based_on": ["f1"]},
    ]
    data["walk"].append({"id": "w9", "tool": "ls", "args": {"purpose": "x"}})
    f2 = facts_of(run(data))["f2"]
    assert (f2["status"], f2["drop_reason"], f2["dropped_by"]) == (
        "dropped",
        "based_on_failed",
        "f1",
    )


def test_a_graph_failure_replaces_unchecked():
    data = case_input("old_shape_found_direct")
    data["walk"].append({"id": "w9", "tool": "ls", "args": {"purpose": "x"}})
    data["finish"]["facts"] = [
        {"id": "f1", "source": "w9", "quote": "anything at all", "value": "a", "based_on": ["f7"]},
    ]
    result = run(data)
    f1 = facts_of(result)["f1"]
    assert (f1["status"], f1["drop_reason"]) == ("failed", "based_on_unknown")
    assert result["graph"]["refusals"] == [
        {"reason": "based_on_unknown", "fact": "f1", "ids": ["f7"]}
    ]


def test_a_worded_fact_resting_on_an_unchecked_fact_is_sent_then_dropped():
    data = case_input("worded_all_pass")
    data["walk"].append({"id": "w9", "tool": "ls", "args": {"purpose": "x"}})
    data["finish"]["facts"] = [
        {"id": "f0", "source": "w9", "quote": "anything at all", "value": "a"},
        {**data["finish"]["facts"][0], "based_on": ["f0"]},
    ]
    f1 = facts_of(run(data))["f1"]
    assert f1["judge"]["option"] == "all"
    assert (f1["status"], f1["dropped_by"]) == ("dropped", "f0")
    assert run(data)["judge_counts"]["llm_judged"] == 1


# --- the contract and sources ----------------------------------------------------------------


def test_a_broken_min_quote_length_fails_every_fact_closed():
    data = case_input("verdicts_on_dropped_facts")
    data["contract"]["min_quote_length"] = 0
    result = run(data)
    assert {f["drop_reason"] for f in result["facts"]} == {"quote_short"}
    assert {v["reason"] for v in result["verdicts"]} == {"basis_refused"}


def test_a_label_carried_by_a_prior_run_and_a_child_is_unknown():
    data = case_input("prior_source_present")
    data["children"] = [{"label": "prior", **data["prior_runs"]["prior"]}]
    assert facts_of(run(data))["f1"]["drop_reason"] == "source_unknown"


def test_an_old_shape_fact_reads_the_saved_result_of_its_walk_id():
    data = case_input("old_shape_found_direct")
    for entry in data["walk"]:
        entry.pop("saved_result", None)
    assert facts_of(run(data))["f1"]["status"] == "passed"


def test_a_pointer_reads_only_a_results_wn_saved_result():
    data = case_input("lines_pointer_no_value")
    data["walk"][0]["saved_result"] = "elsewhere/w1.txt"
    data["results"]["elsewhere/w1.txt"] = data["results"]["results/w1.txt"]
    assert facts_of(run(data))["f1"]["drop_reason"] == "no_saved_result"


def test_the_number_rule_reads_only_a_string_value():
    data = case_input("number_absent")
    data["finish"]["facts"][0]["value"] = 999
    f1 = facts_of(run(data))["f1"]
    assert f1["status"] == "passed"
    assert f1["worded"] is False


def test_an_open_item_without_a_check_is_dropped_with_the_checker_reason():
    data = case_input("verdicts_on_dropped_facts")
    data["finish"]["open_items"] = [{"id": "o1", "text": "?", "basis": ["f4"]}]
    (item,) = run(data)["open_items"]
    assert (item["outcome"], item["strict_reason"]) == ("refused", "open_without_check")


# --- the pointer ----------------------------------------------------------------------------


def test_split_lines_keeps_carriage_returns_and_drops_one_trailing_newline():
    assert split_lines("") == []
    assert split_lines("a\r\nb\n") == ["a\r", "b"]
    assert split_lines("a\n\n") == ["a", ""]


def test_a_search_on_a_stamped_read_reports_the_count_of_an_unstamped_line():
    located, reason = resolve({"search": "tail"}, "10\tone\ntail text\n", "read", False)
    assert reason is None
    assert (located.first, located.last) == (2, 2)


def test_a_stamp_is_matched_as_written():
    _, reason = resolve({"lines": [7, 7]}, "007\tseven\n008\teight\n", "read", False)
    assert reason == "pointer_out_of_range"


def test_a_partial_stamped_read_past_the_last_stamp_is_cut():
    text = "10\tone\n11\ttwo\n12\tthr"
    assert resolve({"lines": [13, 13]}, text, "read", True) == (None, "result_cut")
    assert resolve({"lines": [5, 5]}, text, "read", True) == (None, "pointer_out_of_range")


def test_a_pointer_with_both_or_neither_key_is_malformed():
    for at in ({"lines": [1, 1], "search": "a"}, {}, {"lines": [2, 1]}, {"search": " \u3000"}):
        assert resolve(at, "a\n", "ls", False) == (None, "pointer_malformed")


def test_number_tokens_follow_the_note():
    assert number_tokens("1,234 and 0.50 in w12, v1.5.2") == ["1234", "0.50", "12", "1.5", "2"]
    assert number_tokens("\u0661\u0662\u0663") == []


def test_js_trim_keeps_what_python_strip_would_remove():
    assert js_trim("\x1c a \x85") == "\x1c a \x85"
    assert js_trim("\u3000a\ufeff") == "a"


# --- the command --------------------------------------------------------------------------------


def command(entry: dict[str, Any], root: str = ROOT) -> str:
    return render_command(entry, root, REDACTION)[0]


def test_a_run_worktree_root_prints_paths_of_the_main_checkout_relative():
    root = "/srv/someone/git/.worktrees.proj/run-7/"
    entry = {"tool": "ls", "args_used": {"path": "/srv/someone/git/proj/lib", "b": f"{root}x"}}
    assert command(entry, root) == "ls path=lib b=x"


def test_a_root_alone_or_before_a_quote_or_backtick_prints_a_dot():
    entry = {"tool": "grep", "args_used": {"a": ROOT, "b": f"{ROOT}/`", "c": f"{ROOT}/ x"}}
    assert command(entry) == 'grep a=. b=".`" c=". x"'


def test_a_relative_root_rewrites_no_checkout_path():
    entry = {"tool": "ls", "args_used": {"path": "/root/git/proj/lib"}}
    assert command(entry, "proj") == "ls path=~/git/proj/lib"


def test_an_object_key_is_redacted_but_not_rewritten():
    entry = {"tool": "x", "args_used": {"opts": {"/srv/someone/git/proj/k": 1, "token=abc": 2}}}
    assert command(entry) == 'x opts={"/srv/someone/git/proj/k":1,"[REDACTED]":2}'


def test_array_index_keys_come_first_as_in_ecmascript():
    assert [k for k, _ in js_items({"b": 1, "10": 2, "2": 3, "01": 4})] == ["2", "10", "b", "01"]
    assert command({"tool": "x", "args_used": {"b": 1, "2": True}}) == "x 2=true b=1"


def test_a_read_window_prints_one_and_end_for_a_missing_bound():
    entry = {"tool": "read", "args": {"path": "/root/a b", "end_line": 9.0, "purpose": "p"}}
    assert render_command(entry, ROOT, REDACTION) == ('read "~/a b" lines 1-9', "args")


def test_bash_without_a_string_argv_prints_its_keys():
    entry = {"tool": "bash", "args_used": {"argv": ["ls", 3], "cwd": "  "}}
    assert command(entry) == 'bash argv=["ls",3] cwd="  "'


def test_a_tool_with_no_arguments_prints_its_name_alone():
    assert command({"tool": "finish", "args": {"purpose": "done"}}) == "finish"


# --- ASCII digits only ------------------------------------------------------------


def test_a_saved_result_name_with_a_non_ascii_digit_is_not_read():
    assert SAVED_NAME.fullmatch("results/w12.txt") is not None
    for digit in ("\uff11", "\u0661"):  # fullwidth one, Arabic-Indic one
        assert SAVED_NAME.fullmatch(f"results/w1{digit}.txt") is None


def test_an_array_index_key_is_ascii_digits_only():
    assert [k for k, _ in js_items({"b": 1, "12": 2})] == ["12", "b"]
    for digit in ("\uff11", "\u0661"):
        key = f"1{digit}"
        assert [k for k, _ in js_items({"b": 1, key: 2})] == ["b", key]


def test_a_redaction_pattern_python_cannot_compile_names_the_pattern():
    import pytest

    redaction = {"replacement": "X", "patterns": ["(?<name>secret)"]}
    with pytest.raises(ValueError, match=r"\(\?<name>secret\)"):
        render_command({"tool": "ls", "args": {}}, ROOT, redaction)


def test_a_stored_answer_by_position_wins_over_one_by_id():
    data = case_input("worded_all_pass")
    fact = data["finish"]["facts"][0]
    data["finish"]["facts"] = [fact, dict(fact)]
    data["decider"] = {"f1": {"question": "support", "option": "none"}}
    data["decider_by_position"] = [None, {"question": "support", "option": "all"}]
    outcomes = [f["strict_outcome"] for f in run(data)["facts"]]
    assert outcomes == ["dropped", "pass"]
