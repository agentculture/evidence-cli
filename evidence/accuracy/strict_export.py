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
  option, or the reason it was not judged), given to the fact the record is
  paired with (see the pairing below). The re-check never asks a decider;
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
and ``judge_counts``.

The pairing. One pairing of fact records with the payload's facts serves both
the stored answers and the comparison:

* by position, when the records line up with the payload's facts (the same
  number, the same id at each position);
* else by id, when no id is repeated among the payload's facts or among the
  records. A fact whose id no record has is the fact without a record;
* else the facts cannot be paired: no fact gets a stored answer, no fact is
  compared, and the ``facts`` part is listed under ``not_compared``.

What is a disagreement, and what ``agrees`` says:

* a part the record does not hold is listed under ``not_compared`` and gives no
  disagreement row; ``not_compared_reasons`` says why for each part;
* the decider's stored answers are in the fact records. When a payload fact has
  no record of its own (the ``facts`` part is absent, cannot be paired, or
  lists fewer facts) the answers are incomplete, so every part that follows
  from the outcomes (all but ``facts`` and ``accepted``, the checker's verdict)
  is listed under ``not_compared`` too, whether or not the record holds it;
* a row is a disagreement only when the recorded and the re-checked value
  differ. A fact with no record gives no field rows. It is reported once, by
  the ``facts`` row: the two counts, with ``without_record`` (the fact ids with
  no record) and ``not_in_payload`` (the record ids of no fact). When the
  counts are equal the row's field is ``facts.ids`` and it holds the two id
  lists;
* ``agrees`` is false when there is any disagreement row; true only when there
  is none and the ``facts`` part was compared with a record for every payload
  fact; otherwise None, and ``agrees_reason`` names what was not compared.
  None is not agreement;
* ``incomplete`` is true when a part was not compared or a payload fact has no
  record. A key that is not one of :data:`PARTS` (``strict.returned_before``,
  say) does not make a record incomplete.

Whether facts apply is decided in one place,
:func:`evidence.accuracy.check._not_applicable_reason`, for this re-check and
for :func:`evidence.accuracy.check.inspect_export`: a walk format that is not
supported (or a format marker with no usable version), a walk with no format
marker, or no facts file is not applicable, with the same reason from both.
Nothing is then re-checked or compared; the fact records are still validated.

A passed fact means its evidence was copied from a saved result or its quote
was found in one; a judged fact carries the decider's stored answer. Nothing
here says a value is true.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

from evidence.accuracy.check import (
    CHECK_FILENAME,
    ExportError,
    _export_json,
    _format_reason,
    _not_applicable_reason,
    _open_walk,
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
#: ``not_compared_reasons``: the record does not hold the part (or not in a usable form).
REASON_ABSENT = "absent from check.json"
#: ``not_compared_reasons``: the fact records and the payload's facts cannot be paired.
REASON_UNPAIRED = "the fact records cannot be paired with the payload's facts"
#: ``not_compared_reasons``: the part follows from outcomes that needed a missing stored answer.
REASON_NO_ANSWERS = (
    "a fact has no record in check.json, so the decider's stored answers are incomplete"
)
_COUNT_PARTS = ("counts", "drop_reasons", "judge_counts")
_FACTS = "facts"
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


def _by_name(entries: list[Any], results: Mapping[str, Any]) -> dict[str, str]:
    """Saved texts keyed by the file name each entry's ``saved_result`` gives."""
    out: dict[str, str] = {}
    for entry in entries:
        name, text = _as_dict(entry).get("saved_result"), results.get(_as_dict(entry).get("id"))
        if isinstance(name, str) and isinstance(text, str):
            out[name] = text
    return out


def _run(data: Any) -> dict[str, Any]:
    """One run as the case input holds it: its walk and its saved texts by file name."""
    data = _as_dict(data)
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


# --- pairing fact records with the payload's facts ---------------------------------------------


@dataclass(frozen=True)
class _Pairing:
    """Fact records paired with the payload's facts (see the module text).

    ``records`` holds one entry per payload fact: its record, or None when it
    has none. ``reason`` says why the facts part cannot be compared (the record
    holds none, or they cannot be paired), else None. ``extra`` lists the ids
    of records paired with no fact.
    """

    records: list[Optional[dict[str, Any]]]
    reason: Optional[str]
    extra: list[str]
    recorded: int

    @property
    def paired(self) -> bool:
        return self.reason is None

    @property
    def complete(self) -> bool:
        """Every payload fact has its record, so its stored answer."""
        return self.paired and all(record is not None for record in self.records)


def _unique_strings(ids: list[Any]) -> bool:
    return all(isinstance(item, str) for item in ids) and len(set(ids)) == len(ids)


def _unpaired(payload_ids: list[Any], reason: str, recorded: int) -> _Pairing:
    return _Pairing([None] * len(payload_ids), reason, [], recorded)


def _pair(record: Mapping[str, Any], payload_facts: list[Any]) -> _Pairing:
    """The one pairing of the record's fact records with the payload's facts."""
    payload_ids = [_as_dict(raw).get("id") for raw in payload_facts]
    if not isinstance(record.get(_FACTS), list):
        return _unpaired(payload_ids, REASON_ABSENT, 0)
    records = _record_facts(record)
    record_ids = [fact["id"] for fact in records]
    if payload_ids == record_ids:
        return _Pairing(list(records), None, [], len(records))
    if not (_unique_strings(payload_ids) and _unique_strings(record_ids)):
        return _unpaired(payload_ids, REASON_UNPAIRED, len(records))
    by_id = dict(zip(record_ids, records))
    extra = [item for item in record_ids if item not in payload_ids]
    return _Pairing([by_id.get(item) for item in payload_ids], None, extra, len(records))


def _answers(pairing: _Pairing) -> list[Optional[dict[str, Any]]]:
    """One stored answer or None per payload fact, from the record it is paired with."""
    return [None if record is None else _answer(record) for record in pairing.records]


def _answers_by_id(pairing: _Pairing) -> dict[str, dict[str, Any]]:
    """The same answers keyed by fact id, the first fact of an id first."""
    answers: dict[str, dict[str, Any]] = {}
    for record, answer in zip(pairing.records, _answers(pairing)):
        if answer is not None:
            answers.setdefault(record["id"], answer)
    return answers


def _rounds_left(record: Mapping[str, Any], retry_rounds: Any) -> int:
    """Rounds that could still send facts back when this hand-back was checked."""
    strict = _as_dict(record.get("strict"))
    allowed = _whole(strict.get("retry_rounds"), _whole(retry_rounds))
    used = _whole(strict.get("rounds_used"))
    used_before = used - 1 if strict.get("round_open") is True else used
    return max(0, allowed - used_before)


def _inferred_returned_before(facts: list[dict[str, Any]], rounds_left: int) -> list[str]:
    """Facts kept marked while a round was left: only a fact returned before is kept so."""
    if rounds_left <= 0:
        return []
    return [fact["id"] for fact in facts if fact.get("strict_outcome") == "keep_marked"]


def _returned_before(
    record: Mapping[str, Any], facts: list[dict[str, Any]], rounds_left: int
) -> tuple[list[str], str]:
    """The ids returned in earlier rounds, and where they came from.

    ``strict.returned_before`` when the record holds a list of strings, else the
    ids taken from the facts it records as kept with the mark.
    """
    value = _as_dict(record.get("strict")).get("returned_before")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value), RETURNED_FROM_RECORD
    return _inferred_returned_before(facts, rounds_left), RETURNED_INFERRED


def _build_input(
    loaded: Mapping[str, Any],
    record: Mapping[str, Any],
    contract: Mapping[str, Any],
    checkout_root: str,
) -> tuple[dict[str, Any], str]:
    """The case input, and where its ``returned_before`` came from."""
    facts = _record_facts(record)
    payload = _as_dict(loaded.get("payload"))
    payload_facts = _as_list(payload.get(_FACTS))
    pairing = _pair(record, payload_facts)
    rounds_left = _rounds_left(record, contract.get("retry_rounds"))
    returned_before, returned_source = _returned_before(record, facts, rounds_left)
    children = [_as_dict(child) for child in _as_list(loaded.get("children"))]
    case_input = {
        "checkout_root": checkout_root,
        **_run(loaded),
        "prior_runs": {
            label: _run(run) for label, run in _as_dict(loaded.get("prior_runs")).items()
        },
        "children": [{"label": child.get("label"), **_run(child)} for child in children],
        "finish": {
            "facts": payload_facts,
            "verdicts": _as_list(payload.get("verdicts")),
            "open_items": _as_list(payload.get("open_items")),
        },
        "contract": dict(contract),
        "decider": _answers_by_id(pairing),
        "returned_before": returned_before,
        "rounds_left": rounds_left,
    }
    if pairing.paired:
        case_input["decider_by_position"] = _answers(pairing)
    return case_input, returned_source


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
    return _build_input(loaded, record, contract, checkout_root)[0]


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


def _fact_rows(result: Mapping[str, Any], pairing: _Pairing, payload_facts: list[Any]) -> list:
    """One row per re-checked fact, each beside the record it is paired with (if any)."""
    rows = []
    for position, got in enumerate(result[_FACTS]):
        theirs = pairing.records[position] if position < len(pairing.records) else None
        raw = payload_facts[position] if position < len(payload_facts) else None
        rows.append(_fact_row(position, got, theirs, _as_dict(raw).get("source")))
    return rows


def _without_record(rows: list[dict], pairing: _Pairing) -> list[Any]:
    """The ids of the facts that have no record, when the facts could be paired at all."""
    if not pairing.paired:
        return []
    return [row["id"] for row in rows if not row["recorded_found"]]


def _membership_row(rows: list[dict], pairing: _Pairing, missing: list[Any]) -> list[dict]:
    """The one row that says which facts have no record and which records have no fact."""
    if not missing and not pairing.extra:
        return []
    if pairing.recorded != len(rows):
        row = _difference(None, _FACTS, pairing.recorded, len(rows))
    else:
        theirs = [record["id"] for record in pairing.records if record is not None]
        row = _difference(
            None, f"{_FACTS}.ids", theirs + pairing.extra, [row["id"] for row in rows]
        )
    return [{**row, "without_record": missing, "not_in_payload": pairing.extra}]


def _fact_part(rows: list[dict], pairing: _Pairing, missing: list[Any]) -> list[dict]:
    """The facts part's disagreements: each field that differs, then the membership row."""
    if not pairing.paired:
        return []
    found = [
        _difference(row["id"], name, field["recorded"], field["recheck"])
        for row in rows
        for name, field in row["fields"].items()
        if field["agree"] is False
    ]
    return found + _membership_row(rows, pairing, missing)


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
    """Each part the record holds in a comparable form; an absent or malformed part is left out."""
    strict = _as_dict(record.get("strict"))
    parts: dict[str, Any] = {}
    if isinstance(record.get(_FACTS), list):
        parts[_FACTS] = record[_FACTS]
    for part in ("verdicts", "open_items"):
        if isinstance(record.get(part), list):
            parts[part] = record[part]
    if isinstance(record.get(_ACCEPTED), bool):
        parts[_ACCEPTED] = record[_ACCEPTED]
    for part in _COUNT_PARTS:
        if isinstance(strict.get(part), dict):
            parts[part] = strict[part]
    return parts


def _why_not_compared(part: str, held: Mapping[str, Any], pairing: _Pairing) -> Optional[str]:
    """Why *part* is not compared, or None when it is."""
    if part not in held:
        return REASON_ABSENT
    if part == _FACTS:
        return pairing.reason
    if part != _ACCEPTED and not pairing.complete:
        return REASON_NO_ANSWERS
    return None


def _part_disagreements(part: str, theirs: Any, result: Mapping[str, Any], accepted: bool):
    if part in ("verdicts", "open_items"):
        return _item_part(part, result[part], theirs)
    if part == _ACCEPTED:
        return [] if theirs == accepted else [_difference(None, part, theirs, accepted)]
    return _count_part(part, theirs, result[part])


def _agreement(
    compared: list[str], not_compared: list[str], disagreements: list[dict]
) -> tuple[Optional[bool], Any]:
    """``agrees`` and ``agrees_reason`` (see the module text)."""
    if disagreements:
        return False, None
    if _FACTS in compared:  # with no row: a record for every payload fact
        return True, None
    if not compared:
        return None, NOTHING_COMPARED
    return None, "not compared: " + ", ".join(not_compared)


def compare_with_record(
    result: Mapping[str, Any],
    record: Mapping[str, Any],
    payload_facts: list[Any],
    accepted: bool,
) -> dict[str, Any]:
    """Compare the re-check with the export's own record, part by part (see the module text).

    Returns ``agrees`` (false: a disagreement row; true: none, and every
    payload fact was compared with its record; None otherwise),
    ``agrees_reason`` (None, or what was not compared when ``agrees`` is None),
    ``compared`` and ``not_compared`` (the parts of :data:`PARTS`),
    ``not_compared_reasons`` (why, per part not compared), ``facts`` (one row
    per fact; its ``agrees`` and each field's ``agree`` are None when the fact
    has no record), ``facts_without_record`` (their ids, when the facts could
    be paired), ``incomplete`` (a part was not compared or a fact has no
    record) and ``disagreements`` (each field that differs, with both values;
    never a row for a part in ``not_compared``, never a row whose two values
    are equal). *accepted* is the re-check's checker verdict.
    """
    held = _recorded_parts(record)
    pairing = _pair(record, payload_facts)
    rows = _fact_rows(result, pairing, payload_facts)
    missing = _without_record(rows, pairing)
    reasons = {part: _why_not_compared(part, held, pairing) for part in PARTS}
    compared = [part for part in PARTS if reasons[part] is None]
    not_compared = [part for part in PARTS if reasons[part] is not None]
    disagreements = _fact_part(rows, pairing, missing)
    for part in compared:
        if part != _FACTS:
            disagreements += _part_disagreements(part, held[part], result, accepted)
    agrees, reason = _agreement(compared, not_compared, disagreements)
    return {
        "agrees": agrees,
        "agrees_reason": reason,
        "compared": compared,
        "not_compared": not_compared,
        "not_compared_reasons": {part: reasons[part] for part in not_compared},
        "facts": rows,
        "facts_without_record": missing,
        "incomplete": bool(not_compared or missing),
        "disagreements": disagreements,
    }


def _recorded_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "accepted": record.get("accepted"),
        "outcome": record.get("outcome"),
        "counts": _as_dict(record.get("strict")).get("counts"),
    }


