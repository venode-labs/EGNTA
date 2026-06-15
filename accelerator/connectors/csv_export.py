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
from datetime import timezone
from pathlib import Path

from .. import pii
from ..model import Event
from ..verticals import trades

import math

# a hostile or fat export should not OOM the process; cap rows ingested per file.
MAX_ROWS = 5_000_000


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
    """Epoch seconds from a numeric epoch or an ISO 8601 string. A naive ISO string
    (no offset) is read as UTC so the same export gives the same epoch on any host,
    the determinism the product claims. A timestamp that will not parse, or is not
    finite, raises rather than ingesting a silent wrong time a bottleneck would trust."""
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).strip()
        try:
            val = float(s)
        except ValueError:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            val = dt.timestamp()
    if not math.isfinite(val):
        raise ValueError(f"non-finite timestamp: {raw!r}")
    return val


def _to_event(row: dict, cmap: ColumnMap, normalise) -> Event | None:
    case_id = str(row.get(cmap.case_id, "")).strip()
    raw_activity = str(row.get(cmap.activity, "")).strip()
    ts_raw = row.get(cmap.ts)
    # a row with no case, no status, or no timestamp is not an event; skip, do not crash
    if not case_id or not raw_activity or ts_raw in (None, ""):
        return None
    ts = _parse_ts(ts_raw)
    # scrub EVERY operator-mapped free-text field at the connector boundary, not just
    # the notes column. A credential or card in the case, status or entity column reaches
    # the warehouse and the model otherwise (mining keys metrics off the activity and
    # case id, and synthesis feeds those to the model), so one scrubbed column is not enough.
    case_id, _ = pii.scrub(case_id)
    activity, _ = pii.scrub(normalise(raw_activity))
    resource = str(row.get(cmap.resource, "")) if cmap.resource else ""
    if resource:
        resource, _ = pii.scrub(resource)
    if cmap.entity_fqn and row.get(cmap.entity_fqn):
        fqn, _ = pii.scrub(str(row[cmap.entity_fqn]).strip())
    else:
        fqn = f"{cmap.source_system}.job.{case_id}"
    return Event(case_id, activity, ts, resource, cmap.source_system, fqn)


def read_csv(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Read a CSV export into canonical events. Rows missing a case, status or
    timestamp are skipped; a malformed timestamp raises. utf-8-sig strips the BOM
    Excel writes, which would otherwise glue to the first header and drop every row."""
    events: list[Event] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= MAX_ROWS:
                raise ValueError(f"export exceeds {MAX_ROWS} rows; refusing to ingest unbounded")
            ev = _to_event(row, cmap, normalise)
            if ev is not None:
                events.append(ev)
    return events


_MAX_JSON_BYTES = 256 * 1024 * 1024   # stdlib json can't stream, so cap the file before load


def read_json(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Read a JSON export (a list of row objects, or an object with a 'rows' list). The
    file is size-checked before loading, since json.load reads it whole into memory and
    the row cap below cannot prevent an OOM on a multi-gigabyte JSON file."""
    if Path(path).stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"JSON export exceeds {_MAX_JSON_BYTES} bytes; refusing to load unbounded")
    with Path(path).open(encoding="utf-8-sig") as fh:
        data = json.load(fh)
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("JSON export must be a list of rows or an object with a 'rows' list")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"export exceeds {MAX_ROWS} rows; refusing to ingest unbounded")
    events: list[Event] = []
    for row in rows:
        if not isinstance(row, dict):
            continue  # skip a non-object row rather than crash on it
        ev = _to_event(row, cmap, normalise)
        if ev is not None:
            events.append(ev)
    return events


def read_export(path, cmap: ColumnMap, normalise=trades.canonical_activity) -> list[Event]:
    """Dispatch on extension. .json reads JSON, everything else reads CSV."""
    return (read_json if str(path).lower().endswith(".json") else read_csv)(path, cmap, normalise)
