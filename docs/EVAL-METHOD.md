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

## Trades vertical corpus

`bench/generate_trades.py` is the first-vertical corpus: a synthetic fire/service-trades
business across field-service, finance and compliance sources. It plants ten labelled
defects: unbilled job completion, defect-to-rectification stall, overdue AS 1851
compliance, approval gap, repeat-visit rework, dispatch bottleneck, recording error,
segregation of duties (same resource quotes and approves), cross-source orphan (billed in
finance with no field-service completion), and, held out on purpose, a duplicate invoice
across two finance entities. The held-out class needs entity resolution across invoices,
which no deterministic detector computes, so the miner cannot recover it.

Run it with `python3 -m bench.run --vertical trades`. Deterministic (no key), the trades
miner scores gated precision 1.0, recall 0.9, F1 0.947 (nine of ten caught with no false
positive, the held-out missed), zero hallucination, zero secret leak, against a naive
heuristic at 0.

This fixes the grade-your-own-homework risk the quote-to-cash corpus had grown into: its
held-out bottleneck became recoverable, so REL flattered to 1.0. The rule now is that
every detector added rotates in a harder held-out, so one class is always undetectable and
recall stays honestly below ceiling. Segregation of duties was the held-out, a detector
was written, so the duplicate invoice (needing entity resolution) is the new held-out. The
next real step is an entity-resolution detector for it, not a prompt tune against the key.

## Real public log

The graded corpus is synthetic so it can carry an answer key. The other half of the
honesty story is that the ingest and mining core is not synthetic-only.
`bench/validate_real_log.py` runs the read-only connector and the clean-room miner over a
real public process log in the XES column convention. Verified on the receipt phase of a
Dutch environmental-permit process (pm4py-core public test data): 8577 events, 1434 cases,
27 activities, ingested and mined in well under a second, producing 10 grounded findings
(control-gaps and a bottleneck) on real-world data with real timestamps and real noise.
Not part of CI (which stays hermetic, no network, no bundled data); it is a manual
validator. The trades vertical detectors are domain-specific and stay on the synthetic
corpus until a real trades export arrives; this validates the generic core.
