"""``evidence grade`` — check an answer text against a task's expected values.

Reads an answer (a file, or ``-`` for standard input) and an expected-values
file, and reports one of three results: ``matches``, ``does not match`` or
``cannot tell``, with the items found and missing and the schema version. It
takes no export directory and reads no facts file. Exit code 0 for any of the
three results; a user error for an unreadable or refused input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evidence.answer import ExpectedValuesError
from evidence.answer import grade as grade_answer
from evidence.cli._errors import EXIT_USER_ERROR, CliError
from evidence.cli._output import emit_result

NOTE = "a complete trail does not mean the work is correct"
_VERDICT_TEXT = {
    "matches": "matches",
    "does_not_match": "does not match",
    "cannot_tell": "cannot tell",
}
_CAUSE_TEXT = {
    "empty_answer": "the answer is empty",
    "no_expected_items": "the expected values name no item",
}


def _read_text(path: str, what: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"cannot read {what} {path!r}: {exc.__class__.__name__}",
            f"check that the {what} exists and is readable UTF-8 text",
        ) from exc


def _load_expected_file(path: str) -> Any:
    text = _read_text(path, "expected-values file")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"expected-values file {path!r} is not valid JSON: {exc.msg}",
            "write the expected values as one JSON object with schema_version 1",
        ) from exc
    except RecursionError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"expected-values file {path!r} is nested too deeply to read",
            "write the expected values as one JSON object with schema_version 1",
        ) from exc


def _item_text(item: dict[str, Any]) -> str:
    if "one_of" in item:
        return "one of " + ", ".join(_item_text(i) for i in item["one_of"])
    return f"{item['text']} ({item['kind']})"


def _list_lines(label: str, items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return [f"{label}: none"]
    return [f"{label}:"] + [f"  - {_item_text(i)}" for i in items]


def _render(result: dict[str, Any]) -> str:
    lines = [
        "answer check: a match against recorded expected values",
        f"result: {_VERDICT_TEXT[result['verdict']]}",
    ]
    if result["cause"]:
        lines.append(f"cause: {_CAUSE_TEXT.get(result['cause'], result['cause'])}")
    lines += _list_lines("found", result["found"])
    lines += _list_lines("missing", result["missing"])
    lines += _list_lines("forbidden present", result["forbidden_present"])
    lines.append(f"schema version: {result['schema_version']}")
    lines.append(NOTE)
    return "\n".join(lines)


def cmd_grade(args: argparse.Namespace) -> None:
    answer = _read_text(args.answer_file, "answer file")
    expected = _load_expected_file(args.expected)
    try:
        result = grade_answer(answer, expected)
    except ExpectedValuesError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"expected-values file {args.expected!r} refused: {exc}",
            "fix the expected values to match evidence/data/expected_values.schema.json",
        ) from exc
    json_mode = bool(getattr(args, "json", False))
    emit_result({**result, "note": NOTE} if json_mode else _render(result), json_mode=json_mode)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "grade",
        help="Answer check: a match against recorded expected values.",
    )
    p.add_argument(
        "--answer-file", required=True, help="Answer text file, or - for standard input."
    )
    p.add_argument("--expected", required=True, help="The task's expected-values JSON file.")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_grade)
