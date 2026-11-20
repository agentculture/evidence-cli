"""The Python re-check of a hand-back (moved from associate at commit 266dad3).

A port of the associate extension's ``.pi/extensions/associate/lib/facts.ts``
``checkHandback``: the same inputs give the same verdicts, and both are compared
against the whole-hand-back cases in ``evidence/data/matcher_vectors.json``.
Standard library only; no model is called. Every setting (minimum quote length,
source-kind table, reason-to-check mapping) comes from the settings passed in;
:func:`load_default_settings` returns the bundled copy of associate's
``accuracy.json`` (``evidence/data/accuracy_defaults.json``) and its version.

:func:`check_handback` is the pure checker over parsed inputs. :func:`load_export`
reads an export directory (``walk.jsonl``, ``results/wN.txt``, and the facts
payload :data:`FACTS_FILENAME`); :func:`inspect_export` joins the two for the
run check. An export written before the walk format marker has no facts: they
are reported as not applicable, never as an error. An export whose walk format
is newer than every version in :data:`SUPPORTED_WALK_FORMATS` is reported as
unsupported, with the version found, and is never checked with older rules.

A fact value is a literal, and must occur inside its quote, when it is a string
with no whitespace once trimmed, a JSON number or a JSON boolean; numbers are
written as the TypeScript side's ``String(n)`` writes them (see
:func:`literal_of`). A ``min_quote_length`` that is not a positive integer is a
broken contract and fails closed: every fact is refused as a short quote, its
flag naming the contract value. A child that is not an object, or whose label
is not a run label, is skipped without a flag (no check id fits it).

``passed`` means a fact's quote was found in the saved result it cites; nothing
more is claimed (see :mod:`evidence.accuracy.counts`).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

from evidence.accuracy.counts import (
    SOURCE_KINDS,
    conclusion_counts,
    counts_by_source_kind,
    fact_counts,
)
from evidence.accuracy.matcher import check_quote

#: The walk's file name and the facts payload's file name in an export directory.
WALK_FILENAME = "walk.jsonl"
FACTS_FILENAME = "facts.json"
#: The files the extension writes at ``finish`` beside the facts payload.
CHECK_FILENAME = "check.json"
REPORT_FILENAME = "report.json"
ANSWER_FILENAME = "answer.md"
#: The run label of the ``--continue-from`` export, as in ``lib/torch.ts``.
PRIOR_RUN_LABEL = "prior"
#: The walk format versions this checker knows: 1 (no format marker, no facts) and 2.
SUPPORTED_WALK_FORMATS: tuple[int, ...] = (1, 2)
#: The bundled default settings, inside the ``evidence`` package.
DEFAULT_SETTINGS_RESOURCE = "data/accuracy_defaults.json"


def load_default_settings() -> tuple[dict[str, Any], int]:
    """The bundled default settings and their ``version``.

    ``evidence/data/accuracy_defaults.json`` is a byte-identical copy of
    associate's ``associate/contract/accuracy.json`` at commit 266dad3. Each call
    parses the file again, so a caller may change the returned dict freely.
    """
    text = resources.files("evidence").joinpath(DEFAULT_SETTINGS_RESOURCE).read_text("utf-8")
    settings = json.loads(text)
    return settings, settings["version"]


# re.ASCII: \d is 0-9 only, as in the TypeScript checker (lib/facts.ts).
_REFERENCE = re.compile(r"(?:([A-Za-z0-9_-]+):)?(w[1-9]\d*)", re.ASCII)
_LABEL = re.compile(r"[A-Za-z0-9_-]+")  # used with fullmatch: no trailing newline
_ID = re.compile(r"^w[1-9]\d*$", re.ASCII)
_SAVED = re.compile(r"^results/(w[1-9]\d*)\.txt$", re.ASCII)
_CHILD_ID = re.compile(r"c[1-9]\d*", re.ASCII)  # used with fullmatch
_WS = re.compile(r"[ \t\n\r\f\v]")

#: Kinds that are another model's words or a remembered claim, not a measurement.
_SECOND_HAND = frozenset({"agent", "memory"})
_DELEGATE_STATUS = "delegate_status"
#: Result fields holding the child's own words: its final message and the rendered answer.
#: associate now writes ``unchecked_final_reply`` in place of ``final_reply``; both are read.
_CHILD_ACCOUNT_KEYS = ("final_reply", "answer", "unchecked_final_reply")


def parse_source_ref(ref: Any) -> dict[str, Any]:
    """Parse ``[label:]wN``; a path or anything else is refused, never resolved."""
    if not isinstance(ref, str):
        return {"ok": False, "reason": "source_malformed"}
    if "/" in ref or "\\" in ref:
        return {"ok": False, "reason": "source_path"}
    match = _REFERENCE.fullmatch(ref)
    if not match:
        return {"ok": False, "reason": "source_malformed"}
    return {"ok": True, "label": match.group(1), "id": match.group(2)}


def _is_entry(line: Any) -> bool:
    return (
        isinstance(line, dict)
        and isinstance(line.get("id"), str)
        and bool(_ID.match(line["id"]))
        and isinstance(line.get("tool"), str)
    )


def _index_entries(entries: Any) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for line in entries or []:
        if _is_entry(line):
            index[line["id"]] = line
    return index


def _saved_text(results: Mapping[str, Any], entry_id: str) -> Optional[str]:
    text = results.get(entry_id)
    return text if isinstance(text, str) else None


def _kind_of(entry: Mapping[str, Any], accuracy: Mapping[str, Any]) -> Optional[str]:
    table = accuracy.get("source_kinds") or {}
    if entry["tool"] in table:
        return table[entry["tool"]]
    own = entry.get("source_kind")
    return own if isinstance(own, str) and own in SOURCE_KINDS else None


def _reports_failure(text: Optional[str]) -> bool:
    if text is None:
        return False
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):  # nested too deeply to parse: text, like non-JSON
        return False
    return isinstance(parsed, dict) and parsed.get("ok") is False


def _encode_account(key: str, account: str) -> str:
    # JSON.stringify (the TypeScript side) leaves non-ASCII as is.
    return (
        f"{json.dumps(key, ensure_ascii=False)}:"
        f"{json.dumps(account, ensure_ascii=False, separators=(',', ':'))}"
    )


def _find_child_accounts(value: Any, out: dict[str, str]) -> None:
    """Collect every child-account field anywhere in a parsed result (encoded text to key)."""
    if isinstance(value, list):
        for item in value:
            _find_child_accounts(item, out)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _CHILD_ACCOUNT_KEYS and isinstance(item, str):
                out[_encode_account(key, item)] = key
            else:
                _find_child_accounts(item, out)


def _harness_part(text: str) -> Optional[str]:
    """The delegate_status saved text with the child's own words emptied."""
    accounts: dict[str, str] = {}
    try:
        _find_child_accounts(json.loads(text), accounts)
    except (ValueError, RecursionError):  # nested too deeply: the parts cannot be told apart
        return None
    out = text
    for encoded, key in accounts.items():
        if encoded not in text:
            return None
        out = out.replace(encoded, f'{json.dumps(key, ensure_ascii=False)}:""')
    return out


