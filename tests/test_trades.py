"""Gates for the fire/trades vertical: the synonym map, the seven domain detectors
(including the honestly-missed held-out class), the read-only export connector, and
corpus determinism."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accelerator import warehouse  # noqa: E402
from accelerator.connectors import csv_export  # noqa: E402
from accelerator.model import Event  # noqa: E402
from accelerator.verticals import trades  # noqa: E402
from bench import generate_trades  # noqa: E402


def test_canonical_activity_maps_synonyms():
    assert trades.canonical_activity("quote accepted") == "QuoteApproved"
    assert trades.canonical_activity("On Site") == "Attended"
    assert trades.canonical_activity("AS1851 routine") == "RoutineService"
    # unknown status passes through, never silently dropped
    assert trades.canonical_activity("Custom Step") == "Custom Step"


def test_detects_planted_and_misses_heldout():
    events, _, answer, _ = generate_trades.generate()
    findings, _ = trades.detect(events)
    got = {(f.kind, f.key) for f in findings}
    # every class except the held-out duplicate-invoice has a detector and must fire,
    # including the cross-activity (segregation) and cross-source (orphan) ones
    detectable = [(a.kind, a.key) for a in answer if a.kind != "duplicate-invoice"]
    for kind, key in detectable:
        assert (kind, key) in got, f"detector missed planted {kind}/{key}"
    assert ("segregation-of-duties", "Quote/QuoteApproved") in got
    assert ("cross-source-orphan", "Invoice") in got
    # the held-out class has no detector and must NOT be fabricated
    assert ("duplicate-invoice", "Invoice/duplicate") not in got


def test_clean_log_stays_quiet():
    # one clean job: every stage present, even gaps, distinct quoter and approver,
    # billing recorded in finance against a completed job. Nothing should fire.
    res = {"Quote": "tech-1", "QuoteApproved": "mgr-1"}
    src = {"Invoice": "finance", "Paid": "finance"}
    ev, t = [], 1_700_000_000
    for act in ("Lead", "Quote", "QuoteApproved", "Scheduled", "Attended", "JobComplete",
                "Invoice", "Paid"):
        t += 3600
        fqn = "finance.invoice.1" if act in ("Invoice", "Paid") else "fsm.job.1"
        ev.append(Event("job-1", act, float(t), res.get(act, "tech-2"), src.get(act, "fsm"), fqn))
    findings, _ = trades.detect(ev)
    assert findings == []


def test_csv_connector_maps_and_is_readonly():
    rows = ("job,status,when\n"
            "J1,quote,1700000000\n"
            "J1,quote accepted,1700003600\n"
            "J1,on site,1700100000\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "export.csv"
        p.write_text(rows, encoding="utf-8")
        before = p.read_text(encoding="utf-8")
        cmap = csv_export.ColumnMap(case_id="job", activity="status", ts="when")
        events = csv_export.read_export(p, cmap)
        assert [e.activity for e in events] == ["Quote", "QuoteApproved", "Attended"]
        assert events[0].entity_fqn == "fsm.job.J1"   # default fqn when no column given
        assert p.read_text(encoding="utf-8") == before  # connector never writes the source


def test_json_connector_iso_timestamps():
    import json
    data = [{"job": "J9", "status": "completed", "when": "2026-01-15T08:30:00+00:00"}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "export.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        cmap = csv_export.ColumnMap(case_id="job", activity="status", ts="when")
        events = csv_export.read_export(p, cmap)
        assert len(events) == 1 and events[0].activity == "JobComplete"
        assert events[0].ts > 1_700_000_000  # ISO parsed to epoch


def test_corpus_deterministic():
    a, _, _, _ = generate_trades.generate(seed=7)
    b, _, _, _ = generate_trades.generate(seed=7)
    assert [(e.case_id, e.activity, e.ts) for e in a] == [(e.case_id, e.activity, e.ts) for e in b]


def test_trades_pipeline_grounds_and_beats_naive():
    from bench import run
    r = run.run(vertical="trades")
    assert r["ingest"]["secret_leaked"] is False
    assert r["egnta"]["hallucination_rate"] == 0.0
    assert r["egnta"]["gated"]["f1"] > r["naive"]["gated"]["f1"]
    # precision is the product's claimed edge: no false positives on the corpus.
    # Guards the compliance-flow transition leaking into dispatch-bottleneck.
    assert r["egnta"]["gated"]["precision"] == 1.0
    # held-out class means recall is honestly below 1.0
    assert r["egnta"]["gated"]["recall"] < 1.0


def test_report_renders_register():
    from accelerator import report
    from accelerator.model import Finding
    findings = [
        Finding("compliance-overdue", "3 assets overdue for AS 1851", "RoutineService",
                severity=0.95, frequency=0.2, fixability=0.7, evidence_fqn="metric.compliance-overdue.RoutineService"),
        Finding("unbilled-completion", "5 jobs never invoiced", "JobComplete",
                severity=0.85, frequency=0.1, fixability=0.8, evidence_fqn="metric.unbilled-completion.JobComplete"),
    ]
    md = report.render(findings, "trades")
    assert "pain register" in md.lower()
    assert "Critical" in md                       # severity band rendered
    assert "AS 1851" in md and "RoutineService" in md
    assert report.render([], "trades").lower().count("no material findings") == 1


def test_egress_allowlist_enforced():
    from accelerator import readonly
    readonly.egress_allowlist_check("api.anthropic.com", "GET")   # allowed
    for host, verb in (("evil.example", "GET"), ("api.anthropic.com", "POST")):
        try:
            readonly.egress_allowlist_check(host, verb)
            assert False, f"should refuse {host}/{verb}"
        except readonly.ReadOnlyViolation:
            pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS: {len(fns)} trades tests")
