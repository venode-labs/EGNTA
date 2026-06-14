"""Fire, construction and service-trades vertical pack.

The first EGNTA vertical, built for the businesses Venode knows: fire protection,
electrical, plumbing, HVAC, security and facilities maintenance. It pins three
things so discovery runs on a real field-service export without a bespoke
modelling phase first:

- CANONICAL, the lifecycle activities trades work actually moves through.
- SYNONYMS, the map a connector normalises raw ServiceM8 / simPRO / Uptick
  statuses through into the canonical set.
- detect(), the domain defect detectors that the generic miner cannot express:
  unbilled job completion, defect-to-rectification stall, overdue AS 1851
  compliance, approval/PO gaps, repeat-visit rework, dispatch bottlenecks, and
  recording errors. Each finding cites a metric the engine writes to the
  warehouse, so the grounding gate can resolve it.

Deterministic, stdlib only. No LLM here; this is the evidence the synthesis cites.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from .. import mining
from ..model import Event, Finding

# Canonical job-to-cash plus the defect-rectification and compliance sub-flows.
CANONICAL = [
    "Lead", "Quote", "QuoteApproved", "Scheduled", "Attended", "JobComplete",
    "Invoice", "Paid", "DefectRaised", "RectifyQuote", "RectifyApproved",
    "RectifyComplete", "RoutineService", "CertificateIssued",
]

# Raw source status -> canonical activity. Lower-cased on lookup, so casing in the
# export does not matter. Covers the common ServiceM8 / simPRO / Uptick wording.
SYNONYMS = {
    "lead": "Lead", "enquiry": "Lead", "new": "Lead",
    "quote": "Quote", "estimate": "Quote", "quoted": "Quote",
    "quote accepted": "QuoteApproved", "won": "QuoteApproved", "approved": "QuoteApproved",
    "accepted": "QuoteApproved", "po received": "QuoteApproved",
    "scheduled": "Scheduled", "dispatched": "Scheduled", "booked": "Scheduled",
    "on site": "Attended", "attended": "Attended", "in progress": "Attended",
    "started": "Attended", "checked in": "Attended",
    "completed": "JobComplete", "job complete": "JobComplete", "work complete": "JobComplete",
    "finished": "JobComplete",
    "invoiced": "Invoice", "invoice": "Invoice", "billed": "Invoice",
    "paid": "Paid", "payment received": "Paid", "settled": "Paid",
    "defect": "DefectRaised", "fault": "DefectRaised", "non-conformance": "DefectRaised",
    "defect raised": "DefectRaised", "fail": "DefectRaised",
    "rectification quote": "RectifyQuote", "rectify quote": "RectifyQuote",
    "rectification approved": "RectifyApproved", "rectify approved": "RectifyApproved",
    "rectified": "RectifyComplete", "rectification complete": "RectifyComplete",
    "routine service": "RoutineService", "scheduled service": "RoutineService",
    "as1851 routine": "RoutineService", "annual service": "RoutineService",
    "certificate": "CertificateIssued", "compliance certificate": "CertificateIssued",
    "certified": "CertificateIssued",
}

ENTITY_KINDS = ("job", "asset", "invoice", "technician", "site", "customer")

# A dispatch bottleneck lives in the job-execution flow only. The compliance and
# rectification sub-flows have their own cadence (a certificate issued the day after
# a service is normal, not a bottleneck), so they are excluded from the candidate
# pool, otherwise a routine compliance gap reads as slow against the tight job steps.
_JOB_FLOW = {"Lead", "Quote", "QuoteApproved", "Scheduled", "Attended", "JobComplete",
             "Invoice", "Paid"}

# AS 1851 routine servicing of installed fire safety measures is, at the longest
# routine interval, annual. An asset whose last routine service predates the review
# date by more than this (plus a month of grace) is treated as overdue.
_COMPLIANCE_INTERVAL_S = 365 * 86_400
_COMPLIANCE_GRACE_S = 31 * 86_400


def canonical_activity(raw: str) -> str:
    """Map a raw export status to a canonical activity. Unknown statuses pass
    through unchanged (title-cased) so nothing is silently dropped."""
    key = (raw or "").strip().lower()
    if key in SYNONYMS:
        return SYNONYMS[key]
    return (raw or "").strip()


def _by_case(events: list[Event]) -> dict[str, list[Event]]:
    cases: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        cases[e.case_id].append(e)
    return cases


def detect(events: list[Event]) -> tuple[list[Finding], list[tuple]]:
    """Return (findings, metrics) for the trades vertical. metrics is the list of
    (fqn, name, value, evidence) rows the caller writes so each citation resolves.
    Mirrors accelerator.pain.detect so the bench treats the two identically."""
    findings: list[Finding] = []
    metrics: list[tuple] = []
    cases = _by_case(events)
    n_cases = len(cases) or 1

    def acts(ev):
        return {e.activity for e in ev}

    # unbilled-completion: job complete, never invoiced. Direct revenue leak.
    completed = [c for c, ev in cases.items() if "JobComplete" in acts(ev)]
    unbilled = [c for c in completed if "Invoice" not in acts(cases[c])]
    if completed and len(unbilled) / len(completed) > 0.05:
        freq = len(unbilled) / len(completed)
        fqn = "metric.unbilled-completion.JobComplete"
        metrics.append((fqn, "unbilled_completed_jobs", len(unbilled),
                        {"completed": len(completed), "unbilled": len(unbilled)}))
        findings.append(Finding("unbilled-completion",
                                f"{len(unbilled)} completed jobs never invoiced", "JobComplete",
                                severity=0.85, frequency=round(freq, 3), fixability=0.8,
                                evidence_fqn=fqn))

    # rectification-stall: a defect raised but never rectified. Revenue plus, on fire
    # assets, a live safety and compliance exposure.
    defect_cases = [c for c, ev in cases.items() if "DefectRaised" in acts(ev)]
    stalled = [c for c in defect_cases if "RectifyComplete" not in acts(cases[c])]
    if defect_cases and len(stalled) / len(defect_cases) > 0.05:
        freq = len(stalled) / len(defect_cases)
        fqn = "metric.rectification-stall.DefectRaised"
        metrics.append((fqn, "stalled_rectifications", len(stalled),
                        {"defects": len(defect_cases), "stalled": len(stalled)}))
        findings.append(Finding("rectification-stall",
                                f"{len(stalled)} raised defects never rectified", "DefectRaised",
                                severity=0.9, frequency=round(freq, 3), fixability=0.6,
                                evidence_fqn=fqn))

    # compliance-overdue: an asset whose AS 1851 routine service interval has lapsed
    # relative to the review date (the latest event in the corpus).
    review_ts = max((e.ts for e in events), default=0.0)
    last_service: dict[str, float] = {}
    for e in events:
        if e.activity == "RoutineService" and e.entity_fqn:
            last_service[e.entity_fqn] = max(last_service.get(e.entity_fqn, 0.0), e.ts)
    overdue = [a for a, ts in last_service.items()
               if review_ts - ts > _COMPLIANCE_INTERVAL_S + _COMPLIANCE_GRACE_S]
    if last_service and overdue:
        freq = len(overdue) / len(last_service)
        fqn = "metric.compliance-overdue.RoutineService"
        metrics.append((fqn, "overdue_compliance_assets", len(overdue),
                        {"assets_with_service": len(last_service), "overdue": len(overdue),
                         "interval_days": 365}))
        findings.append(Finding("compliance-overdue",
                                f"{len(overdue)} assets overdue for AS 1851 routine service",
                                "RoutineService", severity=0.95, frequency=round(freq, 3),
                                fixability=0.7, evidence_fqn=fqn))

    # approval-gap: work invoiced with no recorded quote approval or PO.
    invoiced = [c for c, ev in cases.items() if "Invoice" in acts(ev)]
    no_approval = [c for c in invoiced if "QuoteApproved" not in acts(cases[c])]
    if invoiced and len(no_approval) / len(invoiced) > 0.05:
        freq = len(no_approval) / len(invoiced)
        fqn = "metric.approval-gap.QuoteApproved"
        metrics.append((fqn, "invoiced_without_approval", len(no_approval),
                        {"invoiced": len(invoiced), "no_approval": len(no_approval)}))
        findings.append(Finding("approval-gap",
                                f"{len(no_approval)} jobs invoiced without a recorded approval",
                                "QuoteApproved", severity=0.7, frequency=round(freq, 3),
                                fixability=0.7, evidence_fqn=fqn))

    # rework-loop: repeat attendances on the same job (first-time-fix failure).
    rw = mining.rework(events)
    if rw.get("Attended", 0) / n_cases > 0.05:
        freq = rw["Attended"] / n_cases
        fqn = "metric.rework-loop.Attended"
        metrics.append((fqn, "repeat_attendance_cases", rw["Attended"], {"activity": "Attended"}))
        findings.append(Finding("rework-loop", f"Repeat site visits on {rw['Attended']} jobs",
                                "Attended", severity=0.6, frequency=round(freq, 3),
                                fixability=0.6, evidence_fqn=fqn))

    # dispatch-bottleneck: a job-flow stage transition far above the rest (>= 2x median).
    dur_all = mining.transition_durations(events)
    dur = {(a, b): d for (a, b), d in dur_all.items() if a in _JOB_FLOW and b in _JOB_FLOW}
    dfg = mining.directly_follows(events)
    total_trans = sum(dfg.values()) or 1
    if dur:
        med = statistics.median(dur.values()) or 1.0
        max_dur = max(dur.values()) or 1.0
        top = sorted(dur.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for (a, b), d in top:
            metrics.append((f"metric.dispatch-bottleneck.{a}->{b}", "transition_mean_duration", d,
                            {"transition": f"{a}->{b}", "n": dfg.get((a, b), 0)}))
        for (a, b), d in [x for x in top if x[1] >= 2.0 * med]:
            key = f"{a}->{b}"
            findings.append(Finding("dispatch-bottleneck", f"Dispatch bottleneck at {key}", key,
                                    severity=round(d / max_dur, 3),
                                    frequency=round(dfg.get((a, b), 0) / total_trans, 3),
                                    fixability=0.6, evidence_fqn=f"metric.dispatch-bottleneck.{key}"))

    # recording-error: out-of-order timestamps in ingest order, a data-quality finding.
    rec = mining.recording_errors(events)
    if rec:
        freq = len(rec) / n_cases
        fqn = "metric.recording-error.log"
        metrics.append((fqn, "cases_with_recording_errors", len(rec), {"cases": list(rec)[:20]}))
        findings.append(Finding("recording-error", "Out-of-order timestamps in the log", "log",
                                severity=0.3, frequency=round(freq, 3), fixability=0.9,
                                evidence_fqn=fqn))

    findings.sort(key=lambda f: f.score, reverse=True)
    return findings, metrics