def _is_first_hand(
    kind: Optional[str],
    entry: Mapping[str, Any],
    quote: str,
    text: Optional[str],
    min_quote_length: int,
) -> Optional[bool]:
    if kind is None:
        return None
    if entry["tool"] == _DELEGATE_STATUS:
        if text is None:
            return False
        part = _harness_part(text)
        return part is not None and (
            check_quote(quote, None, part, min_quote_length)["verdict"] == "passed"
        )
    return kind not in _SECOND_HAND


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


#: Integers up to this size are exact doubles; a larger one is rounded first, as JSON.parse does.
_EXACT_INT = 2**53


def _number_text(value: Any) -> Optional[str]:
    """A JSON number as ECMAScript ``Number::toString`` writes it (``String(n)``).

    The shortest decimal that reads back as the same double (``repr`` gives the
    digits), no ``.0`` on an integer-valued number, ``0`` for -0, plain digits
    for 1e-6 <= |n| < 1e21 and exponent form (``1e-7``, ``1.5e+300``) outside
    that. None for a non-finite number or an integer no double can hold.
    """
    if isinstance(value, int) and abs(value) <= _EXACT_INT:
        return str(value)
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    mantissa, _, exp = repr(abs(number)).partition("e")
    whole, _, frac = mantissa.partition(".")
    all_digits = whole + frac
    stripped = all_digits.lstrip("0")
    # n: where the decimal point falls relative to the first significant digit.
    n = len(whole) - (len(all_digits) - len(stripped)) + (int(exp) if exp else 0)
    digits = stripped.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mark = "+" if e >= 0 else "-"
        head = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        body = f"{head}e{mark}{abs(e)}"
    return sign + body


def literal_of(value: Any) -> Optional[str]:
    """The literal a fact value must show inside its quote, or None when it is not one.

    A string with no whitespace once trimmed, a JSON number (:func:`_number_text`)
    or a JSON boolean (``true`` / ``false``); null, objects, arrays and
    non-finite numbers are not literals. ``facts.ts`` ``literalOf`` gives the
    same text (shared ``literal_cases`` in ``matcher_vectors.json``).
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number_text(value)
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if trimmed != "" and not _WS.search(trimmed) else None


def _is_positive_integer(value: Any) -> bool:
    """A usable minimum quote length: a positive integer (8.0 counts as 8)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 1
    return isinstance(value, float) and value.is_integer() and value >= 1


_MISSING = object()


def _contract_value_text(value: Any) -> str:
    """How a contract value is named in a refusal: the same text ``facts.ts`` writes."""
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, (bool, int, float)):
        return literal_of(value) or "not a finite number"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return "an array" if isinstance(value, list) else "an object"


def _is_checkable_child(child: Any) -> bool:
    """A child run the checker can read: an object whose label is a run label."""
    return (
        isinstance(child, dict)
        and isinstance(child.get("label"), str)
        and _LABEL.fullmatch(child["label"]) is not None
    )


