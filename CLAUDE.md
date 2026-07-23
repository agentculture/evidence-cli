# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**evidence-cli** is an AgentCulture mesh agent whose intended domain is: document
the evidence trail behind a piece of work — the request, the spec, the plan, the
docs and code, and the validations — then grade that evidence across parameters
and issue a final score.

**None of that is implemented yet.** The repo was scaffolded from
`culture-agent-template` (commit `3ec9943`) and everything on disk today is the
template's baseline: an agent-first introspection CLI (`whoami` / `learn` /
`explain` / `overview` / `doctor` / `cli overview`), a mesh identity, the
vendored skill kit, and CI. There is no evidence model, no grading rubric, no
scoring code, and no domain tests. Expect to *add* the domain surface, not
modify it.

Several scaffold artifacts still describe the repo as "a clonable template for
AgentCulture mesh agents" (`learn` text, `explain` catalog, argparse
`description`, `README.md`'s cloning checklist). Those strings are stale
template residue, not a description of this agent — they need replacing as the
domain lands. Note that `learn` / `explain` / `overview` output is the
agent-facing contract, so fixing them is a real change, not a cosmetic one, and
`tests/test_cli.py` asserts against some of it.

## Commands

```bash
uv sync                                   # create .venv and install dev deps
uv run pytest -n auto                     # full suite (22 tests, ~1s)
uv run pytest tests/test_cli.py::test_whoami_json -v   # a single test
uv run evidence whoami                    # the installed console script (see naming, below)
```

Reproduce CI exactly — `.github/workflows/tests.yml` runs these as separate
gates, all of which block merge:

```bash
uv run pytest -n auto --cov=evidence --cov-report=xml:coverage.xml --cov-report=term -v
uv run black --check evidence tests
uv run isort --check-only evidence tests
uv run flake8 evidence tests
uv run bandit -c pyproject.toml -r evidence
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict        # the agent-first rubric gate
```

Coverage has a floor of 60 (`[tool.coverage.report] fail_under`), and SonarCloud
gates the `test` job when `SONAR_TOKEN` is set (`sonar.qualitygate.wait=true`).
Both the lint tools and the rubric gate are dev-only dependencies; `teken` (the
`afi-cli` toolchain) supplies `teken cli doctor`.

## The naming triple — and the mismatch

Three different names are in play, and they do not all agree:

| Thing | Value | Where |
|-------|-------|-------|
| Distribution / PyPI name | `evidence-cli` | `pyproject.toml` `[project] name` |
| Python package | `evidence` | `evidence/`, `known_first_party`, `sonar.sources` |
| Installed console script | **`evidence`** | `[project.scripts] evidence = "evidence.cli:main"` |
| Module entry point | `python -m evidence` | `evidence/__main__.py` (always works, whatever the script is called) |

Every doc string, help text, `learn` line, and `explain` entry says
`evidence-cli <verb>` — including `argparse`'s `prog="evidence-cli"` — but the
executable that actually lands on PATH is `evidence`. `uv run evidence-cli`
fails with "Failed to spawn". This is a genuine inconsistency inherited from the
scaffold; resolve it deliberately in one direction (either rename the console
script to `evidence-cli`, or rewrite ~50 doc strings to `evidence`) rather than
patching one call site at a time. `README.md` currently documents the working
form (`evidence`).

The rubric gate reads `[project.scripts]` to discover the binary and then probes
`explain <script-name>` — which is why `evidence/explain/catalog.py` carries
**both** `("evidence-cli",)` and `("evidence",)` as keys for the root entry. If
you rename the console script, the catalog key matching the new name must exist
or `explain_self` fails.

## Architecture

### CLI dispatch

`evidence/cli/__init__.py` owns the whole contract. Three pieces work together
and none of them makes sense read alone:

- **`_CliArgumentParser`** overrides `argparse`'s `.error()` so parse-time
  failures (unknown verb, bad flag) route through the same structured
  `error:` / `hint:` format as runtime failures, exiting `1` instead of
  argparse's default `2`. It is passed as `parser_class=` to every
  `add_subparsers()` call — including inside noun groups — so the override
  propagates. `main()` pre-scans raw argv for `--json` and stashes the answer on
  the class-level `_json_hint`, because parse errors happen before `args.json`
  exists.
- **`_dispatch()`** calls `args.func(args)` and converts exceptions to exit
  codes. Handlers signal failure by raising `CliError`; anything else is caught
  and wrapped so no Python traceback ever reaches stderr.
- **`evidence/cli/_output.py`** enforces the stream split: results to stdout,
  errors and diagnostics to stderr, never mixed, in both text and JSON mode.

