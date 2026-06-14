"""The canonical per-engagement warehouse.

SQLite by default so the whole engine and its eval run with zero infrastructure
(a dockerised Postgres with a SELECT-only role is the production parity target,
iteration 2). Read-only is enforced at the database layer: a read-only handle
opens the file with mode=ro and sets PRAGMA query_only, so even a bug in a
reasoner cannot mutate a client's warehouse. That is one of the two read-only
layers that are genuinely enforceable today; OAuth-scope and egress-proxy layers
are documented stubs in readonly.py.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .model import Entity, Event, Finding

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    case_id      TEXT NOT NULL,
    activity     TEXT NOT NULL,
    ts           REAL NOT NULL,
    resource     TEXT DEFAULT '',
    source_system TEXT DEFAULT '',
    entity_fqn   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_events_case ON events(case_id, ts);
CREATE TABLE IF NOT EXISTS entities (
    fqn          TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    name         TEXT DEFAULT '',
    source_system TEXT DEFAULT '',
    attrs_json   TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS metrics (
    fqn          TEXT PRIMARY KEY,   -- citeable, e.g. metric.bottleneck.Quote->Approve
    name         TEXT NOT NULL,
    value        REAL,
    evidence_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS findings (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    key          TEXT NOT NULL,
    severity     REAL, frequency REAL, fixability REAL, score REAL,
    evidence_fqn TEXT DEFAULT '',
    confidence   REAL DEFAULT 1.0
);
-- append-only audit: every read-only decision logged, never updated or deleted
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY,
    ts           REAL NOT NULL,
    actor        TEXT, action TEXT, target TEXT,
    verb         TEXT, decision TEXT
);
"""


def connect(path, read_only: bool = False) -> sqlite3.Connection:
    """Open the warehouse. read_only opens the file mode=ro and sets query_only,
    so writes raise sqlite3.OperationalError, the enforced DB-layer read-only."""
    p = Path(path)
    if read_only:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
    else:
        conn = sqlite3.connect(str(p))
        conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def insert_events(conn: sqlite3.Connection, events: list[Event]) -> None:
    conn.executemany(
        "INSERT INTO events(case_id,activity,ts,resource,source_system,entity_fqn) "
        "VALUES(?,?,?,?,?,?)",
        [(e.case_id, e.activity, e.ts, e.resource, e.source_system, e.entity_fqn) for e in events],
    )
    conn.commit()


def upsert_entities(conn: sqlite3.Connection, entities: list[Entity]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO entities(fqn,kind,name,source_system,attrs_json) VALUES(?,?,?,?,?)",
        [(e.fqn, e.kind, e.name, e.source_system, json.dumps(e.attrs)) for e in entities],
    )
    conn.commit()


def write_metric(conn: sqlite3.Connection, fqn: str, name: str, value: float, evidence: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO metrics(fqn,name,value,evidence_json) VALUES(?,?,?,?)",
        (fqn, name, value, json.dumps(evidence)),
    )
    conn.commit()


def write_findings(conn: sqlite3.Connection, findings: list[Finding]) -> None:
    conn.executemany(
        "INSERT INTO findings(kind,title,key,severity,frequency,fixability,score,evidence_fqn,confidence) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        [(f.kind, f.title, f.key, f.severity, f.frequency, f.fixability, f.score, f.evidence_fqn, f.confidence)
         for f in findings],
    )
    conn.commit()


def load_events(conn: sqlite3.Connection) -> list[Event]:
    # ingest order (id), NOT ts: recording-error detection needs the original
    # order to compare against timestamps. Temporal metrics re-sort by ts internally.
    rows = conn.execute(
        "SELECT case_id,activity,ts,resource,source_system,entity_fqn FROM events ORDER BY case_id, id"
    ).fetchall()
    return [Event(r["case_id"], r["activity"], r["ts"], r["resource"], r["source_system"], r["entity_fqn"])
            for r in rows]


def citation_resolves(conn: sqlite3.Connection, fqn: str) -> bool:
    """A finding is grounded if its evidence_fqn resolves to a real entity, metric,
    or event entity_fqn in this warehouse. This is the deterministic faithfulness
    check the eval uses as its hallucination gate."""
    if not fqn:
        return False
    for sql in (
        "SELECT 1 FROM entities WHERE fqn=? LIMIT 1",
        "SELECT 1 FROM metrics WHERE fqn=? LIMIT 1",
        "SELECT 1 FROM events WHERE entity_fqn=? LIMIT 1",
    ):
        if conn.execute(sql, (fqn,)).fetchone():
            return True
    return False
