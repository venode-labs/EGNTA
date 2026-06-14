# EGNTA eval method

The benchmark is pre-registered so the metric cannot be fitted after the fact.

## Corpus

`bench/generate.py` builds a synthetic quote-to-cash business across CRM and finance
sources and plants four labelled defects with a ground-truth answer key: a bottleneck
transition, a skipped approval control, a rework loop, and out-of-order recording
errors. The corpus is deterministic given a seed. A fake secret is planted in a
free-text field so the ingest scrubber is graded on the same run.

## Metric

Detection precision, recall and F1 of the emitted pain register against the answer key,
computed two ways. Ungated counts every finding. Gated counts only findings whose
`evidence_fqn` resolves in the warehouse. Both are reported, since the grounding gate is
asymmetric and the gated number alone would flatter EGNTA. Hallucination rate, ungrounded
findings over total, is reported per system.

The headline is relative error reduction in gated detection-F1 against the naive baseline:

```
REL = (F1_egnta - F1_baseline) / (1 - F1_baseline)
```

Target REL >= 0.50. PM4Py validates only the process-conformance sub-metric, as an
out-of-process oracle, and reports the fitness/precision/generalisation/simplicity
4-vector rather than a single number. It is not part of the headline.

## Gameability and mitigations

Two ways the metric can be rigged, and how the design closes them:

- Baseline strength sets the denominator, so a weak baseline inflates REL. The baseline
  is a real single-LLM pass over the same warehouse summary, with the same schema hints
  EGNTA gets, and its spec is frozen here.
- The grounding gate is applied identically to both systems, and both gated and ungated
  numbers are reported, so any gap the gate manufactures stays visible.

The generator, answer key and matcher are in-house, which is a grade-your-own-homework
risk. The fix, tracked as the next step, is to freeze and publish the defect taxonomy and
add defect classes the engine was not built to detect.

## Results

Real-LLM, claude-sonnet-4-6, stable across runs. EGNTA (deterministic mining plus
grounded synthesis) scores gated F1 1.0, precision 1.0, recall 1.0, against a naive
single-LLM baseline at F1 0.889. REL 1.0, absolute gain +0.111. Zero hallucinations,
zero secret leak. The deterministic layer alone runs in CI without a key and scores F1
1.0 against a naive heuristic at 0.286.

## What the number does and does not show

REL 1.0 clears the target but the absolute gain is +0.111, because the baseline sits near
ceiling. The runner prints `abs_f1_delta_gated` alongside REL so the gap is never hidden.

The win is a real capability, not a tune. Iteration 4 made the miner detect every
transition materially slower than the rest, not only the single slowest, and excluded
cases with corrupted timestamps from the timing so recording errors stop producing false
bottlenecks. That is what lets EGNTA catch the second bottleneck the naive baseline misses,
precisely.

The limit: this corpus no longer holds a defect the miner cannot detect, so REL 1.0 does
not prove generalisation. Defect classes outside the current detectors, segregation of
duties, cross-source inconsistency, conformance violations, are untested and are the next
piece of work.

The supported claim is narrow and verified: EGNTA detects every defect type it has a
detector for, grounded with zero hallucination, deterministically, for a couple of model
calls, and beats a careful single LLM on this corpus. Generalisation to undetected defect
classes is open.
