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
(`lib/strict.ts` in associate), kept in agreement with it through the 64 shared
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
| `evidence.accuracy.strict_export` | `not_applicable_result` | The result for a strict export where facts do not apply. | no |
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
`recheck_strict_export` fills it from the pairing described below whenever the
fact records can be paired with the payload's facts. The shared cases do not
use it.

`recheck_strict_export` compares, per fact, the kind checked, outcome and drop
reason; per verdict and open item, the id, outcome, reason, strict outcome and
strict reason; `accepted`; and the `strict` object's `counts`, `drop_reasons`
and `judge_counts`. The result names the parts compared and those the record
does not hold (`compared`, `not_compared`). A malformed fact record in
`check.json` (not an object, or no string `id`) is an `ExportError`.

Fact records are paired with the payload's facts once, and that pairing
serves both the stored answers and the comparison: by position when the
records line up with the payload's facts (same number, same id at each
position); else by id when no id is repeated among the payload's facts or
among the records; else not at all. A fact whose id no record has is the fact
without a record, wherever it stands. When the facts cannot be paired, no
stored answer is used and the `facts` part is not compared.

What is a disagreement, and what `agrees` says:

- A part the record does not hold is named in `not_compared` and gives no
  disagreement row. `comparison.not_compared_reasons` gives the reason per
  part: `absent from check.json`, `the fact records cannot be paired with the
  payload's facts`, or `a fact has no record in check.json, so the decider's
  stored answers are incomplete`.
- The decider's stored answers are in the fact records. When any payload fact
  has no record (the `facts` part is absent, cannot be paired, or lists fewer
  facts), every part that follows from the outcomes (`verdicts`, `open_items`,
  `counts`, `drop_reasons`, `judge_counts`) is named in `not_compared` too,
  whether or not the record holds it. `accepted` is the checker's verdict and
  is still compared.
- A row is a disagreement only when the recorded and the re-checked value
  differ. A fact with no record gives no field rows, and its row in
  `comparison.facts` has `agrees: null`. It is reported once, by the `facts`
  row: `recorded` and `recheck` are the two counts, `without_record` lists the
  fact ids with no record and `not_in_payload` the record ids of no fact. When
  the counts are equal and the ids differ, the row's field is `facts.ids` and
  it holds the two id lists. `comparison.facts_without_record` lists the same
  fact ids.
- `comparison.agrees` has three states. `false`: there is a disagreement row.
  `true`: there is none and the `facts` part was compared with a record for
  every payload fact. `null` otherwise, with `comparison.agrees_reason` naming
  what was not compared (`nothing in check.json could be compared`, or
  `not compared:` followed by the parts). `null` is not agreement: test
  `agrees is True`.
- `comparison.incomplete` is true when a part was not compared or a payload
  fact has no record. `evidence check` then writes one reviewer flag,
  `strict_record_incomplete`, naming the parts or fact ids, prints it, and
  counts the run in `sums.strict_not_compared`. A key that is not one of the
  seven parts (`strict.returned_before`, say) does not make a record
  incomplete.

Whether facts apply is decided in one place for `recheck_strict_export` and
`inspect_export`: a walk format that is not supported (or a format marker
whose version is not a positive integer), a walk with no format marker, or no
`facts.json` is not applicable, with the same `not_applicable_reason` from
both. `recheck_strict_export` then returns `applicable: false`, with `recheck`,
`accepted` and `rounds_left` null and a `comparison` holding no rows and
`agrees: null` (its `agrees_reason` is the same reason); for an unsupported
format it adds `unsupported: true`, as `inspect_export` does, and reads
nothing but the walk's format and `check.json`. Otherwise `applicable` is true
and `not_applicable_reason` null. **`recheck` was always an object in 0.8.0:
test `applicable` before indexing it.** A malformed fact record is an
`ExportError` whether or not facts apply.

`returned_before`: when `check.json` holds `strict.returned_before` (the fact
ids returned in earlier rounds, a list of strings), the re-check uses it,
decides `keep_marked` against `returned` itself and can disagree with the
record on it; the result's `returned_before_source` is `check.json`. An export
written before the key existed, or one where the value is not a list of
strings, is read as before: the facts recorded as `keep_marked` while a round
was left are taken as returned before, the re-check cannot disagree with the
record on that one point, and `returned_before_source` is
`inferred from keep_marked`.

`evidence.accuracy.check.inspect_export` and `accuracy_result` route an export
whose `check.json` says strict to the strict re-check, and their result then
carries `check: "strict"`; any other export gives the result it gave before.

`accuracy_result(export_dir, settings, with_strict=True)` adds one key to its
result, `strict`: what `recheck_strict_export` returns for the same export
(with no checkout root), taken from the one re-check the call already ran,
the not applicable result included (`applicable: false`, the reason, `recheck`
null). Where `recheck_strict_export` would raise an `ExportError`, the key
holds that same not applicable shape with the error as the reason. It is
`None` only for an export that is not strict. Without the argument the result has no `strict` key, as before. A caller that
needs paths in the printed command made relative to a checkout calls
`recheck_strict_export` with `checkout_root` instead.

`load_export` and `load_handback_input` return, beside `results` (walk id to the
text of the file the entry names), `result_files` (file name to text): the file
each entry names in `saved_result` and `results/<the entry's own id>.txt`, both
read only inside the export directory. The strict re-check of an export reads
these, because a pointer reads the file the entry names and an old-shape fact
the file under the entry's own id. No other file name is ever opened: an entry
whose id is not `wN` has no file of its own.

### The rules

The rules are associate's `docs/notes/strict-vectors.md`, which is written to
be enough without reading the TypeScript. Points this implementation once had
to take from the TypeScript, now stated there and followed here:

- In the printed command, an object key of the arguments gets the redaction
  filter only: a path in a key is not made relative and a home path in it is
  not shortened. The tool name gets the home rewrite and the redaction filter.
- A checkout path or home path may start anywhere in a string, and a backtick
  ends a path segment just as a slash, whitespace or a quote does.
- `min_quote_length` is usable only when it is a whole number of 1 or more.
  Anything else (absent, `0`, a fraction, a string, `true`) is a broken
  contract and every fact fails as `quote_short`. `True` is an `int` in Python
  and is not counted as 1.
- A pointer reads the file its walk entry names in `saved_result`; an old-shape
  fact, the action check and the `delegate_status` rule read
  `results/<the entry's own id>.txt`.
- `returned_before` is read only for a support answer named in `keep_marked`;
  an id in it that no fact has is ignored.

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
