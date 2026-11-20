"""Re-check a stored strict export and compare the result with what the export recorded.

An associate run with strict facts on leaves, in its export directory,
``walk.jsonl``, ``results/wN.txt``, ``facts.json`` and a ``check.json`` whose
``mode`` is ``strict``: one record per fact (with the decider's stored answer
under ``judge``) and a top-level ``strict`` object (rounds, counts, dropped and
returned items). :func:`strict_export_input` rebuilds the input of
:func:`evidence.accuracy.strict.strict_recheck` from those files;
:func:`recheck_strict_export` runs it and compares, per fact, the kind checked,
the outcome and the drop reason with what ``check.json`` recorded.

What is rebuilt from where:

* the walk, the saved results, a ``--continue-from`` prior run and the child
  runs: read as :func:`evidence.accuracy.check.load_handback_input` reads them
  (nothing outside the export is read through a link, children and the prior
  run are read from where they are);
* the finish payload: ``facts.json``;
* the decider's answers: each fact's ``judge`` in ``check.json`` (an option, or
  the reason it was not judged). The re-check never asks a decider;
* ``rounds_left``: ``check.json`` ``strict.retry_rounds`` less the rounds used
  before this hand-back (``rounds_used``, one fewer when ``round_open`` says
  this hand-back was itself sent back);
* ``returned_before``: ``check.json`` does not record the ids returned in
  earlier rounds, only those returned in its own round. The facts it records as
  ``keep_marked`` while a round was left can only have been returned before, so
  they are taken as ``returned_before``. The re-check therefore cannot disagree
  with the record on ``keep_marked`` against ``returned``;
* the contract values: from the settings the caller passes (as
  :func:`evidence.accuracy.check.check_handback` takes them). A settings
  mapping without a usable ``strict`` block (the bundled default, associate's
  ``accuracy.json`` version 1) takes ``strict`` and the support pass list from
  the contract the shared strict cases record, and says so;
* the redaction filter for the printed command: the settings' ``redaction``,
  else the one the shared strict cases record. The checkout root is not in the
  export; the caller may pass it, else no checkout path is made relative.

A passed fact means its evidence was copied from a saved result or its quote
was found in one; a judged fact carries the decider's stored answer. Nothing
here says a value is true.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from evidence.accuracy.check import (
    CHECK_FILENAME,
    ExportError,
    _export_json,
    load_handback_input,
)
from evidence.accuracy.strict import recheck_with_checker
from evidence.accuracy.vectors import load_strict_vectors

#: ``check.json`` ``mode`` of an export the strict re-check reads.
STRICT_MODE = "strict"
#: The per-fact fields compared with the export's own record.
COMPARED_FIELDS: tuple[str, ...] = ("kind_checked", "strict_outcome", "drop_reason")
_SETTINGS = "settings"
_SHARED = "shared cases"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _whole(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def read_check_record(export_dir: Path) -> Optional[dict[str, Any]]:
    """The export's ``check.json`` as a dict, or None when absent, unreadable or linked outside."""
    return _export_json(Path(export_dir), CHECK_FILENAME)


def is_strict_export(export_dir: Path) -> bool:
    """True when the export's ``check.json`` says ``"mode": "strict"``."""
    record = read_check_record(export_dir)
    return record is not None and record.get("mode") == STRICT_MODE


# --- the contract values -----------------------------------------------------------------


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


