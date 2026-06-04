#!/usr/bin/env python
import argparse
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

from common import (
    fingerprint_messages,
    normalize_messages,
    read_jsonl,
    resolve_path,
    write_jsonl_record,
)


def load_local_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for _, row in read_jsonl(path):
        yield row


def load_source(source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    source_type = source.get("type", "hf")
    if source_type == "local_jsonl":
        yield from load_local_jsonl(resolve_path(source["path"]))
        return

    if source_type == "hf":
        from datasets import load_dataset

        dataset = load_dataset(
            source["path"],
            split=source.get("split", "train"),
            streaming=bool(source.get("streaming", False)),
        )
        for row in dataset:
            yield row
        return

    raise ValueError(f"unknown source type: {source_type}")


def require_source_ready(source: dict[str, Any]) -> None:
    if not source.get("enabled", True):
        raise RuntimeError("disabled")
    license_value = str(source.get("license", "")).strip()
    if not license_value:
        raise ValueError(f"{source['name']}: missing license")
    if license_value.startswith("check-"):
        raise ValueError(f"{source['name']}: license is not verified: {license_value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and normalize SFT datasets into JSONL.")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()

    cfg_path = resolve_path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text())
    output_cfg = cfg["output"]

    train_path = resolve_path(output_cfg["train_path"])
    eval_path = resolve_path(output_cfg["eval_path"])
    train_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(int(output_cfg.get("seed", 3407)))
    eval_fraction = float(output_cfg.get("eval_fraction", 0.02))
    max_total = output_cfg.get("max_total_records")
    max_total = int(max_total) if max_total is not None else None

    seen: set[str] = set()
    stats: Counter[str] = Counter()

    with train_path.open("w", encoding="utf-8") as train_f, eval_path.open(
        "w", encoding="utf-8"
    ) as eval_f:
        for source in cfg.get("sources", []):
            name = source["name"]
            try:
                require_source_ready(source)
            except RuntimeError:
                stats[f"{name}:skipped_disabled"] += 1
                continue

            limit = source.get("limit")
            limit = int(limit) if limit is not None else None

            for source_count, row in enumerate(load_source(source), start=1):
                if limit is not None and source_count > limit:
                    break
                if max_total is not None and stats["written"] >= max_total:
                    break

                try:
                    messages = normalize_messages(row)
                except Exception:
                    stats[f"{name}:bad"] += 1
                    continue

                fp = fingerprint_messages(messages)
                if fp in seen:
                    stats[f"{name}:duplicate"] += 1
                    continue
                seen.add(fp)

                record = {
                    "messages": messages,
                    "source": name,
                    "license": source["license"],
                }
                if source.get("notes"):
                    record["notes"] = source["notes"]

                out = eval_f if rng.random() < eval_fraction else train_f
                write_jsonl_record(out, record)
                stats["written"] += 1
                stats[f"{name}:written"] += 1

            if max_total is not None and stats["written"] >= max_total:
                break

    print(f"wrote train: {train_path}")
    print(f"wrote eval:  {eval_path}")
    for key, value in sorted(stats.items()):
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