def _strict_source(settings: Mapping[str, Any]) -> str:
    return _SETTINGS if _usable_strict(settings.get("strict")) else _DEFAULTS


def not_applicable_result(
    export_dir: Path,
    record: Mapping[str, Any],
    settings: Mapping[str, Any],
    reason: str,
    *,
    unsupported: bool = False,
) -> dict[str, Any]:
    """The result for a strict export where facts do not apply: nothing re-checked or compared.

    The shape of :func:`recheck_strict_export`'s result, with ``applicable``
    false, *reason* as ``not_applicable_reason``, and ``recheck``, ``accepted``
    and ``rounds_left`` None. ``unsupported: true`` is added for a walk format
    that is not supported, as :func:`evidence.accuracy.check.inspect_export`
    adds it.
    """
    result: dict[str, Any] = {
        "check": STRICT_MODE,
        "export": str(export_dir),
        "applicable": False,
        "not_applicable_reason": reason,
        "strict_source": _strict_source(settings),
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
            "not_compared_reasons": dict.fromkeys(PARTS, reason),
            "facts": [],
            "facts_without_record": [],
            "incomplete": False,
            "disagreements": [],
        },
    }
    if unsupported:
        result["unsupported"] = True
    return result


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
    (it is then not read again). The fact records are validated first, so a
    malformed record is an ``ExportError`` whether or not facts apply.
    """
    if record is None:
        record = _strict_record(Path(export_dir))
    _record_facts(record)
    chosen = strict_settings(settings)
    reason = _not_applicable_reason(loaded)
    if reason is not None:
        unsupported = _format_reason(loaded.get("format")) is not None
        return not_applicable_result(
            Path(export_dir), record, settings, reason, unsupported=unsupported
        )
    case_input, returned_source = _build_input(loaded, record, chosen["contract"], checkout_root)
    result, accepted = recheck_with_checker(case_input, chosen["redaction"])
    return {
        "check": STRICT_MODE,
        "export": str(export_dir),
        "applicable": True,
        "not_applicable_reason": None,
        "strict_source": chosen["strict_source"],
        "rounds_left": case_input["rounds_left"],
        "returned_before": case_input["returned_before"],
        "returned_before_source": returned_source,
        "recheck": result,
        "accepted": accepted,
        "recorded": _recorded_summary(record),
        "comparison": compare_with_record(result, record, case_input["finish"][_FACTS], accepted),
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

    An export with a walk format that is not supported, a walk with no format
    marker, or no facts file is not applicable, with the reason
    :func:`evidence.accuracy.check.inspect_export` gives: ``applicable`` is
    false, ``recheck``, ``accepted`` and ``rounds_left`` are None, and
    ``comparison`` holds no rows with ``agrees`` None (``unsupported: true`` is
    added for an unsupported format, and nothing but the walk's format and
    ``check.json`` is then read). Raises
    :class:`evidence.accuracy.check.ExportError` when the export cannot be read,
    a fact record in ``check.json`` is malformed, or a redaction pattern in the
    settings cannot be compiled.
    """
    export_dir = Path(export_dir)
    record = _strict_record(export_dir)
    _record_facts(record)
    version, _ = _open_walk(export_dir)
    if _format_reason(version) is None:
        loaded = load_handback_input(export_dir, continue_from)
    else:  # as inspect_export: nothing else of an unsupported export is read
        loaded = {"format": version}
    return recheck_loaded(export_dir, loaded, settings, checkout_root=checkout_root, record=record)