@dataclass
class _Checker:
    """The contract settings one hand-back check reads, and the flags it raises."""

    accuracy: Mapping[str, Any]
    mapping: Mapping[str, Any]
    min_len: Any
    contract_text: Optional[str]
    flags: list[dict[str, str]] = field(default_factory=list)

    def check_for(self, reason: str) -> Optional[str]:
        return self.mapping.get(reason)

    def flag(
        self, reason: str, item_id: str, ref: Optional[str] = None, note: Optional[str] = None
    ) -> None:
        check = self.check_for(reason)
        if check is None:
            return
        detail = f"{item_id}: {reason}" if note is None else f"{item_id}: {reason} ({note})"
        out = {"check": check, "detail": detail}
        if ref is not None and parse_source_ref(ref)["ok"]:
            out["ref"] = ref
        self.flags.append(out)

    def refuse_fact(
        self,
        base: Mapping[str, Any],
        reason: str,
        extra: Optional[dict[str, Any]] = None,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        self.flag(reason, base["id"], base["source"], note)
        return {
            **base,
            "verdict": "refused",
            "reason": reason,
            "check": self.check_for(reason),
            **(extra or {}),
        }

    def refuse_item(self, item_id: str, reason: str) -> dict[str, Any]:
        self.flag(reason, item_id)
        return {
            "id": item_id,
            "outcome": "refused",
            "reason": reason,
            "check": self.check_for(reason),
        }


@dataclass
class _Runs:
    """The runs a source reference may name: this one, prior runs and children."""

    current: dict[str, Any]
    current_index: dict[str, dict[str, Any]]
    others: dict[str, Optional[dict[str, Any]]]
    prior_indexes: list[dict[str, dict[str, Any]]]
    children: list[dict[str, Any]]


def _new_checker(accuracy: Mapping[str, Any]) -> _Checker:
    raw_min = accuracy.get("min_quote_length", _MISSING)
    contract_ok = _is_positive_integer(raw_min)
    return _Checker(
        accuracy=accuracy,
        mapping=accuracy.get("refusal_checks") or {},
        min_len=raw_min if contract_ok else 0,
        contract_text=None if contract_ok else _contract_value_text(raw_min),
    )


def _build_runs(handback: Mapping[str, Any]) -> _Runs:
    current = {"entries": handback.get("entries") or [], "results": handback.get("results") or {}}
    current_index = _index_entries(current["entries"])

    prior_runs = handback.get("prior_runs") or {}
    # A child that is not an object or has no run label is skipped (no check id fits, so no flag).
    children = [c for c in _as_list(handback.get("children")) if _is_checkable_child(c)]
    others: dict[str, Optional[dict[str, Any]]] = {}
    for label, run in prior_runs.items():
        others[label] = {"run": run, "index": _index_entries(run.get("entries"))}
    for child in children:
        if child["label"] in others:
            others[child["label"]] = None
        else:
            others[child["label"]] = {"run": child, "index": _index_entries(child.get("entries"))}
    prior_indexes = [(others.get(label) or {"index": {}})["index"] for label in prior_runs]
    return _Runs(current, current_index, others, prior_indexes, children)


def _find_entry(
    ctx: _Checker, runs: _Runs, parsed: Mapping[str, Any], base: Mapping[str, Any]
) -> Optional[tuple[Mapping[str, Any], dict[str, Any]]]:
    """The run and entry a parsed reference names, or None when it names neither."""
    if parsed["label"] is None:
        run, index = runs.current, runs.current_index
        if any(parsed["id"] in prior for prior in runs.prior_indexes):
            ctx.flag("ambiguous_reference", base["id"], base["source"])
    else:
        other = runs.others.get(parsed["label"])
        if not other:
            return None
        run, index = other["run"], other["index"]
    entry = index.get(parsed["id"])
    if entry is None:
        return None
    return run, entry


def _action_refusal(
    fact: Mapping[str, Any], entry: Mapping[str, Any], text: Optional[str]
) -> Optional[str]:
    """Why a fact that an action happened is refused, or None when it is not."""
    if fact.get("action") is not True:
        return None
    tool = fact.get("tool") if isinstance(fact.get("tool"), str) and fact["tool"] != "" else None
    if tool is None:
        return "action_tool_missing"
    if entry["tool"] != tool:
        return "action_wrong_tool"
    if "error" in entry or _reports_failure(text):
        return "action_failed"
    return None


def _quote_outcome(
    ctx: _Checker,
    base: Mapping[str, Any],
    located: dict[str, Any],
    match: Mapping[str, Any],
    partial: bool,
) -> dict[str, Any]:
    """The fact's verdict from the matcher's answer for its quote."""
    text_independent = match["reason"] in ("quote_short", "literal_not_in_quote")
    if match["verdict"] == "unchecked":
        return {
            **base,
            **located,
            "verdict": "unchecked",
            "reason": "no_saved_text",
            "check": None,
        }
    if partial and not text_independent:
        return {
            **base,
            **located,
            "verdict": "unchecked",
            "reason": "partial_result",
            "check": None,
        }
    if match["verdict"] == "refused":
        return ctx.refuse_fact(base, match["reason"], {**located, "nearest": match["nearest"]})
    return {**base, **located, "verdict": "passed", "reason": None, "check": None}


def _check_fact(ctx: _Checker, runs: _Runs, raw: Any) -> dict[str, Any]:
    fact = _as_dict(raw)
    quote = _str(fact.get("quote"))
    base: dict[str, Any] = {
        "id": _str(fact.get("id")),
        "source": _str(fact.get("source")),
        "run": None,
        "nearest": None,
        "source_kind": None,
        "first_hand": None,
    }

    if ctx.contract_text is not None:
        note = f"accuracy.json min_quote_length is {ctx.contract_text}, not a positive integer"
        return ctx.refuse_fact(base, "quote_short", note=note)

    parsed = parse_source_ref(fact.get("source"))
    if not parsed["ok"]:
        return ctx.refuse_fact(base, parsed["reason"])
    found = _find_entry(ctx, runs, parsed, base)
    if found is None:
        return ctx.refuse_fact(base, "source_unknown", {"run": parsed["label"]})
    run, entry = found

    text = _saved_text(run.get("results") or {}, entry["id"])
    kind = _kind_of(entry, ctx.accuracy)
    located = {
        "run": parsed["label"],
        "source_kind": kind,
        "first_hand": _is_first_hand(kind, entry, quote, text, ctx.min_len),
    }

    action_reason = _action_refusal(fact, entry, text)
    if action_reason is not None:
        return ctx.refuse_fact(base, action_reason, located)
    match = check_quote(quote, literal_of(fact.get("value")), text, ctx.min_len)
    return _quote_outcome(ctx, base, located, match, entry.get("partial") is True)


def _accept(item_id: str) -> dict[str, Any]:
    return {"id": item_id, "outcome": "accepted", "reason": None, "check": None}


def _has_check(item: Mapping[str, Any]) -> bool:
    return isinstance(item.get("check"), str) and item["check"].strip() != ""


def _closing_index(verdict_items: list[dict[str, Any]]) -> int:
    marked = next((i for i, v in enumerate(verdict_items) if v.get("closing") is True), -1)
    return marked if marked >= 0 else len(verdict_items) - 1


def _verdict_refusal(
    item: Mapping[str, Any], basis: list[str], known: list[dict[str, Any]], closing: bool
) -> Optional[str]:
    """Why one verdict is refused, or None when it is accepted."""
    decided = _str(item.get("verdict")) in ("supported", "refuted")
    if len(known) < len(basis):
        return "unknown_fact"
    if any(f["verdict"] == "refused" for f in known):
        return "basis_refused"
    if decided and not basis:
        return "no_basis"
    if decided and _as_list(item.get("unread")):
        return "verdict_with_unread"
    if not decided and not _has_check(item):
        return "open_without_check"
    if decided and closing and not any(f["first_hand"] is True for f in known):
        return "closing_second_hand"
    return None


def _check_verdicts(
    ctx: _Checker, verdict_items: list[dict[str, Any]], fact_by_id: Mapping[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Each verdict's outcome, and how many verdicts rest on no known fact."""
    closing_index = _closing_index(verdict_items)
    without_fact = 0
    verdicts: list[dict[str, Any]] = []
    for position, item in enumerate(verdict_items):
        item_id = _str(item.get("id"))
        basis = [_str(b) for b in _as_list(item.get("basis"))]
        known = [fact_by_id[b] for b in basis if b in fact_by_id]
        if not known:
            without_fact += 1
        reason = _verdict_refusal(item, basis, known, position == closing_index)
        verdicts.append(_accept(item_id) if reason is None else ctx.refuse_item(item_id, reason))
    return verdicts, without_fact


def _check_open_items(
    ctx: _Checker, raw_items: Any, fact_by_id: Mapping[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Each open item's outcome, and how many open items rest on no known fact."""
    without_fact = 0
    open_items: list[dict[str, Any]] = []
    for raw in _as_list(raw_items):
        item = _as_dict(raw)
        item_id = _str(item.get("id"))
        if not any(_str(b) in fact_by_id for b in _as_list(item.get("basis"))):
            without_fact += 1
        open_items.append(
            _accept(item_id) if _has_check(item) else ctx.refuse_item(item_id, "open_without_check")
        )
    return open_items, without_fact


def check_handback(handback: Mapping[str, Any], accuracy: Mapping[str, Any]) -> dict[str, Any]:
    """Check one hand-back against its walk entries and saved results.

    *handback* has ``payload``, ``entries``, ``results`` and optionally
    ``prior_runs`` (label to ``{entries, results}``) and ``children`` (each a
    hand-back with a ``label``). Returns ``accepted``, ``facts``, ``verdicts``,
    ``open_items`` and ``report``, shaped like the TypeScript checker's result.
    """
    ctx = _new_checker(accuracy)
    runs = _build_runs(handback)
    payload = _as_dict(handback.get("payload"))

    # --- facts ---------------------------------------------------------------
    facts = [_check_fact(ctx, runs, raw) for raw in _as_list(payload.get("facts"))]

    # --- verdicts and open items ---------------------------------------------
    fact_by_id: dict[str, dict[str, Any]] = {}
    for fact_check in facts:
        fact_by_id.setdefault(fact_check["id"], fact_check)

    verdict_items = [_as_dict(v) for v in _as_list(payload.get("verdicts"))]
    verdicts, verdicts_without_fact = _check_verdicts(ctx, verdict_items, fact_by_id)
    open_items, open_without_fact = _check_open_items(ctx, payload.get("open_items"), fact_by_id)
    without_fact = verdicts_without_fact + open_without_fact

    # --- counts ----------------------------------------------------------------
    report = {
        "facts": fact_counts(facts),
        "conclusions": conclusion_counts(_str(v.get("verdict")) for v in verdict_items),
        "statements": {"made": len(verdicts) + len(open_items), "without_fact": without_fact},
        "by_source_kind": counts_by_source_kind(facts),
        "flags": ctx.flags,
        "python_recheck_ran": False,
        "children": [
            {"label": child["label"], "report": check_handback(child, accuracy)["report"]}
            for child in runs.children
        ],
    }
    accepted = (
        all(f["verdict"] != "refused" for f in facts)
        and all(v["outcome"] != "refused" for v in verdicts)
        and all(v["outcome"] != "refused" for v in open_items)
    )
    return {
        "accepted": accepted,
        "facts": facts,
        "verdicts": verdicts,
        "open_items": open_items,
        "report": report,
    }


# --- reading an export directory ------------------------------------------------


class ExportError(Exception):
    """An export directory that cannot be read (the verb turns it into a CliError)."""


def _walk_lines(walk_path: Path) -> list[Any]:
    """Each line of the walk that is whole JSON, parsed; any other line is skipped.

    A partly written last line is what a killed run leaves, and the cut may fall
    inside a multi-byte character: a line that is not UTF-8 is skipped exactly
    like a line that is not JSON. A walk that cannot be read is an ExportError.
    """
    try:
        raw = walk_path.read_bytes()
    except OSError as err:
        raise ExportError(f"cannot read {walk_path}: {err.strerror or err}") from err
    parsed_lines: list[Any] = []
    # surrogateescape keeps the line split of a str; a line holding an escape was not UTF-8.
    for line in raw.decode("utf-8", errors="surrogateescape").splitlines():
        line = line.strip()
        if not line or not _is_utf8(line):
            continue
        try:
            parsed_lines.append(json.loads(line))
        except (ValueError, RecursionError):
            continue
    return parsed_lines


def _is_utf8(line: str) -> bool:
    try:
        line.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _read_walk(walk_path: Path) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    """The format marker (or None for a pre-marker walk) and the tool entries.

    A line with a ``format`` key is the marker, whatever other keys it has; a
    ``format`` value that is not an object is a marker with no version.
    """
    marker: Optional[dict[str, Any]] = None
    entries: list[dict[str, Any]] = []
    for parsed in _walk_lines(walk_path):
        if not isinstance(parsed, dict):
            continue
        if "format" in parsed:
            marker = _as_dict(parsed["format"])
        elif _is_entry(parsed):
            entries.append(parsed)
    return marker, entries


def _format_of(marker: Optional[Mapping[str, Any]]) -> Any:
    """1 for a walk with no marker, else the marker's ``version`` as found (None when absent)."""
    if marker is None:
        return 1
    return marker.get("version")


def _is_format_version(version: Any) -> bool:
    return isinstance(version, int) and not isinstance(version, bool) and version >= 1


def _is_supported_format(version: Any) -> bool:
    """True when a walk format (as :func:`load_export` returns it) can be checked here."""
    return _is_format_version(version) and version <= max(SUPPORTED_WALK_FORMATS)


def inside_export(export_dir: Path, path: Path) -> bool:
    """True when ``path``, with every symbolic link followed, lies inside ``export_dir``.

    An export is written by a model run, so a file in it may be a link to anywhere.
    Nothing outside the export directory is read as part of it.
    """
    return Path(export_dir).resolve() in Path(path).resolve().parents


def _read_saved(export_dir: Path, root: Path, name: str) -> Optional[str]:
    """The text of one saved result file, or None when it is absent, unreadable or outside."""
    target = (export_dir / name).resolve()
    if root not in target.parents or not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _allowed_name(name: Any) -> Optional[str]:
    """*name* when it is a ``results/wN.txt`` name, the only kind ever opened, else None."""
    return name if isinstance(name, str) and _SAVED.match(name) else None


def _saved_names(entry: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """The file the entry names in ``saved_result`` and the file under its own id.

    This is the one place that decides which saved result files may be read:
    each is a ``results/wN.txt`` name, or None (the entry names no such file,
    or its id is not ``wN``).
    """
    entry_id = entry.get("id")
    own = f"results/{entry_id}.txt" if isinstance(entry_id, str) else None
    return _allowed_name(entry.get("saved_result")), _allowed_name(own)


def _read_result_files(export_dir: Path, entries: list[dict[str, Any]]) -> dict[str, str]:
    """File name to text, for the file each entry names and the file under its own id."""
    root = export_dir.resolve()
    files: dict[str, str] = {}
    for entry in entries:
        for name in _saved_names(entry):
            if name is None or name in files:
                continue
            text = _read_saved(export_dir, root, name)
            if text is not None:
                files[name] = text
    return files


def _read_results(entries: list[dict[str, Any]], files: Mapping[str, str]) -> dict[str, str]:
    """Walk id to saved text, for each ``results/wN.txt`` an entry names inside the export."""
    results: dict[str, str] = {}
    for entry in entries:
        named, _ = _saved_names(entry)
        if named is not None and named in files:
            results[entry["id"]] = files[named]
    return results


def _read_payload(export_dir: Path) -> Optional[dict[str, Any]]:
    """The facts payload, or None when the export has no facts file."""
    facts_path = export_dir / FACTS_FILENAME
    if not facts_path.is_file():
        return None
    if not inside_export(export_dir, facts_path):
        raise ExportError(f"{facts_path} points outside the export directory, so it is not read")
    try:
        loaded = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as err:
        raise ExportError(f"cannot read {facts_path}: {err}") from err
    if not isinstance(loaded, dict):
        raise ExportError(f"{facts_path} is not a JSON object")
    return loaded


def _open_walk(export_dir: Path) -> tuple[Any, list[dict[str, Any]]]:
    """The walk format and tool entries of an export directory, reading nothing else."""
    walk_path = export_dir / WALK_FILENAME
    if not export_dir.is_dir():
        raise ExportError(f"{export_dir} is not a directory")
    if not walk_path.is_file():
        raise ExportError(f"{export_dir} has no {WALK_FILENAME}")
    if not inside_export(export_dir, walk_path):
        raise ExportError(f"{walk_path} points outside the export directory, so it is not read")
    marker, entries = _read_walk(walk_path)
    return _format_of(marker), entries


def _load_rest(export_dir: Path, version: Any, entries: list[dict[str, Any]]) -> dict[str, Any]:
    files = _read_result_files(export_dir, entries)
    return {
        "format": version,
        "entries": entries,
        "results": _read_results(entries, files),
        "result_files": files,
        "payload": _read_payload(export_dir),
    }


def load_export(export_dir: Path) -> dict[str, Any]:
    """Read an export directory: walk entries, saved results and the facts payload.

    Returns ``format`` (the walk format version, 1 when there is no marker; the
    marker's ``version`` as found, None when absent, when it is not a positive
    integer), ``entries``, ``results`` (walk id to text), ``result_files`` and
    ``payload`` (None when no facts file exists). Only ``results/wN.txt`` names
    an entry's ``saved_result`` may be read into ``results``, and only inside
    the export directory. ``result_files`` is file name to text for those files
    and for ``results/<the entry's own id>.txt`` of every entry, under the same
    guard: the strict re-check reads an old-shape fact's saved result under the
    entry's own id, whether or not the entry names it.
    """
    export_dir = Path(export_dir)
    version, entries = _open_walk(export_dir)
    return _load_rest(export_dir, version, entries)


def _call_outcome(entry: Mapping[str, Any]) -> str:
    return "error" if "error" in entry else "ok"


def summarise_calls(
    entries: list[dict[str, Any]], accuracy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Each call's id, tool, stated purpose (None when it had none) and outcome."""
    calls = []
    for entry in entries:
        purpose = entry.get("purpose")
        calls.append(
            {
                "id": entry["id"],
                "tool": entry["tool"],
                "purpose": purpose if isinstance(purpose, str) else None,
                "outcome": _call_outcome(entry),
                "error": entry.get("error") if isinstance(entry.get("error"), str) else None,
                "source_kind": _kind_of(entry, accuracy),
                "partial": entry.get("partial") is True,
            }
        )
    return calls


def _child_links(walk_path: Path) -> list[tuple[str, str]]:
    """Each ``child`` line's id and ``child_walk``, first line per id, in walk order."""
    links: list[tuple[str, str]] = []
    try:
        parsed_lines = _walk_lines(walk_path)
    except ExportError:
        return links
    for parsed in parsed_lines:
        child = parsed.get("child") if isinstance(parsed, dict) else None
        if not isinstance(child, dict):
            continue
        child_id, child_walk = child.get("id"), child.get("child_walk")
        if (
            isinstance(child_id, str)
            and _CHILD_ID.fullmatch(child_id)
            and isinstance(child_walk, str)
            and child_id not in [existing for existing, _ in links]
        ):
            links.append((child_id, child_walk))
    return links


def _prior_dir(continue_from: Path) -> Optional[Path]:
    """The directory itself, or its ``export/`` child, whichever holds a walk."""
    for candidate in (continue_from, continue_from / "export"):
        if (candidate / WALK_FILENAME).is_file():
            return candidate
    return None


def _run_data(
    directory: Path, label: str, unsupported: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """A prior or child run, or None when it cannot be read or its walk format is not supported.

    A run in an unsupported format is not loaded (its payload is not read) and is
    added to *unsupported* as ``{label, walk_format}``.
    """
    try:
        version, entries = _open_walk(directory)
        if not _is_supported_format(version):
            unsupported.append({"label": label, "walk_format": version})
            return None
        loaded = _load_rest(directory, version, entries)
    except ExportError:
        return None
    return {
        "entries": loaded["entries"],
        "results": loaded["results"],
        "result_files": loaded["result_files"],
        "payload": loaded["payload"],
    }


def _child_dir(export_dir: Path, child_walk: str) -> Path:
    """The child's directory: the parent of its walk, a relative walk taken from the export."""
    walk = Path(child_walk)
    return (walk if walk.is_absolute() else export_dir / walk).parent


def load_handback_input(export_dir: Path, continue_from: Optional[Path] = None) -> dict[str, Any]:
    """Everything :func:`check_handback` reads for one run.

    The current run (``entries``, ``results``, ``payload``), the prior run under
    the label ``prior`` when *continue_from* names an export holding a walk, and
    each child the walk links, under its ``cN`` label. Labels are looked up, never
    taken from a fact: a child's directory is the parent of the ``child_walk``
    its ``child`` line (written by the harness) names, a relative one taken from
    the export directory. A child or prior run is another directory and is read
    from where it is, not confined to the export. A prior run with no walk is
    skipped; a child whose walk cannot be read counts as an empty run, the way the
    extension reads it. A prior or child run whose walk format is not supported
    is not loaded (skipped, or an empty child) and is listed in
    ``unsupported_runs`` as ``{label, walk_format}``. Each run also carries
    ``result_files`` (see :func:`load_export`).
    """
    export_dir = Path(export_dir)
    current = load_export(export_dir)
    unsupported: list[dict[str, Any]] = []
    prior_runs: dict[str, dict[str, Any]] = {}
    if continue_from is not None:
        prior_dir = _prior_dir(Path(continue_from))
        data = _run_data(prior_dir, PRIOR_RUN_LABEL, unsupported) if prior_dir else None
        if data is not None:
            prior_runs[PRIOR_RUN_LABEL] = {
                "entries": data["entries"],
                "results": data["results"],
                "result_files": data["result_files"],
            }
    children: list[dict[str, Any]] = []
    for label, child_walk in _child_links(export_dir / WALK_FILENAME):
        data = _run_data(_child_dir(export_dir, child_walk), label, unsupported)
        children.append(
            {
                "label": label,
                "payload": (data or {}).get("payload") or {},
                "entries": (data or {}).get("entries") or [],
                "results": (data or {}).get("results") or {},
                "result_files": (data or {}).get("result_files") or {},
            }
        )
    return {
        "format": current["format"],
        "payload": current["payload"],
        "entries": current["entries"],
        "results": current["results"],
        "result_files": current["result_files"],
        "prior_runs": prior_runs,
        "children": children,
        "unsupported_runs": unsupported,
    }


def _not_applicable_reason(loaded: Mapping[str, Any]) -> Optional[str]:
    """Why facts do not apply to a loaded export, or None when they do.

    The one decision both :func:`inspect_export` and the strict re-check use,
    in this order: a walk format that is not supported (or a marker whose
    version is not a positive integer, a missing one included), a walk with no
    format marker, no facts file.
    """
    version = loaded.get("format")
    reason = _format_reason(version)
    if reason is not None:
        return reason
    if version < 2:
        return "pre-change export: the walk has no format marker, so it carries no facts"
    if loaded.get("payload") is None:
        return f"no {FACTS_FILENAME} in the export: no hand-back facts were written"
    return None


def _unsupported_reason(version: Any) -> str:
    if not _is_format_version(version):
        found = "missing or null" if version is None else repr(version)
        return (
            f"unsupported export: the walk format marker's version is {found}, "
            "not a positive integer, so it is not checked"
        )
    known = ", ".join(str(v) for v in SUPPORTED_WALK_FORMATS)
    return (
        f"unsupported export: walk format {version} is newer than the formats "
        f"this checker supports ({known}), so it is not checked"
    )


def _format_reason(version: Any) -> Optional[str]:
    """Why a walk format cannot be checked here, or None when it can."""
    return None if _is_supported_format(version) else _unsupported_reason(version)


def _unsupported_result(export_dir: Path, version: Any) -> dict[str, Any]:
    """The result for a walk format this checker cannot read: no calls, no counts."""
    return {
        "export": str(export_dir),
        "walk_format": version,
        "calls": [],
        "applicable": False,
        "unsupported": True,
        "not_applicable_reason": _unsupported_reason(version),
        "facts": [],
        "report": None,
        "accepted": None,
        "unsupported_runs": [],
    }


def _strict_result(
    export_dir: Path,
    loaded: Mapping[str, Any],
    accuracy: Mapping[str, Any],
    base: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """The strict re-check's result for an export whose check.json says strict, else None."""
    from evidence.accuracy import strict_export  # here: strict_export imports this module

    record = strict_export.read_check_record(Path(export_dir))  # read once, passed down
    if not strict_export.is_strict_record(record):
        return None
    strict = strict_export.recheck_loaded(Path(export_dir), loaded, accuracy, record=record)
    return {
        **base,
        "check": strict_export.STRICT_MODE,
        "applicable": True,
        "not_applicable_reason": None,
        "facts": strict["recheck"]["facts"],
        "verdicts": strict["recheck"]["verdicts"],
        "open_items": strict["recheck"]["open_items"],
        "report": strict["recheck"]["report"],
        "accepted": strict["accepted"],
        "strict": strict,
    }


def inspect_export(
    export_dir: Path, accuracy: Mapping[str, Any], continue_from: Optional[Path] = None
) -> dict[str, Any]:
    """What the run check reports for one export directory.

    An export whose ``check.json`` has ``"mode": "strict"`` (and a facts
    payload) is re-checked by the strict re-check instead
    (:mod:`evidence.accuracy.strict_export`): the result then carries
    ``check: "strict"``, its ``facts``, ``verdicts`` and ``open_items`` are the
    strict records, ``report`` is the strict counts (the shape of
    ``report.json`` ``strict``), ``accepted`` says the checker refused nothing,
    and ``strict`` holds the whole re-check with its comparison against the
    export's own record. Any other export gives the quote check's result, with
    no ``check`` key, exactly as before.

    With no facts (a walk with no format marker, or no facts file) ``applicable``
    is false, ``facts`` is an empty list and ``report`` is None: facts are not
    applicable, not zero. A walk format above every :data:`SUPPORTED_WALK_FORMATS`
    version gives the same empty shape plus ``unsupported: true``, with the
    version found in ``walk_format``; its calls are not listed either. So does a
    format marker whose version is not a positive integer, the value named in
    the reason. The format is tested before anything else of the export is
    read. ``unsupported_runs`` lists each prior or child run that was not loaded
    because its walk format is not supported. *continue_from* adds the prior
    run under ``prior``; children are always read from the walk's ``child``
    lines.
    """
    version, _ = _open_walk(Path(export_dir))
    if _format_reason(version) is not None:
        return _unsupported_result(export_dir, version)
    loaded = load_handback_input(export_dir, continue_from)
    calls = summarise_calls(loaded["entries"], accuracy)
    base: dict[str, Any] = {
        "export": str(export_dir),
        "walk_format": loaded["format"],
        "calls": calls,
        "unsupported_runs": loaded["unsupported_runs"],
    }
    reason = _not_applicable_reason(loaded)
    if reason is not None:
        return {
            **base,
            "applicable": False,
            "not_applicable_reason": reason,
            "facts": [],
            "report": None,
            "accepted": None,
        }
    strict = _strict_result(export_dir, loaded, accuracy, base)
    if strict is not None:
        return strict
    result = check_handback(loaded, accuracy)
    result["report"]["python_recheck_ran"] = True
    return {
        **base,
        "applicable": True,
        "not_applicable_reason": None,
        "facts": result["facts"],
        "verdicts": result["verdicts"],
        "open_items": result["open_items"],
        "report": result["report"],
        "accepted": result["accepted"],
    }


# --- the run result ---------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _export_json(export_dir: Path, name: str) -> Optional[dict[str, Any]]:
    """A JSON file of the export, or None when it is absent, unreadable or linked from outside."""
    path = export_dir / name
    return _read_json(path) if inside_export(export_dir, path) else None


def _export_text(export_dir: Path, name: str) -> Optional[str]:
    """A text file of the export, or None when it is absent, unreadable or linked from outside."""
    path = export_dir / name
    return _read_text(path) if inside_export(export_dir, path) else None


def _handback_outcome(check: Optional[Mapping[str, Any]]) -> str:
    """``accepted``, ``refused_after_rounds`` (the run ended on a refused hand-back),
    ``refused_unresolved`` (a round was refused and the model did not hand back
    again) or ``none`` (no hand-back was recorded)."""
    if check is None:
        return "none"
    if check.get("outcome") == "accepted":
        return "accepted"
    if check.get("outcome") == "refused":
        return "refused_after_rounds" if check.get("run_ended") is True else "refused_unresolved"
    return "none"


def _fill_summary(summary: dict[str, Any], inspected: Mapping[str, Any], export_dir: Path) -> None:
    """Add the re-check's counts and verdict to *summary*, or why facts do not apply."""
    if not inspected["applicable"]:
        summary["not_applicable_reason"] = inspected["not_applicable_reason"]
        return
    report = dict(inspected["report"])
    ext_report = _export_json(export_dir, REPORT_FILENAME) or {}
    unchecked = ext_report.get("unchecked_text")
    if isinstance(unchecked, dict):
        report["unchecked_text"] = dict(unchecked)
        summary["unchecked_text_source"] = "extension"
    summary.update(
        python_recheck_ran=True,
        python_recheck_verdict="accepted" if inspected["accepted"] else "refused",
        report=report,
    )


def _strict_part(
    export_dir: Path,
    check: Optional[Mapping[str, Any]],
    accuracy: Mapping[str, Any],
    inspected: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """``accuracy_result``'s ``strict`` key: None only for an export that is not strict."""
    from evidence.accuracy import strict_export  # here: strict_export imports this module

    if not strict_export.is_strict_record(check):
        return None
    if "strict" in inspected:
        return inspected["strict"]
    return strict_export.not_applicable_result(
        export_dir,
        check,
        accuracy,
        inspected["not_applicable_reason"],
        unsupported=inspected.get("unsupported") is True,
    )


def accuracy_result(
    export_dir: Path,
    accuracy: Mapping[str, Any],
    *,
    continue_from: Optional[Path] = None,
    check_mode: Optional[str] = None,
    with_strict: bool = False,
) -> dict[str, Any]:
    """The accuracy fields of a harness run result (associate's ``associate run``).

    Read after the model stopped. For an unsupported (newer) walk format,
    ``accuracy`` also carries ``unsupported: true`` and ``walk_format``.

    ``answer`` is the harness-rendered ``answer.md`` (``None`` when the extension
    wrote none). ``accuracy.report`` holds the counts from the Python re-check of
    the saved facts, never the extension's own; only ``unchecked_text`` is copied
    from the extension's ``report.json`` (it counts model text this side does not
    have) and ``unchecked_text_source`` says so. ``check_mode`` is the per-run
    override the operator passed (``None`` when none), and ``check_mode_used`` the
    mode the extension recorded in ``check.json``.

    With *with_strict* true the result gains one key, ``strict``: for a strict
    export, what :func:`evidence.accuracy.strict_export.recheck_strict_export`
    returns (with no checkout root), from the one re-check this call already
    ran: the whole re-check with its comparison against the export's own
    record, or the not applicable result (``applicable: false``, the reason,
    ``recheck`` None) when facts do not apply. Where ``recheck_strict_export``
    would raise an ``ExportError`` it is that same not applicable result with
    the error as the reason. None only for an export that is not strict.
    Without the argument the result is what it was before the key existed.
    """
    export_dir = Path(export_dir)
    check = _export_json(export_dir, CHECK_FILENAME)
    answer_path = export_dir / ANSWER_FILENAME
    answer = _export_text(export_dir, ANSWER_FILENAME)
    summary: dict[str, Any] = {
        "check_mode_used": check.get("mode") if check else None,
        "check_mode_source": check.get("mode_source") if check else None,
        "python_recheck_ran": False,
        "python_recheck_verdict": None,
        "extension_accepted": check.get("accepted") if check else None,
        "not_applicable_reason": None,
        "report": None,
        "unchecked_text_source": None,
    }
    try:
        inspected = inspect_export(export_dir, accuracy, continue_from)
    except ExportError as err:
        inspected = {"applicable": False, "not_applicable_reason": str(err)}
    _fill_summary(summary, inspected, export_dir)
    if inspected.get("unsupported") is True:
        summary.update(unsupported=True, walk_format=inspected["walk_format"])
    if "check" in inspected:  # only a strict export names its check; any other is unchanged
        summary["check"] = inspected["check"]
    result = {
        "check_mode": check_mode,
        "answer": answer,
        "answer_path": str(answer_path) if answer is not None else None,
        "handback_outcome": _handback_outcome(check),
        "accuracy": summary,
    }
    if with_strict:
        result["strict"] = _strict_part(export_dir, check, accuracy, inspected)
    return result
