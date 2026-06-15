"""EGNTA CLI. Stdlib-only, so it runs on Linux, macOS and Windows with nothing
but a Python interpreter, and inside the container on any cloud.

    python -m accelerator version
    python -m accelerator bench [--vertical trades] [--real-llm] [--json] [--cases N]
    python -m accelerator report [--vertical trades] [--csv PATH]
    python -m accelerator selfcheck     # run the test suite if pytest is present
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from accelerator import __version__

_ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="egnta", description="EGNTA read-only discovery accelerator")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("version", help="print the version")
    b = sub.add_parser("bench", help="run the graded benchmark")
    b.add_argument("--vertical", default="quote-to-cash")
    b.add_argument("--real-llm", action="store_true", help="use the real Claude client (needs a key)")
    b.add_argument("--json", action="store_true")
    b.add_argument("--cases", type=int, default=120)
    rp = sub.add_parser("report", help="render a plain-language pain register")
    rp.add_argument("--vertical", default="trades")
    rp.add_argument("--csv", help="a field-service CSV/JSON export; omit to use the synthetic demo corpus")
    rp.add_argument("--case-col", default="job")
    rp.add_argument("--activity-col", default="status")
    rp.add_argument("--ts-col", default="when")
    sub.add_parser("selfcheck", help="run the test suite (needs pytest)")
    args = ap.parse_args(argv)

    if args.cmd in (None, "version"):
        print(f"EGNTA {__version__}")
        return 0
    if args.cmd == "bench":
        sys.path.insert(0, str(_ROOT))
        from bench import run as benchrun  # noqa: PLC0415
        bargv = (["--real-llm"] if args.real_llm else []) + (["--json"] if args.json else [])
        bargv += ["--cases", str(args.cases), "--vertical", args.vertical]
        return benchrun.main(bargv)
    if args.cmd == "report":
        sys.path.insert(0, str(_ROOT))
        from accelerator import report, warehouse  # noqa: PLC0415
        from accelerator.connectors import csv_export  # noqa: PLC0415
        from accelerator.verticals import trades  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        if args.csv:
            cmap = csv_export.ColumnMap(case_id=args.case_col, activity=args.activity_col, ts=args.ts_col)
            try:
                events = csv_export.read_export(args.csv, cmap)
            except (OSError, ValueError, KeyError) as e:
                print(f"error reading {args.csv}: {e}", file=sys.stderr)
                return 1
        else:
            from bench import generate_trades  # noqa: PLC0415
            events, _, _, _ = generate_trades.generate()
        with tempfile.TemporaryDirectory() as d:
            conn = warehouse.connect(Path(d) / "report.db")
            try:
                warehouse.init_schema(conn)
                warehouse.insert_events(conn, events)
                findings, _ = trades.detect(warehouse.load_events(conn))
            finally:
                conn.close()
        print(report.render(findings, args.vertical))
        return 0
    if args.cmd == "selfcheck":
        return subprocess.call([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=str(_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
