# evidence-cli run check and answer check

> evidence-cli reads a finished associate run from its export: it re-checks every fact against the saved results, counts them, writes reviewer flags beside the run, and, as a separately named result, says whether the run's answer matches recorded expected values; associate imports it for its own re-check

## Audience

- associate, which imports the re-check as a library and calls the answer check from its measurement runner; an operator or reviewer checking one export or many from the command line
  - instruction: The library surface is what associate imports; the commands are what a person runs.

## Before → After

- Before: evidence-cli is the template scaffold with no domain code; the only re-check of an associate run lives inside associate, and nothing anywhere marks a run's answer right or wrong
- After: evidence check reads one export or many and prints counts per run and summed, each disagreement with the harness's own counts, and reviewer flags, and writes the flags to a file beside the run without touching the run's files; evidence grade takes an answer text and a task's expected values and returns matches, does not match or cannot tell, citing the rule that decided; the same code is importable, and associate uses it in place of its own

## Why it matters

- one place holds the check, so associate gets leaner and every consumer gets the same fixes; and it gives the planned comparison a grader that is not the harness under test

## Requirements

- the matcher, the checker, the counts, the export loader and the run-result summary move from associate/accuracy into evidence-cli with their tests, keeping function names and results; the public names are listed in the documentation and a change to any of them is a breaking release
  - instruction: Source: associate/accuracy at associate main 266dad3. Do not import associate from evidence-cli.
  - honesty: every function associate imports today exists under the documented name and returns the same result on the saved test exports
- the checker's settings (source kinds, the reason-to-check mapping, the minimum quote length) are an explicit input; the command accepts a settings file and otherwise uses a bundled default that it names in its output
  - honesty: running evidence check with no settings file prints which default settings it used and their version
- evidence check reports, per run and summed, the counts by kind and by source kind, and lists each place its own re-check disagrees with the counts the harness wrote; a run with no facts is reported as not applicable, not as zero
  - honesty: on a fixture whose report.json was edited to a wrong count, the command names that count as a disagreement
- reviewer flags are written to a file beside the run, in a location the run did not write, and no file of the export is modified or created inside it
  - honesty: a checksum of every file under the export directory is unchanged after the command
- evidence grade takes the answer text as an explicit input, with the task's expected values, and returns matches, does not match or cannot tell, with the expected items found and missing; it never reads the facts list to decide, and calls no model
  - honesty: the result is unchanged when the export's facts.json is absent, and a grade is reproduced exactly on a second run
- expected values are data with a schema and a version: items that must appear, items that must not, and alternatives, compared after the same normalisation the matcher uses; a result names the schema version it was graded under
  - honesty: two results are reported as comparable only when their schema versions are equal, and a task file with an unknown key is refused
- the words printed keep the two results apart: the run check is described as counts of checked quotes and backed conclusions, the answer check as a match against recorded expected values, and neither as quality, correctness of the work, or accuracy; each output carries the line that a complete trail does not mean the work is correct
  - honesty: a test fails if either command's output contains the words quality score or accuracy
- the shared test vectors ship inside the evidence-cli package, so associate can compare its own copy with the installed one
  - honesty: associate's copy and the packaged copy are compared by a test in associate and are equal at the pinned versions
- CLAUDE.md is re-initialised from its seed into a real project file that states the two results, the public library names and the no-dependency rule
  - honesty: the file no longer contains the seed's re-init instruction
- the run check states which export formats it supports; an export with a newer format than it knows is reported as unsupported with the version it found, never checked with older rules
  - honesty: a fixture whose format marker says a version above the supported one produces an unsupported result and no counts
- an expected item that is a number or an identifier matches only as a whole token, so 9 does not match 19 and 0.5 does not match 10.5; free-text items match after whitespace is collapsed, with case kept or folded as the item says
  - honesty: for each fixture task, an answer holding a longer number that contains the expected one is graded as not matching
- cannot tell is returned only for stated causes (an empty answer text, or expected values that name no item), each named in the result; an answer that simply lacks an expected item is does not match
  - honesty: an empty answer gives cannot tell with its cause, and an answer missing one required item gives does not match
- when the flags file cannot be written the command says so and exits with an error code, and an option sends the file to a named directory or suppresses writing; the printed report is the same either way
  - honesty: run on a read-only location, the command exits non-zero with a remediation line and still prints the counts

## Honesty conditions

- both commands exist and associate's suite passes importing them
- associate's test suite passes using only names this spec lists as public
- git ls-files evidence at origin/main lists only scaffold modules
- both commands run on the committed fixture exports and their output is identical on a second run
- associate's groundwork spec names evidence-cli as its grader and re-check
- each of the five checks is a named test in the evidence-cli suite
- the package's dependencies list is empty and no module imports a network library
- no file under evidence/ imports associate, and the fixture checksums are unchanged by the test suite
- no command added here prints a final score

## Success signals

- 100% of the shared matcher and hand-back vectors pass in evidence-cli; counts over the fixture exports equal a hand count; a second run prints a byte-identical report; every file in the export is byte-identical after both commands; and for every fixture task the recorded answer is graded as matching and a hand-written wrong answer as not matching
  - instruction: Vectors: associate/contract/`matcher_vectors.json` at the pinned associate commit.

## Scope / boundaries

