"""Grade an answer text against validated expected values."""

import re
from typing import Any

from evidence.answer.schema import SCHEMA_VERSION, load_expected

# The matcher's whitespace set; unlike the matcher's normalise, no line stamp is stripped.
_SPACE = re.compile(r"[ \t\n\r\f\v]+")

_WORD = "A-Za-z0-9_"
_NUMBER_BEFORE = rf"(?<![{_WORD}])(?<![0-9][.,])"
_NUMBER_AFTER = rf"(?![{_WORD}])(?![.,][0-9])"
# A minus sign glued to the token makes it a different (negative) number,
# unless the sign is a range dash after a word character ("3-5").
_NOT_NEGATED = rf"(?:(?<!-)|(?<=[{_WORD}]-))"
_IDENT_BEFORE = rf"(?<![{_WORD}./-])"
_IDENT_AFTER = rf"(?![{_WORD}/-])(?!\.[{_WORD}])"


def _collapse(text: str) -> str:
    """Collapse each run of whitespace to one space and trim; nothing else changes.

    An answer line such as ``42<tab>files`` keeps its ``42``: the answer is not a
    saved read result, so it carries no line stamps to strip.
    """
    return _SPACE.sub(" ", text).strip(" ")


def _token_pattern(item: dict[str, Any]) -> str:
    text = re.escape(item["text"])
    if item["kind"] == "number":
        sign = "" if item["text"].startswith("-") else _NOT_NEGATED
        return f"{_NUMBER_BEFORE}{sign}{text}{_NUMBER_AFTER}"
    return f"{_IDENT_BEFORE}{text}{_IDENT_AFTER}"


def _present(item: dict[str, Any], answer: str) -> bool:
    if item["kind"] == "text":
        needle = _collapse(item["text"])
        if item.get("fold_case", False):
            return needle.casefold() in answer.casefold()
        return needle in answer
    return re.search(_token_pattern(item), answer, re.ASCII) is not None


def _result(verdict: str, found, missing, forbidden, cause=None) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "schema_version": SCHEMA_VERSION,
        "found": found,
        "missing": missing,
        "forbidden_present": forbidden,
        "cause": cause,
    }


def _check_groups(groups, answer: str, found: list, missing: list) -> None:
    for group in groups:
        hit = next((item for item in group if _present(item, answer)), None)
        if hit is None:
            missing.append({"one_of": group})
        else:
            found.append(hit)


def grade(answer_text: str, expected: Any) -> dict[str, Any]:
    """Grade ``answer_text`` against ``expected``; see the package docstring."""
    exp = load_expected(expected)
    answer = _collapse(answer_text)
    if not any((exp["must_appear"], exp["must_not_appear"], exp["one_of"])):
        return _result("cannot_tell", [], [], [], "no_expected_items")
    if not answer:
        return _result("cannot_tell", [], [], [], "empty_answer")
    found = [i for i in exp["must_appear"] if _present(i, answer)]
    missing = [i for i in exp["must_appear"] if i not in found]
    _check_groups(exp["one_of"], answer, found, missing)
    forbidden = [i for i in exp["must_not_appear"] if _present(i, answer)]
    verdict = "does_not_match" if missing or forbidden else "matches"
    return _result(verdict, found, missing, forbidden)
