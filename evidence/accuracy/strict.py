"""The strict re-check: a second, independent implementation of associate's strict facts check.

associate's extension checks a strict hand-back in TypeScript
(``.pi/extensions/associate/lib/strict.ts``). This module reaches the same
result from the same inputs, and both are compared against the shared cases in
``evidence/data/strict_vectors.json`` (a byte copy of associate's
``associate/contract/strict_vectors.json``). The rules are written down in
associate's ``docs/notes/strict-vectors.md``; the order of the steps is:

1. each fact on its own: the source, then the pointer (``at``) or, for an
   old-shape fact, the quote matcher, then the number rule, then direct or
   worded;
2. the ``based_on`` graph, then the cascade;
3. the shape rules, then the cascade;
4. the decider in two steps (facts that do not state ``derived``, the outcome
   policy, the cascade, then derived facts), and a last cascade;
5. the outcomes, the verdicts and open items, and the counts.

:func:`strict_recheck` is pure: it never calls the decider, the network or a
process, and never reads the environment or a file. The decider's answers are
an input (``decider``: the stored answer per judged fact id).

A passed fact means its evidence was copied from a saved result or its quote
was found in one; a judged fact carries the decider's stored answer. Neither
says the value is true, and no count here is a measure of correctness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from evidence.accuracy.check import (
    _action_refusal,
    _closing_index,
    _has_check,
    _index_entries,
    _is_first_hand,
    _is_positive_integer,
    _kind_of,
    _verdict_refusal,
    parse_source_ref,
)
from evidence.accuracy.command import render_command
from evidence.accuracy.matcher import check_quote
from evidence.accuracy.pointer import (
    SAVED_NAME,
    js_trim,
    numbers_shown,
    pointer_shape_ok,
    resolve,
)

#: The kinds a fact may state; absent or any other string reads as ``direct``.
KINDS: tuple[str, ...] = ("direct", "llm", "derived")
#: Facts per outcome, in the order the counts are written.
OUTCOMES: tuple[str, ...] = ("pass", "keep_marked", "returned", "dropped", "not_judged")

_DIRECT, _LLM, _DERIVED = KINDS
_PASS, _KEEP, _RETURNED, _DROPPED, _NOT_JUDGED = OUTCOMES
_SUPPORT = "support"
_FAILED, _UNCHECKED, _PASSED, _TO_JUDGE, _JUDGED = (
    "failed",
    "unchecked",
    "passed",
    "to_judge",
    "judged",
)
_CASCADE_REASON = "based_on_failed"
_DECIDER_DROP = "decider_drop"
_NUMBER_ABSENT = "number_absent"
_QUOTE_SHORT = "quote_short"


def _value_given(value: Any) -> bool:
    return isinstance(value, str) and js_trim(value) != ""


def _value_text(value: Any) -> str:
    """The text the number rule reads: a value that is a string and not blank, else nothing."""
    return value if _value_given(value) else ""


def _non_blank(text: Optional[str]) -> Optional[str]:
    return text if text is not None and js_trim(text) != "" else None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


@dataclass
class _Fact:
    """One fact as the re-check sees it, from its own check to its outcome."""

    raw: dict[str, Any]
    position: int
    id: str
    kind_stated: str
    based_on: list[str]
    kind_checked: Optional[str] = None
    worded: Optional[bool] = None
    status: str = _FAILED
    reason: Optional[str] = None
    refused: bool = False
    evidence: Optional[dict[str, Any]] = None
    copied: Optional[str] = None
    command: Optional[str] = None
    own_quote: Optional[str] = None
    source_kind: Optional[str] = None
    first_hand: Optional[bool] = None
    judge: Optional[dict[str, Any]] = None
    sent: Optional[dict[str, Any]] = None
    outcome: Optional[str] = None
    dropped_by: Optional[str] = None

    def fail(self, reason: str, refused: bool = True) -> None:
        self.status, self.reason = _FAILED, reason
        self.refused = self.refused or refused

    def is_root(self, decider_stage: bool) -> bool:
        """A root for the cascade: failed; from the decider step on, also unchecked or
        dropped on the decider's word. A fact already dropped by the cascade is never one."""
        if self.dropped_by is not None:
            return False
        if self.status == _FAILED:
            return True
        if not decider_stage:
            return False
        return self.status == _UNCHECKED or (self.status == _JUDGED and self.outcome == _DROPPED)


