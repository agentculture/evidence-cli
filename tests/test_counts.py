"""Counts over checked facts: a plain tally, and unchecked is never passed."""

from evidence.accuracy.counts import (
    SOURCE_KINDS,
    conclusion_counts,
    count_fact,
    counts_by_source_kind,
    empty_counts,
    fact_counts,
)

FACTS = [
    {"verdict": "passed", "source_kind": "file"},
    {"verdict": "refused", "source_kind": "file"},
    {"verdict": "unchecked", "source_kind": "tool"},
    {"verdict": "passed"},
]


def test_count_fact_never_adds_unchecked_to_passed():
    counts = empty_counts()
    for verdict in ("passed", "unchecked", "refused", "unchecked"):
        count_fact(counts, verdict)
    assert counts == {"made": 4, "checked": 2, "passed": 1, "refused": 1, "unchecked": 2}


def test_fact_counts_cover_every_fact_even_without_a_source_kind():
    assert fact_counts(FACTS) == {
        "made": 4,
        "checked": 3,
        "passed": 2,
        "refused": 1,
        "unchecked": 1,
    }


def test_counts_by_source_kind_leave_a_fact_with_no_kind_out_of_every_row():
    rows = counts_by_source_kind(FACTS)
    assert set(rows) == set(SOURCE_KINDS)
    assert rows["file"] == {"made": 2, "checked": 2, "passed": 1, "refused": 1, "unchecked": 0}
    assert rows["tool"] == {"made": 1, "checked": 0, "passed": 0, "refused": 0, "unchecked": 1}
    assert rows["web"] == empty_counts()


def test_an_unknown_verdict_is_made_but_in_no_other_count():
    counts = fact_counts([{"verdict": "weird"}, {}])
    assert counts == {"made": 2, "checked": 0, "passed": 0, "refused": 0, "unchecked": 0}


def test_conclusion_counts_fold_every_other_value_into_open():
    got = conclusion_counts(["supported", "refuted", "open", "cannot_tell", "supported"])
    assert got == {"made": 5, "supported": 2, "refuted": 1, "open": 2}
