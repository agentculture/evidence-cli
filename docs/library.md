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