@dataclass
class _Context:
    """The case input one re-check reads."""

    walk: list[Any]
    results: Mapping[str, Any]
    prior_runs: Mapping[str, Any]
    children: list[dict[str, Any]]
    contract: Mapping[str, Any]
    strict: Mapping[str, Any]
    decider: Mapping[str, Any]
    decider_by_position: Optional[list[Any]]
    returned_before: frozenset[str]
    rounds_left: int
    checkout_root: str
    redaction: Mapping[str, Any]
    min_len: Any = 0
    facts: list[_Fact] = field(default_factory=list)
    first_by_id: dict[str, _Fact] = field(default_factory=dict)


def _new_context(case_input: Mapping[str, Any], redaction: Mapping[str, Any]) -> _Context:
    contract = _as_dict(case_input.get("contract"))
    rounds = case_input.get("rounds_left")
    return _Context(
        walk=_as_list(case_input.get("walk")),
        results=_as_dict(case_input.get("results")),
        prior_runs=_as_dict(case_input.get("prior_runs")),
        children=[c for c in _as_list(case_input.get("children")) if isinstance(c, dict)],
        contract=contract,
        strict=_as_dict(contract.get("strict")),
        decider=_as_dict(case_input.get("decider")),
        decider_by_position=(
            case_input["decider_by_position"]
            if isinstance(case_input.get("decider_by_position"), list)
            else None
        ),
        returned_before=frozenset(_str(i) for i in _as_list(case_input.get("returned_before"))),
        rounds_left=rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else 0,
        checkout_root=_str(case_input.get("checkout_root")),
        redaction=redaction,
        min_len=contract.get("min_quote_length"),
    )


# --- 1. each fact on its own ---------------------------------------------------------


def _run_for(ctx: _Context, label: Optional[str]) -> Optional[dict[str, Any]]:
    """The run a source label names, or None when no run, or more than one, carries it."""
    if label is None:
        return {"walk": ctx.walk, "results": ctx.results}
    named = [run for name, run in ctx.prior_runs.items() if name == label]
    named += [child for child in ctx.children if child.get("label") == label]
    return _as_dict(named[0]) if len(named) == 1 else None


def _text_named(run: Mapping[str, Any], name: str) -> Optional[str]:
    text = _as_dict(run.get("results")).get(name)
    return text if isinstance(text, str) else None


def _pointer_text(run: Mapping[str, Any], entry: Mapping[str, Any]) -> Optional[str]:
    """The saved result a pointer reads: the ``results/wN.txt`` its ``saved_result`` names."""
    name = entry.get("saved_result")
    if not isinstance(name, str) or not SAVED_NAME.fullmatch(name):
        return None
    return _text_named(run, name)


def _checker_text(run: Mapping[str, Any], entry: Mapping[str, Any]) -> Optional[str]:
    """The saved result the quote matcher reads: ``results/<walk id>.txt`` (the extension's
    checker keys saved results by walk id, whatever ``saved_result`` says)."""
    return _text_named(run, f"results/{entry['id']}.txt")


def _classify(fact: _Fact, evidence_text: str) -> None:
    """Step 5: direct when the trimmed value is word for word in the evidence or not given."""
    value = fact.raw.get("value")
    fact.worded = _value_given(value) and js_trim(value) not in evidence_text
    if fact.kind_stated == _DERIVED:
        fact.kind_checked, fact.status = _DERIVED, _TO_JUDGE
    elif fact.worded:
        fact.kind_checked, fact.status = _LLM, _TO_JUDGE
    else:
        fact.kind_checked, fact.status = _DIRECT, _PASSED


