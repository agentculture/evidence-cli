"""Markdown catalog for ``evidence-cli explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("evidence-cli",)`` both resolve to the root entry.

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

- `evidence-cli whoami` — identity probe from `culture.yaml`.
- `evidence-cli learn` — structured self-teaching prompt.
- `evidence-cli explain <path>` — markdown docs for any noun/verb.
- `evidence-cli overview` — descriptive snapshot of the agent.
- `evidence-cli doctor` — check the agent-identity invariants.
- `evidence-cli cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `evidence-cli explain whoami`
- `evidence-cli explain doctor`
"""

_WHOAMI = """\
# evidence-cli whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    evidence-cli whoami
    evidence-cli whoami --json
"""

_LEARN = """\
# evidence-cli learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    evidence-cli learn
    evidence-cli learn --json
"""

_EXPLAIN = """\
# evidence-cli explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    evidence-cli explain evidence-cli
    evidence-cli explain whoami
    evidence-cli explain --json <path>
"""

_OVERVIEW = """\
# evidence-cli overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    evidence-cli overview
    evidence-cli overview --json
"""

_DOCTOR = """\
# evidence-cli doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    evidence-cli doctor
    evidence-cli doctor --json
"""

_CLI = """\
# evidence-cli cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    evidence-cli cli overview
    evidence-cli cli overview --json
"""

_CHECK = """\
# evidence-cli check

Run check: counts of checked quotes and backed conclusions, recomputed from one or
more run export directories (`walk.jsonl`, the saved results, the facts file). It
reports counts per kind and per source kind, any disagreement with the run's own
`report.json`, and sums over the runs where facts apply. "Quote found" means the
quote was found in the saved result the fact cites; it does not say the fact is
true. Reviewer flags are written to `evidence/flags.json` beside the export
directory (`--flags-dir DIR` to move it, `--no-flags` to skip it).

A complete trail does not mean the work is correct.

## Usage

    evidence-cli check <export_dir>...
    evidence-cli check <export_dir> --json
"""

_GRADE = """\
# evidence-cli grade

Answer check: a match against recorded expected values. Reads an answer text
(`--answer-file`, or `-` for standard input) and an expected-values JSON file
(`--expected`) and prints one of `matches`, `does not match` or `cannot tell`, with
the items found and missing. All three results exit 0; an unreadable or refused
input exits 1.

A complete trail does not mean the work is correct.

## Usage

    evidence-cli grade --answer-file answer.txt --expected expected.json
    evidence-cli grade --answer-file - --expected expected.json --json
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
