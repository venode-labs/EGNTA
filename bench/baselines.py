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

import json
from collections import Counter

from accelerator import mining, pain, synthesis, warehouse
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


# ---- real-LLM systems (iteration 2): need a key via the vault ----------------

def egenta_llm(conn, llm) -> list[Finding]:
    """The product: deterministic mining + grounded Claude synthesis."""
    return synthesis.synthesise(conn, llm)


_BASELINE_SYSTEM = """You are an operations analyst. From the process data given, find
the top operational problems and classify each as one of: bottleneck, rework,
control-gap, recording-error. Cite an entity id from the provided list for each.
This is a single pass, no tools. Australian English, no em dashes.

Return ONLY JSON: {"findings":[{"kind":str,"key":str,"evidence_fqn":str}]}
For a bottleneck, key is the slow "A->B" transition; for control-gap/rework, key is
the activity; for recording-error, key is "log"."""


def llm_baseline(conn, llm) -> list[Finding]:
    """A fair naive single-LLM baseline: handed the SAME summary the synthesis sees,
    but no pre-grounded metrics, no mining classification, no safety net. The honest
    comparator the 50% headline is computed against."""
    events = warehouse.load_events(conn)
    if not events:
        return []
    summ = mining.summary(events)
    sample_fqns = sorted({e.entity_fqn for e in events if e.entity_fqn})[:8]
    user = ("Process data:\n" + json.dumps(summ, indent=2) +
            "\n\nEntity ids you may cite:\n" + json.dumps(sample_fqns))
    try:
        out = llm.complete_json(_BASELINE_SYSTEM, user, max_tokens=1500)
        raw = out.get("findings", []) if isinstance(out, dict) else []
    except (ValueError, RuntimeError, KeyError):
        raw = []
    findings: list[Finding] = []
    for f in raw:
        fqn = str(f.get("evidence_fqn", ""))
        findings.append(Finding(str(f.get("kind", "")), str(f.get("kind", "")), str(f.get("key", "")),
                                severity=0.5, frequency=0.5, fixability=0.5, evidence_fqn=fqn))
    return findings