def strict_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The contract subset and redaction filter the strict re-check reads, and their source.

    Returns ``contract`` (``strict``, ``support_passes``, ``min_quote_length``,
    ``retry_rounds``, ``source_kinds``), ``redaction`` and ``strict_source``:
    ``settings`` when *settings* holds a usable ``strict`` block and a support
    pass list (associate's ``accuracy.json`` version 2 has both), else
    ``shared cases`` (the values recorded in ``strict_vectors.json``).
    """
    shared = load_strict_vectors()
    shared_contract = shared["cases"][0]["input"]["contract"]
    section, passes = settings.get("strict"), _support_passes(settings)
    own = _usable_strict(section) and passes is not None
    strict = section if own else shared_contract["strict"]
    redaction = settings.get("redaction")
    return {
        "contract": {
            "strict": {
                "keep_marked": strict["keep_marked"],
                "drop": strict["drop"],
                "mark_text": strict.get("mark_text"),
                "derived_decides_drops": strict.get("derived_decides_drops") is True,
            },
            "support_passes": passes if own else shared_contract["support_passes"],
            "min_quote_length": settings.get("min_quote_length"),
            "retry_rounds": settings.get("retry_rounds"),
            "source_kinds": _as_dict(settings.get("source_kinds")),
        },
        "redaction": redaction if isinstance(redaction, dict) else shared["redaction"],
        "strict_source": _SETTINGS if own else _SHARED,
    }


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
    entries = _as_list(data.get("entries"))
    return {"walk": entries, "results": _by_name(entries, _as_dict(data.get("results")))}


def _stored_answers(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The decider's stored answer per fact id: ``{question, option}`` or ``{not_judged}``."""
    answers: dict[str, dict[str, Any]] = {}
    for fact in _as_list(record.get("facts")):
        judge = _as_dict(fact).get("judge") if isinstance(fact, dict) else None
        if not isinstance(judge, dict) or fact.get("id") in answers:
            continue
        if judge.get("option") is not None:
            answers[fact["id"]] = {"question": judge.get("question"), "option": judge["option"]}
        else:
            answers[fact["id"]] = {"not_judged": judge.get("reason")}
    return answers


def _rounds_left(record: Mapping[str, Any], retry_rounds: Any) -> int:
    """Rounds that could still send facts back when this hand-back was checked."""
    strict = _as_dict(record.get("strict"))
    allowed = _whole(strict.get("retry_rounds"), _whole(retry_rounds))
    used = _whole(strict.get("rounds_used"))
    used_before = used - 1 if strict.get("round_open") is True else used
    return max(0, allowed - used_before)


def _returned_before(record: Mapping[str, Any], rounds_left: int) -> list[str]:
    """Facts kept marked while a round was left: only a fact returned before is kept so."""
    if rounds_left <= 0:
        return []
    return [
        fact["id"]
        for fact in _as_list(record.get("facts"))
        if isinstance(fact, dict) and fact.get("strict_outcome") == "keep_marked"
    ]


def _strict_record(export_dir: Path) -> dict[str, Any]:
    record = read_check_record(export_dir)
    if record is None or record.get("mode") != STRICT_MODE:
        raise ExportError(f"{export_dir} has no {CHECK_FILENAME} with mode strict")
    return record


def _build_input(
    loaded: Mapping[str, Any],
    record: Mapping[str, Any],
    contract: Mapping[str, Any],
    checkout_root: str,
) -> dict[str, Any]:
    payload = _as_dict(loaded.get("payload"))
    rounds_left = _rounds_left(record, contract.get("retry_rounds"))
    return {
        "checkout_root": checkout_root,
        **_run(loaded),
        "prior_runs": {label: _run(run) for label, run in loaded["prior_runs"].items()},
        "children": [{"label": c["label"], **_run(c)} for c in loaded["children"]],
        "finish": {
            "facts": _as_list(payload.get("facts")),
            "verdicts": _as_list(payload.get("verdicts")),
            "open_items": _as_list(payload.get("open_items")),
        },
        "contract": dict(contract),
        "decider": _stored_answers(record),
        "returned_before": _returned_before(record, rounds_left),
        "rounds_left": rounds_left,
    }


def strict_export_input(
    export_dir: Path,
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
    continue_from: Optional[Path] = None,
) -> dict[str, Any]:
    """The strict re-check's input rebuilt from a stored strict export (see the module text).

    Raises :class:`evidence.accuracy.check.ExportError` when the export cannot
    be read or its ``check.json`` is not a strict record.
    """
    export_dir = Path(export_dir)
    record = _strict_record(export_dir)
    loaded = load_handback_input(export_dir, continue_from)
    contract = strict_settings(settings)["contract"]
    return _build_input(loaded, record, contract, checkout_root)


# --- the comparison -----------------------------------------------------------------------------


def _fact_row(position: int, got: Mapping[str, Any], recorded: Any, source: Any) -> dict:
    theirs = _as_dict(recorded)
    fields = {
        name: {
            "recorded": theirs.get(name),
            "recheck": got[name],
            "agree": recorded is not None and theirs.get(name) == got[name],
        }
        for name in COMPARED_FIELDS
    }
    return {
        "position": position,
        "id": got["id"],
        "source": source if isinstance(source, str) else None,
        "recorded_found": recorded is not None,
        "agrees": all(field["agree"] for field in fields.values()),
        "fields": fields,
    }


def _count_disagreements(record: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict]:
    strict = _as_dict(record.get("strict"))
    found = []
    for section in ("counts", "drop_reasons"):
        theirs, ours = _as_dict(strict.get(section)), result[section]
        for key in sorted(set(theirs) | set(ours)):
            if theirs.get(key, 0) != ours.get(key, 0):
                found.append(
                    {
                        "id": None,
                        "field": f"{section}.{key}",
                        "recorded": theirs.get(key, 0),
                        "recheck": ours.get(key, 0),
                    }
                )
    return found


def compare_with_record(
    result: Mapping[str, Any], record: Mapping[str, Any], payload_facts: list[Any]
) -> dict[str, Any]:
    """Per fact (by position), whether kind checked, outcome and drop reason agree with the record.

    Also compares the facts' number and the ``strict`` object's ``counts`` and
    ``drop_reasons``. ``disagreements`` lists each field that differs.
    """
    recorded = _as_list(record.get("facts"))
    rows = []
    disagreements: list[dict[str, Any]] = []
    for position, got in enumerate(result["facts"]):
        theirs = recorded[position] if position < len(recorded) else None
        raw = payload_facts[position] if position < len(payload_facts) else None
        row = _fact_row(position, got, theirs, _as_dict(raw).get("source"))
        rows.append(row)
        for name, field in row["fields"].items():
            if not field["agree"]:
                disagreements.append({"id": got["id"], "field": name, **_pair(field)})
    if len(recorded) != len(result["facts"]):
        disagreements.append(
            {"id": None, "field": "facts", "recorded": len(recorded), "recheck": len(rows)}
        )
    disagreements += _count_disagreements(record, result)
    return {"agrees": not disagreements, "facts": rows, "disagreements": disagreements}


def _pair(field: Mapping[str, Any]) -> dict[str, Any]:
    return {"recorded": field["recorded"], "recheck": field["recheck"]}


# --- the entry point ------------------------------------------------------------------------------


def recheck_loaded(
    export_dir: Path,
    loaded: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
) -> dict[str, Any]:
    """:func:`recheck_strict_export` over an export already read by ``load_handback_input``."""
    record = _strict_record(Path(export_dir))
    chosen = strict_settings(settings)
    case_input = _build_input(loaded, record, chosen["contract"], checkout_root)
    result, accepted = recheck_with_checker(case_input, chosen["redaction"])
    return {
        "check": STRICT_MODE,
        "export": str(export_dir),
        "strict_source": chosen["strict_source"],
        "rounds_left": case_input["rounds_left"],
        "returned_before": case_input["returned_before"],
        "recheck": result,
        "accepted": accepted,
        "recorded": {
            "accepted": record.get("accepted"),
            "outcome": record.get("outcome"),
            "counts": _as_dict(record.get("strict")).get("counts"),
        },
        "comparison": compare_with_record(result, record, case_input["finish"]["facts"]),
    }


def recheck_strict_export(
    export_dir: Path,
    settings: Mapping[str, Any],
    *,
    checkout_root: str = "",
    continue_from: Optional[Path] = None,
) -> dict[str, Any]:
    """Re-check a stored strict export and compare it with the export's own ``check.json``.

    Returns ``check`` (``"strict"``), ``export``, ``strict_source`` (where the
    strict contract values came from), ``rounds_left`` and ``returned_before``
    (as rebuilt), ``recheck`` (the :func:`strict_recheck` result), ``accepted``
    (the checker refused nothing), ``recorded`` (what ``check.json`` says) and
    ``comparison`` (``agrees``, one row per fact, ``disagreements``). Raises
    :class:`evidence.accuracy.check.ExportError` when the export cannot be read.
    """
    export_dir = Path(export_dir)
    _strict_record(export_dir)
    loaded = load_handback_input(export_dir, continue_from)
    return recheck_loaded(export_dir, loaded, settings, checkout_root=checkout_root)
