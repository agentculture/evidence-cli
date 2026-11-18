"""Answer check library: grade an answer text against a task's expected values.

Nothing here reads an export or calls a model; it is a pure function of two
inputs and uses only the standard library and ``evidence``.

Expected values (JSON object, ``schema_version`` 1; the schema ships as
``evidence/data/expected_values.schema.json``)::

    {
      "schema_version": 1,              # required, must equal SCHEMA_VERSION
      "must_appear":     [item, ...],   # every one must be in the answer
      "must_not_appear": [item, ...],   # none may be in the answer
      "one_of": [[item, ...], ...]      # per group, at least one must appear
    }                                   # the three lists are optional

    item = {"text": str,                # non-empty
            "kind": "number" | "identifier" | "text",
            "fold_case": bool}          # optional, "text" items only

Any other key, at any level, is refused. Matching, after
``evidence.accuracy.matcher.normalise`` has collapsed whitespace in the answer:

* ``text``: substring; ``fold_case`` compares case-insensitively.
* ``number`` (``-?digits`` with optional ``.``/``,`` groups): a whole token, so
  ``9`` is not in ``19``, ``0.5`` not in ``10.5``, ``1.2`` and ``2.3`` not in
  ``1.2.3``. Currency signs, ``%``, brackets, commas and a sentence-ending
  full stop may touch it. ``5`` does not match inside ``-5``. ASCII digits only.
* ``identifier`` (no whitespace; dots, underscores, dashes, slashes allowed): a
  whole token, so ``check_quote`` is not in ``check_quote_all`` and
  ``lib/facts.ts`` is not in ``src/lib/facts.ts`` or ``lib/facts.ts.bak``.

``grade(answer_text, expected)`` returns a JSON-serialisable dict:

* ``verdict``: ``"matches"``, ``"does_not_match"`` or ``"cannot_tell"``
* ``schema_version``: the schema version graded under
* ``found``: items (as given) that were required and present, plus, for each
  satisfied group, the alternative that was found
* ``missing``: required items absent, and for an unsatisfied group
  ``{"one_of": [items]}``
* ``forbidden_present``: ``must_not_appear`` items that are in the answer
* ``cause``: ``None``, or for ``cannot_tell`` ``"empty_answer"`` or
  ``"no_expected_items"``

``cannot_tell`` happens only for an empty (blank) answer or expected values
naming no item; its three lists are empty. Invalid expected values raise
``ExpectedValuesError`` (a ``ValueError``) whose message is the reason.
``load_expected(data)`` validates without grading.
"""

from evidence.answer.grade import grade
from evidence.answer.schema import SCHEMA_VERSION, ExpectedValuesError, load_expected

__all__ = ["SCHEMA_VERSION", "ExpectedValuesError", "grade", "load_expected"]
