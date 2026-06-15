"""Regression gates for the hardening pass: the read-only SQL guard, timestamp
determinism and finiteness, connector scrubbing/robustness, metric dedup, the score
clamp, and the tightened grounding gate. Each pins a hole found in the line-by-line
audit so it cannot silently reopen."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accelerator import llm, readonly, synthesis, warehouse  # noqa: E402
from accelerator.connectors import csv_export  # noqa: E402
from accelerator.model import AnswerItem, Event, Finding  # noqa: E402
from accelerator.verticals import trades  # noqa: E402
from bench import metric  # noqa: E402


def test_select_only_blocks_cte_and_stacked_writes():
    for bad in ("WITH x AS (SELECT 1) DELETE FROM events",
                "SELECT 1; DROP TABLE events",
                "EXPLAIN DELETE FROM events",
                "SELECT 1; PRAGMA query_only=OFF"):
        try:
            readonly.assert_select_only(bad)
            assert False, f"must refuse: {bad}"
        except readonly.ReadOnlyViolation:
            pass
    for ok in ("SELECT * FROM events", "WITH x AS (SELECT 1) SELECT * FROM x", "EXPLAIN SELECT 1"):
        readonly.assert_select_only(ok)  # must not raise


def test_parse_ts_naive_is_utc_and_finite():
    assert csv_export._parse_ts("2026-01-15T08:30:00") == csv_export._parse_ts("2026-01-15T08:30:00+00:00")
    for bad in ("1e400", "nan", "-inf"):
        try:
            csv_export._parse_ts(bad)
            assert False, f"must reject non-finite: {bad}"
        except ValueError:
            pass


def test_connector_scrubs_and_handles_bom_and_missing_ts():
    secret = "sk-ant-api03-" + "A" * 30
    body = ("﻿job,status,when,note\n"            # BOM prefix (Excel) must not drop rows
            f"J1,quote,1700000000,key {secret}\n"     # secret in notes must be scrubbed
            "J2,quote,,no timestamp here\n")          # missing ts row skipped, not a crash
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.csv"
        p.write_text(body, encoding="utf-8")
        cm = csv_export.ColumnMap(case_id="job", activity="status", ts="when", resource="note")
        events = csv_export.read_export(p, cm)
    assert len(events) == 1                            # J1 kept, J2 (no ts) skipped
    assert secret not in events[0].resource           # scrubbed at the connector boundary


def test_read_json_rejects_malformed_shape():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.json"
        p.write_text("42", encoding="utf-8")           # scalar, not a row list
        cm = csv_export.ColumnMap(case_id="job", activity="status", ts="when")
        try:
            csv_export.read_export(p, cm)
            assert False, "must reject a non-list JSON export"
        except ValueError:
            pass


def test_metric_dedups_duplicate_findings():
    # two identical FALSE findings (match no answer) count as one false positive, not zero
    f = Finding("bottleneck", "x", "K", 0.5, 0.5, 0.5, "e")
    r = metric._prf([f, f], [AnswerItem("rework", "Q")])
    assert r["fp"] == 1


def test_score_clamp_neutralises_nan_and_out_of_range():
    assert synthesis._clamp01(float("nan")) == 0.5
    assert synthesis._clamp01(float("inf")) == 0.5
    assert synthesis._clamp01(5.0) == 1.0
    assert synthesis._clamp01(-2.0) == 0.0
    assert synthesis._clamp01("not a number") == 0.5


def test_grounding_gate_drops_mismatched_citation():
    # 10 completed jobs, 2 never invoiced -> the miner fires unbilled-completion and
    # writes metric.unbilled-completion.JobComplete. The mock model returns that finding
    # but cites a real entity id (fsm.job.0), NOT the supporting metric. The tightened
    # gate must drop the model's mis-cited finding; the safety net re-adds the
    # deterministic one, which carries the correct metric citation.
    events = []
    for i in range(10):
        for act in ("Quote", "QuoteApproved", "Scheduled", "Attended", "JobComplete"):
            events.append(Event(f"job-{i}", act, float(1_700_000_000 + i * 86400), "t", "fsm", f"fsm.job.{i}"))
        if i >= 2:  # 8 of 10 invoiced, 2 unbilled -> detector fires
            events.append(Event(f"job-{i}", "Invoice", float(1_700_000_500 + i * 86400), "t", "finance", f"finance.invoice.{i}"))
    mock = llm.Client(mock=True, mock_reply=json.dumps({"findings": [
        {"kind": "unbilled-completion", "key": "JobComplete", "evidence_fqn": "fsm.job.0",
         "severity": 0.9, "frequency": 0.5, "fixability": 0.5}]}))
    with tempfile.TemporaryDirectory() as d:
        c = warehouse.connect(Path(d) / "w.db")
        try:
            warehouse.init_schema(c)
            warehouse.insert_events(c, events)
            findings = synthesis.synthesise(c, mock, detect=trades.detect, system=synthesis._SYSTEM_TRADES)
        finally:
            c.close()
    unbilled = [f for f in findings if f.kind == "unbilled-completion"]
    assert unbilled, "the deterministic safety net should still surface unbilled-completion"
    # the surviving finding cites the metric, NOT the model's mismatched fsm.job.0
    assert unbilled[0].evidence_fqn == "metric.unbilled-completion.JobComplete"


def test_connector_scrubs_all_freetext_columns():
    # a secret in the STATUS or CASE column, not just notes, must be scrubbed
    aws = "AKIA" + "1234567890ABCDEF"
    body = (f"job,status,when,note\n{aws},quote,1700000000,clean\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.csv"
        p.write_text(body, encoding="utf-8")
        cm = csv_export.ColumnMap(case_id="job", activity="status", ts="when", resource="note")
        events = csv_export.read_export(p, cm)
    assert events, "row should ingest"
    blob = events[0].case_id + events[0].activity + events[0].entity_fqn
    assert aws not in blob, "a secret in the case/status column must be scrubbed too"


def test_card_split_across_newline_redacted():
    from accelerator import pii
    out, counts = pii.scrub("card 4111 1111 1111\n1111 here")
    assert counts.get("payment-card", 0) >= 1
    assert "1111 here" not in out or "[REDACTED" in out


def test_url_credential_with_slash_redacted():
    from accelerator import pii
    out, _ = pii.scrub("conn postgres://user:pa/ss@db.host/x")
    assert "pa/ss" not in out  # password with a slash no longer leaks


def test_report_cell_neutralises_formula_and_pipe():
    from accelerator import report
    out = report._cell("=cmd|danger")
    assert out.startswith("'")          # leading formula char neutralised
    assert "\\|" in out                 # pipe escaped so it cannot break the table


def test_synthesis_accept_path_keeps_model_finding():
    # the model returns a VALID, correctly-cited finding with a distinctive severity; the
    # gate must ACCEPT it (not fall back to the deterministic finding's severity 0.85),
    # proving the accept path works and is not masked by the safety net.
    events = []
    for i in range(10):
        for act in ("Quote", "QuoteApproved", "Scheduled", "Attended", "JobComplete"):
            events.append(Event(f"job-{i}", act, float(1_700_000_000 + i * 86400), "t", "fsm", f"fsm.job.{i}"))
        if i >= 2:
            events.append(Event(f"job-{i}", "Invoice", float(1_700_000_500 + i * 86400), "t", "finance", f"finance.invoice.{i}"))
    mock = llm.Client(mock=True, mock_reply=json.dumps({"findings": [
        {"kind": "unbilled-completion", "key": "JobComplete",
         "evidence_fqn": "metric.unbilled-completion.JobComplete",
         "severity": 0.99, "frequency": 0.5, "fixability": 0.5}]}))
    with tempfile.TemporaryDirectory() as d:
        c = warehouse.connect(Path(d) / "w.db")
        try:
            warehouse.init_schema(c)
            warehouse.insert_events(c, events)
            findings = synthesis.synthesise(c, mock, detect=trades.detect, system=synthesis._SYSTEM_TRADES)
        finally:
            c.close()
    unbilled = [f for f in findings if f.kind == "unbilled-completion"]
    assert unbilled and unbilled[0].severity == 0.99, "the accepted model finding's severity should survive"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS: {len(fns)} hardening tests")