def _check_pointer(
    ctx: _Context, fact: _Fact, run: Mapping[str, Any], entry: Mapping[str, Any], label: Any
) -> None:
    text = _pointer_text(run, entry)
    located, reason = resolve(fact.raw["at"], text, entry.get("tool"), entry.get("partial") is True)
    if located is None:
        fact.fail(reason or "pointer_unresolved")
        return
    # A copied quote is in the result by construction: the first-hand test uses a minimum of 1.
    fact.first_hand = _is_first_hand(fact.source_kind, entry, located.quote, text, 1)
    # The number rule is the pointer's last step: a fact failing it records no evidence.
    if not numbers_shown(_value_text(fact.raw.get("value")), located.quote):
        fact.fail(_NUMBER_ABSENT)
        return
    command, origin = render_command(entry, ctx.checkout_root, ctx.redaction)
    fact.copied, fact.command = located.quote, command
    fact.evidence = {
        "quote": located.quote,
        "command": command,
        "command_from": origin,
        "result_file": entry.get("saved_result"),
        "lines": [located.first, located.last],
        "run": label,
    }
    _classify(fact, located.quote)


def _check_old_shape(ctx: _Context, fact: _Fact, text: Optional[str], partial: bool) -> None:
    quote = _str(fact.raw.get("quote"))
    match = check_quote(quote, None, text, ctx.min_len)
    if match["verdict"] == "unchecked":
        fact.status, fact.reason = _UNCHECKED, "no_saved_text"
    elif partial and match["reason"] != _QUOTE_SHORT:
        fact.status, fact.reason = _UNCHECKED, "partial_result"
    elif match["verdict"] == "refused":
        fact.fail(match["reason"])
    elif not numbers_shown(_value_text(fact.raw.get("value")), quote):
        fact.fail(_NUMBER_ABSENT)
    else:
        _classify(fact, quote)


def _locate(ctx: _Context, fact: _Fact) -> Optional[tuple[dict[str, Any], dict[str, Any], Any]]:
    """Step 1, the source: the run, entry and label it names, or None after failing the fact."""
    parsed = parse_source_ref(fact.raw.get("source"))
    if not parsed["ok"]:
        fact.fail(parsed["reason"])
        return None
    run = _run_for(ctx, parsed["label"])
    entry = _index_entries(_as_list(run.get("walk"))).get(parsed["id"]) if run else None
    if run is None or entry is None:
        fact.fail("source_unknown")
        return None
    return run, entry, parsed["label"]


def _new_fact(raw: Any, position: int) -> _Fact:
    data = _as_dict(raw)
    stated = data.get("kind")
    kind = stated if isinstance(stated, str) and stated in KINDS else _DIRECT
    quote = data.get("quote")
    return _Fact(
        raw=data,
        position=position,
        id=_str(data.get("id")),
        kind_stated=kind,
        based_on=[_str(b) for b in _as_list(data.get("based_on"))],
        kind_checked=kind,
        own_quote=quote if isinstance(quote, str) and quote != "" else None,
    )


def _check_fact(ctx: _Context, position: int, raw: Any) -> _Fact:
    fact = _new_fact(raw, position)
    if not _is_positive_integer(ctx.min_len):
        fact.fail(_QUOTE_SHORT)  # a broken contract fails every fact closed, as check_handback does
        return fact
    located = _locate(ctx, fact)
    if located is None:
        return fact
    run, entry, label = located
    text = _checker_text(run, entry)
    fact.source_kind = _kind_of(entry, ctx.contract)
    raw_quote = _str(fact.raw.get("quote"))
    fact.first_hand = _is_first_hand(fact.source_kind, entry, raw_quote, text, ctx.min_len)
    action = _action_refusal(fact.raw, entry, text)
    if action is not None:
        fact.fail(action)
    elif isinstance(fact.raw.get("at"), dict):
        _check_pointer(ctx, fact, run, entry, label)
    else:
        _check_old_shape(ctx, fact, text, entry.get("partial") is True)
    return fact


