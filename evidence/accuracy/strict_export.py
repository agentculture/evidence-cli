"""Re-check a stored strict export and compare the result with what the export recorded.

An associate run with strict facts on leaves, in its export directory,
``walk.jsonl``, ``results/wN.txt``, ``facts.json`` and a ``check.json`` whose
``mode`` is ``strict``: one record per fact in hand-back order (with the
decider's stored answer under ``judge``), one per verdict and open item,
``accepted``, and a top-level ``strict`` object (rounds, counts, drop reasons,
judge counts, dropped and returned items). :func:`strict_export_input` rebuilds
the input of :func:`evidence.accuracy.strict.strict_recheck` from those files;
:func:`recheck_strict_export` runs it and compares the result with the record.

What is rebuilt from where:

* the walk, the saved results, a ``--continue-from`` prior run and the child
  runs: read as :func:`evidence.accuracy.check.load_handback_input` reads them
  (nothing outside the export is read through a link, children and the prior
  run are read from where they are). The saved results are its
  ``result_files``: the file each entry names in ``saved_result`` and the file
  under the entry's own id, because a pointer reads the first and an old-shape
  fact the second;
* the finish payload: ``facts.json``;
* the decider's answers: each fact record's ``judge`` in ``check.json`` (an
  option, or the reason it was not judged), keyed by the fact's position when
  the records line up with the payload's facts (same number, same id at each
  position), else by fact id. The re-check never asks a decider;
* ``rounds_left``: ``check.json`` ``strict.retry_rounds`` less the rounds used
  before this hand-back (``rounds_used``, one fewer when ``round_open`` says
  this hand-back was itself sent back);
* ``returned_before``: ``check.json`` ``strict.returned_before`` (the fact ids
  returned in earlier rounds, a list of strings) when the record holds it. The
  re-check then decides ``keep_marked`` against ``returned`` itself and can
  disagree with the record on it; the result's ``returned_before_source`` is
  ``check.json``. An export written before the key existed does not hold it
  (and a value that is not a list of strings counts as not recorded). Then the
  facts the record has as ``keep_marked`` while a round was left can only have
  been returned before, so they are taken as ``returned_before``; the re-check
  cannot disagree with the record on ``keep_marked`` against ``returned``, and
  ``returned_before_source`` is ``inferred from keep_marked``;
* the contract values: from the settings the caller passes (as
  :func:`evidence.accuracy.check.check_handback` takes them). The settings'
  ``strict`` block is used whenever it is well formed (``keep_marked`` and
  ``drop`` lists); otherwise the bundled defaults
  (``evidence/data/strict_defaults.json``) are, and the result says which;
* the redaction filter for the printed command: the settings' ``redaction``,
  else the bundled default. A pattern Python cannot compile is an
  :class:`~evidence.accuracy.check.ExportError` naming it. The checkout root is
  not in the export; the caller may pass it, else no checkout path is made
  relative.

What is compared: per fact the kind checked, the outcome and the drop reason;
per verdict and open item the id, outcome, reason, strict outcome and strict
reason; ``accepted``; and the ``strict`` object's ``counts``, ``drop_reasons``
and ``judge_counts``. One rule decides what is a disagreement:

* a part the record does not hold is listed under ``not_compared`` and gives no
  disagreement row, never an agreement either;
* the decider's stored answers are in the record's ``facts``. Without that part
  the re-check has no answers, so every part that follows from the outcomes
  (all but ``accepted``, the checker's verdict) is listed under
  ``not_compared`` too, whether or not the record holds it;
* a row is a disagreement only when the recorded and the re-checked value
  differ. A fact with no record of its own (the record lists fewer facts) gives
  no field rows: the ``facts`` count row says the numbers differ;
* ``agrees`` is true when at least one part was compared and no row differs,
  false when a row differs, and None when no part could be compared
  (``agrees_reason`` then says so). None is not agreement.

A strict export with no facts file (or a walk with no format marker) is not
applicable, as :func:`evidence.accuracy.check.inspect_export` reports it, with
the same reason: nothing is re-checked and nothing is compared.

A passed fact means its evidence was copied from a saved result or its quote
was found in one; a judged fact carries the decider's stored answer. Nothing
here says a value is true.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

from evidence.accuracy.check import (
    CHECK_FILENAME,
    ExportError,
    _export_json,
    _not_applicable_reason,
    load_handback_input,
)
from evidence.accuracy.command import compile_redaction
from evidence.accuracy.strict import recheck_with_checker

#: ``check.json`` ``mode`` of an export the strict re-check reads.
STRICT_MODE = "strict"
#: The per-fact fields compared with the export's own record.
COMPARED_FIELDS: tuple[str, ...] = ("kind_checked", "strict_outcome", "drop_reason")
#: The per-item fields (verdicts and open items) compared with the record.
ITEM_FIELDS: tuple[str, ...] = ("id", "outcome", "reason", "strict_outcome", "strict_reason")
#: The parts of the record the comparison reads, in the order they are reported.
PARTS: tuple[str, ...] = (
    "facts",
    "verdicts",
    "open_items",
    "accepted",
    "counts",
    "drop_reasons",
    "judge_counts",
)
_SETTINGS = "settings"
_DEFAULTS = "bundled defaults"
#: ``returned_before_source``: the record held ``strict.returned_before``.
RETURNED_FROM_RECORD = "check.json"
#: ``returned_before_source``: the record did not; taken from its ``keep_marked`` facts.
RETURNED_INFERRED = "inferred from keep_marked"
#: ``agrees_reason`` when the record holds none of :data:`PARTS`.
NOTHING_COMPARED = "nothing in check.json could be compared"
_COUNT_PARTS = ("counts", "drop_reasons", "judge_counts")
_ACCEPTED = "accepted"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _whole(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def read_check_record(export_dir: Path) -> Optional[dict[str, Any]]:
    """The export's ``check.json`` as a dict, or None when absent, unreadable or linked outside."""
    return _export_json(Path(export_dir), CHECK_FILENAME)