- no runtime dependency, no model call and no network access; the same inputs give the same output
- evidence-cli never imports associate, and never edits a run; the TypeScript checker stays in associate's extension
- this work does not build the general trail of the build brief (request, spec, plan, code, validations), its rubric or a final score, and does not settle the overlap with storybook-cli

## Non-goals

- computing the decider score, grading with a model, or grading runs of harnesses other than associate

## Assumptions

- associate keeps its associate check command as a thin wrapper over the imported code, so its output and its documented interface do not change
- evidence-cli is released to PyPI before the associate change that imports it is merged, and associate pins the released version as its floor

## Scope exploration

- `s1` — `evidence-cli tree at origin/main (git ls-files evidence tests, pyproject.toml, CLAUDE.md)`: The package is the template scaffold: evidence/cli/`_commands` holds cli, doctor, explain, learn, overview, whoami and nothing else; tests are `test_cli.py` and `test_cli_introspection.py`; version 0.6.1; dependencies = \[\] (pyproject.toml:16); requires Python 3.12 or newer; CLAUDE.md is a seed placeholder that says to re-initialise it.
- `s2` — `evidence-cli issue #1 (build brief)`: The brief's load-bearing distinction: a high evidence grade means the trail is complete and traceable, not that the work is correct; the lane is the trail around the code, never the code's correctness. It asks for a rubric that is data with a version, sub-scores that cite the artifact that justified them, a not-applicable outcome distinct from missing, and determinism or disclosed non-determinism. It names storybook-cli as an overlap to settle.
- `s3` — `evidence-cli issue #3 (first input)`: Asks to read one export or many and report counts per run and summed; re-run the quote match from the saved files and report disagreements with the harness's counts; write reviewer flags to a file beside the result; stay read-only on the run. Acceptance: counts equal a hand count on a fixture, identical report on re-run, hand-back byte-identical, and the report named for what it is.
- `s4` — `associate/accuracy/ at associate main 266dad3 (matcher.py, check.py, counts.py, 1,079 lines) and its importers`: Public functions: `check_quote` (matcher.py:56), `parse_source_ref`, `check_handback`, `load_export`, `load_handback_input`, `inspect_export`, `accuracy_result` (check.py:69,550,666,763,811,883), `fact_counts` (counts.py:32). `check_handback` takes the accuracy settings as an argument (check.py:7, 550) and reads no associate file. Importers in associate: harness/pi.py:88, harness/stub.py:21, cli/`_commands`/check.py:15-16, and six test files. The code is standard library only (check.py:5).
- `s5` — `challenge pass / upgrade-path lens: associate/accuracy/check.py:681-685, 804`: The loader reads the walk's format version and treats anything below 2 as not applicable (check.py:804); a version above 2 passes that test and would be checked with today's rules. Once the checker lives in another package than the extension that writes exports, the two can be at different versions.
  - seeds: `c26`
- `s6` — `challenge pass / unstated-assumptions lens: associate/accuracy/matcher.py:37-40`: The matcher's normalise strips read line stamps and collapses whitespace; case and punctuation stay, and matching is plain substring. That is right for a quote copied from a source, but for an answer check a short expected value such as a number would match inside a longer one. The draft said the answer check uses the same normalisation without saying this.
  - seeds: `c27`, `c28`
- `s7` — `challenge pass / failure-mode lens: evidence-cli issue #3 (flags written beside the result)`: Exports may sit in a directory the caller cannot write (another user's scratch space, a read-only mount); the draft did not say what happens then, and a silent skip would leave a reviewer believing there were no flags.
  - seeds: `c29`
- `s8` — `challenge pass / security lens: associate/accuracy/check.py load_export (lines 666-700)`: The loader opens only results/wN.txt names matched by a pattern and only when the resolved path stays inside the export directory; this behaviour and its tests move unchanged. Clean for this spec. Not examined: symlinks inside an export that point outside it.
- `s9` — `challenge pass / portability lens: associate tests/fixtures/accuracy`: A search of the six fixture files for home or temporary directory paths found none, so they can be copied into evidence-cli without tripping its portability check. Not examined: the export directories other tests build at run time.
- `s10` — `challenge pass / operations lens: release order between two repositories`: A fix to the checker now needs an evidence-cli release and then a floor bump in associate: two pull requests where there was one. Accepted by the operator's import decision; recorded so the cost is visible. Not examined: how associate's TestPyPI pre-release job resolves the dependency.

## Decisions

- the grader that marks a run's answer right or wrong lives in evidence-cli (operator, 2026-11-18)
- the answer check is a separately named result, never folded into the evidence counts or any completeness grade, and every output says which of the two it is; this keeps the build brief's distinction that a complete trail does not mean the work is correct (operator, 2026-11-18)
- the answer check and the run check are two commands of one package, evidence check and evidence grade, not a separate tool
- associate imports evidence-cli as a first-party, zero-dependency package with a version floor (operator, 2026-11-18)

## Open parks

- [unknown_nonblocking] the name and location of the flags file beside the run
- [unknown_nonblocking] whether the answer text for a run of the older harness is its final reply or its statements file; the caller supplies the text, so this is decided in associate's runner
- [follow_up] the moved Python tests were written after the code and never seen to fail (lapse l3 of the accuracy-method work); whether to add tests shown to fail when a rule is removed is not decided here
