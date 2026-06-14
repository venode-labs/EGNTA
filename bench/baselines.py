"""The two systems under test.

egnta_pipeline is the real deterministic discovery layer (mining -> grounded
pain register). It writes its supporting metrics to the warehouse so every
finding's citation resolves.

naive_baseline is a deliberately simple single-pass heuristic, the honest stand-in
for the real single-LLM baseline that lands in iteration 2 (when an Anthropic key
is wired). It is NOT a strawman: it does the obvious thing a one-shot pass would,
flags the most frequent activity as a bottleneck and the most-repeated activity as
rework, and cites a real event entity so it can ground. It simply lacks the
structured mining, which is the point being measured. The iteration-1 number is
therefore "deterministic mining layer vs naive heuristic", a lower bound and a
plumbing proof, NOT the headline real-LLM result.
"""
from __future__ import annotations

import json
from collections import Counter

from accelerator import mining, pain, synthesis, warehouse
from accelerator.model import Finding
from accelerator.verticals import trades


def egnta_pipeline(conn) -> list[Finding]:
    events = warehouse.load_events(conn)
    findings, metrics = pain.detect(events)
    for fqn, name, value, evidence in metrics:
        warehouse.write_metric(conn, fqn, name, value, evidence)
    warehouse.write_findings(conn, findings)
    return findings


def egnta_trades_pipeline(conn) -> list[Finding]:
    """The trades vertical pipeline: domain detectors instead of the generic ones,
    same grounded shape. The held-out segregation-of-duties defect has no detector,
    so this honestly does not recover it."""
    events = warehouse.load_events(conn)
    findings, metrics = trades.detect(events)
    for fqn, name, value, evidence in metrics:
        warehouse.write_metric(conn, fqn, name, value, evidence)
    warehouse.write_findings(conn, findings)
    return findings


def naive_trades_baseline(conn) -> list[Finding]:
    """A weak single-pass trades heuristic, the lower-bound comparator for CI. Flags
    the most frequent transition as a dispatch bottleneck and guesses unbilled work
    from a raw count, with no grounding discipline beyond citing one real entity."""
    events = warehouse.load_events(conn)
    if not events:
        return []
    dfg = mining.directly_follows(events)
    if not dfg:
        return []
    (a, b), _ = dfg.most_common(1)[0]
    cite = next((e.entity_fqn for e in events if e.entity_fqn), "")
    return [Finding("dispatch-bottleneck", f"Frequent transition {a}->{b}", f"{a}->{b}",
                    severity=0.5, frequency=0.5, fixability=0.5, evidence_fqn=cite)]


def naive_baseline(conn) -> list[Finding]:
    events = warehouse.load_events(conn)
    if not events:
        return []
    freq = Counter(e.activity for e in events)
    top_act, _ = freq.most_common(1)[0]
    # a real, resolvable citation (an event entity) so the baseline can ground
    cite = next((e.entity_fqn for e in events if e.activity == top_act and e.entity_fqn), "")
    n_cases = len({e.case_id for e in events}) or 1
    findings = [
        Finding("bottleneck", f"High-volume activity {top_act}", top_act,
                severity=0.5, frequency=freq[top_act] / sum(freq.values()),
                fixability=0.5, evidence_fqn=cite),
    ]
    # crude rework guess: any activity occurring more than once on average
    per_case = freq[top_act] / n_cases
    if per_case > 1.0:
        findings.append(Finding("rework", f"Frequent {top_act}", top_act,
                                severity=0.5, frequency=0.5, fixability=0.5, evidence_fqn=cite))
    return findings


# ---- real-LLM systems (iteration 2): need a key via the vault ----------------

def egnta_llm(conn, llm) -> list[Finding]:
    """The product: deterministic mining + grounded Claude synthesis."""
    return synthesis.synthesise(conn, llm)


def egnta_trades_llm(conn, llm) -> list[Finding]:
    """The trades product: trades mining + grounded Claude synthesis on the trades
    prompt. The held-out segregation-of-duties defect has no mined fact, so neither
    the miner nor the synthesis recovers it; that is the honest discriminator."""
    return synthesis.synthesise(conn, llm, detect=trades.detect, system=synthesis._SYSTEM_TRADES)


_BASELINE_SYSTEM = """You are an operations analyst. From the process data given, find
the top operational problems and classify each as one of: bottleneck, rework,
control-gap, recording-error. Cite an entity id from the provided list for each.
This is a single pass, no tools. Australian English, no em dashes.

Return ONLY JSON: {"findings":[{"kind":str,"key":str,"evidence_fqn":str}]}
For a bottleneck, key is the slow "A->B" transition; for control-gap/rework, key is
the activity; for recording-error, key is "log"."""


_TRADES_BASELINE_SYSTEM = """You are an operations analyst reviewing a fire/trades business.
From the process data given, find the top operational problems and classify each as one of:
unbilled-completion, rectification-stall, compliance-overdue, approval-gap, rework-loop,
dispatch-bottleneck, recording-error. Cite an entity id from the provided list for each.
This is a single pass, no tools. Australian English, no em dashes.

Return ONLY JSON: {"findings":[{"kind":str,"key":str,"evidence_fqn":str}]}
For dispatch-bottleneck, key is the slow "A->B" transition; for the others, key is the
activity (JobComplete, DefectRaised, RoutineService, QuoteApproved, Attended) or "log"."""


def _llm_findings(conn, llm, system) -> list[Finding]:
    events = warehouse.load_events(conn)
    if not events:
        return []
    summ = mining.summary(events)
    sample_fqns = sorted({e.entity_fqn for e in events if e.entity_fqn})[:8]
    user = ("Process data:\n" + json.dumps(summ, indent=2) +
            "\n\nEntity ids you may cite:\n" + json.dumps(sample_fqns))
    try:
        out = llm.complete_json(system, user, max_tokens=1500)
        raw = out.get("findings", []) if isinstance(out, dict) else []
    except (ValueError, RuntimeError, KeyError):
        raw = []
    findings: list[Finding] = []
    for f in raw:
        fqn = str(f.get("evidence_fqn", ""))
        findings.append(Finding(str(f.get("kind", "")), str(f.get("kind", "")), str(f.get("key", "")),
                                severity=0.5, frequency=0.5, fixability=0.5, evidence_fqn=fqn))
    return findings


def llm_baseline(conn, llm) -> list[Finding]:
    """A fair naive single-LLM baseline: handed the SAME summary the synthesis sees,
    but no pre-grounded metrics, no mining classification, no safety net. The honest
    comparator the 50% headline is computed against."""
    return _llm_findings(conn, llm, _BASELINE_SYSTEM)


def llm_trades_baseline(conn, llm) -> list[Finding]:
    """The trades naive single-LLM baseline, told the same trades taxonomy so the
    comparison is fair, but with no mining and no grounding gate."""
    return _llm_findings(conn, llm, _TRADES_BASELINE_SYSTEM)
