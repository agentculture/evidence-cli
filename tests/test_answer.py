"""Tests for the answer check library, evidence.answer."""

import json
import re
from importlib import resources

import pytest

from evidence.answer import SCHEMA_VERSION, ExpectedValuesError, grade, load_expected


def num(t):
    return {"text": t, "kind": "number"}


def ident(t):
    return {"text": t, "kind": "identifier"}


def txt(t, fold=False):
    item = {"text": t, "kind": "text"}
    if fold:
        item["fold_case"] = True
    return item


def exp(**kw):
    return {"schema_version": 1, **kw}


def verdict(answer, **kw):
    return grade(answer, exp(**kw))["verdict"]


# --- criterion 1
def test_all_required_and_no_forbidden_matches():
    r = grade("The count is 9 in lib/facts.ts", exp(must_appear=[num("9"), ident("lib/facts.ts")]))
    assert r["verdict"] == "matches"
    assert [i["text"] for i in r["found"]] == ["9", "lib/facts.ts"]
    assert r["missing"] == []
    assert r["forbidden_present"] == []


def test_missing_required_is_does_not_match_and_named():
    r = grade("nothing here 9", exp(must_appear=[num("9"), txt("alpha")]))
    assert r["verdict"] == "does_not_match"
    assert [i["text"] for i in r["missing"]] == ["alpha"]


def test_forbidden_present_is_does_not_match_and_named():
    r = grade("alpha and beta", exp(must_appear=[txt("alpha")], must_not_appear=[txt("beta")]))
    assert r["verdict"] == "does_not_match"
    assert [i["text"] for i in r["forbidden_present"]] == ["beta"]


def test_group_one_alternative_enough():
    assert verdict("it is blue", one_of=[[txt("red"), txt("blue")]]) == "matches"


def test_group_none_appears_is_missing():
    r = grade("it is green", exp(one_of=[[txt("red"), txt("blue")]]))
    assert r["verdict"] == "does_not_match"
    assert [i["text"] for i in r["missing"][0]["one_of"]] == ["red", "blue"]


def test_only_forbidden_absent_matches():
    assert verdict("fine", must_not_appear=[txt("bad")]) == "matches"


# --- criterion 2
@pytest.mark.parametrize(
    "answer,item,want",
    [
        ("19 items", "9", False),
        ("10.5 s", "0.5", False),
        ("0.5 s", "0.5", True),
        ("costs 9.", "9", True),
        ("costs $9", "9", True),
        ("(9)", "9", True),
        ("9%", "9", True),
        ("[9]", "9", True),
        ("a, 9, b", "9", True),
        ("1,000 items", "1", False),
        ("1,000 items", "1,000", True),
        ("version 1.2.3", "1.2", False),
        ("version 1.2.3", "2.3", False),
        ("version 1.2.3", "1.2.3", True),
        ("delta -5 here", "-5", True),
        ("delta -5 here", "5", False),
        ("delta 5 here", "-5", False),
        ("value 9a", "9", False),
        ("x9", "9", False),
        ("٩", "9", False),
        ("٩9", "9", True),
    ],
)
def test_number_whole_token(answer, item, want):
    assert (verdict(answer, must_appear=[num(item)]) == "matches") is want


@pytest.mark.parametrize(
    "answer,item,want",
    [
        ("see lib/facts.ts.", "lib/facts.ts", True),
        ("see `lib/facts.ts`", "lib/facts.ts", True),
        ("see src/lib/facts.ts", "lib/facts.ts", False),
        ("see lib/facts.ts.bak", "lib/facts.ts", False),
        ("see lib/facts.tsx", "lib/facts.ts", False),
        ("call check_quote now", "check_quote", True),
        ("call check_quote_all now", "check_quote", False),
        ("call my_check_quote now", "check_quote", False),
        ("call my-check_quote now", "check_quote", False),
        ("call check_quote-v2 now", "check_quote", False),
        ("(check_quote)", "check_quote", True),
        ("check_quote, then", "check_quote", True),
        ("a.b", "b", False),
    ],
)
def test_identifier_whole_token(answer, item, want):
    assert (verdict(answer, must_appear=[ident(item)]) == "matches") is want


def test_text_substring_after_whitespace_collapse():
    assert verdict("the   quick\n brown fox", must_appear=[txt("quick brown")]) == "matches"


def test_text_case_folding():
    assert verdict("Hello World", must_appear=[txt("hello world")]) == "does_not_match"
    assert verdict("Hello World", must_appear=[txt("hello world", fold=True)]) == "matches"
    assert verdict("hello", must_appear=[txt("HELLO", fold=True)]) == "matches"


# --- criterion 3
def test_empty_answer_cannot_tell():
    for answer in ("", "   \n "):
        r = grade(answer, exp(must_appear=[num("9")]))
        assert r["verdict"] == "cannot_tell"
        assert r["cause"] == "empty_answer"


def test_no_items_cannot_tell():
    r = grade("something", exp())
    assert r["verdict"] == "cannot_tell"
    assert r["cause"] == "no_expected_items"
    assert grade("something", exp(must_appear=[], one_of=[]))["verdict"] == "cannot_tell"


def test_cause_only_for_cannot_tell():
    assert grade("9", exp(must_appear=[num("9")]))["cause"] is None
    assert grade("8", exp(must_appear=[num("9")]))["cause"] is None


