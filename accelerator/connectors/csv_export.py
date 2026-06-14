"""Read-only CSV / JSON export connector.

Trades data does not arrive over a tidy API; it arrives as an export. A ServiceM8,
simPRO or Uptick operator pulls a job or inspection report to CSV (or JSON), and
that file is the source. This connector reads such a file and normalises each row
into the canonical Event shape, mapping the raw status through a vertical's synonym
table on the way in.

Read-only by nature: it opens the file for reading and never writes back to it or
to the source system. That is the read-only guarantee at this layer, the file is
never the connector's to change.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from ..model import Event
from ..verticals import trades


class ColumnMap:
    """Which export columns carry which Event field. Only case_id, activity and ts
    are required; the rest default sensibly so a minimal export still ingests."""

    def __init__(self, case_id: str, activity: str, ts: str, resource: str = "",
                 entity_fqn: str = "", source_system: str = "fsm"):
        self.case_id = case_id
        self.activity = activity
        self.ts = ts
        self.resource = resource
        self.entity_fqn = entity_fqn
        self.source_system = source_system


def _parse_ts(raw) -> float:
    """Epoch seconds from a numeric epoch or an ISO 8601 string. A row whose
    timestamp will not parse raises, rather than ingesting a silent wrong time
    that a later bottleneck reading would treat as real."""
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    try:
        return float(s)
    except ValueError:
        pass
    iso = s.replace("Z", "+00:00")
    return datetime.fromisoformat(iso).timestamp()


def _to_event(row: dict, cmap: ColumnMap, normalise) -> Event | None:
    case_id = str(row.get(cmap.case_id, "")).strip()
    raw_activity = str(row.get(cmap.activity, "")).strip()
    if not case_id or not raw_activity:
        return None  # a row with no case or no status is not an event
    ts = _parse_ts(row[cmap.ts])
    resource = str(row.get(cmap.resource, "")) if cmap.resource else ""
    if cmap.entity_fqn and row.get(cmap.entity_fqn):
        fqn = str(row[cmap.entity_fqn]).strip()
    else:
        fqn = f"{cmap.source_system}.job.{case_id}"
    return Event(case_id, normalise(raw_activity), ts, resource, cmap.source_system, fqn)


def read_csv(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Read a CSV export into canonical events. Rows missing a case or status are
    skipped; a malformed timestamp raises."""
    events: list[Event] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ev = _to_event(row, cmap, normalise)
            if ev is not None:
                events.append(ev)
    return events


def read_json(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Read a JSON export (a list of row objects, or an object with a 'rows' list)."""
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
    events: list[Event] = []
    for row in rows:
        ev = _to_event(row, cmap, normalise)
        if ev is not None:
            events.append(ev)
    return events


def read_export(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Dispatch on extension. .json reads JSON, everything else reads CSV."""
    return (read_json if str(path).lower().endswith(".json") else read_csv)(path, cmap, normalise)
