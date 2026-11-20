"""Markdown catalog for ``evidence explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
, ``("evidence",)`` and ``("evidence-cli",)`` all resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# evidence-cli

Checks the evidence around an agent run, and an answer against expected values.
The run check (`check`) re-reads a run export and counts the facts whose quote is
found in the saved result they cite. The answer check (`grade`) matches an answer
text against recorded expected values. The two results are separate, and a
complete trail does not mean the work is correct.

## Verbs

- `evidence whoami` — identity probe from `culture.yaml`.
- `evidence learn` — structured self-teaching prompt.
- `evidence explain <path>` — markdown docs for any noun/verb.
- `evidence overview` — descriptive snapshot of the agent.
- `evidence doctor` — check the agent-identity invariants.
- `evidence cli overview` — describe the CLI surface.
- `evidence check` — the run check: counts of checked quotes and backed conclusions.
- `evidence grade` — the answer check: a match against recorded expected values.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `evidence explain whoami`
- `evidence explain doctor`
- `evidence explain check`
- `evidence explain grade`
"""

_WHOAMI = """\
# evidence whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    evidence whoami
    evidence whoami --json
"""

_LEARN = """\
# evidence learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    evidence learn
    evidence learn --json
"""

_EXPLAIN = """\
# evidence explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    evidence explain evidence
    evidence explain whoami
    evidence explain --json <path>
"""

_OVERVIEW = """\
# evidence overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    evidence overview
    evidence overview --json
"""

_DOCTOR = """\
# evidence doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    evidence doctor
    evidence doctor --json
"""

_CLI = """\
# evidence cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    evidence cli overview
    evidence cli overview --json
"""

_CHECK = """\
# evidence check

Run check: counts of checked quotes and backed conclusions, recomputed from one or
more run export directories (`walk.jsonl`, the saved results, the facts file). It
reports counts per kind and per source kind, any disagreement with the run's own
`report.json`, and sums over the runs where facts apply. "Quote found" means the
quote was found in the saved result the fact cites; it does not say the fact is
true. Reviewer flags are written to `evidence/flags.json` beside the export
directory (`--flags-dir DIR` to move it, `--no-flags` to skip it).

An export whose `check.json` says `"mode": "strict"` (associate's strict facts)
gets the strict re-check instead: a second implementation of associate's strict
check, run on the saved files with the decider's stored answers (no decider is
asked). It prints, per fact, its id, source, kind checked, outcome and drop
reason; the counts; and whether it agrees with the export's own `check.json`
(naming the parts compared and any it could not compare), listing each
disagreement. It says "agrees" only when nothing differs and every fact was
compared with its own record in `check.json`. When the fact records are absent
or cannot be paired with the facts it says "neither agrees nor disagrees"
(`agrees` is null in `--json`, with `agrees_reason`), which is not agreement.
A record with a part that was not compared, or a fact without a record, gets
one reviewer flag (`strict_record_incomplete`) naming them; it is printed and
such runs are counted in the sums (`strict_not_compared`) and on the last
line. It also says whether the fact ids
returned in earlier rounds were read from `check.json`
(`strict.returned_before`) or taken from the facts it records as kept with the
mark. Each disagreement is also a reviewer flag
(`strict_record_disagrees`); it does not change the exit code, and the count of
disagreements is in the `--json` sums and the last line printed. A fact with
outcome pass had its evidence copied from a saved result or its quote found in
one; a judged fact carries the decider's stored answer. A strict run is not
added to the quote sums.

A complete trail does not mean the work is correct.

## Usage

    evidence check <export_dir>...
    evidence check <export_dir> --json
"""

_GRADE = """\
# evidence grade

Answer check: a match against recorded expected values. Reads an answer text
(`--answer-file`, or `-` for standard input) and an expected-values JSON file
(`--expected`) and prints one of `matches`, `does not match` or `cannot tell`, with
the items found and missing. All three results exit 0; an unreadable or refused
input exits 1.

A complete trail does not mean the work is correct.

## Usage

    evidence grade --answer-file answer.txt --expected expected.json
    evidence grade --answer-file - --expected expected.json --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("evidence-cli",): _ROOT,
    ("evidence",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("check",): _CHECK,
    ("grade",): _GRADE,
}
