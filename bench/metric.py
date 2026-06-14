"""The pre-registered graded metric.

Detection precision/recall/F1 of the emitted pain register against the planted
answer key, computed both ungated and gated by citation grounding (a finding is
grounded only if its evidence_fqn resolves in the warehouse). The headline is
relative error reduction in gated detection-F1 against the naive baseline:

    REL = (F1_egnta - F1_baseline) / (1 - F1_baseline)

Both systems are scored through the SAME gate, and both gated and ungated numbers
are reported, because the gate is asymmetric (only EGNTA grounds) and hiding the
ungated number would flatter EGNTA. The hallucination rate (ungrounded findings
over total) is reported per system. PM4Py is NOT part of this metric.
"""
from __future__ import annotations

from accelerator import warehouse
from accelerator.model import AnswerItem, Finding


def _matches(f: Finding, a: AnswerItem) -> bool:
    if f.kind != a.kind:
        return False
    return f.key.strip().lower() == a.key.strip().lower()


def _prf(findings: list[Finding], answer: list[AnswerItem]) -> dict:
    matched: set[int] = set()
    fp = 0
    for f in findings:
        hit = next((i for i, a in enumerate(answer) if i not in matched and _matches(f, a)), None)
        if hit is None:
            # allow a finding to match an already-claimed answer without double-FP
            if any(_matches(f, a) for a in answer):
                continue
            fp += 1
        else:
            matched.add(hit)
    tp = len(matched)
    fn = len(answer) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4)}


def score_system(conn, findings: list[Finding], answer: list[AnswerItem]) -> dict:
    grounded = [f for f in findings if warehouse.citation_resolves(conn, f.evidence_fqn)]
    ungrounded = len(findings) - len(grounded)
    return {
        "ungated": _prf(findings, answer),
        "gated": _prf(grounded, answer),
        "n_findings": len(findings),
        "hallucination_rate": round(ungrounded / len(findings), 4) if findings else 0.0,
    }


def rel_error_reduction(f1_egnta: float, f1_baseline: float) -> float:
    """Relative error reduction. >= 0.50 is the pre-registered target. Computed
    against the naive baseline only, on gated detection-F1."""
    if f1_baseline >= 1.0:
        return 0.0
    return round((f1_egnta - f1_baseline) / (1.0 - f1_baseline), 4)
