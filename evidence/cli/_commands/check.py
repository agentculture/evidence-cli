"""``evidence check`` — re-check the hand-back facts of one or more run exports.

For each export directory it reads ``walk.jsonl``, the saved results and the
facts payload, runs the re-check and reports the counts per kind and per source
kind, and any disagreement with the counts in the run's own ``report.json``.
Then it sums over the runs where facts apply. A run with no facts is not
applicable; a walk format newer than supported is unsupported; neither adds to
the sums. A fact counted as passed means its quote was found in the saved
result it cites, nothing more.

An export whose ``check.json`` says ``"mode": "strict"`` is re-checked by the
strict re-check instead: per fact its id, source, kind checked, outcome and drop
reason, the counts, and whether the re-check agrees with the export's own
record (the parts compared named, each disagreement listed and written as a
reviewer flag). A strict run is not added to the quote sums. A disagreement does
not change the exit code, as a disagreement with ``report.json`` does not: the
documented non-zero codes are a user error (1) and an environment error (2).
The count of disagreements is in the ``--json`` sums and in the last line.
A fact with outcome pass had its evidence copied from a saved result or its
quote found in one; a judged fact carries the decider's stored answer.

Reviewer flags are written to ``evidence/flags.json`` in the directory that
holds the export directory (never inside it). ``--flags-dir`` writes
``<dir>/flags.json`` instead and ``--no-flags`` writes nothing. If the file
cannot be written the report is still printed and the exit code is the
environment error code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from evidence.accuracy.check import (
    WALK_FILENAME,
    ExportError,
    _prior_dir,
    inside_export,
    inspect_export,
    load_default_settings,
    load_export,
    parse_source_ref,
)
from evidence.accuracy.counts import SOURCE_KINDS, empty_counts
from evidence.accuracy.strict_export import RETURNED_FROM_RECORD
from evidence.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from evidence.cli._output import emit_error, emit_result

NOTE = "a complete trail does not mean the work is correct"
FLAGS_NAME = "flags.json"
FLAGS_SUBDIR = "evidence"
_COUNT_KEYS = tuple(empty_counts())
_COMPARED_SECTIONS = ("facts", "conclusions")
_DECIDED = ("supported", "refuted")
_OUTCOME_KEYS = ("backed", "open", "refused")
_SETTINGS_HINT = "pass a JSON object shaped like the bundled default, or omit --settings"
STRICT = "strict"
#: The flag ``check`` for a strict re-check that disagrees with the export's own record.
STRICT_FLAG = "strict_record_disagrees"
_STRICT_NOTE_LINES = (
    "strict: pass means the evidence was copied from a saved result or its quote was found in",
    "one; a judged fact carries the decider's stored answer. Neither says a value is true.",
)
STRICT_NOTE = " ".join(_STRICT_NOTE_LINES)

# --- settings -----------------------------------------------------------------


def _load_settings(path: Optional[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The settings mapping and the description of where it came from."""
    if path is None:
        settings, version = load_default_settings()
        return settings, {"source": "bundled default", "version": version}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"cannot read settings file {path!r}: {exc.__class__.__name__}",
            "pass a readable JSON settings file, or omit --settings for the bundled default",
        ) from exc
    if not isinstance(loaded, dict):
        raise CliError(
            EXIT_USER_ERROR,
            f"settings file {path!r} is not a JSON object",
            "pass a JSON object, or omit --settings for the bundled default",
        )
    _check_settings_shape(loaded, path)
    return loaded, {"source": "file", "path": path, "version": loaded.get("version")}


