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

## Results

- **Iteration 1, deterministic layer (CI default, no key):** gated F1 1.0 vs the
  naive heuristic 0.333, zero hallucinations, zero secret leak. A lower bound and
  a plumbing proof, not the headline.
- **Easy corpus (4 defects, all in-scope for the miner), real-LLM:** Egenta gated F1
  1.0 vs naive single-LLM 0.889, REL 1.0. This LOOKED like a clean win but was
  FLATTERED: the absolute gain was only +0.111 and the baseline was near ceiling
  (denominator 1 - 0.889). A well-fed single LLM finds all four easy defects, so
  detection-F1 here is not discriminating.
- **Discriminating corpus (5 defects, incl. a second bottleneck), iteration 3:** the
  miner reported only the single slowest transition, so the second bottleneck was
  genuinely held-out. Egenta then either missed it (precision-tuned, REL 0.444, under
  target) or caught it while over-flagging (REL negative). The 50% target was NOT met.
- **Iteration 4 fixed the real limitation the held-out defect exposed:** the miner now
  detects EVERY transition materially slower than the rest (>= 2x median), a
  generalisable capability, not a tune; and timing now excludes cases with corrupted
  timestamps (a data-quality fix) so recording errors stop creating false bottlenecks.
  Result, real-LLM, stable over runs: Egenta gated F1 **1.0** (P 1.0, R 1.0, catches
  the second bottleneck precisely) vs naive single-LLM **0.889**. REL **1.0**,
  absolute **+0.111**.

## Honest verdict on the 50% claim

The 50% target is met on this corpus (REL 1.0), but read it straight:

- **REL is still flattered.** The absolute gain is +0.111; REL amplifies it because the
  baseline is near ceiling. The runner prints `abs_f1_delta_gated` so this is visible.
- **The genuine iteration-4 win is real, though:** a generalisable multi-bottleneck
  detector plus a timestamp-quality fix, so the miner catches a defect the naive
  baseline misses (R 1.0 vs the baseline missing the second bottleneck), precisely.
  That is a capability improvement, not prompt-tuning against the answer key.
- **The honesty cost:** the corpus no longer contains a defect the miner cannot detect,
  so REL 1.0 here does NOT prove generalisation. A true generalisation test needs defect
  CLASSES outside the miner's detectors, segregation-of-duties, cross-source
  inconsistency, conformance violations, which remain untested and are the next step.

**What is substantiated (verified):** Egenta detects every defect type it has a detector
for, precisely and grounded (zero hallucination, every finding cites a warehouse fact),
deterministically and cheaply (two calls, a couple of cents), and beats a careful single
LLM on this corpus. The honest pitch is "grounded, deterministic, auditable, cheap
discovery that beats a strong LLM on the defects it detects", with generalisation to
undetected defect classes stated as open, NOT a blanket "50% better at finding any
problem".
