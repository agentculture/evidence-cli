"""Validation of a task's expected values (see the package docstring)."""

import re
from typing import Any

SCHEMA_VERSION = 1

KINDS = ("number", "identifier", "text")
_TOP_KEYS = {"schema_version", "must_appear", "must_not_appear", "one_of"}
_ITEM_KEYS = {"text", "kind", "fold_case"}
_NUMBER = re.compile(r"-?[0-9]+(?:[.,][0-9]+)*", re.ASCII)
_SPACE = re.compile(r"\s")


class ExpectedValuesError(ValueError):
    """The expected values are not valid; the message is the reason."""


def _check_keys(obj: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ExpectedValuesError(f"unknown key in {where}: {', '.join(map(str, unknown))}")


def _check_text(item: dict[str, Any], where: str) -> None:
    text, kind = item["text"], item["kind"]
    if kind == "number" and not _NUMBER.fullmatch(text):
        raise ExpectedValuesError(f"{where}: {text!r} is not a number")
    if kind == "identifier" and _SPACE.search(text):
        raise ExpectedValuesError(f"{where}: identifier {text!r} holds whitespace")
    if "fold_case" in item and (kind != "text" or not isinstance(item["fold_case"], bool)):
        raise ExpectedValuesError(f"{where}: fold_case is a boolean on text items only")


def _check_item(item: Any, where: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ExpectedValuesError(f"{where} is not an object")
    _check_keys(item, _ITEM_KEYS, where)
    for key in ("text", "kind"):
        if key not in item:
            raise ExpectedValuesError(f"{where} has no {key}")
    if not isinstance(item["text"], str) or not item["text"].strip():
        raise ExpectedValuesError(f"{where}: text must be a non-empty string")
    if item["kind"] not in KINDS:
        raise ExpectedValuesError(f"{where}: kind must be one of {', '.join(KINDS)}")
    _check_text(item, where)
    return item


def _check_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExpectedValuesError(f"{where} is not a list")
    return value


def _check_items(value: Any, where: str) -> list[dict[str, Any]]:
    return [_check_item(item, f"{where}[{i}]") for i, item in enumerate(_check_list(value, where))]


def _check_groups(value: Any) -> list[list[dict[str, Any]]]:
    groups = _check_list(value, "one_of")
    for i, group in enumerate(groups):
        if not isinstance(group, list) or not group:
            raise ExpectedValuesError(f"one_of[{i}] is not a non-empty list of items")
    return [_check_items(group, f"one_of[{i}]") for i, group in enumerate(groups)]


def load_expected(data: Any) -> dict[str, Any]:
    """Validate ``data`` and return it normalised, or raise ``ExpectedValuesError``."""
    if not isinstance(data, dict):
        raise ExpectedValuesError("expected values must be a JSON object")
    _check_keys(data, _TOP_KEYS, "expected values")
    version = data.get("schema_version")
    if "schema_version" not in data:
        raise ExpectedValuesError("expected values have no schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ExpectedValuesError(
            f"schema_version {version!r} is not supported; use {SCHEMA_VERSION}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "must_appear": _check_items(data.get("must_appear", []), "must_appear"),
        "must_not_appear": _check_items(data.get("must_not_appear", []), "must_not_appear"),
        "one_of": _check_groups(data.get("one_of", [])),
    }