# --- 6. the shape rules ----------------------------------------------------------------


def _shape_reason(fact: _Fact) -> Optional[str]:
    raw = fact.raw
    if "kind" in raw and raw["kind"] not in KINDS:
        return "kind_unknown"
    if "at" in raw and not pointer_shape_ok(raw["at"]):
        return "pointer_malformed"
    if "at" not in raw and "quote" not in raw:
        return "pointer_missing"
    if "value" not in raw and (fact.kind_stated != _DIRECT or "at" not in raw):
        return "value_missing"
    if fact.kind_stated == _DERIVED and not fact.based_on:
        return "based_on_missing"
    return None


def _apply_shape_rules(ctx: _Context) -> None:
    for fact in ctx.facts:
        reason = _shape_reason(fact)
        if reason is None:
            continue
        fact.fail(reason, refused=False)
        fact.kind_checked = fact.worded = fact.evidence = None
        fact.dropped_by = None


# --- 7. the graph and 8. the cascade ------------------------------------------------------


def _edges(ctx: _Context) -> list[list[int]]:
    """For each fact (by position), the positions of the facts its based_on resolves to."""
    index = {id(f): i for i, f in enumerate(ctx.facts)}
    return [
        [index[id(ctx.first_by_id[b])] for b in fact.based_on if b in ctx.first_by_id]
        for fact in ctx.facts
    ]


def _strong_groups(edges: list[list[int]]) -> list[list[int]]:
    """Strongly connected groups (Tarjan, iterative), each sorted by position."""
    order: dict[int, int] = {}
    low: dict[int, int] = {}
    stack: list[int] = []
    on_stack: set[int] = set()
    groups: list[list[int]] = []
    for start in range(len(edges)):
        if start not in order:
            _visit(start, edges, order, low, stack, on_stack, groups)
    return [sorted(g) for g in groups]


def _visit(start, edges, order, low, stack, on_stack, groups) -> None:
    work = [(start, 0)]
    while work:
        node, next_edge = work.pop()
        if next_edge == 0:
            order[node] = low[node] = len(order)
            stack.append(node)
            on_stack.add(node)
        if next_edge < len(edges[node]):
            work.append((node, next_edge + 1))
            target = edges[node][next_edge]
            if target not in order:
                work.append((target, 0))
            elif target in on_stack:
                low[node] = min(low[node], order[target])
            continue
        if low[node] == order[node]:
            groups.append(_pop_group(node, stack, on_stack))
        if work:
            parent = work[-1][0]
            low[parent] = min(low[parent], low[node])


def _pop_group(node: int, stack: list[int], on_stack: set[int]) -> list[int]:
    group: list[int] = []
    while True:
        member = stack.pop()
        on_stack.discard(member)
        group.append(member)
        if member == node:
            return group


def _topological(groups: list[list[int]], edges: list[list[int]]) -> list[list[int]]:
    """Groups in dependency order; among ready groups, the one whose first fact is earliest."""
    group_of = {member: gi for gi, group in enumerate(groups) for member in group}
    needs = [
        {group_of[t] for m in group for t in edges[m]} - {gi} for gi, group in enumerate(groups)
    ]
    done: set[int] = set()
    out: list[list[int]] = []
    while len(out) < len(groups):
        ready = [gi for gi in range(len(groups)) if gi not in done and needs[gi] <= done]
        chosen = min(ready, key=lambda gi: groups[gi][0])
        done.add(chosen)
        out.append(groups[chosen])
    return out


def _is_cycle(group: list[int], edges: list[list[int]]) -> bool:
    return len(group) > 1 or group[0] in edges[group[0]]


def _graph_fail(fact: _Fact, reason: str) -> None:
    """A graph failure never replaces an earlier failure; it does replace ``unchecked``."""
    if fact.status != _FAILED:
        fact.fail(reason, refused=False)


