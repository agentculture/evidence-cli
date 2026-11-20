# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.1] - 2026-11-20

### Added

- **`strict.returned_before` is read.** associate's `check.json` may now carry
  `strict.returned_before`, the sorted fact ids returned to the model in
  earlier rounds. When the record holds it (a list of strings),
  `recheck_strict_export` uses it, decides kept with the mark against returned
  itself, and can disagree with the record on that; the result's new
  `returned_before_source` is `check.json`. An export without the key is read
  as before (the facts recorded as kept with the mark while a round was left
  stand in, and that one point cannot disagree); `returned_before_source` is
  then `inferred from keep_marked`. `evidence check` prints which it was.
- `accuracy_result(..., with_strict=True)` adds one key, `strict`: the whole
  strict re-check with its comparison, from the one re-check the call already
  ran (None for an export that is not strict or where facts do not apply).
  Without the argument the result is unchanged.
- `load_export` and `load_handback_input` also return `result_files` (file name
  to text): the file each entry names and the file under the entry's own id.

### Changed

- **The shared strict cases grew from 45 to 64.**
  `evidence/data/strict_vectors.json` is the byte copy of associate's file at
  associate commit `533c2b8`, sha256
  `94e07a7a43d9cbc45e6a6e9975d9aead8e37a432b1c85fb2794ed2774813d5fd`. The first
  45 cases are unchanged. All 64 agree through `strict_recheck` with no change
  to the rules it implements.
- The re-check of a stored export reads an old-shape fact's saved result from
  `results/<the entry's own id>.txt` whether or not the entry names that file,
  as the rules say (the shared case `saved_result_file_read`). An export
  written by associate's extension names each entry's own file, so its result
  does not change.
- `recheck_strict_export`'s result gains `applicable`, `not_applicable_reason`
  and `returned_before_source`; its `comparison` gains `agrees_reason`.
  `evidence check --json` gains `agrees_reason` and `returned_before_source`
  per strict run and `strict_not_compared` in the sums. No key was renamed or
  removed.
- The description of the rules here follows associate's extended note: an
  object key of a command's arguments is redacted and its paths are not made
  relative, a backtick ends a path match, and `min_quote_length` must be a
  whole number of 1 or more (`true` does not count as 1).

### Fixed

Fixes #8.

- **A part absent from `check.json` gives no disagreement rows.** A part listed
  under `not_compared` yields no rows; a fact with no record of its own yields
  no field rows (the `facts` count row reports the difference); a row whose
  recorded and re-checked values are equal is never a disagreement. When the
  record's `facts` are absent the decider's stored answers are absent with
  them, so only `accepted` is still compared. When nothing could be compared,
  `agrees` is `null` (it was `false`) and `agrees_reason` reads "nothing in
  check.json could be compared"; `evidence check` prints "neither agrees nor
  disagrees" with that reason and counts such runs on its last line. A fact
  row's `agrees`, and `agrees_with_record` in `--json`, is `null` for a fact
  with no record.
- **A strict export with no `facts.json` is not applicable from both
  `recheck_strict_export` and `inspect_export`,** with the same reason.
  `recheck_strict_export` used to re-check zero facts and report count
  disagreements.
- **The comparison is available from `accuracy_result`** (`with_strict=True`),
  so a caller wanting both no longer re-checks the export twice.

## [0.8.0] - 2026-11-20

### Added

- **The strict re-check.** A second, independent implementation of
  associate's strict facts check (`evidence/accuracy/strict.py`, with
  `pointer.py` and `command.py`). It takes one hand-back's input, including the
  decider's stored answers, and returns per fact the kind checked, the outcome
  and the drop reason, the verdicts and open items, and the counts. It never
  asks a decider and reads no environment. All 45 shared cases in
  `evidence/data/strict_vectors.json`, a byte copy of associate's
  `associate/contract/strict_vectors.json`, agree; `load_strict_vectors()`
  loads them for other packages' tests.
