# evidence-cli

Agent and CLI that documents the evidence trail behind a piece of work — the request, the spec, the plan, the docs and code, and the validations — then grades that evidence across parameters and issues a final score.

## Status

**Scaffold stage.** The evidence model, the grading parameters, and the scoring
verb are not implemented yet. What ships today is the agent baseline this repo
was scaffolded with: an agent-first CLI, a mesh identity, the vendored skill
kit, and CI. Some self-description strings still carry template wording from the
scaffold.

## What you get

- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken)
  (`afi-cli`) — the runtime package has no third-party dependencies.
- **A mesh identity** — `culture.yaml` (`suffix: evidence-cli`,
  `backend: colleague`) and the matching resident prompt file,
  `AGENTS.colleague.md`.
- **A vendored skill kit** (18 skills) under `.claude/skills/`, cite-don't-import.
  Provenance in [`docs/skill-sources.md`](docs/skill-sources.md).
- **A build + deploy baseline** — pytest, lint, the agent-first rubric gate, and
  PyPI Trusted Publishing wired into GitHub Actions.

## Install

```bash
uv tool install evidence-cli    # or: pipx install evidence-cli
evidence whoami
```

The installed console script is `evidence` (the distribution is named
`evidence-cli`); `python -m evidence` works too. Note that the CLI's own help and
docs text currently spell the command `evidence-cli` — `evidence` is the name
that actually resolves.

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants (prompt-file-present, backend-consistency). |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Development

```bash
uv sync                               # create .venv and install dev deps
uv run pytest -n auto                 # run the test suite (22 tests, ~1s)
uv run evidence learn                 # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

CI also gates on `black`, `isort`, `flake8`, `bandit`, `markdownlint-cli2`, a 60%
coverage floor, and — where `SONAR_TOKEN` is configured — the SonarCloud quality
gate.

## Contributing

Every PR bumps the version in `pyproject.toml` — CI's `version-check` job blocks
merge otherwise, and a merge to `main` touching `evidence/**` or `pyproject.toml`
publishes that version straight to PyPI. See [`CLAUDE.md`](CLAUDE.md) for the
full conventions (the `cicd` PR lane, worktree layout, skill re-sync procedure).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
