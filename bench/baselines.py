"""The two systems under test.

egenta_pipeline is the real deterministic discovery layer (mining -> grounded
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

from collections import Counter

from accelerator import pain, warehouse
from accelerator.model import Finding


def egenta_pipeline(conn) -> list[Finding]:
    events = warehouse.load_events(conn)
    findings, metrics = pain.detect(events)
    for fqn, name, value, evidence in metrics:
        warehouse.write_metric(conn, fqn, name, value, evidence)
    warehouse.write_findings(conn, findings)
    return findings


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