def _json_type(value: Any) -> str:
    """The JSON type of a parsed value; an int and a float are both a number."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _inner_values(value: Any) -> list[Any]:
    return list(value.values()) if isinstance(value, dict) else list(value)


def _shape_error(loaded: dict[str, Any], key: str, want: Any) -> Optional[str]:
    """What is wrong with one top-level key of a settings file, or None."""
    if key not in loaded:
        return f"has no {key!r}"
    got = loaded[key]
    if _json_type(got) != _json_type(want):
        return f"{key!r} is a JSON {_json_type(got)}, not a JSON {_json_type(want)}"
    if not isinstance(want, (dict, list)):
        return None
    allowed = {_json_type(v) for v in _inner_values(want)}
    wrong = sorted({_json_type(v) for v in _inner_values(got)} - allowed)
    if allowed and wrong:
        return f"{key!r} holds a JSON {wrong[0]}; its values must be: {', '.join(sorted(allowed))}"
    return None


def _check_settings_shape(loaded: dict[str, Any], path: str) -> None:
    """Refuse a settings file whose top-level keys differ in type from the bundled default.

    Each key of the default (except ``$comment``-style keys) must be present with
    the same JSON type, and the values one level inside an object or array must
    have the types the default's values have.
    """
    default, _ = load_default_settings()
    for key, want in default.items():
        if key.startswith("$"):
            continue
        problem = _shape_error(loaded, key, want)
        if problem is not None:
            raise CliError(EXIT_USER_ERROR, f"settings file {path!r} {problem}", _SETTINGS_HINT)


# --- one run ------------------------------------------------------------------


def _own_report(export_dir: Path) -> Optional[dict[str, Any]]:
    path = export_dir / "report.json"
    if not inside_export(export_dir, path):
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _disagreements(own: Optional[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """Each count where the run's own report.json and the re-check differ."""
    found: list[dict[str, Any]] = []
    if own is None:
        return found
    for section in _COMPARED_SECTIONS:
        theirs, ours = own.get(section), report.get(section)
        if not isinstance(theirs, dict) or not isinstance(ours, dict):
            continue
        for key in sorted(ours):
            if key in theirs and theirs[key] != ours[key]:
                found.append(
                    {"key": f"{section}.{key}", "report_json": theirs[key], "recheck": ours[key]}
                )
    return found


def _outcome_key(outcome: dict[str, Any], stated: Any) -> str:
    if outcome.get("outcome") != "accepted":
        return "refused"
    return "backed" if stated in _DECIDED else "open"


def _outcomes(items: list[dict[str, Any]], payload: Optional[dict[str, Any]]) -> dict[str, int]:
    """How many conclusions the re-check backed, left open (accepted, but stated open or
    cannot tell) and refused.

    The stated verdict comes from the run's payload. The checker returns one outcome
    per payload verdict in payload order, so the two are paired by position (which
    is the pairing by verdict id, and stays right when an id repeats).
    """
    raw = (payload or {}).get("verdicts")
    stated = [v.get("verdict") if isinstance(v, dict) else None for v in raw or []]
    counts = dict.fromkeys(_OUTCOME_KEYS, 0)
    for position, item in enumerate(items):
        value = stated[position] if position < len(stated) else None
        counts[_outcome_key(item, value)] += 1
    return counts


def _fact_line_data(row: dict[str, Any]) -> dict[str, Any]:
    fields = row["fields"]
    return {
        "id": row["id"],
        "source": row["source"],
        "kind_checked": fields["kind_checked"]["recheck"],
        "outcome": fields["strict_outcome"]["recheck"],
        "drop_reason": fields["drop_reason"]["recheck"],
        "agrees_with_record": row["agrees"],
    }


def _item_data(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": i["id"], "outcome": i["strict_outcome"], "drop_reason": i["strict_reason"]}
        for i in items
    ]


def _difference_text(diff: dict[str, Any]) -> str:
    where = f"{diff['id']} " if diff["id"] is not None else ""
    return f"{where}{diff['field']}: check.json {diff['recorded']!r}, re-check {diff['recheck']!r}"


def _strict_flags(comparison: dict[str, Any]) -> list[dict[str, str]]:
    """One reviewer flag per disagreement, in the shape of the run check's flags.

    A flag on a fact field carries the fact's source as ``ref``; one on a
    verdict, an open item or a count carries none.
    """
    sources = {}
    for row in comparison["facts"]:
        sources.setdefault(row["id"], row["source"])
    flags = []
    for diff in comparison["disagreements"]:
        flag = {"check": STRICT_FLAG, "detail": _difference_text(diff)}
        source = sources.get(diff["id"]) if "." not in diff["field"] else None
        if source is not None and parse_source_ref(source)["ok"]:
            flag["ref"] = source
        flags.append(flag)
    return flags


