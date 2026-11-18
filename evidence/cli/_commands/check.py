"""``evidence-cli check`` — re-check the hand-back facts of one or more run exports.

For each export directory it reads ``walk.jsonl``, the saved results and the
facts payload, runs the re-check and reports the counts per kind and per source
kind, and any disagreement with the counts in the run's own ``report.json``.
Then it sums over the runs where facts apply. A run with no facts is not
applicable; a walk format newer than supported is unsupported; neither adds to
the sums. A fact counted as passed means its quote was found in the saved
result it cites, nothing more.

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

from evidence.accuracy.check import ExportError, inspect_export, load_default_settings
from evidence.accuracy.counts import SOURCE_KINDS, empty_counts
from evidence.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from evidence.cli._output import emit_diagnostic, emit_result

FLAGS_NAME = "flags.json"
FLAGS_SUBDIR = "evidence"
_COUNT_KEYS = tuple(empty_counts())
_COMPARED_SECTIONS = ("facts", "conclusions")

# --- settings -----------------------------------------------------------------


def _load_settings(path: Optional[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The settings mapping and the description of where it came from."""
    if path is None:
        settings, version = load_default_settings()
        return settings, {"source": "bundled default", "version": version}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
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
    return loaded, {"source": "file", "path": path, "version": loaded.get("version")}


# --- one run ------------------------------------------------------------------


def _own_report(export_dir: Path) -> Optional[dict[str, Any]]:
    try:
        loaded = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
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


def _run_entry(
    export_dir: Path, settings: dict[str, Any], continue_from: Optional[Path]
) -> dict[str, Any]:
    result = inspect_export(export_dir, settings, continue_from=continue_from)
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
        return entry
    report = result["report"]
    own = _own_report(export_dir)
    entry.update(
        facts=report["facts"],
        by_source_kind=report["by_source_kind"],
        conclusions=report["conclusions"],
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
    applicable = [e for e in entries if e["applicable"]]
    for entry in applicable:
        _add(facts, entry["facts"])
        for kind in SOURCE_KINDS:
            _add(by_kind[kind], entry["by_source_kind"][kind])
    unsupported = sum(1 for e in entries if e.get("unsupported"))
    return {
        "runs": {
            "given": len(entries),
            "applicable": len(applicable),
            "not_applicable": len(entries) - len(applicable) - unsupported,
            "unsupported": unsupported,
        },
        "facts": facts,
        "by_source_kind": by_kind,
    }


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
            target = Path(entry["export"]).parent / FLAGS_SUBDIR / FLAGS_NAME
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


def _settings_line(settings: dict[str, Any]) -> str:
    if settings["source"] == "file":
        return f"settings file: {settings['path']} (version {settings['version']})"
    return f"bundled default settings, version {settings['version']}"


def _render_run(entry: dict[str, Any]) -> list[str]:
    out = [f"export: {entry['export']} (walk format {entry['walk_format']})"]
    if not entry["applicable"]:
        label = "unsupported" if entry.get("unsupported") else "not applicable"
        out.append(f"  {label}: {entry['not_applicable_reason']}")
        return out
    out.append(_counts_line("all", entry["facts"]))
    for kind in SOURCE_KINDS:
        out.append(_counts_line(kind, entry["by_source_kind"][kind]))
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


def render(report: dict[str, Any]) -> str:
    """The text form of the whole report."""
    out = [_settings_line(report["settings"]), ""]
    for entry in report["runs"]:
        out += _render_run(entry) + [""]
    runs = report["sums"]["runs"]
    out.append(
        f"Sums over {runs['applicable']} applicable run(s) of {runs['given']} given "
        f"({runs['not_applicable']} not applicable, {runs['unsupported']} unsupported)"
    )
    out.append(_counts_line("all", report["sums"]["facts"]))
    for kind in SOURCE_KINDS:
        out.append(_counts_line(kind, report["sums"]["by_source_kind"][kind]))
    out += [
        "",
        _render_flags_file(report["flags_file"]),
        "",
        "quote found means the quote was found in the saved result the fact cites; it is not",
        "a statement that the fact is true. Unchecked facts are never counted as quote found.",
    ]
    return "\n".join(out)


# --- the verb -----------------------------------------------------------------


def _inspect_all(
    exports: list[str], settings: dict[str, Any], prior: Optional[Path]
) -> list[dict[str, Any]]:
    entries = []
    for name in sorted(set(exports)):
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
    prior = Path(args.continue_from) if getattr(args, "continue_from", None) else None
    entries = _inspect_all(list(args.exports), settings, prior)
    flags_file = _write_flags(
        entries, getattr(args, "flags_dir", None), bool(getattr(args, "no_flags", False))
    )
    report = {
        "settings": described,
        "runs": entries,
        "sums": _sums(entries),
        "flags_file": flags_file,
    }
    emit_result(report if json_mode else render(report), json_mode=json_mode)
    if not flags_file["written"] and flags_file.get("reason") != "--no-flags":
        emit_diagnostic(
            f"error: the flags file was not written ({flags_file['path']}): "
            f"{flags_file['reason']}\n"
            "hint: pass --flags-dir DIR to write it elsewhere, or --no-flags to skip it"
        )
        return EXIT_ENV_ERROR
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "check",
        help="Re-check the hand-back facts of run export directories; print counts and sums.",
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
