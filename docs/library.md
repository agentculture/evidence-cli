# Public library names

These are the names other packages may import from `evidence`. associate is
planned to import the eight functions marked in the last column (see the
[groundwork spec][spec], a branch link that will move). associate does not
import this package yet.

**Changing the signature or behaviour of a listed name, or removing or renaming
it, is a breaking release.** Add a name here (and in the test that imports it)
in the same change that makes it public. Everything not listed is internal, even
if it has no leading underscore.

`tests/test_public_names.py` reads the table below and imports every row, so a
listed name that does not exist fails the test suite. Standard library only: no
listed name needs a third-party package.

## Run check: `evidence.accuracy`

| Module | Name | What it is | Used by associate |
|--------|------|------------|-------------------|
| `evidence.accuracy.matcher` | `check_quote` | Check a quote (and optional literal) against saved result text. | yes |
| `evidence.accuracy.matcher` | `normalise` | The whitespace and read-stamp normalisation the matcher applies. | no |
| `evidence.accuracy.check` | `parse_source_ref` | Parse a fact's source reference (`wN`, `prior:wN`, `cN:wN`). | yes |
| `evidence.accuracy.check` | `check_handback` | Check one hand-back against its walk entries and saved results. | yes |
| `evidence.accuracy.check` | `load_export` | Read an export directory: walk entries, saved results, facts payload. | yes |
| `evidence.accuracy.check` | `load_handback_input` | Everything `check_handback` reads for one run, with prior run and children. | yes |
| `evidence.accuracy.check` | `inspect_export` | What the run check reports for one export directory. | yes |
| `evidence.accuracy.check` | `accuracy_result` | The result fields of a harness run, read after the model stopped. | yes |
| `evidence.accuracy.check` | `load_default_settings` | The bundled default settings and their version. | no |
| `evidence.accuracy.check` | `SUPPORTED_WALK_FORMATS` | The walk format versions this checker reads. | no |
| `evidence.accuracy.check` | `ExportError` | Raised when an export directory cannot be read. | no |
| `evidence.accuracy.counts` | `fact_counts` | Tally checked facts into made, checked, passed, refused, unchecked. | yes |
| `evidence.accuracy.counts` | `counts_by_source_kind` | The same tally split by source kind. | no |
| `evidence.accuracy.counts` | `conclusion_counts` | Tally conclusion verdicts. | no |
| `evidence.accuracy.counts` | `count_fact` | Add one fact verdict to a tally. | no |
| `evidence.accuracy.vectors` | `load_matcher_vectors` | The shared matcher vectors shipped in the package. | no |

A passed fact means its quote was found in the saved result it cites. It does
not mean the value is true.

## Strict re-check: `evidence.accuracy`

A second, independent implementation of associate's strict facts check
(`lib/strict.ts` in associate), kept in agreement with it through the shared
cases in `evidence/data/strict_vectors.json`, a byte copy of associate's
`associate/contract/strict_vectors.json`. It never asks a decider: the
decider's stored answers are an input. associate is expected to import the four
names marked in the last column for strict: `strict_recheck` and
`load_strict_vectors` to run the shared cases from its Python tests,
`is_strict_export` and `recheck_strict_export` to re-check a strict run's
export.

| Module | Name | What it is | Used by associate |
|--------|------|------------|-------------------|
| `evidence.accuracy.strict` | `strict_recheck` | Re-check one strict hand-back from a case input; returns the shape of a case's `expect`. | yes |
| `evidence.accuracy.strict` | `KINDS` | The kinds a fact may state: `direct`, `llm`, `derived`. | no |
| `evidence.accuracy.strict` | `OUTCOMES` | The strict outcomes, in the order the counts are written. | no |
| `evidence.accuracy.strict_export` | `is_strict_export` | Whether an export's `check.json` says `"mode": "strict"`. | yes |
| `evidence.accuracy.strict_export` | `recheck_strict_export` | Re-check a stored strict export and compare it with the export's own `check.json`. | yes |
| `evidence.accuracy.strict_export` | `strict_export_input` | The strict re-check's input, rebuilt from a stored strict export. | no |
| `evidence.accuracy.strict_export` | `strict_settings` | The contract values and redaction filter the strict re-check reads from given settings. | no |
| `evidence.accuracy.strict_export` | `load_strict_defaults` | The bundled default strict contract values (`evidence/data/strict_defaults.json`). | no |
| `evidence.accuracy.strict_export` | `compare_with_record` | Compare a re-check with an export's `check.json`, part by part. | no |
| `evidence.accuracy.command` | `compile_redaction` | Compile a redaction filter's patterns; a pattern Python cannot compile raises `ValueError` naming it. | no |
| `evidence.accuracy.vectors` | `load_strict_vectors` | The shared strict cases shipped in the package. | yes |

Settings: `strict_settings` uses the caller's `strict` block whenever it is
well formed (`keep_marked` and `drop` are lists), whatever else the settings
hold, and otherwise the bundled defaults; the result's `strict_source` says
which. The support pass list (`support_passes`, or `support_score.passes`) is
not required and is not read by the re-check: a support answer named in no
strict list passes. A redaction pattern Python cannot compile is an
`ExportError` naming it.

`strict_recheck` also accepts `decider_by_position` in its input (one stored
answer or null per fact, in hand-back order); an entry there is used in place of
the answer keyed by fact id, so two facts sharing an id keep their own answers.
`recheck_strict_export` fills it when `check.json`'s fact records line up with
the payload's facts, and falls back to ids otherwise. The shared cases do not
use it.

`recheck_strict_export` compares, per fact, the kind checked, outcome and drop
reason; per verdict and open item, the id, outcome, reason, strict outcome and
strict reason; `accepted`; and the `strict` object's `counts`, `drop_reasons`
and `judge_counts`. The result names the parts compared and those the record
does not hold (`compared`, `not_compared`). A malformed fact record in
`check.json` (not an object, or no string `id`) is an `ExportError`.

`evidence.accuracy.check.inspect_export` and `accuracy_result` route an export
whose `check.json` says strict to the strict re-check, and their result then
carries `check: "strict"`; any other export gives the result it gave before.

A fact with outcome `pass` had its evidence copied from a saved result, or its
quote found in one; a judged fact carries the decider's stored answer. Neither
means the value is true, and no count here is a measure of correctness.

## Answer check: `evidence.answer`

| Module | Name | What it is | Used by associate |
|--------|------|------------|-------------------|
| `evidence.answer` | `grade` | Grade an answer text against expected values. | no |
| `evidence.answer` | `load_expected` | Validate expected values without grading. | no |
| `evidence.answer` | `ExpectedValuesError` | Raised (a `ValueError`) when expected values are invalid. | no |
| `evidence.answer` | `SCHEMA_VERSION` | The expected-values schema version. | no |

The answer check is a match against recorded expected values. It is separate
from the run check and is never folded into its counts.

[spec]: https://github.com/agentculture/associate/blob/clef/accuracy/docs/specs/2026-11-18-associate-graded-measurement-groundwork.md
