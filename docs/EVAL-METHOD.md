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
- **Iteration 2, real-LLM headline (15/06/2026, claude-sonnet-4-6, 120-case corpus,
  2 calls, ~2.3k tokens, ~2 cents):** Egenta (deterministic mining + grounded
  synthesis) gated F1 **1.0** (precision 1.0, recall 1.0, 0 false positives, 0
  hallucination) vs a fair naive single-LLM baseline gated F1 **0.889** (precision
  0.8, recall 1.0, 1 false positive). REL = **1.0**, which clears the pre-registered
  0.50 target. Stable across two runs.

## Honest reading of that number

REL 1.0 meets the target but is FLATTERED, and the build says so out loud:

- The absolute gated-F1 gain is only **+0.111** (eliminating one false positive).
  REL amplifies it to 1.0 because the baseline is near ceiling (denominator
  1 - 0.889 = 0.111). The runner now prints `abs_f1_delta_gated` next to REL so the
  inflation is never hidden.
- A well-fed single LLM already finds all four planted defects (recall 1.0). These
  four defect types are too easy to be discriminating. So detection-F1 is NOT where
  Egenta wins big.
- Egenta's genuine, non-inflated edge on this corpus: **precision 1.0 vs 0.8**
  (zero false claims), **zero hallucination** under the grounding gate,
  **determinism**, an **immutable evidence citation per finding**, and **cost** (two
  calls, a couple of cents).

## Honest limitation and next step

The headline detection number is only as meaningful as the corpus is hard. The next
step to make detection-F1 discriminating is a **held-out harder corpus**: defect
types the deterministic miner has no detector for (segregation-of-duties, subtle
non-slowest bottlenecks, cross-source inconsistencies), where a single-pass LLM
genuinely struggles and the grounded-synthesis layer has to earn its recall from the
raw summary. Until that exists, the honest claim is: "Egenta matches a strong single
LLM on detecting in-scope defects while eliminating false positives and
hallucinations, deterministically and cheaply; the pre-registered REL target is met
but flattered by an easy corpus." Do not claim "50% better at finding problems"
without the harder corpus.