`evidence/cli/_errors.py` centralises the exit-code policy: `0` success, `1`
user-input error, `2` environment/setup error, `3+` reserved.

### Adding a verb touches five files

Command modules live in `evidence/cli/_commands/` and each exposes a
`register(sub)` that builds its own subparser. A new verb is not done until all
of these are updated, and the rubric gate or tests will fail if you miss one:

1. `evidence/cli/_commands/<verb>.py` — handler + `register(sub)`, with
   `--json` on the subparser.
2. `evidence/cli/__init__.py` `_build_parser()` — import and call `register()`.
3. `evidence/explain/catalog.py` — an `ENTRIES` entry keyed by the command-path
   tuple. `tests/test_cli.py::test_every_catalog_path_resolves` walks every key.
4. `evidence/cli/_commands/learn.py` — both `_TEXT` and `_as_json_payload()`.
5. `evidence/cli/_commands/overview.py` — the `_VERBS` list, which feeds both
   the global `overview` and `cli overview`.

Noun groups follow `evidence/cli/_commands/cli.py`: a parser with its own
`add_subparsers(parser_class=type(p))`, a bare-noun default handler, and an
`overview` sub-verb.

### The agent-first rubric constrains the design

`teken cli doctor . --strict` is a CI gate, and several otherwise-odd choices
exist only to satisfy it. Do not "clean these up":

- Every command accepts `--json`; stderr must be empty on success.
- Errors must emit a `hint:` line and must never print a traceback.
- `learn` must be >=200 chars and mention purpose, the command map, exit codes,
  `--json`, and `explain`.
- Descriptive verbs must not hard-fail on a missing target — hence `overview`'s
  ignored optional `target` positional (`overview /no/such/path` exits 0).
- Any noun carrying action-verbs must also expose `overview`; the `cli` noun
  group exists solely to satisfy this today.
- `doctor` must return `{healthy, checks: [{id, passed, severity, message,
  remediation}]}`.
- `explain <script-name>` must resolve (see the naming section above), and
  `main(argv) -> int` must be importable as `evidence.cli.main` — the gate calls
  it directly for its `main_entry_contract` check.

The gate is at 26/26 today, so any regression it reports is something you just
introduced. Run it before opening a PR; it is faster than a CI round-trip.

### Identity, and why `doctor` passes

`culture.yaml` declares `suffix: evidence-cli`, `backend: colleague`, and a
pinned Qwen model. Because the backend is `colleague`, the load-bearing prompt
file for the `backend-consistency` invariant is **`AGENTS.colleague.md`**, not
this file — `doctor`'s `_PROMPT_FILE` map is what defines the pairing
(`claude` → `CLAUDE.md`, `colleague` → `AGENTS.colleague.md`, `acp` →
`AGENTS.md`, `gemini` → `GEMINI.md`). Changing `culture.yaml`'s backend without
adding the matching prompt file breaks `doctor` and
`tests/test_cli_introspection.py::test_doctor_recognizes_declared_backend`.

`whoami.py` resolves identity by walking up from `__file__` (not the CWD) to
find the agent's *own* `culture.yaml`, and parses it with a hand-rolled
line-scanner rather than PyYAML. That is deliberate: **the runtime must keep
`dependencies = []`**. Anything that would add a third-party import at runtime
needs a different approach. In a wheel install no `culture.yaml` ships, so
`whoami` falls back to literals and `doctor` reports a single info check.

`__version__` comes from `importlib.metadata.version("evidence-cli")` — the
*installed* distribution, not `pyproject.toml`. After a version bump, `whoami`
and `--version` keep reporting the old number until `uv sync` reinstalls the
editable package. The tests compare against `__version__` itself, so they never
catch a stale install.

**Two prompt files, and only one of them is loaded by the resident.** This file
guides Claude Code. The mesh agent this repo declares runs `backend: colleague`
and loads `AGENTS.colleague.md`, which today is a 12-line generic
resident prompt carrying none of the conventions below. A repo convention
written only here is invisible to the colleague resident (and the operator's
user-level Claude Code instructions are not loaded by the mesh daemon at all) —
when a rule must bind both readers, it has to land in both files.

## Vendored skills — cite, don't import