def _strict_entry(export_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    """The strict re-check of one export, as the report carries it."""
    strict = result["strict"]
    recheck, comparison = strict["recheck"], strict["comparison"]
    return {
        "export": str(export_dir),
        "walk_format": result["walk_format"],
        "applicable": True,
        "check": STRICT,
        "unsupported_runs": result["unsupported_runs"],
        "strict_source": strict["strict_source"],
        "facts": [_fact_line_data(row) for row in comparison["facts"]],
        "verdicts": _item_data(recheck["verdicts"]),
        "open_items": _item_data(recheck["open_items"]),
        "counts": recheck["counts"],
        "drop_reasons": recheck["drop_reasons"],
        "judge_counts": recheck["judge_counts"],
        "report": recheck["report"],
        "returned_before_source": strict["returned_before_source"],
        "agrees": comparison["agrees"],
        "agrees_reason": comparison["agrees_reason"],
        "compared": comparison["compared"],
        "not_compared": comparison["not_compared"],
        "disagreements": comparison["disagreements"],
        "flags": _strict_flags(comparison),
    }


def _run_entry(
    export_dir: Path, settings: dict[str, Any], continue_from: Optional[Path]
) -> dict[str, Any]:
    result = inspect_export(export_dir, settings, continue_from=continue_from)
    if result.get("check") == STRICT:
        return _strict_entry(export_dir, result)
    entry: dict[str, Any] = {
        "export": str(export_dir),
        "walk_format": result["walk_format"],
        "applicable": result["applicable"],
        "flags": [],
    }
    if not result["applicable"]:
        entry["not_applicable_reason"] = result["not_applicable_reason"]
        if result.get("unsupported"):
            entry["unsupported"] = True
        entry["unsupported_runs"] = result["unsupported_runs"]
        return entry
    report = result["report"]
    own = _own_report(export_dir)
    entry.update(
        unsupported_runs=result["unsupported_runs"],
        facts=report["facts"],
        by_source_kind=report["by_source_kind"],
        conclusions=report["conclusions"],
        conclusion_outcomes=_outcomes(result["verdicts"], load_export(export_dir)["payload"]),
        statements=report["statements"],
        own_report_found=own is not None,
        disagreements=_disagreements(own, report),
        flags=list(report["flags"]),
    )
    return entry


# --- sums ---------------------------------------------------------------------


def _add(total: dict[str, int], counts: dict[str, int]) -> None:
    for key in _COUNT_KEYS:
        total[key] += counts[key]


def _sums(entries: list[dict[str, Any]]) -> dict[str, Any]:
    facts = empty_counts()
    by_kind = {kind: empty_counts() for kind in SOURCE_KINDS}
    strict = sum(1 for e in entries if e.get("check") == STRICT)
    applicable = [e for e in entries if e["applicable"] and e.get("check") != STRICT]
    conclusions: dict[str, int] = {}
    outcomes = dict.fromkeys(_OUTCOME_KEYS, 0)
    for entry in applicable:
        for key in outcomes:
            outcomes[key] += entry["conclusion_outcomes"][key]
        for key, value in entry["conclusions"].items():
            conclusions[key] = conclusions.get(key, 0) + value
        _add(facts, entry["facts"])
        for kind in SOURCE_KINDS:
            _add(by_kind[kind], entry["by_source_kind"][kind])
    unsupported = sum(1 for e in entries if e.get("unsupported"))
    runs = {
        "given": len(entries),
        "applicable": len(applicable),
        "not_applicable": len(entries) - len(applicable) - unsupported - strict,
        "unsupported": unsupported,
    }
    sums = {
        "runs": runs,
        "facts": facts,
        "by_source_kind": by_kind,
        "conclusions": conclusions,
        "conclusion_outcomes": outcomes,
    }
    if strict:  # only present when a strict run was given, so other reports are unchanged
        runs["strict"] = strict
        sums["strict_disagreements"] = sum(
            len(e["disagreements"]) for e in entries if e.get("check") == STRICT
        )
        sums["strict_not_compared"] = sum(
            1 for e in entries if e.get("check") == STRICT and e["agrees"] is None
        )
    return sums


# --- the flags file -----------------------------------------------------------


def _write_flags(
    entries: list[dict[str, Any]], flags_dir: Optional[str], no_flags: bool
) -> dict[str, Any]:
    """Write the reviewer flags; describe what happened (never raises on I/O)."""
    if no_flags:
        return {"written": False, "reason": "--no-flags"}
    groups: dict[Path, list[dict[str, Any]]] = {}
    for entry in entries:
        slim = {"export": entry["export"], "flags": entry["flags"]}
        if flags_dir is not None:
            target = Path(flags_dir) / FLAGS_NAME
        else:
            # Resolved first, so "." or a path ending in ".." still lands beside the export.
            target = Path(entry["export"]).resolve().parent / FLAGS_SUBDIR / FLAGS_NAME
        groups.setdefault(target, []).append(slim)
    written: list[str] = []
    for target in sorted(groups):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"runs": groups[target]}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return {
                "written": False,
                "path": str(target),
                "reason": f"{exc.__class__.__name__}: {exc.strerror or exc}",
            }
        written.append(str(target))
    if len(written) == 1:
        return {"written": True, "path": written[0]}
    return {"written": True, "paths": written}


