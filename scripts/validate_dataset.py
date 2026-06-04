#!/usr/bin/env python
import argparse
from pathlib import Path

from common import normalize_messages, read_jsonl, resolve_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SFT JSONL dataset rows.")
    parser.add_argument("path", type=Path, help="JSONL file to validate")
    parser.add_argument("--max-errors", type=int, default=20)
    args = parser.parse_args()

    path = resolve_path(args.path)
    total = 0
    errors = 0

    for line_no, row in read_jsonl(path):
        total += 1
        try:
            normalize_messages(row)
        except Exception as exc:
            errors += 1
            print(f"[ERROR] {path}:{line_no}: {exc}")
            if errors >= args.max_errors:
                break

    if errors:
        raise SystemExit(f"validation failed: {errors} bad rows out of {total}")

    print(f"validation passed: {total} rows")


if __name__ == "__main__":
    main()