# --- criterion 4
@pytest.mark.parametrize(
    "bad",
    [
        {"must_appear": []},
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 1, "bogus": []},
        {"schema_version": 1, "must_appear": [{"text": "a", "kind": "text", "extra": 1}]},
        {"schema_version": 1, "must_appear": [{"text": "a", "kind": "word"}]},
        {"schema_version": 1, "must_appear": [{"text": "", "kind": "text"}]},
        {"schema_version": 1, "must_appear": [{"kind": "text"}]},
        {"schema_version": 1, "must_appear": [{"text": "a", "kind": "number"}]},
        {"schema_version": 1, "must_appear": [{"text": "a b", "kind": "identifier"}]},
        {"schema_version": 1, "must_appear": [{"text": "a", "kind": "number", "fold_case": True}]},
        {"schema_version": 1, "must_appear": "x"},
        {"schema_version": 1, "one_of": [[]]},
        {"schema_version": 1, "one_of": [num("1")]},
    ],
)
def test_bad_expected_refused_with_reason(bad):
    with pytest.raises(ExpectedValuesError) as err:
        grade("answer", bad)
    assert str(err.value)


def test_refusal_reasons_name_the_problem():
    with pytest.raises(ExpectedValuesError, match="schema_version"):
        load_expected({"must_appear": []})
    with pytest.raises(ExpectedValuesError, match="bogus"):
        load_expected({"schema_version": 1, "bogus": 1})


def test_non_object_refused():
    with pytest.raises(ExpectedValuesError):
        load_expected([])


def test_every_result_names_schema_version():
    for answer, e in [
        ("", exp()),
        ("9", exp(must_appear=[num("9")])),
        ("8", exp(must_appear=[num("9")])),
    ]:
        assert grade(answer, e)["schema_version"] == SCHEMA_VERSION == 1


def _schema():
    text = (
        resources.files("evidence").joinpath("data/expected_values.schema.json").read_text("utf-8")
    )
    return json.loads(text)


def test_schema_file_ships_and_agrees():
    schema = _schema()
    assert schema["properties"]["schema_version"] == {"const": SCHEMA_VERSION}
    assert set(schema["properties"]) == {
        "schema_version",
        "must_appear",
        "must_not_appear",
        "one_of",
    }


def _breaks(rule, item):
    """The parts of one schema rule (``properties.text.pattern`` or ``not.required``) broken."""
    broken = []
    pattern = rule.get("properties", {}).get("text", {}).get("pattern")
    if pattern is not None and not re.search(pattern, item["text"]):
        broken.append(f"text pattern {pattern}")
    forbidden = rule.get("not", {}).get("required")
    if forbidden is not None and all(key in item for key in forbidden):
        broken.append(f"forbidden {forbidden}")
    return broken


def _item_errors(item):
    """A hand evaluation of the schema's item rules (no validator library is available).

    It reads only what the file says: the item's own ``properties.text.pattern``, and
    for each ``allOf`` entry its ``if`` (a ``kind`` const) and the ``then`` or
    ``else`` that applies. Returns the rules the item breaks.
    """
    rules = _schema()["$defs"]["item"]
    broken = _breaks(rules, item)
    for rule in rules["allOf"]:
        applies = item["kind"] == rule["if"]["properties"]["kind"]["const"]
        broken += _breaks(rule.get("then" if applies else "else", {}), item)
    return broken


@pytest.mark.parametrize(
    "item",
    [
        {"text": "   ", "kind": "text"},
        {"text": "\t\n", "kind": "identifier"},
        {"text": "abc", "kind": "number", "fold_case": True},
        {"text": "x", "kind": "identifier", "fold_case": False},
        {"text": "1.5x", "kind": "number"},
        {"text": "twelve", "kind": "number"},
        {"text": "1..2", "kind": "number"},
        {"text": "a b", "kind": "identifier"},
    ],
)
def test_each_rule_the_validator_refuses_is_a_rule_in_the_schema_file(item):
    with pytest.raises(ExpectedValuesError):
        load_expected(exp(must_appear=[item]))
    assert _item_errors(item), item


@pytest.mark.parametrize(
    "item",
    [
        {"text": "x", "kind": "text", "fold_case": True},
        {"text": "-1,234.5", "kind": "number"},
        {"text": "7", "kind": "number"},
        {"text": "lib/facts.ts", "kind": "identifier"},
        {"text": " padded text ", "kind": "text"},
    ],
)
def test_items_the_validator_accepts_break_no_rule_in_the_schema_file(item):
    load_expected(exp(must_appear=[item]))
    assert _item_errors(item) == []


def test_a_number_then_a_tab_at_the_start_of_an_answer_line_is_kept():
    answer = "files checked:\n42\tfiles\n"
    assert grade(answer, exp(must_appear=[num("42")]))["verdict"] == "matches"
    assert grade(answer, exp(must_appear=[txt("42 files")]))["verdict"] == "matches"
    assert grade("7\tidentifiers", exp(must_appear=[ident("7")]))["verdict"] == "matches"


def test_an_expected_text_item_keeps_a_leading_number_and_tab():
    expected = exp(must_appear=[txt("42\tfiles")])
    assert grade("x 42 files y", expected)["verdict"] == "matches"
    assert grade("x files y", expected)["verdict"] == "does_not_match"


# --- criterion 5
def test_deterministic_and_json_serialisable():
    e = exp(must_appear=[num("9"), txt("a", fold=True)], one_of=[[ident("x_y"), ident("z")]])
    a, b = grade("9 A x_y", e), grade("9 A x_y", e)
    assert a == b
    assert json.loads(json.dumps(a)) == a


def test_grade_does_not_mutate_expected():
    e = exp(must_appear=[num("9")])
    before = json.dumps(e)
    grade("9", e)
    assert json.dumps(e) == before


def test_imports_only_stdlib_and_evidence():
    import ast
    import sys
    from pathlib import Path

    import evidence.answer as pkg

    for path in Path(pkg.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or top == "evidence", (path, name)
