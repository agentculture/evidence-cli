# evidence-cli

A zero-dependency Python package and CLI (`evidence`) with two separate checks
for runs of an agent harness:

- **`evidence check`, the run check** reads run exports, re-runs the quote match
  from the saved files, and reports counts of facts whose quote was found in the
  saved result they cite. It is read-only on the export.
- **`evidence grade`, the answer check** matches an answer text against recorded
  expected values and says `matches`, `does_not_match` or `cannot_tell`.

The two are separate results and are never folded together. Both commands print the line "a complete trail does not mean the work is correct". A passed fact means its quote was found, not that the value is true, and the answer check is an internal measurement, not a benchmark score. Both are built and unit-tested; neither has been run against live model output yet.

Before 0.7.0 this package was the `culture-agent-template` scaffold. The run
check code was moved from [associate](https://github.com/agentculture/associate)
at commit `266dad3` (`associate/accuracy/`).

## Quickstart

```bash
uv sync
uv run evidence check path/to/export-dir [more-export-dirs] [--json]
uv run evidence grade --answer-file answer.txt --expected expected.json [--json]
uv run pytest -n auto                 # run the test suite
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

`evidence check` writes a reviewer flags file in the directory that holds the
export (`--flags-dir DIR` writes it elsewhere, `--no-flags` writes none).
`evidence grade` reads the answer from a file, or `-` for standard input.

## First consumer

associate is the first consumer. It does not import this package yet; that is
planned work in its
[groundwork spec](https://github.com/agentculture/associate/blob/clef/accuracy/docs/specs/2026-11-18-associate-graded-measurement-groundwork.md)
(a branch link, which will move once the branch merges). The public library
names it is planned to import are listed in [`docs/library.md`](docs/library.md);
changing one is a breaking release.

## CLI

| Verb | What it does |
|------|--------------|
| `check` | Run check: re-check the facts of one or more run exports. |
| `grade` | Answer check: a match against recorded expected values. |
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants. |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors and diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Not built

The general evidence trail, rubric and final score of the original build brief
(issue #1) are not built, and the overlap with storybook-cli is not settled. See
[`CLAUDE.md`](CLAUDE.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
