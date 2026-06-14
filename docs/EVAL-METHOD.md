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
- **Discriminating corpus (5 defects, incl. a HELD-OUT second bottleneck the
  deterministic miner cannot report), real-LLM, claude-sonnet-4-6, 2 calls/run,
  stable over two runs:**
  - Precision-tuned synthesis: Egenta gated F1 **0.889** (P 1.0, R 0.8) vs naive
    **0.8** (P 0.8, R 0.8). REL **0.444**, absolute **+0.089**.
  - Recall-favouring synthesis: Egenta catches the held-out defect (R 1.0) but
    over-flags (P 0.71, F1 0.833), scoring BELOW the naive baseline (REL negative).

## Honest verdict on the 50% claim

**The pre-registered 50% target is NOT met on the discriminating corpus.** REL 0.444
is just under 0.50, and the only way to push past it is to keep tuning the prompt
against an in-house answer key, which is the grade-your-own-homework trap the method
was designed to avoid. The easy-corpus REL 1.0 was an artefact of a near-ceiling
baseline, not a real 50% advantage.

There is a genuine precision/recall tradeoff a single-pass LLM synthesis cannot
cleanly resolve with prompting alone: it either catches the held-out defect at a
precision cost, or stays precise and misses it. Reliably catching held-out defects
precisely needs more than a prompt, a conformance-based detector or multi-pass
synthesis, which is real engineering, not a tuning knob.

**What IS substantiated (verified, not claimed):** Egenta modestly beats a careful
single LLM on this harder corpus (F1 0.889 vs 0.8) and its real, repeatable edge is
**precision and grounding** (every finding cites a resolvable warehouse fact, zero
hallucination under the gate), **determinism**, **auditability**, and **cost** (two
calls, a couple of cents). The honest pitch is "grounded, deterministic, auditable,
cheap discovery that matches a strong LLM and beats it on precision", NOT "50%
better at finding problems".