- **Re-checking a stored strict export** (`evidence/accuracy/strict_export.py`):
  the input is rebuilt from `walk.jsonl`, `results/`, `facts.json` and
  `check.json`, and the result is compared with what the export's own
  `check.json` recorded: per fact the kind checked, outcome and drop reason;
  per verdict and open item the id, outcome, reason, strict outcome and strict
  reason; `accepted`; and the strict counts, drop reasons and judge counts. The
  result names the parts compared and any the record does not hold. Stored
  decider answers are matched to facts by position (by id when the records do
  not line up), so two facts sharing an id keep their own answers. A malformed
  fact record or a redaction pattern Python cannot compile is reported as an
  error about the export or settings. `check.json` does not record the ids
  returned in earlier rounds, so facts it records as kept with the mark stand
  for them.
- The strict re-check's default contract values, used when the settings hold no
  well-formed `strict` block, are in this package's own
  `evidence/data/strict_defaults.json` (equal to what every shared case uses
  today). A caller's `strict` block is used whenever it is well formed; a
  support pass list is not required (the re-check does not read it).
- `evidence check` prints the strict re-check for an export whose `check.json`
  says `"mode": "strict"`: each fact's id, source, kind checked, outcome and
  drop reason, the counts, and whether it agrees with the export's own record,
  with each disagreement. Each disagreement is also written as a reviewer flag
  (`strict_record_disagrees`). It does not change the exit code (as a
  disagreement with `report.json` does not); the count is in the `--json` sums
  and in the last line printed. `--json` carries the same. A strict run is not
  added to the quote sums.
- The new public names are in `docs/library.md`.

A fact with outcome pass had its evidence copied from a saved result or its
quote found in one; a judged fact carries the decider's stored answer. Neither
says a value is true.

### Changed

- An export that is not strict gives exactly the result it gave before, from
  the library and from `evidence check`.
- In a saved `delegate_status` result, the key `unchecked_final_reply` is now
  read as the delegated model's own account, like `final_reply` (kept) and
  `answer`. associate now writes it in place of `final_reply`.

## [0.7.2] - 2026-11-18

### Added

- CI fails a pull request that has any open or confirmed SonarCloud issue (`scripts/sonar-pr-issues.py`, cited from culture-rules); issues marked accepted or false positive pass. The quality gate alone stays green on a code smell.

## [0.7.1] - 2026-11-18

### Added

- The delivery record for the run check and the answer check:
  `docs/deliveries/2026-11-18-evidence-cli-run-check-and-answer-check.md`, with
  the evidence, behaviour changes, deviations and lapses filed in `.devague/`.
  The run is recorded as partial: the comparison with associate's checker
  covered three live exports, not every saved one.

### Changed

- `tests/test_release_docs.py` no longer pins the package version to 0.7.0; it
  checks that the 0.7.0 changelog entry exists.

## [0.7.0] - 2026-11-18

Before this release the package was the `culture-agent-template` scaffold: the
verbs `whoami`, `learn`, `explain`, `overview`, `doctor` and the `cli` group,
and nothing that checks a run or an answer. Every entry below 0.7.0 is that
scaffold's history, not work done on evidence-cli itself. This release is the
first one with content of its own.

### Added

- **`evidence check`, the run check.** Reads one or more run exports
  (`walk.jsonl`, saved results, the facts payload), re-runs the quote match from
  the saved files, reports counts per kind and per source kind, reports any
  disagreement with the counts in the run's own `report.json`, and sums over the
  runs where facts apply. It is read-only on the export and writes a reviewer
  flags file beside it (beside the resolved export path, so `evidence check .`
  run from inside an export does not write into it). It also reports how many
  of a run's stated conclusions the re-check backed (accepted and stated
  supported or refuted), left open (accepted and stated open or cannot tell)
  and refused (`conclusion_outcomes`: `backed`, `open`, `refused`). Exports are
  counted once per resolved path. `--continue-from` takes one export only and
  must name a directory holding `walk.jsonl` (or its `export/`). A `--settings`
  file whose keys differ in JSON type from the bundled default is refused,
  naming the key. Under `--json` a flags-file failure is one
  `{code, message, remediation}` object on stderr. One live test is recorded in
  `docs/notes/2026-11-18-live-test.md`: six associate runs, three of which
  handed back facts; each is one run, not a rate.
