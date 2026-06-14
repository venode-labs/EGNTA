"""Unit gates for the discovery engine: mining correctness, the warehouse
read-only enforcement, the read-only guards, and the PII+credential scrubber."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accelerator import mining, pii, readonly, warehouse  # noqa: E402
from accelerator.model import Entity, Event  # noqa: E402


def _log():
    # two clean cases A,B following a->b->c; case C has an out-of-order ts
    return [
        Event("A", "a", 10), Event("A", "b", 20), Event("A", "c", 30),
        Event("B", "a", 10), Event("B", "b", 20), Event("B", "b", 25), Event("B", "c", 40),
        Event("C", "a", 100), Event("C", "b", 50), Event("C", "c", 120),  # b before a in ts
    ]


def test_directly_follows():
    # case C has out-of-order ts, so under the temporal DFG it re-sorts to b->a->c
    # and does not contribute an a->b / b->c edge. A and B do. Hence 2, not 3.
    dfg = mining.directly_follows(_log())
    assert dfg[("a", "b")] == 2
    assert dfg[("b", "c")] == 2
    assert dfg[("b", "b")] == 1  # case B rework


def test_rework_detects_repeat():
    rw = mining.rework(_log())
    assert rw.get("b") == 1  # only case B repeats b


def test_recording_error_needs_ingest_order():
    # in ingest order, case C has b(50) after a(100): out of order
    rec = mining.recording_errors(_log())
    assert "C" in rec and rec["C"] >= 1


def test_coverage():
    cov = mining.activity_case_coverage(_log())
    assert cov["a"] == 1.0


def test_warehouse_readonly_blocks_writes():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "w.db"
        c = warehouse.connect(p)
        warehouse.init_schema(c)
        warehouse.insert_events(c, [Event("A", "a", 1.0, entity_fqn="e.1")])
        c.close()
        ro = warehouse.connect(p, read_only=True)
        try:
            ro.execute("INSERT INTO events(case_id,activity,ts) VALUES('x','y',1)")
            raised = False
        except sqlite3.OperationalError:
            raised = True
        assert raised, "read-only handle must refuse writes"
        ro.close()


def test_citation_resolves():
    with tempfile.TemporaryDirectory() as d:
        c = warehouse.connect(Path(d) / "w.db")
        try:
            warehouse.init_schema(c)
            warehouse.upsert_entities(c, [Entity("crm.deal.1", "deal")])
            warehouse.write_metric(c, "metric.x", "x", 1.0, {})
            assert warehouse.citation_resolves(c, "crm.deal.1")
            assert warehouse.citation_resolves(c, "metric.x")
            assert not warehouse.citation_resolves(c, "does.not.exist")
            assert not warehouse.citation_resolves(c, "")
        finally:
            c.close()  # Windows cannot delete the temp .db while the handle is open


def test_select_only_guard():
    readonly.assert_select_only("SELECT 1")
    for bad in ("INSERT INTO t VALUES(1)", "DROP TABLE t", "UPDATE t SET a=1", "PRAGMA query_only=OFF"):
        try:
            readonly.assert_select_only(bad)
            assert False, f"should refuse: {bad}"
        except readonly.ReadOnlyViolation:
            pass


def test_tool_guard():
    assert readonly.read_only_tool_guard("Write", {})[0] == "deny"
    assert readonly.read_only_tool_guard("http", {"method": "POST"})[0] == "deny"
    assert readonly.read_only_tool_guard("http", {"method": "GET"})[0] == "allow"
    assert readonly.read_only_tool_guard("warehouse_query", {"sql": "SELECT 1"})[0] == "allow"
    assert readonly.read_only_tool_guard("warehouse_query", {"sql": "DELETE FROM t"})[0] == "deny"
    assert readonly.read_only_tool_guard("unknown_tool", {})[0] == "deny"  # default-deny


def test_pii_scrubs_card_phone_credential():
    text = "card 4111 1111 1111 1111 phone +61 2 9876 5432 key sk-ant-api03-" + "A" * 24
    out, counts = pii.scrub(text)
    assert "4111 1111 1111 1111" not in out and counts.get("payment-card", 0) >= 1
    assert "9876 5432" not in out and counts.get("phone", 0) >= 1
    assert "sk-ant-api03-" + "A" * 24 not in out  # credential wall still fires
    # a non-card 16-digit-ish that fails Luhn should not be flagged as a card
    out2, c2 = pii.scrub("order 1234 5678 9012 3456")
    assert c2.get("payment-card", 0) == 0


def test_dfg_fitness():
    ref = mining.directly_follows([Event("A", "a", 1), Event("A", "b", 2), Event("A", "c", 3)])
    good = mining.dfg_fitness([Event("B", "a", 1), Event("B", "b", 2), Event("B", "c", 3)], ref)
    assert good == 1.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS: {len(fns)} engine tests")