# --- text ---------------------------------------------------------------------


def _counts_line(label: str, counts: dict[str, int]) -> str:
    return (
        f"  {label:<8} made {counts['made']}  checked {counts['checked']}  "
        f"quote found {counts['passed']}  refused {counts['refused']}  "
        f"unchecked {counts['unchecked']}"
    )


def _conclusions_line(counts: dict[str, int], outcomes: dict[str, int]) -> str:
    stated = "  ".join(f"{key} {counts[key]}" for key in sorted(counts))
    return (
        f"  conclusions as the run stated them: {stated}; "
        f"backed {outcomes['backed']}, left open {outcomes['open']}, "
        f"refused {outcomes['refused']}"
    )


def _settings_line(settings: dict[str, Any]) -> str:
    if settings["source"] == "file":
        return f"settings file: {settings['path']} (version {settings['version']})"
    return f"bundled default settings, version {settings['version']}"


def _unsupported_run_lines(entry: dict[str, Any]) -> list[str]:
    return [
        f"  run {run['label']} not loaded: walk format {run['walk_format']!r} is not supported"
        for run in entry.get("unsupported_runs", [])
    ]


def _fact_line(fact: dict[str, Any]) -> str:
    reason = f", drop reason {fact['drop_reason']}" if fact["drop_reason"] else ""
    return (
        f"  fact {fact['id']} (source {fact['source']}): checked {fact['kind_checked']}, "
        f"outcome {fact['outcome']}{reason}"
    )


def _pairs(counts: dict[str, int]) -> str:
    return "  ".join(f"{key} {value}" for key, value in counts.items()) or "none"


def _disagreement_line(diff: dict[str, Any]) -> str:
    return f"  disagreement {_difference_text(diff)}"


_ABSENT = "absent from check.json"
#: Without the record's facts there are no stored answers, so the parts resting on them go too.
_ABSENT_WITH_FACTS = "absent from check.json, or resting on its absent facts"
_RETURNED_READ = (
    "  returned_before read from check.json: keep_marked against returned is re-decided"
)
_RETURNED_INFERRED = (
    "  returned_before not recorded in check.json: taken from its keep_marked facts, so "
    "keep_marked against returned is not re-decided"
)


def _returned_line(entry: dict[str, Any]) -> str:
    read = entry["returned_before_source"] == RETURNED_FROM_RECORD
    return _RETURNED_READ if read else _RETURNED_INFERRED


