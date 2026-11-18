"""Replays of the recorded 2026-11-17 failures through the Python re-check.

Ported from associate's ``tests/test_accuracy_replays.py`` at commit 266dad3,
with ``tests/fixtures/accuracy/`` copied byte for byte. The fixtures are trimmed
copies of the pre-change exports of the runs scope20-cortex-t1,
scope20-worker-t2, scope20-worker-t3 and scope20-worker-t5; the senses case
(t20 run A2) has no recorded walk and its fixture is rebuilt from associate's
``docs/notes/t20-live-acceptance.md`` and says so. This file replays the four
that reach the checker through ``evidence.accuracy.check``, holds the
portability scan for every fixture, and checks by checksum that the replays
leave every fixture file unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evidence.accuracy.check import check_handback, load_default_settings

ACCURACY, _ = load_default_settings()
FIXTURES_ROOT = Path(__file__).parent / "fixtures"
FIXTURES = FIXTURES_ROOT / "accuracy"

#: associate/contract/policy.json ``redaction.patterns`` at associate commit 266dad3.
REDACTION_PATTERNS = [
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}",
    r"(?i)\b(api[_-]?key|apikey|secret|password|passwd|token)\b\s*[:=]\s*\S+",
    r"\bsk-[A-Za-z0-9]{16,}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
]

#: sha256 of every file under tests/fixtures/, as copied from associate at 266dad3.
FIXTURE_SHA256 = {
    "accuracy/final_message_w999.json": (
        "8cf19beeaf447f27454b6f5eda8ecea76c8cb247f4fe37e85cadc6f6683c7998"
    ),
    "accuracy/finish_summary_pyproject.json": (
        "19113039399c222c2c233b640ee8a700af0a9b97327ad24803348ec7f6463a81"
    ),
    "accuracy/no_purpose_calls.json": (
        "292be826b0d893790f8ea0d17dd203484ee2e4fcd84fa25be4b085c58ee127d0"
    ),
    "accuracy/prior_run_ids.json": (
        "5b74e4b99bb11d5e0d34cd23488968ef722af736a825830ce87a57c958c7ee80"
    ),
    "accuracy/quote_absent_example_markers.json": (
        "4a9341799793f2d893a86b91b2f1f9b675756de34f75e821a1aeea1fbdc796c8"
    ),
    "accuracy/senses_remember_success.json": (
        "168dbc43762f9a4149d7cac12d4c57f7bc86681a3f02935a221540730f059d19"
    ),
}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_data(entries: list[dict]) -> dict:
    """Entries as the checker reads them; the saved text of each is its inline content."""
    return {
        "entries": [{**e, "ts": "2026-11-17T00:00:00Z", "truncated": False} for e in entries],
        "results": {e["id"]: e["result"]["content"] for e in entries},
    }


def verdicts(got: dict) -> dict:
    return {f["id"]: f for f in got["facts"]}


def test_replay_quote_absent_on_w3_and_w7():
    fx = fixture("quote_absent_example_markers.json")
    got = check_handback(
        {"payload": {"facts": [*fx["facts"], fx["control_fact"]]}, **run_data(fx["entries"])},
        ACCURACY,
    )
    by_id = verdicts(got)
    for fact_id in ("f1", "f2"):
        assert by_id[fact_id]["verdict"] == "refused"
        assert by_id[fact_id]["reason"] == "quote_absent"
        assert by_id[fact_id]["nearest"] is not None
    assert by_id["f3"]["verdict"] == "passed"
    assert got["accepted"] is False


def test_replay_prior_run_id_cited_bare_in_a_continued_run():
    fx = fixture("prior_run_ids.json")
    current = run_data(fx["current_entries"])
    prior = {"prior": run_data(fx["prior_entries"])}
    bare = check_handback(
        {"payload": {"facts": [fx["fact"]]}, **current, "prior_runs": prior}, ACCURACY
    )
    assert bare["facts"][0]["verdict"] == "refused"
    assert bare["facts"][0]["reason"] == "quote_absent"
    assert any(
        "ambiguous_reference" in flag["detail"] and flag.get("ref") == "w10"
        for flag in bare["report"]["flags"]
    ), bare["report"]["flags"]
    labelled = check_handback(
        {
            "payload": {"facts": [{**fx["fact"], "source": "prior:w10"}]},
            **current,
            "prior_runs": prior,
        },
        ACCURACY,
    )
    assert labelled["facts"][0]["verdict"] == "passed"
    assert labelled["facts"][0]["run"] == "prior"


def test_replay_pyproject_sentence_as_a_fact_is_refused():
    fx = fixture("finish_summary_pyproject.json")
    assert fx["pyproject_sentence"] in fx["summary"]
    got = check_handback(
        {"payload": {"summary": fx["summary"], "facts": [fx["fact"]]}, **run_data(fx["entries"])},
        ACCURACY,
    )
    assert got["facts"][0]["verdict"] == "refused"
    assert got["facts"][0]["reason"] == "quote_absent"


def test_replay_senses_remember_success_without_the_call():
    fx = fixture("senses_remember_success.json")
    assert fx["kind"] == "rebuilt-from-note"
    assert fx["_origin"].startswith("REBUILT FROM A NOTE")
    assert not any(e["tool"] == "eidetic_remember" for e in fx["entries"])
    got = check_handback({"payload": {"facts": fx["facts"]}, **run_data(fx["entries"])}, ACCURACY)
    wrong_tool, unknown = got["facts"]
    assert (wrong_tool["verdict"], wrong_tool["reason"]) == ("refused", "action_wrong_tool")
    assert (unknown["verdict"], unknown["reason"]) == ("refused", "source_unknown")
    assert got["accepted"] is False


def test_every_fixture_is_free_of_home_and_temp_paths_and_secrets():
    patterns = [re.compile(p) for p in REDACTION_PATTERNS]
    names = sorted(p.name for p in FIXTURES.glob("*.json"))
    assert len(names) >= 6, names
    for name in names:
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert "/home/" not in text, f"{name} holds /home/"
        assert "/tmp/" not in text, f"{name} holds /tmp/"
        for pattern in patterns:
            assert not pattern.search(text), f"{name} matches redaction pattern {pattern.pattern}"
        doc = json.loads(text)
        assert doc["kind"] in ("recorded", "rebuilt-from-note"), name
        assert doc["_origin"], name


def test_the_rebuilt_fixture_is_the_only_one_not_from_a_recorded_run():
    kinds = {
        p.name: json.loads(p.read_text(encoding="utf-8"))["kind"] for p in FIXTURES.glob("*.json")
    }
    assert [n for n, k in kinds.items() if k != "recorded"] == ["senses_remember_success.json"]


# --- the fixtures are read, never written ------------------------------------------------


def _fixture_checksums() -> dict[str, str]:
    return {
        p.relative_to(FIXTURES_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(FIXTURES_ROOT.rglob("*"))
        if p.is_file()
    }


def test_the_replays_leave_every_fixture_file_unchanged():
    """Checksums before and after running every replay match the committed table.

    The committed table also catches a change made by any other test in an
    earlier run, since a changed file would no longer match it.
    """
    assert _fixture_checksums() == FIXTURE_SHA256
    test_replay_quote_absent_on_w3_and_w7()
    test_replay_prior_run_id_cited_bare_in_a_continued_run()
    test_replay_pyproject_sentence_as_a_fact_is_refused()
    test_replay_senses_remember_success_without_the_call()
    test_every_fixture_is_free_of_home_and_temp_paths_and_secrets()
    test_the_rebuilt_fixture_is_the_only_one_not_from_a_recorded_run()
    assert _fixture_checksums() == FIXTURE_SHA256