def is_strict_record(record: Optional[Mapping[str, Any]]) -> bool:
    return record is not None and record.get("mode") == STRICT_MODE


def is_strict_export(export_dir: Path) -> bool:
    """True when the export's ``check.json`` says ``"mode": "strict"``."""
    return is_strict_record(read_check_record(export_dir))


# --- the contract values -----------------------------------------------------------------


def load_strict_defaults() -> dict[str, Any]:
    """The bundled default strict contract values (``evidence/data/strict_defaults.json``).

    ``strict``, ``support_passes`` and ``redaction``: the values the shared
    strict cases record today, but for the two cases that set their own strict
    block (a test keeps them equal). Each call parses the
    file again, so a caller may change the returned dict freely.
    """
    text = resources.files("evidence").joinpath("data/strict_defaults.json").read_text("utf-8")
    return json.loads(text)


def _usable_strict(section: Any) -> bool:
    return (
        isinstance(section, dict)
        and isinstance(section.get("keep_marked"), list)
        and isinstance(section.get("drop"), list)
    )


def _support_passes(settings: Mapping[str, Any]) -> Optional[list[Any]]:
    if isinstance(settings.get("support_passes"), list):
        return settings["support_passes"]
    passes = _as_dict(settings.get("support_score")).get("passes")
    return passes if isinstance(passes, list) else None


