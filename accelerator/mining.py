"""Clean-room process mining over the canonical event log.

Reimplemented from the published algorithms (directly-follows graph, frequency
and performance metrics in the edeaR vein, a DFG-conformance fitness proxy)
rather than vendoring PM4Py, which is AGPL-3.0 and viral over a network service.
PM4Py is used only as a CI-time eval oracle, never shipped in the product.

Everything here is deterministic and explainable, the grounded evidence the
Claude reasoners cite. No LLM, stdlib only.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .model import Event


def _by_case(events: list[Event]) -> dict[str, list[Event]]:
    cases: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        cases[e.case_id].append(e)
    for ev in cases.values():
        ev.sort(key=lambda e: e.ts)
    return cases


def directly_follows(events: list[Event]) -> Counter:
    """DFG: Counter[(a, b)] of directly-follows pair frequencies."""
    dfg: Counter = Counter()
    for ev in _by_case(events).values():
        for a, b in zip(ev, ev[1:]):
            dfg[(a.activity, b.activity)] += 1
    return dfg


def activity_frequency(events: list[Event]) -> Counter:
    return Counter(e.activity for e in events)


def selfloops(events: list[Event]) -> dict[str, int]:
    return {a: n for (a, b), n in directly_follows(events).items() if a == b}


def rework(events: list[Event]) -> dict[str, int]:
    """Per activity: how many cases execute it more than once (rework signal)."""
    out: Counter = Counter()
    for ev in _by_case(events).values():
        counts = Counter(e.activity for e in ev)
        for act, n in counts.items():
            if n > 1:
                out[act] += 1
    return dict(out)


def case_throughput(events: list[Event]) -> dict[str, float]:
    """Per case: wall-clock from first to last event (the throughput-time metric)."""
    return {cid: (ev[-1].ts - ev[0].ts) for cid, ev in _by_case(events).items() if ev}


def transition_durations(events: list[Event]) -> dict[tuple, float]:
    """Mean duration of each directly-follows transition; the bottleneck signal."""
    sums: dict[tuple, float] = defaultdict(float)
    counts: dict[tuple, int] = defaultdict(int)
    for ev in _by_case(events).values():
        for a, b in zip(ev, ev[1:]):
            sums[(a.activity, b.activity)] += (b.ts - a.ts)
            counts[(a.activity, b.activity)] += 1
    return {k: sums[k] / counts[k] for k in sums}


def activity_case_coverage(events: list[Event]) -> dict[str, float]:
    """Fraction of cases that contain each activity. A normally-present activity
    that drops below 1.0 is a candidate control-gap (a skipped step)."""
    cases = _by_case(events)
    n = len(cases) or 1
    present: Counter = Counter()
    for ev in cases.values():
        for act in {e.activity for e in ev}:
            present[act] += 1
    return {act: present[act] / n for act in present}


def recording_errors(events: list[Event]) -> dict[str, int]:
    """Per case count of out-of-order timestamps in INGEST order (a clean log has
    timestamps that rise in recorded order). Deliberately does NOT use _by_case,
    which sorts by ts and would mask exactly this defect. Relies on events being
    passed in ingest order (warehouse.load_events guarantees it)."""
    per_case: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        per_case[e.case_id].append(e)
    out: Counter = Counter()
    for cid, ev in per_case.items():
        for a, b in zip(ev, ev[1:]):
            if b.ts < a.ts:
                out[cid] += 1
    return dict(out)


def variants(events: list[Event]) -> Counter:
    return Counter(tuple(e.activity for e in ev) for ev in _by_case(events).values())


def dfg_fitness(events: list[Event], reference_dfg: Counter) -> float:
    """A clean-room conformance proxy (NOT token-replay): the mean fraction, per
    case, of consecutive activity pairs that exist in a reference DFG. Named
    honestly so it is not mistaken for PM4Py alignment fitness."""
    ref = set(reference_dfg)
    scores = []
    for ev in _by_case(events).values():
        pairs = list(zip([e.activity for e in ev], [e.activity for e in ev][1:]))
        if not pairs:
            scores.append(1.0)
            continue
        scores.append(sum(1 for p in pairs if p in ref) / len(pairs))
    return sum(scores) / len(scores) if scores else 1.0
