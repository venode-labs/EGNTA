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
from bench import baselines, generate, generate_trades, metric  # noqa: E402

# vertical -> (generator, deterministic pipeline, naive heuristic, llm product, llm baseline)
_VERTICALS = {
    "quote-to-cash": (generate.generate, baselines.egnta_pipeline, baselines.naive_baseline,
                      baselines.egnta_llm, baselines.llm_baseline),
    "trades": (generate_trades.generate, baselines.egnta_trades_pipeline,
               baselines.naive_trades_baseline, baselines.egnta_trades_llm,
               baselines.llm_trades_baseline),
}


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


def run(seed: int = 7, n_cases: int = 120, real_llm: bool = False,
        vertical: str = "quote-to-cash") -> dict:
    gen, det_pipeline, naive_fn, llm_product, llm_naive = _VERTICALS[vertical]
    events, entities, answer, secret = gen(n_cases=n_cases, seed=seed)
    usage = {}
    with tempfile.TemporaryDirectory() as d:
        dbp = Path(d) / "engagement.db"
        conn = warehouse.connect(dbp)
        try:
            warehouse.init_schema(conn)
            warehouse.upsert_entities(conn, entities)
            redactions = _ingest(conn, events)

            # leak check: the planted secret must not survive anywhere in the warehouse
            stored = " ".join(r["resource"] for r in conn.execute("SELECT resource FROM events"))
            leaked = secret in stored

            if real_llm:
                from accelerator import llm  # noqa: PLC0415
                client = llm.Client()
                if client.mock:
                    raise RuntimeError("real_llm requested but no key in vault/env (client is in mock mode)")
                egnta_findings = llm_product(conn, client)
                naive_findings = llm_naive(conn, client)
                usage = {"calls": client.calls, "input_tokens": client.input_tokens,
                         "output_tokens": client.output_tokens, "model": client.model}
                mode = "real-LLM: deterministic mining + grounded Claude synthesis vs naive single-LLM"
            else:
                egnta_findings = det_pipeline(conn)
                naive_findings = naive_fn(conn)
                mode = ("deterministic mining layer vs naive heuristic (lower bound / CI plumbing proof, "
                        "NOT the headline; run --real-llm for the headline)")

            egnta = metric.score_system(conn, egnta_findings, answer)
            naive = metric.score_system(conn, naive_findings, answer)
            rel_gated = metric.rel_error_reduction(egnta["gated"]["f1"], naive["gated"]["f1"])
            rel_ungated = metric.rel_error_reduction(egnta["ungated"]["f1"], naive["ungated"]["f1"])
            # absolute delta exposes REL inflation when the baseline is near ceiling
            abs_delta = round(egnta["gated"]["f1"] - naive["gated"]["f1"], 4)
        finally:
            conn.close()  # always close, so Windows can delete the temp warehouse

    return {
        "corpus": {"vertical": vertical, "cases": n_cases, "seed": seed,
                   "planted_defects": len(answer)},
        "ingest": {"redactions": redactions, "secret_leaked": leaked},
        "egnta": egnta, "naive": naive,
        "rel_error_reduction_gated": rel_gated,
        "rel_error_reduction_ungated": rel_ungated,
        "abs_f1_delta_gated": abs_delta,
        "target": 0.50, "real_llm": real_llm, "usage": usage, "note": mode,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EGNTA graded benchmark")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cases", type=int, default=120)
    ap.add_argument("--vertical", choices=sorted(_VERTICALS), default="quote-to-cash")
    ap.add_argument("--real-llm", action="store_true", help="use the real Claude client (spends credit)")
    args = ap.parse_args(argv)
    r = run(seed=args.seed, n_cases=args.cases, real_llm=args.real_llm, vertical=args.vertical)

    if r["ingest"]["secret_leaked"]:
        print("FAIL: planted secret leaked into the warehouse", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    e, n = r["egnta"]["gated"], r["naive"]["gated"]
    print(f"EGNTA benchmark, vertical: {r['corpus']['vertical']}\n")
    print(f"  corpus: {r['corpus']['cases']} cases, {r['corpus']['planted_defects']} planted defects")
    print(f"  ingest: {r['ingest']['redactions']} redactions, secret leaked: {r['ingest']['secret_leaked']}")
    print(f"  egnta  gated  P={e['precision']} R={e['recall']} F1={e['f1']}  halluc={r['egnta']['hallucination_rate']}")
    print(f"  naive   gated  P={n['precision']} R={n['recall']} F1={n['f1']}  halluc={r['naive']['hallucination_rate']}")
    print(f"  REL error reduction (gated)   = {r['rel_error_reduction_gated']}  (target {r['target']})")
    print(f"  absolute gated-F1 delta       = {r.get('abs_f1_delta_gated')}  (exposes REL inflation near ceiling)")
    print(f"  REL error reduction (ungated) = {r['rel_error_reduction_ungated']}")
    if r.get("usage"):
        u = r["usage"]
        print(f"  llm usage: {u['calls']} calls, {u['input_tokens']} in / {u['output_tokens']} out tokens ({u['model']})")
    print(f"\n  mode: {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