- **`evidence grade`, the answer check.** Matches an answer text against
  recorded expected values (`must_appear`, `must_not_appear`, `one_of`) and
  returns `matches`, `does_not_match` or `cannot_tell`. It is a separate result
  from the run check and is an internal measurement, not a benchmark score.
  Only whitespace is collapsed before matching: a line starting with a number
  and a tab keeps the number (the quote matcher's read-line-stamp stripping is
  not applied to answers).
- **The hand-back checker, export loader, counts and quote matcher**, moved from
  the associate repository (`agentculture/associate`) at commit `266dad3`,
  directory `associate/accuracy/`, into `evidence/accuracy/`, with the shared
  matcher vectors and the bundled default settings under `evidence/data/`.
  Standard library only. These behaviours differ from the code as it was in
  associate:
  - An export whose walk format is newer than supported is reported as
    unsupported, and the format is tested before anything else of the export
    is read. A format marker whose version is not a positive integer is
    unsupported too, the value named; a line with a `format` key is the marker
    even with other keys.
  - The export's own files are never read through a link pointing outside it
    (`facts.json` or `walk.jsonl` linked from outside is an error;
    `report.json`, `check.json` and `answer.md` linked from outside are treated
    as absent). associate at `266dad3` guards only the saved result files. A
    child run or a `--continue-from` run is another directory, named by the
    walk or the operator, and is read from where it is.
  - A relative `child_walk` is taken from the export directory, not the
    process's working directory.
  - A prior or child run whose walk format is not supported is not loaded (a
    fact citing it is refused as an unknown source) and is listed under
    `unsupported_runs`.
  - A walk line that is not UTF-8 (cut mid character by a killed run) is
    skipped like a line that is not JSON, instead of failing the check.
  - JSON nested too deeply for the json module is handled: in a walk line it is
    skipped, in `facts.json` it is an export error, in `check.json` or
    `report.json` the file is treated as absent, a saved result is then text,
    and a `delegate_status` result is then not first-hand.
- **`evidence/answer/`**, the answer check library, with the expected-values
  schema (`evidence/data/expected_values.schema.json`, schema version 1).
- **`docs/library.md`**, the public library names with their modules, and
  `tests/test_public_names.py`, which imports every name listed there. The
  eight functions associate is planned to import are `check_quote`,
  `parse_source_ref`, `check_handback`, `load_export`, `load_handback_input`,
  `inspect_export`, `accuracy_result` and `fact_counts`. Changing or removing a
  listed name is a breaking release.
- A real `CLAUDE.md` replacing the seed placeholder, and a README that describes
  the two commands.

### Changed

- `README.md` describes what the package does today instead of the template.
- The printed program name is `evidence`, the installed command. Usage lines,
  hints, `learn` and `explain` said `evidence-cli` before, which is the package
  name and not a command. `evidence explain evidence-cli` still resolves to the
  root entry.

### Notes

- associate does not import this package yet. That is planned work in
  associate's groundwork spec (a branch link, which will move):
  <https://github.com/agentculture/associate/blob/clef/accuracy/docs/specs/2026-11-18-associate-graded-measurement-groundwork.md>.
