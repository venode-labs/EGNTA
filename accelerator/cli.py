"""Egenta CLI. Stdlib-only, so it runs on Linux, macOS and Windows with nothing
but a Python interpreter, and inside the container on any cloud.

    python -m accelerator version
    python -m accelerator bench [--real-llm] [--json] [--cases N]
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
    ap = argparse.ArgumentParser(prog="egenta", description="Egenta read-only discovery accelerator")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("version", help="print the version")
    b = sub.add_parser("bench", help="run the graded benchmark")
    b.add_argument("--real-llm", action="store_true", help="use the real Claude client (needs a key)")
    b.add_argument("--json", action="store_true")
    b.add_argument("--cases", type=int, default=120)
    sub.add_parser("selfcheck", help="run the test suite (needs pytest)")
    args = ap.parse_args(argv)

    if args.cmd in (None, "version"):
        print(f"EGNTA {__version__}")
        return 0
    if args.cmd == "bench":
        sys.path.insert(0, str(_ROOT))
        from bench import run as benchrun  # noqa: PLC0415
        bargv = (["--real-llm"] if args.real_llm else []) + (["--json"] if args.json else [])
        bargv += ["--cases", str(args.cases)]
        return benchrun.main(bargv)
    if args.cmd == "selfcheck":
        return subprocess.call([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=str(_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
