# Decisions

## 0003, enterprise architecture (14/06/2026)

Status: accepted.

The field was reviewed at code level, PM4Py, bupaR, Apromore, ProM, Airbyte,
OpenMetadata, before any code was written.

- Single language, Python. The Claude Agent SDK has first-class Python PreToolUse
  hooks and `can_use_tool`, the redactor and the mining and eval stack are Python, and
  a TypeScript split would add a process boundary for no gain.
- Clean-room miner. PM4Py is AGPL-3.0, viral over a network service, so EGNTA ships its
  own miner and uses PM4Py only as a development and CI oracle, never in the product.
- Eval first. The benchmark, corpus and metric were built before the engine, so the
  improvement claim is falsifiable rather than retrofitted. See EVAL-METHOD.md.
- Reuse the redactor, add a PII pass. The redactor is a credential wall; `accelerator/
  pii.py` adds phone and payment-card scrubbing. A model-based name pass is a stub for
  later.
- Read-only is two enforced layers today, a SELECT-only handle and a read-only tool
  guard. OAuth scopes, an egress proxy and network isolation are stubs that raise.
- Warehouse is SQLite per engagement now, with a Postgres backend as the scale target.

## 0004, grounded synthesis and the real-LLM benchmark (15/06/2026)

Status: accepted.

`accelerator/synthesis.py` lets Claude reason over the deterministic mining; every
finding cites a resolvable `evidence_fqn` or is dropped, and a safety net keeps it from
regressing below the miner. `accelerator/llm.py` is a thin Claude client, key from the
vault or `ANTHROPIC_API_KEY`, with a mock mode so CI runs without a key. The naive
single-LLM baseline gets the same warehouse summary. `bench.run --real-llm` measures the
headline; CI stays on the deterministic path.

The benchmark went through an honest correction. On the first four-defect corpus EGNTA
scored F1 1.0 against a naive baseline at 0.889, but the baseline sat near ceiling so REL
was flattered. Adding a held-out fifth defect (a second bottleneck the miner could not
report) dropped EGNTA below target. The fix was a capability, not a prompt tune, and
shipped in 0005. The benchmark was never tuned against its own answer key to pass.

## 0005, multi-bottleneck detection and cross-platform deployment (15/06/2026)

Status: accepted.

The held-out defect showed the miner reported only the single slowest transition. The
miner now flags every transition at least twice the median duration, and timing excludes
cases with corrupted timestamps so recording errors stop producing false bottlenecks.
EGNTA then catches the second bottleneck precisely: real-LLM gated F1 1.0 against the naive
baseline at 0.889, absolute gain +0.111. REL stays flattered by a strong baseline, and the
corpus no longer holds a defect the miner cannot detect, so generalisation to other defect
classes, segregation of duties and cross-source inconsistency among them, is still open.

The engine is stdlib-only with a per-engagement SQLite warehouse and runs on Linux, macOS
and Windows unchanged. Shipped with it: a `python -m accelerator` CLI, a non-root
`python:3.12-slim` Dockerfile, docker-compose, a cross-OS CI matrix plus a container build
job, a Windows-safe SQLite file URI, and DEPLOY.md. The Anthropic key is injected via
`ANTHROPIC_API_KEY` in containers; the Postgres backend is the documented scale target.