- Not built: the general evidence trail, rubric and final score of the original
  build brief (issue #1). The overlap with storybook-cli is not settled.

## [0.6.1] - 2026-07-20

### Added

- **Worktree location convention** in `CLAUDE.md` — every worktree you create
  by hand (workforce fan-out lanes, scratch checkouts) lives in
  `../.worktrees.evidence-cli/<name>/`, one
  repo-named directory beside the checkout, replacing a shared `../worktrees/`
  folder. This workspace holds many sibling projects, so a generic shared
  folder accumulates orphaned trees from several repos at once with nothing
  indicating ownership — a stale-tree sweep can't tell a live lane from junk.
  Matches the convention already documented in sibling repo `reachy-mini-cli`.
  Adds branch-prefix guidance (scope the prefix to the work; plain `agent/*`
  collides with leftovers from earlier fan-outs and fails `git worktree add
  -b`), and notes that the vendored `assign-to-workforce` skill uses both the
  shared path *and* `agent/<task-id>` branches in its fan-out example — it is
  cited verbatim and must not be edited, so both are overridden when following
  it. Teardown guidance names `git worktree remove <path>` as the verb that
  actually deletes a worktree; `git worktree prune` only clears metadata for
  directories that are already gone. Tool-managed throwaways are explicitly
  out of scope: `ask-colleague`'s read-only verbs create a detached worktree
  under `${TMPDIR:-/tmp}` and reap it on an EXIT trap, so they never persist
  to need an owner.

## [0.6.0] - 2026-07-18

### Added

- **Four devague-origin skills re-vendored into `.claude/skills/`**
  (cite-don't-import), synced to the fixed devague source
  (devague#74/#75/#76):
  - `challenge` — a risk-scaled blind-spot discovery pass that runs between
    `/think` and `/spec-to-plan`, routing findings back through the existing
    deterministic moves as human-adjudicated proposals.
  - `scope` — the idea→scope leg that surveys the surfaces an idea touches
    before framing, seeding the Announcement Frame with provenance-backed
    boundary/non-goal/assumption claims.
  - `deviate` — stops an in-flight `assign-to-workforce` run when execution
    must diverge from the confirmed plan and records the divergence as a
    first-class, append-only deviation record.
  - `summarize-delivery` — closes the loop after an `assign-to-workforce`
    run with a planned-vs-actual accountability artifact.

  These four originate in `devague` and are re-broadcast via guildmaster; see
  `docs/skill-sources.md` for provenance.

## [0.5.0] - 2026-06-24

### Added

- **Memory-discipline "Conventions and workflow" section in `CLAUDE.md`** — a
  per-task *recall-before / remember-after* convention (scope localized to this
  repo's nick) so the vendored `remember` / `recall` skills are actually used,
  not just present: `/recall` before non-trivial work to build on prior
  decisions instead of re-deriving them, and `/remember` when a non-obvious
  decision, constraint, fix-and-why, or hard-won gotcha surfaces. The section
  documents this repo's memory as **in-repo and public** — records resolve to
  `<repo-root>/.eidetic/memory` (committed, team- and mesh-shared). Inserted
  idempotently (skipped if already present), slotted under an existing
  "Conventions and workflow" heading when one exists, else appended.

### Changed

- **Refreshed the `remember` + `recall` wrappers from eidetic-cli 0.10.0**
  (cite-don't-import) — picks up eidetic's **project-local store default**: the
  files backend now resolves per record by visibility — PUBLIC records inside a
  git repo go to `<repo-root>/.eidetic/memory` (committed, team-shared), PRIVATE
  records (or any record outside a repo) go to `$HOME/.eidetic/memory` (never
  committed), an explicit `EIDETIC_DATA_DIR` still wins, and recall reads both
  stores and merges. Also carries the 0.9.3 hardening (interactive-stdin guard,
  `help` as a search term, SIGPIPE-safe suffix parsing). **Recipe policy
  override (the wrappers here are NOT byte-verbatim):** the injected default
  visibility is flipped from eidetic's `private` to **`public`**, so a plain
  `/remember` lands the note in `./.eidetic/memory` in this repo, kept as part
  of the repo — pass `--visibility private` to route a record to `$HOME`
  instead. `remember` drives `eidetic remember` (idempotent upsert of one JSON
  record or an NDJSON batch on stdin); `recall` drives `eidetic recall` with
  four search modes (exact / approximate / keyword / hybrid). Each `SKILL.md` is
  localized only in the illustrative `--scope <nick>` examples (Provenance keeps
  "First-party to eidetic-cli"). Runtime dep: the `eidetic` CLI on PATH (else a
  local eidetic-cli checkout with `uv`) — **`eidetic >= 0.10.0`** for the
  in-repo routing; on an older CLI the public records still work but are stored
  in `$HOME/.eidetic/memory` instead of in-repo. Propagated by rollout-cli's
  `eidetic-memory` recipe.

## [0.4.0] - 2026-06-23

### Added

- **Vendored the `remember` + `recall` memory skills from eidetic-cli**
  (cite-don't-import) — the write/read halves of eidetic's shared
  `$HOME/.eidetic/memory` surface, so this agent (Claude and its colleague
  backend) can persist facts across sessions and recall them later, sharing
  one store.
  `remember` drives `eidetic remember` (idempotent upsert of one JSON record or
  an NDJSON batch on stdin, dedup by id + content hash); `recall` drives
  `eidetic recall` with four search modes — exact / approximate / keyword /
  hybrid — each hit carrying text, full provenance metadata, a relevance score,
  and a freshness signal. The `.sh` wrappers are byte-verbatim from eidetic-cli
  (their first-party origin); each `SKILL.md` is localized only in the
  illustrative `--scope <nick>` examples (Provenance keeps "First-party to
  eidetic-cli"). Both default to this agent's PRIVATE scope, reading the suffix
  from `culture.yaml`. Runtime dep: the `eidetic` CLI on PATH (else a local
  eidetic-cli checkout with `uv`). Propagated by rollout-cli's `eidetic-memory`
  recipe.

## [0.3.4] - 2026-06-20

### Fixed

- Identity docs and self-description strings still claimed `backend: claude`
  (prompt file `CLAUDE.md`), but this template was promoted to a colleague
  resident in #14/#15: `culture.yaml` declares `backend: colleague` (Qwen) with
  `AGENTS.colleague.md` as the resident prompt. Corrected the stale claim in
  `CLAUDE.md` (Identity section), `README.md`, `docs/skill-sources.md`, and the
  two CLI description strings (`overview` artifacts and `explain doctor`). The
  `doctor` backend→prompt-file mapping and the tests were already on
  `colleague`; this aligns the prose and self-description with them.

## [0.3.3] - 2026-06-20

### Fixed

- pyproject.toml: correct the `license` field and PyPI classifier from MIT to
  Apache-2.0 to match the `LICENSE` file. The README License section was already
  corrected in 0.3.2, but the package metadata was missed; the built wheel now
  reports `License-Expression: Apache-2.0`.

## [0.3.2] - 2026-06-18

### Added

- ask-colleague skill: `monitor`/`guide`/`stop` pilot verbs plus a `--watch`
  flag to dispatch, watch the live feed of, send mid-flight guidance to, and
  cooperatively stop a running colleague flight (re-vendored from colleague).

### Changed

- README: correct the License section from MIT to Apache 2.0 to match the
  `LICENSE` file.

## [0.3.1] - 2026-06-13

### Changed

- CLAUDE.md: add a convention to reach for the `ask-colleague` skill reflexively
  for explore/review/write/grade — read-only `review`/`explore` are always safe;
  side-effecting `write` needs the user's go-ahead.

## [0.3.0] - 2026-06-13

### Added

- AGENTS.colleague.md resident prompt file (backend colleague <-> AGENTS.colleague.md)

### Changed

- Promote agent identity to a colleague resident: culture.yaml backend
  claude -> colleague with a pinned model. The `doctor` backend-consistency
  map gains `colleague` -> AGENTS.colleague.md.

## [0.2.1] - 2026-06-12

### Changed

- **Re-vendored the `ask-colleague` skill from colleague (now 1.7.0, up from the
  0.39.2 sync)** — the wrapper had drifted multiple releases behind origin. Picks
  up the `clean` verb (reap stale/corrupt `colleague/*` branches + orphaned
  `.colleague/` artifacts a crashed run left behind), the `--json` flag on every
  verb (result JSON on stdout, diagnostics/digest on stderr), the
  `_colleague_via_uv` local-dev resolution that honors `--repo`, and the
  tri-state (0/1/2) exit-code contract. `scripts/ask-colleague.sh` + `prompts/`
  are byte-identical to the origin; `SKILL.md` diverges only in the one
  consumer-identifying Provenance clause (`evidence-cli vendors from
  guildmaster`). `docs/skill-sources.md` sync row updated to
  `2026-06-12 (colleague 1.7.0, direct)`. Refs: colleague#183, #186.

## [0.2.0] - 2026-06-06

### Added

- **`ask-colleague` skill** (`.claude/skills/ask-colleague/`) — the first-party front door to the `colleague` CLI (the renamed `convertible`). On top of `explore` / `review` / `write` it adds a `feedback` verb (grade a finished work item — the ROI loop), and `write` now **previews by default** in a throwaway worktree (no side effects) unless `--apply` / `--pr` is given. Reach for it reflexively — `review` for a diverse second opinion on a committed diff before opening a PR, `explore` for a fresh read of an unfamiliar area.

### Changed

- **Replaced the `outsource` skill with `ask-colleague`.** `outsource` was renamed to `ask-colleague` upstream ([colleague#148](https://github.com/agentculture/colleague/pull/148)). Because guildmaster has not re-broadcast the rename yet (its kit still ships the old `outsource`), `ask-colleague` is vendored **directly from the sibling `colleague` checkout** rather than from guildmaster — a tracked local divergence recorded in `docs/skill-sources.md`, parallel to the `agex` → `devex` one. Vendored verbatim except one consumer-identifying clause in the Provenance paragraph.
- **Ledger + CLAUDE.md + `.gitignore`:** point `docs/skill-sources.md` and the CLAUDE.md Skills section at `colleague` / `ask-colleague`, swap the *optional* runtime prerequisite `convertible` → `colleague` (env prefix `CONVERTIBLE_*` → `COLLEAGUE_*`, with the legacy names kept as a deprecated fallback), and gitignore the `.colleague/` run-artifact dir the skill writes (plus the stale `.agex/`).

## [0.1.4] - 2026-05-31

### Added

- **Vendor the `outsource` skill** (`.claude/skills/outsource/`) from
  guildmaster's canonical copy (origin
  [`agentculture/convertible`](https://github.com/agentculture/convertible),
  re-broadcast via guildmaster — guildmaster
  [#51](https://github.com/agentculture/guildmaster/pull/51)). Every agent
  cloned from this template now inherits the ability to hand a scoped task to a
  *different* engine/mind: `explore` (read-only investigation), `review` (a
  diverse second opinion on the committed diff), and `write` (delegate a small
  implementation). `explore`/`review` run isolated in a throwaway `git worktree`;
  `write` refuses a dirty tree. Fulfils
  [#8](https://github.com/agentculture/evidence-cli/issues/8).
- **Ledger + CLAUDE.md:** record `outsource` in `docs/skill-sources.md`
  (origin = convertible, re-broadcast via guildmaster; vendored verbatim — it
  already carries `type: command`) and document its *optional* runtime
  dependency on the `convertible` CLI (the skill exits with an install hint if
  absent, so a clone that never uses it is unaffected).

### Changed

### Fixed

## [0.1.3] - 2026-05-31

### Changed

- Expanded the clone-and-rename instructions in `CLAUDE.md`: added `README.md` to
  the rename targets and a portable `git grep` discovery command so a cloner can
  find every occurrence of the template name (hard-coded in ~100 places across the
  package, including the CLI command files and `_ISSUES_URL` in
  `evidence/cli/__init__.py`) rather than renaming by hand.
- Synced `README.md`'s "Make it your own" checklist with `CLAUDE.md`: it now lists
  `README.md` itself as a rename target and points to `CLAUDE.md`'s discovery
  command as the authoritative procedure, so the two onboarding checklists no
  longer drift.

## [0.1.2] - 2026-05-30

### Changed

- Renamed the PR-lifecycle CLI references `agex` / `agex-cli` to `devex` (same
  tool, new name) across `CLAUDE.md`, `docs/skill-sources.md`, `.gitignore`, and
  the vendored `cicd`, `assign-to-workforce`, and `communicate` skills — the
  `cicd` scripts now invoke `devex pr`.
- Logged the vendored-skill in-place patch as a local divergence in
  `docs/skill-sources.md`; the matching canonical rename is tracked upstream for
  guildmaster in
  [agentculture/guildmaster#48](https://github.com/agentculture/guildmaster/issues/48)
  so a future re-sync reconciles cleanly.
- Aligned the documented `devex` version floor to `>=0.21` across the vendored
  `cicd` `SKILL.md` and `workflow.sh` install hint (were `>=0.1`), matching
  `docs/skill-sources.md` and the `await`-era feature set; flagged upstream on
  guildmaster#48.

### Fixed

- SonarCloud now reports code coverage — added `relative_files = true` to
  `[tool.coverage.run]` so `coverage.xml` emits repo-relative paths that map to
  `sonar.sources=evidence` (absolute / `.venv` paths were dropped
  as unmappable). Mirrors the sibling `convertible` setup.

## [0.1.1] - 2026-05-26

### Changed

- **CI gates on the SonarCloud quality gate**
  ([issue #3](https://github.com/agentculture/evidence-cli/issues/3)) —
  added `sonar.qualitygate.wait=true` to `sonar-project.properties` so a failing
  gate fails the `test` job when `SONAR_TOKEN` is set. Token-less repos and fork
  PRs remain green (the scan step is guarded by `if: env.SONAR_TOKEN != ''`).

## [0.1.0] - 2026-05-26

### Added

- **Onboarded into the AgentCulture mesh** ([issue #1](https://github.com/agentculture/evidence-cli/issues/1)).
- **Agent-first CLI** cited from teken's (`afi-cli`) `python-cli` reference
  (`teken cli cite`) — verbs `whoami`, `learn`, `explain`, `overview`, `doctor`,
  and the `cli` noun group. Runtime is self-contained (`dependencies = []`);
  `teken>=0.8` is a dev dependency only. Passes the seven-bundle agent-first
  rubric (`teken cli doctor . --strict`). `doctor` checks the agent-identity
  invariants (prompt-file-present, backend-consistency, skills-present).
- **Mesh identity**: `culture.yaml` (`suffix: evidence-cli`,
  `backend: claude`) and the matching `CLAUDE.md` prompt file.
- **Canonical guildmaster skill kit** (11 skills) vendored under
  `.claude/skills/` (cite-don't-import): `agent-config`, `assign-to-workforce`,
  `cicd`, `communicate`, `doc-test-alignment`, `pypi-maintainer`, `run-tests`,
  `sonarclaude`, `spec-to-plan`, `think`, `version-bump`. Every `SKILL.md`
  carries `type: command` (load-bearing for the culture/claude backend);
  `cicd` / `communicate` consumer-identifying prose adapted, all script bodies
  verbatim. Provenance in `docs/skill-sources.md`. Three skills (`think`,
  `spec-to-plan`, `assign-to-workforce`) originate in `devague`, re-broadcast
  via guildmaster.
- **Build + deploy baseline**: `pyproject.toml` (hatchling), `tests/` (pytest,
  xdist, coverage), `.github/workflows/{tests,publish}.yml` (CI rubric/lint gate,
  PyPI Trusted Publishing), `.flake8`, `.markdownlint-cli2.yaml`,
  `sonar-project.properties`, and `.claude/skills.local.yaml.example`.

### Changed

### Fixed