def _check_graph(ctx: _Context) -> tuple[list[_Fact], list[dict[str, Any]]]:
    edges = _edges(ctx)
    refusals: list[dict[str, Any]] = []
    for fact in ctx.facts:
        unknown = [b for b in fact.based_on if b not in ctx.first_by_id]
        if unknown:
            refusals.append({"reason": "based_on_unknown", "fact": fact.id, "ids": unknown})
            _graph_fail(fact, "based_on_unknown")
    groups = _topological(_strong_groups(edges), edges)
    for group in groups:
        if _is_cycle(group, edges):
            ids = [ctx.facts[i].id for i in group]
            refusals.append({"reason": "based_on_cycle", "fact": None, "ids": ids})
            for i in group:
                _graph_fail(ctx.facts[i], "based_on_cycle")
    return [ctx.facts[i] for group in groups for i in group], refusals


def _root_of(basis: Optional[_Fact], decider_stage: bool) -> Optional[str]:
    """The root a basis fact passes on: itself when it is a root, its own root when dropped."""
    if basis is None:
        return None
    if basis.is_root(decider_stage):
        return basis.id
    return basis.dropped_by


def _cascade(ctx: _Context, order: list[_Fact], decider_stage: bool = False) -> None:
    """Drop each fact that rests on a root or a dropped fact, naming the root, in check order.

    Before the decider step only a failed fact is a root (an unchecked fact can then itself
    be dropped); from the decider step on, an unchecked fact and a fact the decider's answer
    drops are roots too. A dropped fact stays dropped.
    """
    for fact in order:
        if fact.is_root(decider_stage):
            continue
        for name in fact.based_on:
            root = _root_of(ctx.first_by_id.get(name), decider_stage)
            if root is not None:
                fact.dropped_by = root
                break


# --- 9. the decider and 10. the outcome policy ------------------------------------------------


def _material_quote(fact: _Fact) -> Optional[str]:
    """The text held for a fact: its copied quote, else its own quote (None when neither)."""
    return fact.copied if fact.copied is not None else fact.own_quote


def _support_sent(fact: _Fact) -> Optional[dict[str, Any]]:
    """The support question's pair, or None when the fact has no evidence text to send."""
    quote = _non_blank(_material_quote(fact))
    if quote is None:
        return None
    command = fact.command
    evidence = f"command: {command}\n{quote}" if _non_blank(command) else quote
    return {"question": _SUPPORT, "value": _str(fact.raw.get("value")), "evidence": evidence}


def _basis_line(name: str, basis: _Fact) -> tuple[str, bool]:
    """One line of the derived question's evidence, and whether it carries any material."""
    value = basis.raw.get("value")
    if _value_given(value):
        return f"{name}: {value}", True
    quote = _non_blank(_material_quote(basis))
    if quote is not None:
        return f"{name}: (no value given; its copied quote) {quote}", True
    return f"{name}: (no value or quote available)", False


def _derived_sent(ctx: _Context, fact: _Fact) -> Optional[dict[str, Any]]:
    lines = [_basis_line(name, ctx.first_by_id[name]) for name in fact.based_on]
    if not any(material for _, material in lines):
        return None
    evidence = "\n".join(line for line, _ in lines)
    return {"question": _DERIVED, "value": _str(fact.raw.get("value")), "evidence": evidence}


def _support_outcome(ctx: _Context, fact: _Fact, option: Any) -> str:
    if option in _as_list(ctx.strict.get("keep_marked")):
        first_time = fact.id not in ctx.returned_before and ctx.rounds_left > 0
        return _RETURNED if first_time else _KEEP
    if option in _as_list(ctx.strict.get("drop")):
        return _DROPPED
    return _PASS  # in support_passes, or in none of the three lists


def _derived_outcome(ctx: _Context, option: Any) -> str:
    if ctx.strict.get("derived_decides_drops") is not True:
        return _PASS  # a derived answer is only shown
    # A contract with no derived_passes passes no derived answer: it fails closed.
    return _PASS if option in _as_list(ctx.strict.get("derived_passes")) else _DROPPED


