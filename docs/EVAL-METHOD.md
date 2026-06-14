# Egenta eval method, pre-registered

The claim "Egenta is better than the alternative" is treated as a measurement
problem, not a marketing line. This document pre-registers the metric so the
number cannot be reverse-fitted later.

## Corpus

`bench/generate.py` builds a synthetic quote-to-cash business across CRM and
finance source systems and plants four labelled defects with a ground-truth
answer key: a bottleneck transition, a skipped control (approval), a rework loop,
and out-of-order recording errors. Deterministic given a seed. A fake secret is
planted in a free-text field so the ingest scrubber is graded too.

## Metric

Detection precision/recall/F1 of the emitted pain register against the answer key,
computed two ways:

- **ungated**: every finding counts.
- **gated**: only findings whose `evidence_fqn` resolves in the warehouse count
  (the grounding/faithfulness gate).

Both are reported, because the gate is asymmetric (only Egenta grounds by design),
and reporting only the gated number would flatter Egenta. Hallucination rate
(ungrounded findings over total) is reported per system.

The headline is **relative error reduction in gated detection-F1 against the naive
baseline**:

```
REL = (F1_egenta - F1_baseline) / (1 - F1_baseline)
```

Target: REL >= 0.50. PM4Py is NOT part of this metric. It validates only the
process-conformance sub-metric (reported as the fitness/precision/generalisation/
simplicity 4-vector, never a single number, because precision measures are
axiomatically unreliable), and only as an out-of-process oracle.

## Known gameability and the mitigations

The red-team flagged two real ways REL can be rigged:

1. **Baseline strength is the one knob.** A weak/strawman baseline inflates REL
   (the denominator). Mitigation: the baseline is a genuine simple single-pass,
   not a strawman, and in iteration 2 becomes a real single-LLM prompt with the
   same warehouse, schema hints, and output coaching Egenta gets. The baseline
   spec is frozen here.
2. **Gate asymmetry.** The faithfulness gate is applied identically to both
   systems and both gated and ungated numbers are reported, so a gap the gate
   manufactures is visible, not hidden.

Further: the generator, answer key, and matcher are in-house (grade-your-own-
homework risk). Mitigation for iteration 2+: freeze and publish the defect
taxonomy and a synonym table, and add held-out defect types the engine was not
tuned on.

## Honest status

- **Iteration 1 (now):** the DETERMINISTIC mining layer vs the naive heuristic, on
  the synthetic corpus, runs in CI with no LLM key. Result: gated F1 1.0 vs 0.333,
  REL = 1.0, zero hallucinations, zero secret leak. This is a **lower bound and a
  plumbing proof**, NOT the headline.
- **Iteration 2 (deferred, needs an Anthropic key):** the grounded LLM synthesis
  layer and a real single-LLM baseline. The headline real-LLM REL is measured
  here and is allowed to honestly report a miss; "tune until >= 0.50" is a research
  outcome, not a scheduled deliverable.

No "Egenta is 50% better" claim may appear in any deck, README, or proposal until
the iteration-2 real-LLM run exists. Until then the only true statement is "metric
pre-registered, deterministic-layer lower bound measured".
