"""Validate the deterministic core on a REAL public event log, not the synthetic corpus.

The graded benchmark runs on a generated corpus so it has a ground-truth answer key.
This is the other half of the honesty story: prove the connector and the clean-room
miner handle real-world data, variable case lengths, real timestamps with offsets,
genuine noise. It runs the GENERIC miner (the trades detectors are domain-specific);
the point is that the ingest + mining core is not synthetic-only.

Not part of CI (CI stays hermetic, no network, no bundled data). Point it at any
event-log CSV in the XES column convention, or your own export.

  python3 -m bench.validate_real_log path/to/log.csv \
      --case-col case:concept:name --activity-col concept:name --ts-col time:timestamp

Verified once on the public "receipt" log (receipt phase of a Dutch environmental
permit process, pm4py-core test data): 8577 events, 1434 cases, 27 activities,
ingested in well under a second, 10 grounded findings (control-gaps and a bottleneck).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accelerator import pain, warehouse  # noqa: E402
from accelerator.connectors import csv_export  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="validate the EGNTA core on a real event log")
    ap.add_argument("path")
    ap.add_argument("--case-col", default="case:concept:name")
    ap.add_argument("--activity-col", default="concept:name")
    ap.add_argument("--ts-col", default="time:timestamp")
    ap.add_argument("--resource-col", default="org:resource")
    args = ap.parse_args(argv)

    cmap = csv_export.ColumnMap(case_id=args.case_col, activity=args.activity_col,
                                ts=args.ts_col, resource=args.resource_col, source_system="real")
    events = csv_export.read_export(args.path, cmap, normalise=lambda s: s.strip())
    n_cases = len({e.case_id for e in events})
    n_acts = len({e.activity for e in events})
    print(f"ingested {len(events)} events, {n_cases} cases, {n_acts} activities from {args.path}")

    with tempfile.TemporaryDirectory() as d:
        conn = warehouse.connect(Path(d) / "real.db")
        try:
            warehouse.init_schema(conn)
            warehouse.insert_events(conn, events)
            findings, _ = pain.detect(warehouse.load_events(conn))
        finally:
            conn.close()

    print(f"deterministic miner produced {len(findings)} grounded findings:")
    for f in sorted(findings, key=lambda x: x.score, reverse=True):
        print(f"  [{f.kind}] {f.title}  (score {f.score})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