def _stored_answer(ctx: _Context, fact: _Fact) -> dict[str, Any]:
    """The stored answer for a fact: by its position when one is given there, else by its id."""
    by_position = ctx.decider_by_position
    if by_position is not None and fact.position < len(by_position):
        answer = by_position[fact.position]
        if isinstance(answer, dict):
            return answer
    return _as_dict(ctx.decider.get(fact.id))


def _not_judged(fact: _Fact, question: str, reason: Any) -> None:
    fact.judge = {"question": question, "option": None, "reason": reason}
    fact.status = _NOT_JUDGED


def _record_answer(
    ctx: _Context, fact: _Fact, question: str, sent: Optional[dict[str, Any]]
) -> None:
    """Use the stored answer for a fact to judge: judged with its option, or not judged.

    A fact with nothing to send is not judged (``no_evidence`` for the support
    question, ``no_inputs`` for the derived one) and records nothing as sent. A
    sent fact with no stored answer is not judged with ``no_stored_answer``.
    """
    if sent is None:
        _not_judged(fact, question, "no_evidence" if question == _SUPPORT else "no_inputs")
        return
    fact.sent = sent
    stored = _stored_answer(ctx, fact)
    if "option" not in stored:
        _not_judged(fact, question, stored.get("not_judged", "no_stored_answer"))
        return
    option = stored["option"]
    fact.judge = {"question": question, "option": option, "reason": None}
    fact.status = _JUDGED
    if question == _SUPPORT:
        fact.outcome = _support_outcome(ctx, fact, option)
    else:
        fact.outcome = _derived_outcome(ctx, option)
    if fact.outcome == _DROPPED:
        fact.reason = _DECIDER_DROP


def _waiting(fact: _Fact) -> bool:
    return fact.status == _TO_JUDGE and fact.dropped_by is None


def _ask_decider(ctx: _Context, order: list[_Fact]) -> None:
    for fact in ctx.facts:
        if _waiting(fact) and fact.kind_stated != _DERIVED:
            _record_answer(ctx, fact, _SUPPORT, _support_sent(fact))
    _cascade(ctx, order, decider_stage=True)
    for fact in ctx.facts:
        if _waiting(fact) and fact.kind_stated == _DERIVED:
            _record_answer(ctx, fact, _DERIVED, _derived_sent(ctx, fact))


# --- the result ----------------------------------------------------------------------------


def _final(fact: _Fact) -> tuple[str, str, Optional[str]]:
    """``(status, strict_outcome, drop_reason)`` after the last cascade."""
    if fact.dropped_by is not None:
        return _DROPPED, _DROPPED, _CASCADE_REASON
    if fact.status in (_FAILED, _UNCHECKED):
        return fact.status, _DROPPED, fact.reason
    if fact.status == _PASSED:
        return _PASSED, _PASS, None
    if fact.status == _JUDGED:
        reason = _DECIDER_DROP if fact.outcome == _DROPPED else None
        return _JUDGED, fact.outcome or _PASS, reason
    return _NOT_JUDGED, _NOT_JUDGED, None


def _fact_record(fact: _Fact) -> dict[str, Any]:
    status, outcome, reason = _final(fact)
    return {
        "id": fact.id,
        "kind_stated": fact.kind_stated,
        "kind_checked": fact.kind_checked,
        "worded": fact.worded,
        "status": status,
        "strict_outcome": outcome,
        "drop_reason": reason,
        "dropped_by": fact.dropped_by,
        "evidence": fact.evidence,
        "judge": fact.judge,
        "sent": fact.sent,
    }


def _checker_view(fact: _Fact) -> dict[str, Any]:
    """What the checker rules for verdicts read of a fact: its verdict and first-hand flag."""
    return {"verdict": "refused" if fact.refused else "passed", "first_hand": fact.first_hand}


