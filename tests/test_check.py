"""The hand-back checker and the export loader (moved from associate at commit 266dad3).

Ported from associate's ``tests/test_accuracy_check.py``: the checker parts run
unchanged in what they assert; the parts that went through the ``associate
check`` verb now call :func:`inspect_export` / :func:`load_export` directly (the
command module is another task). Added here: the bundled default settings and
their loader, unsupported (newer) walk formats, and the no-``associate`` import
rule.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from importlib import import_module, resources
from pathlib import Path

import pytest

from evidence.accuracy import check as check_mod
from evidence.accuracy.check import check_handback, literal_of
from evidence.accuracy.counts import count_fact, empty_counts
from evidence.accuracy.vectors import load_matcher_vectors

ACCURACY, ACCURACY_VERSION = check_mod.load_default_settings()
VECTORS = load_matcher_vectors()

#: sha256 of associate/contract/accuracy.json at associate commit 266dad3.
ASSOCIATE_ACCURACY_SHA256 = "b44bd3678b2cf08df1e63b3036e4452599b7803699609e377f6532eb2488c374"


def project(got):
    """The fields the shared vectors compare (fix texts are not compared)."""
    return {
        "accepted": got["accepted"],
        "facts": [
            {
                k: f[k]
                for k in (
                    "id",
                    "run",
                    "verdict",
                    "reason",
                    "check",
                    "nearest",
                    "source_kind",
                    "first_hand",
                )
            }
            for f in got["facts"]
        ],
        "verdicts": [
            {k: v[k] for k in ("id", "outcome", "reason", "check")} for v in got["verdicts"]
        ],
        "open_items": [
            {k: v[k] for k in ("id", "outcome", "reason", "check")} for v in got["open_items"]
        ],
        "report": got["report"],
    }


def test_the_shared_vectors_hold_handback_cases():
    assert len(VECTORS["handback_cases"]) >= 1


@pytest.mark.parametrize("case", VECTORS["handback_cases"], ids=lambda c: c["name"][:50])
def test_python_checker_reproduces_every_handback_vector(case):
    assert project(check_handback(case["input"], ACCURACY)) == case["expect"]


# --- the bundled default settings ---------------------------------------------------


def test_the_default_settings_loader_returns_the_bundled_file_and_its_version():
    settings, version = check_mod.load_default_settings()
    text = resources.files("evidence").joinpath("data/accuracy_defaults.json").read_text("utf-8")
    assert settings == json.loads(text)
    assert version == settings["version"] == 1
    assert isinstance(version, int)


def test_the_bundled_settings_are_byte_identical_to_associate_at_266dad3():
    data = resources.files("evidence").joinpath("data/accuracy_defaults.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == ASSOCIATE_ACCURACY_SHA256


def test_the_default_settings_loader_returns_a_fresh_copy():
    settings, _ = check_mod.load_default_settings()
    settings["min_quote_length"] = 999
    assert check_mod.load_default_settings()[0]["min_quote_length"] == 8


# --- review fixes: number and boolean literals, a broken contract, malformed children --------


@pytest.mark.parametrize("case", VECTORS["literal_cases"], ids=lambda c: repr(c["value"]))
def test_literal_of_matches_the_shared_literal_cases(case):
    assert literal_of(case["value"]) == case["literal"]


def test_literal_of_treats_non_finite_and_overflowing_numbers_as_no_literal():
    assert literal_of(float("inf")) is None
    assert literal_of(float("nan")) is None
    assert literal_of(10**400) is None


@pytest.mark.parametrize("case", VECTORS["contract_cases"], ids=lambda c: c["name"])
def test_a_broken_min_quote_length_fails_closed_as_in_typescript(case):
    contract = dict(ACCURACY)
    if "min_quote_length" in case:
        contract["min_quote_length"] = case["min_quote_length"]
    else:
        del contract["min_quote_length"]
    got = check_handback(VECTORS["contract_input"], contract)
    summary = {
        "accepted": got["accepted"],
        "facts": [{k: f[k] for k in ("id", "verdict", "reason", "check")} for f in got["facts"]],
        "verdicts": [
            {k: v[k] for k in ("id", "outcome", "reason", "check")} for v in got["verdicts"]
        ],
        "flags": got["report"]["flags"],
    }
    assert summary == case["expect"]


def test_a_child_label_with_a_trailing_newline_is_skipped():
    handback = {
        "payload": {"facts": []},
        "entries": [],
        "results": {},
        "children": [{"label": "c1\n", "payload": {}, "entries": [], "results": {}}],
    }
    assert check_handback(handback, ACCURACY)["report"]["children"] == []


# --- a fixture export with a hand count -------------------------------------------

FORMAT_LINE = {"format": {"name": "associate-walk", "version": 2}}


def entry(n, tool, kind, *, saved=True, purpose=None, **extra):
    e = {
        "id": f"w{n}",
        "ts": "2026-11-17T10:00:00Z",
        "tool": tool,
        "args": {},
        "result": {},
        "truncated": False,
        "source_kind": kind,
    }
    if purpose is not None:
        e["purpose"] = purpose
    if saved:
        e["saved_result"] = f"results/w{n}.txt"
    e.update(extra)
    return e


def write_export(root, entries, results, facts=None, *, marker=True, name="export"):
    export = root / name
    (export / "results").mkdir(parents=True)
    if marker is True:
        marker_lines = [FORMAT_LINE]
    elif marker:
        marker_lines = [marker]
    else:
        marker_lines = []
    lines = (
        marker_lines
        + entries
        + [
            {
                "run": {
                    "duration_ms": 1,
                    "tool_calls": len(entries),
                    "outcome": "ok",
                    "truncated": False,
                }
            }
        ]
    )
    (export / "walk.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
    )
    for n, text in results.items():
        (export / "results" / f"w{n}.txt").write_text(text, encoding="utf-8")
    if facts is not None:
        (export / check_mod.FACTS_FILENAME).write_text(json.dumps(facts), encoding="utf-8")
    return export


def fixture_entries():
    return [
        entry(1, "read", "file", purpose="read the config"),
        entry(2, "grep", "tool", saved=False, purpose="find the call"),
        entry(3, "bash", "tool", purpose="run the check"),
        entry(4, "ledger_append", "tool", saved=False, error="refused: gate", partial=True),
    ]


FIXTURE_RESULTS = {1: "The quick brown fox jumps over the lazy dog", 3: "tests passed: 12 of 12"}
FIXTURE_FACTS = {
    "facts": [
        {"id": "f1", "value": "lazy", "source": "w1", "quote": "over the lazy dog"},  # passed
        {"id": "f2", "value": "leaps", "source": "w1", "quote": "brown fox leaps"},  # refused
        {"id": "f3", "value": "hit", "source": "w2", "quote": "some grep output"},  # unchecked
        {"id": "f4", "value": "12", "source": "w3", "quote": "tests passed: 12 of 12"},  # passed
        {"id": "f5", "value": "x", "source": "nowhere", "quote": "whatever it was"},  # refused
    ]
}


def fixture(root, *, marker=True):
    return write_export(root, fixture_entries(), FIXTURE_RESULTS, FIXTURE_FACTS, marker=marker)


def test_counts_match_a_hand_count_and_unchecked_is_never_passed(tmp_path):
    result = json.loads(json.dumps(check_mod.inspect_export(fixture(tmp_path), ACCURACY)))
    report = result["report"]
    # Hand count: 5 facts; f1 and f4 passed, f2 and f5 refused, f3 unchecked.
    assert report["facts"] == {"made": 5, "checked": 4, "passed": 2, "refused": 2, "unchecked": 1}
    assert report["by_source_kind"]["file"] == {
        "made": 2,
        "checked": 2,
        "passed": 1,
        "refused": 1,
        "unchecked": 0,
    }
    assert report["by_source_kind"]["tool"] == {
        "made": 2,
        "checked": 1,
        "passed": 1,
        "refused": 0,
        "unchecked": 1,
    }
    for kind in ("web", "memory", "agent", "harness"):
        assert report["by_source_kind"][kind]["made"] == 0
    assert report["python_recheck_ran"] is True
    by_id = {f["id"]: f for f in result["facts"]}
    assert by_id["f3"]["verdict"] == "unchecked"
    assert by_id["f3"]["source_kind"] == "tool"
    assert by_id["f5"]["source_kind"] is None


def test_calls_report_purpose_and_outcome(tmp_path):
    result = check_mod.inspect_export(fixture(tmp_path), ACCURACY)
    calls = {c["id"]: c for c in result["calls"]}
    assert calls["w1"]["purpose"] == "read the config"
    assert calls["w1"]["outcome"] == "ok"
    assert calls["w4"]["purpose"] is None
    assert calls["w4"]["outcome"] == "error"
    assert calls["w1"]["source_kind"] == "file"


def test_count_fact_never_adds_unchecked_to_passed():
    counts = empty_counts()
    for verdict in ("unchecked", "unchecked", "passed", "refused"):
        count_fact(counts, verdict)
    assert counts == {"made": 4, "checked": 2, "passed": 1, "refused": 1, "unchecked": 2}


def test_a_partial_entry_is_unchecked_not_passed(tmp_path):
    entries = [entry(1, "read", "file", partial=True)]
    facts = {"facts": [{"id": "f1", "value": "lazy", "source": "w1", "quote": "over the lazy dog"}]}
    export = write_export(tmp_path, entries, {1: "over the lazy dog and more"}, facts)
    report = check_mod.inspect_export(export, ACCURACY)["report"]
    assert report["facts"]["passed"] == 0
    assert report["facts"]["unchecked"] == 1


# --- exports written before this change ---------------------------------------------


def test_an_old_export_is_read_and_its_facts_are_not_applicable(tmp_path):
    old = write_export(tmp_path, [entry(1, "read", "file", saved=False)], {}, marker=False)
    result = check_mod.inspect_export(old, ACCURACY)
    assert result["applicable"] is False
    assert result["facts"] == []
    assert result["report"] is None
    assert "pre-change" in result["not_applicable_reason"]
    assert [c["id"] for c in result["calls"]] == ["w1"]
    assert "unsupported" not in result


def test_a_new_walk_without_a_facts_file_is_not_applicable(tmp_path):
    export = write_export(tmp_path, [entry(1, "read", "file", saved=False)], {})
    result = check_mod.inspect_export(export, ACCURACY)
    assert result["applicable"] is False
    assert "facts.json" in result["not_applicable_reason"]


def test_a_saved_result_path_outside_results_is_never_read(tmp_path):
    export = write_export(
        tmp_path, [entry(1, "read", "file", saved=False, saved_result="../secret.txt")], {}
    )
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    assert check_mod.load_export(export)["results"] == {}


def test_bad_inputs_raise_an_export_error_not_another_exception(tmp_path):
    with pytest.raises(check_mod.ExportError):
        check_mod.inspect_export(tmp_path / "missing", ACCURACY)
    export = write_export(tmp_path, [], {}, name="bad")
    (export / "facts.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(check_mod.ExportError, match="facts.json"):
        check_mod.inspect_export(export, ACCURACY)


# --- exports written by a newer harness than this checker knows -----------------------


def test_the_supported_walk_formats_are_named_by_a_constant():
    assert check_mod.SUPPORTED_WALK_FORMATS == (1, 2)


@pytest.mark.parametrize("version", [3, 17])
def test_a_newer_walk_format_is_unsupported_with_the_version_found_and_no_counts(tmp_path, version):
    marker = {"format": {"name": "associate-walk", "version": version}}
    export = fixture(tmp_path, marker=marker)
    assert check_mod.load_export(export)["format"] == version
    result = check_mod.inspect_export(export, ACCURACY)
    assert result["unsupported"] is True
    assert result["walk_format"] == version
    assert result["applicable"] is False
    assert result["report"] is None
    assert result["facts"] == []
    assert result["accepted"] is None
    assert "verdicts" not in result
    assert f"walk format {version}" in result["not_applicable_reason"]
    assert "unsupported" in result["not_applicable_reason"]


def test_the_run_summary_marks_a_newer_walk_format_unsupported(tmp_path):
    marker = {"format": {"name": "associate-walk", "version": 3}}
    result = check_mod.accuracy_result(fixture(tmp_path, marker=marker), ACCURACY)
    summary = result["accuracy"]
    assert summary["unsupported"] is True
    assert summary["walk_format"] == 3
    assert summary["python_recheck_ran"] is False
    assert summary["python_recheck_verdict"] is None
    assert summary["report"] is None
    assert "walk format 3" in summary["not_applicable_reason"]


def test_the_highest_supported_format_is_still_checked(tmp_path):
    result = check_mod.inspect_export(fixture(tmp_path), ACCURACY)
    assert result["walk_format"] == max(check_mod.SUPPORTED_WALK_FORMATS)
    assert result["applicable"] is True
    assert "unsupported" not in result


# --- wording ------------------------------------------------------------------------------


def test_no_result_calls_the_quote_checked_count_accuracy(tmp_path):
    texts = [json.dumps(check_mod.inspect_export(fixture(tmp_path / "new"), ACCURACY))]
    old = write_export(tmp_path, [], {}, marker=False, name="old")
    texts.append(json.dumps(check_mod.inspect_export(old, ACCURACY)))
    newer = fixture(tmp_path / "newer", marker={"format": {"version": 3}})
    texts.append(json.dumps(check_mod.inspect_export(newer, ACCURACY)))
    for text in texts:
        assert not re.search(r"accura", text, re.IGNORECASE), text[:80]


def test_a_source_reference_with_a_trailing_newline_is_malformed_as_in_typescript():
    """`$` alone would let "w1\\n" through in Python; the TypeScript pattern does not."""
    from evidence.accuracy import check

    for ref in ("w1\n", "prior:w3\n"):
        parsed = check.parse_source_ref(ref)
        assert parsed.get("ok") is not True, ref


# --- digits are ASCII only, as in the TypeScript checker ----------------------------

FULLWIDTH_ONE = "１"
ARABIC_INDIC_ONE = "١"


@pytest.mark.parametrize("digit", [FULLWIDTH_ONE, ARABIC_INDIC_ONE])
def test_a_source_reference_with_a_non_ascii_digit_is_malformed(digit):
    assert check_mod.parse_source_ref("w1")["ok"] is True
    assert check_mod.parse_source_ref(f"w1{digit}") == {"ok": False, "reason": "source_malformed"}
    assert check_mod.parse_source_ref(f"prior:w1{digit}")["ok"] is False


@pytest.mark.parametrize("digit", [FULLWIDTH_ONE, ARABIC_INDIC_ONE])
def test_a_walk_id_with_a_non_ascii_digit_is_not_an_entry(digit):
    assert check_mod._is_entry({"id": "w11", "tool": "read"}) is True
    assert check_mod._is_entry({"id": f"w1{digit}", "tool": "read"}) is False


@pytest.mark.parametrize("digit", [FULLWIDTH_ONE, ARABIC_INDIC_ONE])
def test_a_saved_result_name_with_a_non_ascii_digit_is_not_read(tmp_path, digit):
    assert check_mod._SAVED.match("results/w11.txt") is not None
    name = f"results/w1{digit}.txt"
    walk_entry = {"id": "w1", "tool": "read", "saved_result": name}
    (tmp_path / "results").mkdir()
    (tmp_path / name).write_text("saved text", encoding="utf-8")
    (tmp_path / "walk.jsonl").write_text(json.dumps(walk_entry) + "\n", encoding="utf-8")
    loaded = check_mod.load_export(tmp_path)
    assert [e["id"] for e in loaded["entries"]] == ["w1"]
    assert loaded["results"] == {}


@pytest.mark.parametrize("digit", [FULLWIDTH_ONE, ARABIC_INDIC_ONE])
def test_a_child_id_with_a_non_ascii_digit_is_not_linked(tmp_path, digit):
    walk = tmp_path / "walk.jsonl"
    lines = [
        {"child": {"id": f"c1{digit}", "child_walk": "/x/a/walk.jsonl"}},
        {"child": {"id": "c11", "child_walk": "/x/b/walk.jsonl"}},
    ]
    walk.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    assert check_mod._child_links(walk) == [("c11", "/x/b/walk.jsonl")]


def test_a_delegate_status_quote_from_the_rendered_answer_is_second_hand():
    """The result's `answer` holds the child's own words, like `final_reply`."""
    text = json.dumps(
        {
            "ok": True,
            "result": {
                "outcome": "ok",
                "merge": "merged",
                "answer": "# Answer\n\nFinish summary: every test passed here",
                "final_reply": "all good here",
            },
        },
        separators=(",", ":"),
    )
    handback = {
        "payload": {
            "facts": [
                {"id": "f1", "value": "passed", "source": "w1", "quote": "every test passed here"},
                {"id": "f2", "value": "merged", "source": "w1", "quote": '"merge":"merged"'},
            ]
        },
        "entries": [{"id": "w1", "tool": "delegate_status", "saved_result": "results/w1.txt"}],
        "results": {"w1": text},
    }
    facts = check_mod.check_handback(handback, ACCURACY)["facts"]
    assert facts[0]["verdict"] == "passed"
    assert facts[0]["first_hand"] is False
    assert facts[1]["first_hand"] is True


# --- the public names and the import rule ---------------------------------------------

PUBLIC = {
    "evidence.accuracy.matcher": ["check_quote"],
    "evidence.accuracy.counts": ["fact_counts"],
    "evidence.accuracy.check": [
        "parse_source_ref",
        "check_handback",
        "load_export",
        "load_handback_input",
        "inspect_export",
        "accuracy_result",
    ],
}


@pytest.mark.parametrize(
    "module,name", [(m, n) for m, names in PUBLIC.items() for n in names], ids=str
)
def test_each_public_function_is_importable_from_its_module(module, name):
    assert callable(getattr(import_module(module), name))


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_module_under_evidence_imports_associate():
    package = Path(check_mod.__file__).resolve().parents[1]
    modules = sorted(package.rglob("*.py"))
    assert len(modules) > 5
    offenders = [str(p) for p in modules if "associate" in _imported_roots(p)]
    assert offenders == []
