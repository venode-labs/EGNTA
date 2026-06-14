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
