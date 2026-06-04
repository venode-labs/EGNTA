#!/usr/bin/env python
"""Phase 3 redaction audit, the gate before any text reaches the deep brain or a
dataset. Runs the redactor over every transcript in a tree, then re-scans the
redacted output. A second-pass hit means a secret survived, which fails the audit.
Counts only are printed, never a secret. Exit 1 on any leak, so it works as a CI
or pre-train gate."""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "observer"))
from redactor import redact  # noqa: E402


def audit(root: pathlib.Path) -> int:
    files = sorted(p for p in root.rglob("*.jsonl") if p.is_file()) if root.is_dir() else [root]
    if not files:
        print(f"redact-audit: no files under {root}")
        return 0
    leaks = 0
    held_secrets = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        first = redact(text)
        if first.total:
            held_secrets += 1
        second = redact(first.text)
        if second.total:
            leaks += 1
            print(f"LEAK {path.name}: {second.total} survived ({', '.join(sorted(second.counts))})")
    print(f"redact-audit: {len(files)} files, {held_secrets} held secrets, {leaks} leak(s) after redaction")
    return 1 if leaks else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 3 redaction audit. Never prints a secret.")
    ap.add_argument(
        "path",
        nargs="?",
        default=str(pathlib.Path.home() / "clilogs/claude-logs/sessions"),
        help="file or directory of transcripts to audit",
    )
    args = ap.parse_args(argv)
    return audit(pathlib.Path(args.path).expanduser())


if __name__ == "__main__":
    raise SystemExit(main())