def _render_strict(entry: dict[str, Any]) -> list[str]:
    out = [
        "  strict re-check (check.json mode strict); "
        f"strict contract values from: {entry['strict_source']}"
    ]
    out += [_fact_line(fact) for fact in entry["facts"]]
    for kind in ("verdicts", "open_items"):
        for item in entry[kind]:
            reason = f", drop reason {item['drop_reason']}" if item["drop_reason"] else ""
            out.append(f"  {kind[:-1].replace('_', ' ')} {item['id']}: {item['outcome']}{reason}")
    out.append(f"  counts: {_pairs(entry['counts'])}")
    out.append(f"  drop reasons: {_pairs(entry['drop_reasons'])}")
    out.append(_returned_line(entry))
    out += _agreement_lines(entry)
    if entry["not_compared"]:
        absent = ", ".join(entry["not_compared"])
        why = _ABSENT_WITH_FACTS if "facts" in entry["not_compared"] else _ABSENT
        out.append(f"  not compared ({why}): {absent}")
    return out


def _agreement_lines(entry: dict[str, Any]) -> list[str]:
    """Agrees, disagrees (with each disagreement), or neither when nothing was compared."""
    if entry["agrees"] is None:
        return [f"  neither agrees nor disagrees: {entry['agrees_reason']}"]
    compared = ", ".join(entry["compared"])
    if entry["agrees"]:
        return [f"  agrees with the export's own check.json on: {compared}"]
    count = len(entry["disagreements"])
    head = f"  disagrees with the export's own check.json ({count}): compared on {compared}"
    return [head] + [_disagreement_line(diff) for diff in entry["disagreements"]]


def _render_run(entry: dict[str, Any]) -> list[str]:
    out = [f"export: {entry['export']} (walk format {entry['walk_format']})"]
    out += _unsupported_run_lines(entry)
    if entry.get("check") == STRICT:
        return out + _render_strict(entry)
    if not entry["applicable"]:
        label = "unsupported" if entry.get("unsupported") else "not applicable"
        out.append(f"  {label}: {entry['not_applicable_reason']}")
        return out
    out.append(_counts_line("all", entry["facts"]))
    for kind in SOURCE_KINDS:
        out.append(_counts_line(kind, entry["by_source_kind"][kind]))
    out.append(_conclusions_line(entry["conclusions"], entry["conclusion_outcomes"]))
    if not entry["own_report_found"]:
        out.append("  no report.json to compare with")
    for diff in entry["disagreements"]:
        out.append(
            f"  disagreement {diff['key']}: report.json {diff['report_json']}, "
            f"re-check {diff['recheck']}"
        )
    out.append(f"  reviewer flags: {len(entry['flags'])}")
    return out


def _render_flags_file(info: dict[str, Any]) -> str:
    if info["written"]:
        return "flags file written: " + ", ".join(info.get("paths") or [info["path"]])
    if info.get("reason") == "--no-flags":
        return "flags file not written (--no-flags)"
    return f"the flags file was not written: {info['path']}: {info['reason']}"


def _not_compared_clause(sums: dict[str, Any]) -> str:
    """Said only when a strict run had nothing to compare, so other reports read as before."""
    count = sums["strict_not_compared"]
    return f"; {count} strict run(s) where nothing could be compared" if count else ""


def render(report: dict[str, Any]) -> str:
    """The text form of the whole report."""
    out = [
        "run check: counts of checked quotes and backed conclusions",
        _settings_line(report["settings"]),
        "",
    ]
    for entry in report["runs"]:
        out += _render_run(entry) + [""]
    runs = report["sums"]["runs"]
    strict = f", {runs['strict']} strict, not summed here" if runs.get("strict") else ""
    out.append(
        f"Sums over {runs['applicable']} applicable run(s) of {runs['given']} given "
        f"({runs['not_applicable']} not applicable, {runs['unsupported']} unsupported{strict})"
    )
    out.append(_counts_line("all", report["sums"]["facts"]))
    for kind in SOURCE_KINDS:
        out.append(_counts_line(kind, report["sums"]["by_source_kind"][kind]))
    out.append(
        _conclusions_line(report["sums"]["conclusions"], report["sums"]["conclusion_outcomes"])
    )
    out += [
        "",
        _render_flags_file(report["flags_file"]),
        "",
        "quote found means the quote was found in the saved result the fact cites; it is not",
        "a statement that the fact is true. Unchecked facts are never counted as quote found.",
    ]
    if runs.get("strict"):
        out += _STRICT_NOTE_LINES
    out.append(NOTE)
    if runs.get("strict"):
        # Kept last: a disagreement does not change the exit code (see the module text).
        out.append(
            f"strict re-check: {report['sums']['strict_disagreements']} disagreement(s) "
            "with the exports' own check.json" + _not_compared_clause(report["sums"])
        )
    return "\n".join(out)


