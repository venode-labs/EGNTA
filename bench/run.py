"""End-to-end benchmark run: generate -> scrub at ingest -> load -> score both
systems -> report. Produces a real number for the deterministic discovery layer
and proves the ingest scrubber leaks nothing. Stdlib only, no infra, no LLM key.

Run: python3 -m bench.run            (human report)
     python3 -m bench.run --json     (machine report, for CI)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# make repo root importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accelerator import pii, warehouse  # noqa: E402
from accelerator.model import Event  # noqa: E402
from bench import baselines, generate, metric  # noqa: E402


def _ingest(conn, events: list[Event]) -> int:
    """Scrub every free-text field at the ingest boundary, then load. Returns the
    number of redactions, the proof the scrubber ran before anything was stored."""
    redactions = 0
    clean: list[Event] = []
    for e in events:
        scrubbed, counts = pii.scrub(e.resource)
        redactions += sum(counts.values())
        clean.append(Event(e.case_id, e.activity, e.ts, scrubbed, e.source_system, e.entity_fqn))
    warehouse.insert_events(conn, clean)
    return redactions


def run(seed: int = 7, n_cases: int = 120) -> dict:
    events, entities, answer, secret = generate.generate(n_cases=n_cases, seed=seed)
    with tempfile.TemporaryDirectory() as d:
        dbp = Path(d) / "engagement.db"
        conn = warehouse.connect(dbp)
        warehouse.init_schema(conn)
        warehouse.upsert_entities(conn, entities)
        redactions = _ingest(conn, events)

        # leak check: the planted secret must not survive anywhere in the warehouse
        stored = " ".join(r["resource"] for r in conn.execute("SELECT resource FROM events"))
        leaked = secret in stored

        egenta_findings = baselines.egenta_pipeline(conn)
        naive_findings = baselines.naive_baseline(conn)
        egenta = metric.score_system(conn, egenta_findings, answer)
        naive = metric.score_system(conn, naive_findings, answer)
        rel_gated = metric.rel_error_reduction(egenta["gated"]["f1"], naive["gated"]["f1"])
        rel_ungated = metric.rel_error_reduction(egenta["ungated"]["f1"], naive["ungated"]["f1"])
        conn.close()

    return {
        "corpus": {"cases": n_cases, "seed": seed, "planted_defects": len(answer)},
        "ingest": {"redactions": redactions, "secret_leaked": leaked},
        "egenta": egenta, "naive": naive,
        "rel_error_reduction_gated": rel_gated,
        "rel_error_reduction_ungated": rel_ungated,
        "target": 0.50,
        "note": ("Iteration 1: deterministic mining layer vs a naive heuristic baseline. "
                 "This is a lower bound and a plumbing proof, NOT the headline. The headline "
                 "50% is relative error reduction against a real single-LLM baseline with the "
                 "grounded synthesis layer, gated by faithfulness, and is deferred to iteration 2 "
                 "(needs an Anthropic key)."),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Egenta graded benchmark")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cases", type=int, default=120)
    args = ap.parse_args(argv)
    r = run(seed=args.seed, n_cases=args.cases)

    if r["ingest"]["secret_leaked"]:
        print("FAIL: planted secret leaked into the warehouse", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    e, n = r["egenta"]["gated"], r["naive"]["gated"]
    print("Egenta benchmark, iteration 1 (deterministic layer)\n")
    print(f"  corpus: {r['corpus']['cases']} cases, {r['corpus']['planted_defects']} planted defects")
    print(f"  ingest: {r['ingest']['redactions']} redactions, secret leaked: {r['ingest']['secret_leaked']}")
    print(f"  egenta  gated  P={e['precision']} R={e['recall']} F1={e['f1']}  halluc={r['egenta']['hallucination_rate']}")
    print(f"  naive   gated  P={n['precision']} R={n['recall']} F1={n['f1']}  halluc={r['naive']['hallucination_rate']}")
    print(f"  REL error reduction (gated)   = {r['rel_error_reduction_gated']}  (target {r['target']})")
    print(f"  REL error reduction (ungated) = {r['rel_error_reduction_ungated']}")
    print(f"\n  {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
