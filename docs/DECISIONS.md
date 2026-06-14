# Decisions

## 0003, enterprise architecture for the discovery accelerator (14/06/2026)

**Status:** accepted, iteration 1 shipped.

**Context.** Egenta is being built enterprise-grade as a read-only client-discovery
accelerator (atlas decisions 0001/0002: read-only, any business, configurable
engine). The field was reviewed at code level (PM4Py, bupaR, Apromore, ProM,
Airbyte, OpenMetadata) before writing a line.

**Decisions.**
- **Single language, Python.** The Claude Agent SDK has first-class Python
  PreToolUse hooks and `can_use_tool`; the redactor and mining/eval stack are
  Python; a TS split buys nothing but an IPC tax.
- **Clean-room miner, PM4Py as oracle only.** PM4Py is AGPL-3.0, viral over a
  network service. Egenta ships its own miner; PM4Py is dev/CI-only, never shipped,
  never conveyed over a network.
- **Eval-first.** The graded benchmark, synthetic corpus, and metric were built
  before the engine so the improvement claim is falsifiable, not retro-fitted. See
  EVAL-METHOD.md.
- **Reuse the redactor; add a PII pass.** The redactor is a credential wall, not a
  PII wall; `accelerator/pii.py` adds phone and payment-card scrubbing. Name PII
  is a flagged model-based stub for iteration 2.
- **Honest read-only accounting.** Two enforced layers now (SELECT-only handle,
  read-only tool guard); three labelled stubs that raise (OAuth scopes, egress
  proxy, network isolation). No "five layers" claim before they exist.
- **Warehouse: SQLite now, Postgres parity in iteration 2.** Zero-infra CI today.

**Consequences / honest boundary.**
- Iteration 1 (shipped): scaffold, canonical warehouse, clean-room mining, the
  two enforced read-only layers, the PII+credential scrubber, the graded benchmark
  with a planted-defect answer key, the naive baseline, green CI. The deterministic
  layer scores gated F1 1.0 vs 0.333 naive (REL 1.0) on the synthetic corpus, a
  lower bound, not the headline.
- Iterations 2-3 (deferred, need an Anthropic key + live infra): the grounded LLM
  synthesis layer, a real single-LLM baseline, real connectors, Postgres parity,
  and the headline real-LLM 50% measurement, which is allowed to honestly report a
  miss. Live connectors, OAuth, client Postgres, and the Anthropic key are explicit
  stubs, not claimed as done.

## 0004, iteration 2 shipped, the real-LLM headline (15/06/2026)

**Status:** accepted, shipped.

**What.** The grounded synthesis layer (`accelerator/synthesis.py`, Claude reasons
over the deterministic mining, every finding cites a resolvable evidence_fqn or is
dropped, with a safety net so it never regresses below the miner), a thin
vault-keyed Claude client (`accelerator/llm.py`, key from `vault get
anthropic/api-key`, prompt-cached system, mock mode for CI), and a fair naive
single-LLM baseline. Both systems get the same warehouse summary. `bench.run
--real-llm` measures the headline; CI stays on the deterministic path (no key).

**Result (honest, after iteration 3 added a held-out defect).** On the EASY 4-defect
corpus Egenta scored F1 1.0 vs naive 0.889 (REL 1.0), but that was flattered by a
near-ceiling baseline. On the DISCRIMINATING corpus (5 defects incl a held-out
second bottleneck the miner cannot report), precision-tuned Egenta scores F1 0.889
(P 1.0, R 0.8) vs naive 0.8, REL **0.444**, just under target; recall-favouring
Egenta catches the held-out (R 1.0) but over-flags and scores below naive. **The 50%
target is NOT met on the discriminating corpus.** See EVAL-METHOD.md.

**Honest verdict.** Egenta modestly beats a careful single LLM (F1 0.889 vs 0.8) and
its real, repeatable edge is precision, grounding (zero hallucination, every finding
cited), determinism, auditability, and cost. The honest pitch is NOT "50% better at
finding problems". A single-pass LLM synthesis cannot cleanly resolve the
precision/recall tradeoff on held-out defects by prompting alone; reliably closing it
needs a conformance-based detector or multi-pass synthesis (real future work, not a
tuning knob). I stopped tuning rather than game the in-house answer key past 0.50.
