# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this project is

**evidence-cli** is a zero-dependency Python package and CLI (`evidence`) that
checks the evidence around a run of an agent harness, and checks an answer
against recorded expected values. It is an AgentCulture mesh agent; its mesh
identity is in `culture.yaml` and its resident prompt is
`AGENTS.colleague.md`. This `CLAUDE.md` is for Claude Code sessions working on
the repository.

Where it came from, stated plainly:

- Before 0.7.0 the package was the `culture-agent-template` scaffold. Entries in
  `CHANGELOG.md` below 0.7.0 are that scaffold's history, not work done here.
- The run check code was moved from the associate repository
  (github.com/agentculture/associate) at commit `266dad3`, directory
  `associate/accuracy/`, into `evidence/accuracy/`.
- associate does not import this package yet. That is planned work in
  associate's groundwork spec,
  `docs/specs/2026-11-18-associate-graded-measurement-groundwork.md` on the
  `clef/accuracy` branch of that repository (not on its `main` yet, so the
  link moves):
  <https://github.com/agentculture/associate/blob/clef/accuracy/docs/specs/2026-11-18-associate-graded-measurement-groundwork.md>.
  associate is the first consumer.

## Current state vs. not built

### Built and unit-tested

One live test exists (`docs/notes/2026-11-18-live-test.md`): six associate runs,
three of which handed back facts. On those three the run check printed the same
counts as `associate check`, and the answer check agreed with a hand reading.
Each is one run, not a rate. Beyond that, say "built and unit-tested", never
"works".

- **`evidence check <export-dir>...`, the run check.** For each run export it
  reads `walk.jsonl`, the saved results (`results/wN.txt`) and the facts payload,
  re-runs the quote match, and reports counts per kind and per source kind, plus
  any disagreement with the counts in the run's own `report.json`. It sums over
  the runs where facts apply (a run with no facts is not applicable; a walk
  format newer than supported is unsupported; neither adds to the sums). It is
  read-only on the export and writes a reviewer flags file in the directory that
  holds the export (`--flags-dir` moves it, `--no-flags` skips it). Code:
  `evidence/accuracy/`, command `evidence/cli/_commands/check.py`.
- **`evidence grade --answer-file F --expected F`, the answer check.** Matches an
  answer text against expected values (`must_appear`, `must_not_appear`,
  `one_of`; schema in `evidence/data/expected_values.schema.json`) and returns
  `matches`, `does_not_match` or `cannot_tell`. Code: `evidence/answer/`,
  command `evidence/cli/_commands/grade.py`.

**The two are separate results.** The run check counts quotes found in saved
results. The answer check is a match against recorded expected values. Never
fold one into the other, and every output says which one it is. Both carry the
line "a complete trail does not mean the work is correct".

Wording rules that tests enforce (`tests/test_wording.py`):

- A passed fact means its quote was found in the saved result it cites. It does
  not mean the value is true. Do not call that count "accuracy" in prose that
  describes results; `evidence.accuracy` is a module path and may be written as
  such.
- The answer check is an internal measurement, never a benchmark score or a
  quality score.

### Not built

- **The build brief's general trail, rubric and final score** (issue #1 in this
  repository): documenting the request, spec, plan, docs, code and validations
  as one evidence trail, grading it across parameters and issuing a final score.
  None of that exists. The brief's load-bearing distinction is that a high
  evidence grade means the trail is complete and traceable, not that the work is
  correct.
- **The overlap with storybook-cli is not settled.** The build brief names
  storybook-cli as an overlap to settle. This repository holds no further source
  for what that overlap is, so do not guess.
- Anything that calls a model, uses the network, grades runs of harnesses other
  than associate, or computes the decider score. All out of scope for now.

## Public library names

`docs/library.md` lists every public name with its module. associate is planned
to import eight of them: `check_quote`, `parse_source_ref`, `check_handback`,
`load_export`, `load_handback_input`, `inspect_export`, `accuracy_result` and
`fact_counts`.

**Changing a listed name's signature or behaviour, or removing or renaming it, is
a breaking release.** Add new public names to `docs/library.md` in the same
change; `tests/test_public_names.py` imports every row of its tables.

## Project shape

```text
evidence/
├── __init__.py          # __version__ via importlib.metadata("evidence-cli")
├── __main__.py          # python -m evidence
├── cli/
│   ├── __init__.py      # argparse main() + _build_parser() + _dispatch()
│   ├── _errors.py       # CliError + EXIT_SUCCESS / EXIT_USER_ERROR / EXIT_ENV_ERROR
│   ├── _output.py       # emit_result / emit_error / emit_diagnostic
│   └── _commands/       # one module per verb, each exposing register(sub)
├── accuracy/            # run check: matcher.py, counts.py, check.py, vectors.py
├── answer/              # answer check: grade.py, schema.py
├── explain/             # resolve(path) / known_paths(); catalog.py ENTRIES
└── data/                # matcher_vectors.json, accuracy_defaults.json,
                         #   expected_values.schema.json (ship in the wheel)
tests/                   # pytest; fixtures/ holds copied exports and answers
docs/                    # library.md, skill-sources.md, specs/, plans/
.claude/skills/          # vendored skills (cite-don't-import)
culture.yaml             # mesh identity
```

Verbs today: `whoami`, `learn`, `explain`, `overview`, `doctor`, `cli overview`,
`check`, `grade`.

