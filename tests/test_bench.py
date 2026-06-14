"""End-to-end benchmark gate: the deterministic layer must beat the naive baseline
on the planted corpus, the metric must compute, and the ingest scrubber must never
leak the planted secret. This is the runnable proof behind the improvement claim
(for the deterministic layer; the real-LLM headline is iteration 2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench import metric, run  # noqa: E402


def test_no_secret_leak():
    r = run.run()
    assert r["ingest"]["secret_leaked"] is False
    assert r["ingest"]["redactions"] >= 1


def test_egenta_beats_naive_and_is_grounded():
    r = run.run()
    assert r["egenta"]["gated"]["f1"] > r["naive"]["gated"]["f1"]
    assert r["egenta"]["hallucination_rate"] == 0.0           # every finding grounded
    assert r["rel_error_reduction_gated"] >= 0.50             # the pre-registered target, deterministic layer


def test_metric_rel_formula():
    assert metric.rel_error_reduction(1.0, 0.0) == 1.0
    assert metric.rel_error_reduction(0.6, 0.2) == 0.5        # (0.6-0.2)/(1-0.2)
    assert metric.rel_error_reduction(0.5, 1.0) == 0.0        # guard divide-by-zero


def test_corpus_is_deterministic():
    a = run.run(seed=7)
    b = run.run(seed=7)
    assert a["egenta"]["gated"]["f1"] == b["egenta"]["gated"]["f1"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS: {len(fns)} bench tests")