def _item_strict(basis: list[dict[str, Any]]) -> tuple[str, Optional[str]]:
    outcomes = {record["strict_outcome"] for record in basis}
    if outcomes & {_DROPPED, _RETURNED}:
        return _DROPPED, "basis_dropped"
    if _NOT_JUDGED in outcomes:
        return _NOT_JUDGED, None
    return _PASS, None


def _item_record(item_id: str, reason: Optional[str], basis: list[dict[str, Any]]) -> dict:
    if reason is not None:
        strict_outcome, strict_reason = _DROPPED, reason
    else:
        strict_outcome, strict_reason = _item_strict(basis)
    return {
        "id": item_id,
        "outcome": "refused" if reason is not None else "accepted",
        "reason": reason,
        "strict_outcome": strict_outcome,
        "strict_reason": strict_reason,
    }


def _known(ctx: _Context, records: Mapping[str, dict[str, Any]], basis: list[str]):
    names = [b for b in basis if b in ctx.first_by_id]
    return [ctx.first_by_id[b] for b in names], [records[b] for b in names]


def _verdict_records(ctx, finish, records) -> list[dict[str, Any]]:
    items = [_as_dict(v) for v in _as_list(finish.get("verdicts"))]
    closing = _closing_index(items)
    out = []
    for position, item in enumerate(items):
        basis = [_str(b) for b in _as_list(item.get("basis"))]
        facts, basis_records = _known(ctx, records, basis)
        views = [_checker_view(f) for f in facts]
        reason = _verdict_refusal(item, basis, views, position == closing)
        out.append(_item_record(_str(item.get("id")), reason, basis_records))
    return out


def _open_item_records(ctx, finish, records) -> list[dict[str, Any]]:
    out = []
    for raw in _as_list(finish.get("open_items")):
        item = _as_dict(raw)
        _, basis_records = _known(ctx, records, [_str(b) for b in _as_list(item.get("basis"))])
        reason = None if _has_check(item) else "open_without_check"
        out.append(_item_record(_str(item.get("id")), reason, basis_records))
    return out