## The CLI contract

Enforced by tests and by the `teken cli doctor . --strict` rubric gate in CI.

1. **Results to stdout, diagnostics and errors to stderr. Never mixed.**
   `evidence/cli/_output.py` is the only module that writes to either stream.
   Every command takes `--json`; in JSON mode errors are
   `{code, message, remediation}` on stderr.
2. **Every failure raises `CliError`; no traceback reaches stderr.**
   `_dispatch()` in `evidence/cli/__init__.py` catches `CliError` and wraps any
   other exception into one pointing at the issue tracker. A handler returns
   `None` (exit 0) or an `int`. Exit codes: `0` success, `1` user error,
   `2` environment error, `3+` reserved. `evidence check` prints its report and
   still exits `2` if the flags file cannot be written.
3. **Argparse errors use the same contract.** `_CliArgumentParser.error()` emits
   `error:` / `hint:` and exits `1`. Subparsers are built with
   `parser_class=_CliArgumentParser`; a noun group that adds its own subparsers
   must pass `parser_class=type(p)` (see `_commands/cli.py`). `main()` pre-scans
   argv for `--json` so parse-time errors honour it.
4. **Descriptive verbs never hard-fail on a bad target.** `overview` accepts and
   ignores an optional positional target.

### Adding a verb: four places that stay in sync

1. `evidence/cli/_commands/<verb>.py`: a `register(sub)` function and the
   handler; add `--json`; raise `CliError` on failure.
2. `evidence/cli/__init__.py`: import inside `_build_parser()` and call
   `register(sub)`.
3. `evidence/explain/catalog.py`: an `ENTRIES` entry keyed by the command-path
   tuple. The root key is `("evidence-cli",)` and the empty tuple; check the
   file before renaming anything.
4. `evidence/cli/_commands/learn.py`: both `_TEXT` and `_as_json_payload()`.

A new noun (verb group) also needs an `overview` sub-verb under it.

## Build, test, lint

```bash
uv sync
uv run pytest -n auto -q                      # tests
uv run pytest -n auto --cov=evidence --cov-report=term   # coverage, fail_under = 60
uv run black --check evidence tests
uv run isort --check-only evidence tests
uv run flake8 evidence tests
uv run bandit -c pyproject.toml -r evidence
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict            # the agent-first rubric gate (required in CI)
uv run evidence whoami                        # identity from culture.yaml
```

The markdown config is the repo-local `.markdownlint-cli2.yaml`. Vendored skills
under `.claude/skills/` are excluded on purpose: do not reformat them, and fix
findings against them upstream.

SonarCloud fails CI on any new issue: keep functions small (cognitive
complexity 15 or less), avoid string literals repeated three or more times,
unused variables and nested conditionals. In a regex that must match associate's
TypeScript matcher, `\d` needs `re.ASCII`.

## Version bump: required on every PR

```bash
python3 .claude/skills/version-bump/scripts/bump.py {patch|minor|major}
```

The script edits `pyproject.toml` and prepends a `CHANGELOG.md` entry (pass the
entry as JSON on stdin). Then run `uv lock`: `uv.lock` records this package's
version and goes in the same commit. The `version-check` CI job fails when the
version matches `main`, including for docs-only changes.

## Dependency rule

`dependencies = []` in `pyproject.toml` is deliberate: the package imports only
the standard library (and `evidence` itself), makes no model call and no network
call, and gives the same output for the same input. Do not add a runtime
dependency; if you think you need one, that is a conversation, not a commit.
`teken` is a dev dependency only. Data files ship inside the package
(`evidence/data/`) and are read with `importlib.resources`.

## Worktrees

Every worktree you create by hand lives in one directory beside the repo:

```bash
repo_root=$(git rev-parse --show-toplevel)
wt_root="$(dirname "$repo_root")/.worktrees.$(basename "$repo_root")"
git worktree add "$wt_root/agent-<task-id>" -b <scoped-prefix>/<task-id>
```

Never use a shared `../worktrees/` and never create one inside the repo. Scope
the branch prefix to the work (a plain `agent/*` collides with leftovers). Tear a
lane down with `git worktree remove`. The vendored `assign-to-workforce` skill
uses the shared path and `agent/<task-id>` in its example; it is cited verbatim
and not edited, so this section overrides it.

## Skills and workflow

Skills are copied into `.claude/skills/<name>/` (cite-don't-import); provenance
is in `docs/skill-sources.md`, and a finding against a vendored script is fixed
upstream, never patched here. The devague chain (`scope`, `think`, `challenge`,
`spec-to-plan`, `assign-to-workforce`, `deviate`, `validate-delivery`,
`summarize-delivery`) has its plans in `docs/specs/` and `docs/plans/`. Finish a
branch by pushing it and opening a PR with the `cicd` skill.

Memory is in-repo and public: `/recall` before non-trivial work, `/remember`
when a non-obvious decision or gotcha surfaces; pass `--visibility private` to
keep a record out of the repo.

When posting online on the operator's behalf, sign as `- evidence-cli (Claude)`.

## What not to invent

- Do not describe the checks as working on live output, or call the passed-fact
  count "accuracy", or present the answer check as a benchmark score.
- Do not build the general trail, rubric or final score here without a spec.
- Do not guess what the storybook-cli overlap is.
- Do not add a runtime dependency, an absolute home-directory path, or a model
  checkpoint id to any tracked file.