def _checked_redaction(redaction: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        compile_redaction(redaction)
    except ValueError as err:
        raise ExportError(f"settings: {err}") from err
    return redaction


def strict_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The contract subset and redaction filter the strict re-check reads, and their source.

    Returns ``contract`` (``strict``, ``support_passes``, ``min_quote_length``,
    ``retry_rounds``, ``source_kinds``), ``redaction`` and ``strict_source``:
    ``settings`` when *settings* holds a well-formed ``strict`` block (lists
    ``keep_marked`` and ``drop``), else ``bundled defaults``. ``support_passes``
    is carried in the contract for the record only: the re-check does not read
    it (a support answer named in no strict list passes). Raises
    :class:`~evidence.accuracy.check.ExportError` for a redaction pattern Python
    cannot compile.
    """
    defaults = load_strict_defaults()
    section = settings.get("strict")
    own = _usable_strict(section)
    strict = section if own else defaults["strict"]
    redaction = settings.get("redaction")
    return {
        "contract": {
            "strict": {
                "keep_marked": strict["keep_marked"],
                "drop": strict["drop"],
                "mark_text": strict.get("mark_text"),
                "derived_decides_drops": strict.get("derived_decides_drops") is True,
                "derived_passes": _as_list(strict.get("derived_passes")),
            },
            "support_passes": _support_passes(settings) or defaults["support_passes"],
            "min_quote_length": settings.get("min_quote_length"),
            "retry_rounds": settings.get("retry_rounds"),
            "source_kinds": _as_dict(settings.get("source_kinds")),
        },
        "redaction": _checked_redaction(
            redaction if isinstance(redaction, dict) else defaults["redaction"]
        ),
        "strict_source": _SETTINGS if own else _DEFAULTS,
    }


# --- the record ----------------------------------------------------------------------------


def _record_facts(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The record's fact records, each an object with a string ``id``, else an ExportError."""
    facts = record.get("facts", [])
    if not isinstance(facts, list):
        raise ExportError(f"{CHECK_FILENAME} facts is not a list")
    for number, fact in enumerate(facts, start=1):
        if not isinstance(fact, dict) or not isinstance(fact.get("id"), str):
            raise ExportError(
                f"{CHECK_FILENAME} fact record {number} is not an object with a string id"
            )
    return facts


def _strict_record(export_dir: Path) -> dict[str, Any]:
    record = read_check_record(export_dir)
    if not is_strict_record(record):
        raise ExportError(f"{export_dir} has no {CHECK_FILENAME} with mode strict")
    return record


# --- rebuilding the case input --------------------------------------------------------------


def _by_name(entries: list[dict[str, Any]], results: Mapping[str, Any]) -> dict[str, str]:
    """Saved texts keyed by the file name each entry's ``saved_result`` gives."""
    out: dict[str, str] = {}
    for entry in entries:
        name = entry.get("saved_result")
        if isinstance(name, str) and isinstance(results.get(entry["id"]), str):
            out[name] = results[entry["id"]]
    return out


def _run(data: Mapping[str, Any]) -> dict[str, Any]:
    """One run as the case input holds it: its walk and its saved texts by file name."""
    entries = _as_list(data.get("entries"))
    files = data.get("result_files")
    if not isinstance(files, dict):  # a caller's own loaded data, without the file names
        files = _by_name(entries, _as_dict(data.get("results")))
    return {"walk": entries, "results": files}


def _answer(fact: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """A fact record's stored decider answer: ``{question, option}``, ``{not_judged}`` or None."""
    judge = fact.get("judge")
    if not isinstance(judge, dict):
        return None
    if judge.get("option") is not None:
        return {"question": judge.get("question"), "option": judge["option"]}
    return {"not_judged": judge.get("reason")}


def _answers_by_id(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    for fact in facts:
        answer = _answer(fact)
        if answer is not None:
            answers.setdefault(fact["id"], answer)
    return answers


def _answers_by_position(facts: list[dict[str, Any]], payload: list[Any]) -> Optional[list]:
    """Answers in hand-back order, or None when the records do not line up with the payload."""
    ids = [_as_dict(raw).get("id") for raw in payload]
    if ids != [fact["id"] for fact in facts]:
        return None
    return [_answer(fact) for fact in facts]


def _rounds_left(record: Mapping[str, Any], retry_rounds: Any) -> int:
    """Rounds that could still send facts back when this hand-back was checked."""
    strict = _as_dict(record.get("strict"))
    allowed = _whole(strict.get("retry_rounds"), _whole(retry_rounds))
    used = _whole(strict.get("rounds_used"))
    used_before = used - 1 if strict.get("round_open") is True else used
    return max(0, allowed - used_before)


def _recorded_returned_before(record: Mapping[str, Any]) -> Optional[list[str]]:
    """``strict.returned_before`` when the record holds a list of strings, else None."""
    value = _as_dict(record.get("strict")).get("returned_before")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _inferred_returned_before(facts: list[dict[str, Any]], rounds_left: int) -> list[str]:
    """Facts kept marked while a round was left: only a fact returned before is kept so."""
    if rounds_left <= 0:
        return []
    return [fact["id"] for fact in facts if fact.get("strict_outcome") == "keep_marked"]


def _returned_before(
    record: Mapping[str, Any], facts: list[dict[str, Any]], rounds_left: int
) -> list[str]:
    """The ids returned in earlier rounds: as recorded, else taken from the kept facts."""
    recorded = _recorded_returned_before(record)
    if recorded is not None:
        return recorded
    return _inferred_returned_before(facts, rounds_left)


def _returned_source(record: Mapping[str, Any]) -> str:
    """Where ``returned_before`` came from: the record, or its ``keep_marked`` facts."""
    held = _recorded_returned_before(record) is not None
    return RETURNED_FROM_RECORD if held else RETURNED_INFERRED


def _build_input(
    loaded: Mapping[str, Any],
    record: Mapping[str, Any],
    contract: Mapping[str, Any],
    checkout_root: str,
) -> dict[str, Any]:
    facts = _record_facts(record)
    payload = _as_dict(loaded.get("payload"))
    payload_facts = _as_list(payload.get("facts"))
    rounds_left = _rounds_left(record, contract.get("retry_rounds"))
    returned_before = _returned_before(record, facts, rounds_left)
    case_input = {
        "checkout_root": checkout_root,
        **_run(loaded),
        "prior_runs": {label: _run(run) for label, run in loaded["prior_runs"].items()},
        "children": [{"label": c["label"], **_run(c)} for c in loaded["children"]],
        "finish": {
            "facts": payload_facts,
            "verdicts": _as_list(payload.get("verdicts")),
            "open_items": _as_list(payload.get("open_items")),
        },
        "contract": dict(contract),
        "decider": _answers_by_id(facts),
        "returned_before": returned_before,
        "rounds_left": rounds_left,
    }
    by_position = _answers_by_position(facts, payload_facts)
    if by_position is not None:
        case_input["decider_by_position"] = by_position
    return case_input


def strict_export_input(
    export_dir: Path,
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
    continue_from: Optional[Path] = None,
) -> dict[str, Any]:
    """The strict re-check's input rebuilt from a stored strict export (see the module text).

    Raises :class:`evidence.accuracy.check.ExportError` when the export cannot
    be read, its ``check.json`` is not a strict record, or a fact record in it
    is malformed.
    """
    export_dir = Path(export_dir)
    record = _strict_record(export_dir)
    loaded = load_handback_input(export_dir, continue_from)
    contract = strict_settings(settings)["contract"]
    return _build_input(loaded, record, contract, checkout_root)


# --- the comparison -----------------------------------------------------------------------------


def _difference(item_id: Any, field: str, recorded: Any, recheck: Any) -> dict[str, Any]:
    return {"id": item_id, "field": field, "recorded": recorded, "recheck": recheck}


def _field(recorded: Any, got: Any, found: bool) -> dict[str, Any]:
    """One compared field; ``agree`` is None when there is no record to compare with."""
    return {"recorded": recorded, "recheck": got, "agree": recorded == got if found else None}


def _fact_row(position: int, got: Mapping[str, Any], recorded: Any, source: Any) -> dict:
    """One fact's row. *recorded* is its record, or None when there is none to compare."""
    found = recorded is not None
    theirs = _as_dict(recorded)
    fields = {name: _field(theirs.get(name), got[name], found) for name in COMPARED_FIELDS}
    return {
        "position": position,
        "id": got["id"],
        "source": source if isinstance(source, str) else None,
        "recorded_found": found,
        "agrees": all(field["agree"] for field in fields.values()) if found else None,
        "fields": fields,
    }


def _fact_rows(result, facts: Optional[list], payload_facts) -> list[dict]:
    """One row per re-checked fact; *facts* is None when the record holds no facts part."""
    rows = []
    for position, got in enumerate(result["facts"]):
        theirs = facts[position] if facts is not None and position < len(facts) else None
        raw = payload_facts[position] if position < len(payload_facts) else None
        rows.append(_fact_row(position, got, theirs, _as_dict(raw).get("source")))
    return rows


def _fact_part(rows: list[dict], recorded_count: int) -> list[dict]:
    """The facts part's disagreements: each field that differs, and the count when it does."""
    found = [
        _difference(row["id"], name, field["recorded"], field["recheck"])
        for row in rows
        for name, field in row["fields"].items()
        if field["agree"] is False
    ]
    if recorded_count != len(rows):
        found.append(_difference(None, PARTS[0], recorded_count, len(rows)))
    return found


def _item_part(part: str, ours: list[dict], theirs: list[Any]) -> list[dict[str, Any]]:
    """Per verdict or open item, by position: each field of ITEM_FIELDS that differs."""
    found = []
    for position, got in enumerate(ours):
        if position >= len(theirs):
            break
        recorded = _as_dict(theirs[position])
        for name in ITEM_FIELDS:
            if recorded.get(name) != got[name]:
                found.append(
                    _difference(got["id"], f"{part}.{name}", recorded.get(name), got[name])
                )
    if len(theirs) != len(ours):
        found.append(_difference(None, part, len(theirs), len(ours)))
    return found


def _count_part(section: str, theirs: Mapping[str, Any], ours: Mapping[str, Any]) -> list[dict]:
    return [
        _difference(None, f"{section}.{key}", theirs.get(key, 0), ours.get(key, 0))
        for key in sorted(set(theirs) | set(ours))
        if theirs.get(key, 0) != ours.get(key, 0)
    ]


def _recorded_parts(record: Mapping[str, Any]) -> dict[str, Any]:
    """Each part of the record that can be compared.

    An absent or malformed part is left out; so is every part but ``accepted``
    when the record holds no ``facts`` (see the module text).
    """
    strict = _as_dict(record.get("strict"))
    parts: dict[str, Any] = {}
    if isinstance(record.get("facts"), list):
        parts["facts"] = record["facts"]
    for part in ("verdicts", "open_items"):
        if isinstance(record.get(part), list):
            parts[part] = record[part]
    if isinstance(record.get(_ACCEPTED), bool):
        parts[_ACCEPTED] = record[_ACCEPTED]
    for part in _COUNT_PARTS:
        if isinstance(strict.get(part), dict):
            parts[part] = strict[part]
    if PARTS[0] not in parts:  # no stored answers: only the checker's verdict can be compared
        return {part: value for part, value in parts.items() if part == _ACCEPTED}
    return parts


def _part_disagreements(part: str, theirs: Any, result: Mapping[str, Any], accepted: bool):
    if part in ("verdicts", "open_items"):
        return _item_part(part, result[part], theirs)
    if part == _ACCEPTED:
        return [] if theirs == accepted else [_difference(None, part, theirs, accepted)]
    return _count_part(part, theirs, result[part])


def _agreement(compared: list[str], disagreements: list[dict]) -> tuple[Optional[bool], Any]:
    """``agrees`` and ``agrees_reason``: None with the reason when nothing was compared."""
    if not compared:
        return None, NOTHING_COMPARED
    return not disagreements, None


def compare_with_record(
    result: Mapping[str, Any],
    record: Mapping[str, Any],
    payload_facts: list[Any],
    accepted: bool,
) -> dict[str, Any]:
    """Compare the re-check with the export's own record, part by part (see the module text).

    Returns ``agrees`` (true: a part was compared and nothing differs; false:
    something differs; None: no part could be compared), ``agrees_reason``
    (None, or why ``agrees`` is None), ``compared`` and ``not_compared`` (the
    parts of :data:`PARTS` the record does or does not hold), ``facts`` (one row
    per fact; its ``agrees`` and each field's ``agree`` are None when the record
    holds no record of that fact) and ``disagreements`` (each field that
    differs, with both values; never a row for a part in ``not_compared``, never
    a row whose two values are equal). *accepted* is the re-check's checker
    verdict.
    """
    held = _recorded_parts(record)
    facts = _record_facts(record) if PARTS[0] in held else None
    rows = _fact_rows(result, facts, payload_facts)
    disagreements = _fact_part(rows, len(facts)) if facts is not None else []
    for part in PARTS[1:]:
        if part in held:
            disagreements += _part_disagreements(part, held[part], result, accepted)
    compared = [part for part in PARTS if part in held]
    agrees, reason = _agreement(compared, disagreements)
    return {
        "agrees": agrees,
        "agrees_reason": reason,
        "compared": compared,
        "not_compared": [part for part in PARTS if part not in held],
        "facts": rows,
        "disagreements": disagreements,
    }


def _recorded_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "accepted": record.get("accepted"),
        "outcome": record.get("outcome"),
        "counts": _as_dict(record.get("strict")).get("counts"),
    }


def _not_applicable(export_dir: Path, record: Mapping[str, Any], source: str, reason: str) -> dict:
    """The result for a strict export where facts do not apply: nothing re-checked or compared."""
    return {
        "check": STRICT_MODE,
        "export": str(export_dir),
        "applicable": False,
        "not_applicable_reason": reason,
        "strict_source": source,
        "rounds_left": None,
        "returned_before": [],
        "returned_before_source": None,
        "recheck": None,
        "accepted": None,
        "recorded": _recorded_summary(record),
        "comparison": {
            "agrees": None,
            "agrees_reason": reason,
            "compared": [],
            "not_compared": list(PARTS),
            "facts": [],
            "disagreements": [],
        },
    }


# --- the entry point ------------------------------------------------------------------------------


def recheck_loaded(
    export_dir: Path,
    loaded: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
    record: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """:func:`recheck_strict_export` over an export already read by ``load_handback_input``.

    *record* is the export's ``check.json`` when the caller has read it already
    (it is then not read again).
    """
    if record is None:
        record = _strict_record(Path(export_dir))
    chosen = strict_settings(settings)
    reason = _not_applicable_reason(loaded)
    if reason is not None:
        return _not_applicable(Path(export_dir), record, chosen["strict_source"], reason)
    case_input = _build_input(loaded, record, chosen["contract"], checkout_root)
    result, accepted = recheck_with_checker(case_input, chosen["redaction"])
    return {
        "check": STRICT_MODE,
        "export": str(export_dir),
        "applicable": True,
        "not_applicable_reason": None,
        "strict_source": chosen["strict_source"],
        "rounds_left": case_input["rounds_left"],
        "returned_before": case_input["returned_before"],
        "returned_before_source": _returned_source(record),
        "recheck": result,
        "accepted": accepted,
        "recorded": _recorded_summary(record),
        "comparison": compare_with_record(result, record, case_input["finish"]["facts"], accepted),
    }


def recheck_strict_export(
    export_dir: Path,
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
    continue_from: Optional[Path] = None,
) -> dict[str, Any]:
    """Re-check a stored strict export and compare it with the export's own ``check.json``.

    Returns ``check`` (``"strict"``), ``export``, ``applicable`` and
    ``not_applicable_reason``, ``strict_source`` (where the strict contract
    values came from), ``rounds_left`` and ``returned_before`` (as rebuilt),
    ``returned_before_source`` (``check.json`` when the record holds
    ``strict.returned_before``, else ``inferred from keep_marked``), ``recheck``
    (the :func:`strict_recheck` result), ``accepted`` (the checker refused
    nothing), ``recorded`` (what ``check.json`` says) and ``comparison`` (see
    :func:`compare_with_record`).

    An export with no facts file, or a walk with no format marker, is not
    applicable, with the reason :func:`evidence.accuracy.check.inspect_export`
    gives: ``applicable`` is false, ``recheck``, ``accepted`` and
    ``rounds_left`` are None, and ``comparison`` holds no rows with ``agrees``
    None. Raises
    :class:`evidence.accuracy.check.ExportError` when the export cannot be read,
    a fact record in ``check.json`` is malformed, or a redaction pattern in the
    settings cannot be compiled.
    """
    export_dir = Path(export_dir)
    record = _strict_record(export_dir)
    loaded = load_handback_input(export_dir, continue_from)
    return recheck_loaded(export_dir, loaded, settings, checkout_root=checkout_root, record=record)