def _tally(reasons: list[Optional[str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for reason in reasons:
        if reason is not None:
            out[reason] = out.get(reason, 0) + 1
    return out


def _answered(record: Mapping[str, Any], question: str) -> bool:
    judge = record["judge"]
    return judge is not None and judge["option"] is not None and judge["question"] == question


def _judge_counts(facts: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "direct_passed": sum(
            1 for f in facts if f["status"] == _PASSED and f["strict_outcome"] == _PASS
        ),
        "llm_judged": sum(1 for f in facts if _answered(f, _SUPPORT)),
        "derived_judged": sum(1 for f in facts if _answered(f, _DERIVED)),
        "not_judged": sum(1 for f in facts if f["strict_outcome"] == _NOT_JUDGED),
    }


def _passes_on(facts: list[dict[str, Any]], question: Optional[str]) -> int:
    """Facts with outcome pass on an answer to *question* (None: no answer from the decider)."""
    count = 0
    for record in facts:
        if record["strict_outcome"] != _PASS:
            continue
        answered = [q for q in (_SUPPORT, _DERIVED) if _answered(record, q)]
        if (answered[0] if answered else None) == question:
            count += 1
    return count


def _by_stated_kind(facts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out = {kind: {"stated": 0, "checked_as_direct": 0} for kind in KINDS}
    for record in facts:
        row = out[record["kind_stated"]]
        row["stated"] += 1
        if record["kind_checked"] == _DIRECT and record["status"] == _PASSED:
            row["checked_as_direct"] += 1
    return out


def _outcome_total(facts: list[dict[str, Any]], outcome: str) -> int:
    return sum(1 for f in facts if f["strict_outcome"] == outcome)


def _report(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_reason = _tally([f["drop_reason"] for f in facts if f["strict_outcome"] == _DROPPED])
    return {
        "direct_passed": _passes_on(facts, None),
        "llm_judged": _passes_on(facts, _SUPPORT),
        "derived": _passes_on(facts, _DERIVED),
        "kept_with_mark": _outcome_total(facts, _KEEP),
        "returned": _outcome_total(facts, _RETURNED),
        "not_judged": _outcome_total(facts, _NOT_JUDGED),
        "dropped": {"total": sum(by_reason.values()), "by_reason": by_reason},
        "by_stated_kind": _by_stated_kind(facts),
        "worded": sum(1 for f in facts if f["worded"] is True),
        "judged": sum(1 for f in facts if _answered(f, _SUPPORT) or _answered(f, _DERIVED)),
    }


def strict_recheck(case_input: Mapping[str, Any], redaction: Mapping[str, Any]) -> dict[str, Any]:
    """Re-check one strict hand-back; the result has the shape of a shared case's ``expect``.

    *case_input* has the keys of a case ``input`` in ``strict_vectors.json``:
    ``checkout_root``, ``walk``, ``results`` (by file name), ``prior_runs``,
    ``children``, ``finish``, ``contract``, ``decider`` (the decider's stored
    answer per judged fact id), ``returned_before`` and ``rounds_left``.
    An input may also hold ``decider_by_position``: a list, one entry per fact
    in hand-back order, each a stored answer or null. An entry there is used in
    place of the answer keyed by the fact's id, so two facts that share an id
    keep their own answers (the shared cases do not use it).
    *redaction* is the contract's ``{replacement, patterns}`` filter, applied to
    the printed command.

    Returns ``facts``, ``graph`` (``order`` and ``refusals``), ``verdicts``,
    ``open_items``, ``counts``, ``drop_reasons``, ``judge_counts`` and
    ``report``. No decider, network, process, file or environment is used.
    """
    return recheck_with_checker(case_input, redaction)[0]


def _run_steps(ctx: _Context, finish: Mapping[str, Any]) -> tuple[list[_Fact], list[dict]]:
    ctx.facts = [_check_fact(ctx, i, raw) for i, raw in enumerate(_as_list(finish.get("facts")))]
    for fact in ctx.facts:
        ctx.first_by_id.setdefault(fact.id, fact)
    order, refusals = _check_graph(ctx)
    _cascade(ctx, order)
    _apply_shape_rules(ctx)
    _cascade(ctx, order)
    _ask_decider(ctx, order)
    _cascade(ctx, order, decider_stage=True)
    return order, refusals


def recheck_with_checker(
    case_input: Mapping[str, Any], redaction: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    """:func:`strict_recheck`'s result, and whether the checker refused nothing.

    The second value is what associate writes as ``check.json`` ``accepted``
    under strict: no fact's checker verdict is ``refused`` (steps 1 to 3) and
    no verdict or open item was refused by the checker rules. A strict
    hand-back is never refused for it; the value is reported, nothing more.
    """
    ctx = _new_context(case_input, redaction)
    finish = _as_dict(case_input.get("finish"))
    order, refusals = _run_steps(ctx, finish)
    facts = [_fact_record(f) for f in ctx.facts]
    records: dict[str, dict[str, Any]] = {}
    for fact, record in zip(ctx.facts, facts):
        records.setdefault(fact.id, record)
    verdicts = _verdict_records(ctx, finish, records)
    open_items = _open_item_records(ctx, finish, records)
    item_reasons = [
        i["strict_reason"] for i in verdicts + open_items if i["strict_outcome"] == _DROPPED
    ]
    fact_reasons = [f["drop_reason"] for f in facts if f["strict_outcome"] == _DROPPED]
    result = {
        "facts": facts,
        "graph": {"order": [f.id for f in order], "refusals": refusals},
        "verdicts": verdicts,
        "open_items": open_items,
        "counts": {outcome: _outcome_total(facts, outcome) for outcome in OUTCOMES},
        "drop_reasons": _tally(fact_reasons + item_reasons),
        "judge_counts": _judge_counts(facts),
        "report": _report(facts),
    }
    accepted = not any(f.refused for f in ctx.facts) and all(
        item["outcome"] == "accepted" for item in verdicts + open_items
    )
    return result, accepted
