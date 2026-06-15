"""Turn deterministic mining metrics into a grounded pain register.

Each finding carries frequency, a cost-signal severity, and a fixability, and
cites a metric the engine wrote to the warehouse. A finding with no resolvable
citation is ungrounded and the eval gates it out. This is the deterministic layer
the Claude synthesis sits on top of (iteration 2): it never guesses, it scores
what the mining measured.
"""
from __future__ import annotations

import statistics

from . import mining
from .model import Event, Finding


def detect(events: list[Event]) -> tuple[list[Finding], list[tuple]]:
    """Return (findings, metrics). metrics is a list of (fqn, name, value, evidence)
    rows the caller writes to the warehouse so each finding's citation resolves."""
    findings: list[Finding] = []
    metrics: list[tuple] = []
    n_cases = len({e.case_id for e in events}) or 1

    durations = mining.transition_durations(events)
    dfg = mining.directly_follows(events)
    total_trans = sum(dfg.values()) or 1
    if durations:
        max_dur = max(durations.values()) or 1.0
        med = statistics.median(durations.values()) or 1.0
        # flag EVERY transition materially slower than the rest (>= 2x the median), not
        # just the top five: capping the candidate pool at 5 before the gate could miss a
        # genuine bottleneck on a wide process. Sort by duration and cap the emitted list
        # so pathological input cannot produce findings unboundedly.
        flagged = sorted(((ab, d) for ab, d in durations.items() if d >= 2.0 * med),
                         key=lambda kv: kv[1], reverse=True)[:10]
        for (a, b), d in flagged:
            key = f"{a}->{b}"
            metrics.append((f"metric.bottleneck.{key}", "bottleneck_mean_duration", d,
                            {"transition": key, "n": dfg.get((a, b), 0)}))
            findings.append(Finding("bottleneck", f"Bottleneck at {key}", key,
                                    severity=round(d / max_dur, 3),
                                    frequency=round(dfg.get((a, b), 0) / total_trans, 3),
                                    fixability=0.6, evidence_fqn=f"metric.bottleneck.{key}"))

    rw = mining.rework(events)
    for act, cases in rw.items():
        freq = cases / n_cases
        if freq < 0.1:
            continue
        fqn = f"metric.rework.{act}"
        metrics.append((fqn, "rework_case_count", cases, {"activity": act}))
        findings.append(Finding("rework", f"Rework loop on {act}", act,
                                severity=0.5, frequency=round(freq, 3),
                                fixability=0.7, evidence_fqn=fqn))

    cov = mining.activity_case_coverage(events)
    for act, c in cov.items():
        if 0.4 <= c < 0.92:  # normally present, skipped in a meaningful minority
            fqn = f"metric.control-gap.{act}"
            metrics.append((fqn, "activity_coverage", c, {"activity": act}))
            findings.append(Finding("control-gap", f"{act} skipped in {round((1 - c) * 100)}% of cases",
                                    act, severity=0.8, frequency=round(1 - c, 3),
                                    fixability=0.5, evidence_fqn=fqn))

    rec = mining.recording_errors(events)
    if rec:
        freq = len(rec) / n_cases
        fqn = "metric.recording-error.log"
        metrics.append((fqn, "cases_with_recording_errors", len(rec), {"cases": list(rec)[:20]}))
        findings.append(Finding("recording-error", "Out-of-order timestamps in the log", "log",
                                severity=0.3, frequency=round(freq, 3),
                                fixability=0.9, evidence_fqn=fqn))

    findings.sort(key=lambda f: f.score, reverse=True)
    return findings, metrics