# --- the verb -----------------------------------------------------------------


def _unique_exports(exports: list[str]) -> list[str]:
    """Each export once, as first spelled, ordered by its resolved path."""
    first: dict[Path, str] = {}
    for name in exports:
        first.setdefault(Path(name).resolve(), name)
    return [first[key] for key in sorted(first)]


def _prior_from(continue_from: Optional[str], exports: list[str]) -> Optional[Path]:
    """The --continue-from directory holding a walk (itself or its export/), checked."""
    if continue_from is None:
        return None
    if len(exports) > 1:
        raise CliError(
            EXIT_USER_ERROR,
            f"--continue-from names one prior run, but {len(exports)} exports were given",
            "check each continued run on its own, with its own --continue-from",
        )
    prior = _prior_dir(Path(continue_from))
    if prior is None:
        raise CliError(
            EXIT_USER_ERROR,
            f"--continue-from {continue_from!r} holds no {WALK_FILENAME} (nor does its export/)",
            "pass the export directory (or the session directory holding export/) of the "
            "run this one continued from",
        )
    return prior


def _inspect_all(
    exports: list[str], settings: dict[str, Any], prior: Optional[Path]
) -> list[dict[str, Any]]:
    entries = []
    for name in exports:
        try:
            entries.append(_run_entry(Path(name), settings, prior))
        except ExportError as err:
            raise CliError(
                EXIT_USER_ERROR,
                str(err),
                "pass export directories holding walk.jsonl (<session>/export)",
            ) from err
    return entries


def cmd_check(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    settings, described = _load_settings(getattr(args, "settings", None))
    exports = _unique_exports(list(args.exports))
    prior = _prior_from(getattr(args, "continue_from", None), exports)
    entries = _inspect_all(exports, settings, prior)
    flags_file = _write_flags(
        entries, getattr(args, "flags_dir", None), bool(getattr(args, "no_flags", False))
    )
    report = {
        "settings": described,
        "runs": entries,
        "sums": _sums(entries),
        "flags_file": flags_file,
        "note": NOTE,
    }
    if report["sums"]["runs"].get("strict"):
        report["strict_note"] = STRICT_NOTE
    emit_result(report if json_mode else render(report), json_mode=json_mode)
    if not flags_file["written"] and flags_file.get("reason") != "--no-flags":
        failure = CliError(
            EXIT_ENV_ERROR,
            f"the flags file was not written ({flags_file['path']}): {flags_file['reason']}",
            "pass --flags-dir DIR to write it elsewhere, or --no-flags to skip it",
        )
        emit_error(failure, json_mode=json_mode)
        return EXIT_ENV_ERROR
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "check",
        help=(
            "Run check: counts of checked quotes and backed conclusions for run exports; "
            "a strict export gets the strict re-check."
        ),
    )
    p.add_argument("exports", nargs="+", metavar="export_dir", help="Export directories.")
    p.add_argument("--settings", metavar="FILE", help="A JSON settings file (default: bundled).")
    p.add_argument(
        "--continue-from",
        metavar="DIR",
        help="The export directory the run continued from, so prior:wN facts can be checked.",
    )
    p.add_argument(
        "--flags-dir", metavar="DIR", help="Write flags.json here instead of beside the run."
    )
    p.add_argument("--no-flags", action="store_true", help="Do not write the flags file.")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_check)
