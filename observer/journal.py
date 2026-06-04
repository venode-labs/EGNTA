"""Egenta journal: append-only triage records. Writes live ONLY inside
~/Egenta/journal, which the write gate in the system prompt allows without
asking. One JSON object per line in triage.ndjson.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_JOURNAL = Path.home() / "Egenta" / "journal"


def _journal_file(journal_dir) -> Path:
    return Path(journal_dir) / "triage.ndjson"


def append_record(record: dict, journal_dir=DEFAULT_JOURNAL) -> None:
    d = Path(journal_dir)
    d.mkdir(parents=True, exist_ok=True)
    with _journal_file(d).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_finding(record: dict, journal_dir=DEFAULT_JOURNAL) -> None:
    """Deep-brain findings live beside the triage journal, in findings.ndjson.
    Same append-only contract, same inside-Egenta-only write."""
    d = Path(journal_dir)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "findings.ndjson").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def triaged_ids(journal_dir=DEFAULT_JOURNAL) -> set[str]:
    """Session ids that already have an 'ok' record. Read the journal once, so a
    triage run over many sessions does not re-scan a growing file per session.
    Pending records do not count, a failed model call is retried next run."""
    f = _journal_file(journal_dir)
    ids: set[str] = set()
    if not f.exists():
        return ids
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok" and rec.get("id"):
            ids.add(rec["id"])
    return ids


def already_triaged(session_id: str, journal_dir=DEFAULT_JOURNAL) -> bool:
    return session_id in triaged_ids(journal_dir)