`.claude/skills/` holds 18 skills vendored verbatim from sibling repos
(guildmaster is the skills supplier; `devague`, `colleague`, and `eidetic-cli`
are origins for some). **Do not edit them as if they were local code.**
`docs/skill-sources.md` is the authoritative provenance ledger: per-skill
upstream path, origin, the exact local adaptations applied, and the re-sync
procedure. It also records four tracked divergences (the `agex` → `devex`
rename, `ask-colleague` vendored directly from `colleague`, and
`scope`/`challenge`/`deviate`/`summarize-delivery` vendored directly from
`devague` to avoid guildmaster's added wrapper scripts). If a change belongs in
a skill, lift it upstream and re-vendor; if you must patch in place, record it
in the ledger as a divergence.

Two details are load-bearing: every `SKILL.md` needs `type: command` in its
frontmatter (`core.skill_loader` silently skips files without it), and
`.claude/skills/**` is excluded from markdownlint, Sonar, and the rename sweep.

Skills that shell out need these on PATH: `devex` (>=0.21, for `cicd`), `agtag`
(>=0.1, for `communicate`), and optionally `colleague` (for `ask-colleague`) and
`eidetic` (>=0.10, for `remember` / `recall`).

Per-machine skill config lives in `.claude/skills.local.yaml` (git-ignored; copy
`skills.local.yaml.example`). It supplies `culture_server_yaml` and the
`sibling_projects` list the `cicd` alignment-delta step walks. `devex pr delta`
**hard-fails** with a copy-the-example hint when the file is absent — the
example's "skills fall back to this example" comment does not hold for it — so
make the copy before the first `workflow.sh delta`. Siblings listed but not
checked out render as `_No CLAUDE.md found._` and do not fail the run; the
shipped example lists `../teken`, which is not checked out in this workspace.

## Conventions and workflow

**Every PR bumps the version — even docs-only, config-only, or CI-only ones.**
The `version-check` job compares `pyproject.toml` against `origin/main` and
fails the PR when they match. Use the `version-bump` skill
(`python3 .claude/skills/version-bump/scripts/bump.py patch|minor|major`, with
optional changelog JSON on stdin) so `CHANGELOG.md` stays in Keep-a-Changelog
form. `CHANGELOG.md` here is unusually detailed — entries carry the *why*, and
it is often the fastest way to recover the rationale behind a decision.

**The bump rule has teeth because merging publishes.**
`.github/workflows/publish.yml` fires on any change under `evidence/**` or to
`pyproject.toml`: on a PR it builds `<version>.dev<run_number>` to TestPyPI
(same-repo PRs only — fork PRs have no OIDC context and are skipped), and on
push to `main` it publishes the real version to PyPI via Trusted Publishing.
`evidence-cli` is live on PyPI, so a merge with an unbumped version is a
duplicate upload that fails the publish job after the merge has already landed.
Docs-only PRs skip publishing but still need the bump — `version-check` runs on
every PR.

**PR lane:** use the `cicd` skill (`workflow.sh`), which delegates
lint/open/read/reply/delta to `devex pr` and adds `status` (SonarCloud gate +
hotspots + unresolved threads) and `await`. PR replies are signed automatically
by `_resolve-nick.sh` from `culture.yaml` — do not hand-sign inside the body.

**Memory:** `/recall` before non-trivial work rather than re-deriving prior
decisions, and `/remember` when a non-obvious decision, constraint, fix-and-why,
or gotcha surfaces. This repo's wrappers inject `--visibility public`, so a
plain `/remember` writes to `<repo-root>/.eidetic/memory` — **in-repo and
committed**, shared with the team and the mesh. Pass `--visibility private` to
route a record to `$HOME` instead. (The vendored `SKILL.md` descriptions still
claim a private `$HOME` default; the wrapper scripts are what actually run.)

**Second opinions:** reach for `ask-colleague` reflexively, not only when asked.
`review` (a diverse second opinion on a committed diff, before opening a PR) and
`explore` (a fresh read of an unfamiliar area) are read-only, run in a throwaway
worktree, and are always safe. The side-effecting `write --apply` / `write --pr`
needs the user's go-ahead first.

**Worktrees:** every worktree you create by hand lives in
`../.worktrees.evidence-cli/<name>/` — one repo-named directory beside the
checkout, never a shared `../worktrees/`. This workspace holds many sibling
projects, and a shared folder accumulates orphaned trees from several repos with
nothing indicating ownership. Scope branch prefixes to the work at hand; a plain
`agent/*` prefix collides with leftovers from earlier fan-outs and fails
`git worktree add -b`. Tear down with `git worktree remove <path>` —
`git worktree prune` only clears metadata for directories that are already gone.
The vendored `assign-to-workforce` skill's fan-out example uses both the shared
path *and* `agent/<task-id>` branches; it is cited verbatim and must not be
edited, so override both when following it. Tool-managed throwaways are out of
scope — `ask-colleague`'s read-only verbs create a detached worktree under
`${TMPDIR:-/tmp}` and reap it on an EXIT trap.
