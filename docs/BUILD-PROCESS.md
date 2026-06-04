<!--
  doc: mara brain build process
  owner: Kaspar Tavitian
  status: active
  created: 04/06/2026
  scope: the end-to-end pipeline that turns local data into a coding + security
         specialisation of an open base model, run to research-lab standard.
-->

# Build process: the mara brain

How the coding + cyber-security model is built, to the standard a serious lab
holds. Every stage is reproducible from a pinned config, gated before it advances,
and documented in a card. No stage trusts the previous one's word, it checks.

Target: a QLoRA specialisation of Qwen3-14B, served via ollama, driven by the mara
harness, measured by a held-out eval. The model is the brain, mara is the body,
the eval is the scoreboard.

## Principles (the lab discipline)

1. **No eval, no claim.** A training run that did not move a held-out number did
   nothing. Every run reports before-and-after on the same fixed eval.
2. **Reproducible or it did not happen.** A run is a pinned config plus a pinned
   data snapshot plus a seed. Same inputs, same model, every time.
3. **The redaction wall is absolute.** No raw session log, no own-code repo, no
   secret-bearing text enters a dataset or leaves the box un-redacted. `observer/redactor.py`
   is the only door, and it over-redacts on purpose.
4. **Dual-use gate.** This is a security model. Offensive capability ships behind
   the scope policy and an explicit review, never on by default.
5. **Cards, not memory.** Every dataset and every model carries a card stating
   provenance, contents, eval, intended use, and limits.

## Stage 0, environment

- Python pinned to 3.12 (`.python-version`), deps locked by `uv` from `pyproject.toml`
  (datasets, transformers, peft, trl, bitsandbytes, unsloth, torch). `uv sync` rebuilds
  the exact env. Training runs on rented cloud GPU (HF Jobs), not this box.
- One command: `uv venv && uv sync`. The data-assembly stage needs only `datasets`
  and `pyyaml`; the training stage needs the full stack on the GPU host.

## Stage 1, data

Source of truth is `DATA-CATALOGUE.md`. The assembly is config-driven:
`configs/datasets.coding-security.yaml` consumed by `scripts/collect_dataset.py`.

- **Provenance and licence** per source, recorded in the config `notes` and the
  output rows (`source`, `license` fields). A source with an unverified licence
  stays `enabled: false`.
- **Redaction gate.** Secret-bearing sources (agent transcripts, own-code repos)
  are `enabled: false` until each row has passed `observer/redactor.py`. The
  redactor is unit-tested against planted secrets before it is trusted.
- **Dedup** by message fingerprint (`scripts/common.py`), so near-duplicate
  trajectories do not inflate the set or leak across the split.
- **Splits** are deterministic (seed 3407), train and a held-back eval fraction,
  written to `datasets/processed/cs-{train,eval}.jsonl`. The eval split is frozen
  and never trained on, to keep the scoreboard honest.
- **Contamination check.** Before training, scan the train split for the eval
  tasks' fingerprints; any overlap is removed and logged.
- **Dataset card** written per snapshot: row count, source mix, redaction status,
  licences, date, the config hash that produced it.

## Stage 2, the eval (built before any training)

The held-out eval is the keystone, built first because it both measures the model
and seeds the targeted data.

- A fixed set of coding and security tasks, each a setup, a prompt, and a
  deterministic checker (final file state, command exit, or test result), the same
  shape the mara harness runs.
- `scripts/eval.py` runs a candidate model over the set headless and emits metrics
  as JSON: task-success rate, tool-call validity, turns-to-completion, wall-clock.
- A baseline is recorded for the un-tuned base and for the best accessible model
  (Opus 4.8), so every later number has two reference points.
- Targeted data factory: running the best model over these tasks and keeping only
  the trajectories whose checker passes produces gold agentic training rows.

## Stage 3, training

- One QLoRA config per run (`configs/*.yaml`): base model, LoRA rank and target
  modules, hyperparameters, seed, dataset snapshot path. Nothing implicit.
- `scripts/train.py` trains; `scripts/merge.py` merges the adapter. Cloud GPU via
  `configs/hf-jobs-*.yaml` (HF Jobs), so the run is portable and logged off-box.
- **Experiment tracking:** every run logs to a tracker (trackio is a dep; braintrust
  is being wired on the harness side) with the config, the dataset card hash, the
  loss curve, and the eval deltas, so runs are comparable and a regression is
  visible. A run with no tracked eval delta is not a result.

## Stage 4, evaluate and gate

- Run `scripts/eval.py` on the merged model, compare to the baselines from Stage 2.
- **Promotion gate:** the run is promoted only if it beats the previous champion on
  task-success with no regression on tool-call validity, and shows no eval
  contamination. Otherwise it is archived, not shipped.
- The model is honest about its ceiling: a 14B specialist wins on its niche, not on
  general benchmarks, and the card says so.

## Stage 5, package and serve

- Merged weights to GGUF, a `Modelfile` (the hugo pattern), loaded in ollama.
- mara points at it through an ollama provider adapter; `MARA_MODEL` selects it.
- **Model card** ships with the model: base, dataset snapshot, eval scores against
  the fixed set, intended use, known limits, and the dual-use note (offensive
  capability is scope-gated, defensive use is the default).

## Stage 6, safety and release

- **Dual-use review** before any model with offensive capability is used outside a
  scoped, authorised context. The release records who reviewed and the authorised
  scope.
- **Redaction audit** of the training data is re-run before release; a single
  leaked secret in the set fails the release.
- Private by default. Weights and datasets never go to a public remote.

## Runbook (reproduce a run)

```
uv venv && uv sync
python scripts/collect_dataset.py --config configs/datasets.coding-security.yaml   # -> cs-train/eval.jsonl + dataset card
python scripts/eval.py --model <base> --tasks eval/tasks                           # baseline
# train on the GPU host:
python scripts/train.py --config configs/cs-qwen3-14b.yaml                          # -> adapter + tracked run
python scripts/merge.py --config configs/cs-qwen3-14b.yaml                          # -> merged weights
python scripts/eval.py --model <merged> --tasks eval/tasks                          # after; gate on the delta
# package: merge -> GGUF -> Modelfile -> ollama; point mara at it
```

## What is not built yet

- `configs/cs-qwen3-14b.yaml`, the real 14B training config (the smoke config is 0.5B).
- The transcript-to-messages converter for the redacted gold trajectories.
- The coding+security eval task set and `eval/tasks`.
- The ollama provider adapter in mara.
- Experiment-tracker wiring end to end.

These are the next build items, in that order. Each lands with its own card and a
green eval before it counts.
