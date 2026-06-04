# Egenta data catalogue

Central index of every training-usable data source on this machine, with its
format, domain, and the pipeline step it needs before it can train a model. This
is the map, not the data. Large corpora and anything secret-bearing are referenced
by path, never copied into this repo. Built 04/06/2026.

Target model: a coding + cyber-security specialisation of Qwen3-14B via the QLoRA
pipeline in `scripts/` (train.py, merge.py), measured by `scripts/eval.py`.

## Pipeline status legend

- **ready**: messages or instruction format, clean, ingest now via `collect_dataset.py`.
- **redact**: contains secrets, must pass the Egenta redactor (Phase 3) before use.
- **convert**: useful content in the wrong shape, needs a transcript or lesson converter.
- **reference**: domain knowledge or scale data, used as reference or retrieval, not SFT.

## A. Agent trajectories, the highest-value data (redact + convert)

Real multi-step tool-use by coding agents. This is the closest thing to the
behaviour we want to teach, and the rarest to buy. All of it is secret-bearing.

| Source | Path | Size | Records | Status |
|---|---|---|---|---|
| Claude Code sessions | `~/clilogs/claude-logs/sessions/` | 16M, 12 files | ~6,000 lines | redact + convert |
| Codex CLI rollouts | `~/.codex/sessions/` | ~5M, 7 files | ~3,400 lines | redact + convert |
| hugo CLI transcripts | `~/clilogs/hugo-logs/` | 264K, 28 files | conversations | redact + convert |
| openclaw / kimi sessions | `~/.openclaw`, `~/.kimi` | small | few | redact + convert |

14 of these files contain secret-like strings (confirmed scan). None may be used
or pushed until run through `observer/redactor.py`. Then a converter maps each
transcript to the messages-jsonl shape `train.py` expects.

## B. Instruction / QA datasets (ready, verify licence)

| Source | Path | Records | Format | Domain | Status |
|---|---|---|---|---|---|
| Algorithmic Data Library, SFT | `~/github/Algorithmitic-Data-/datasets/sft.jsonl` | 1,228 | instruction/input/output | maths, ML, LLM science, agents, prompt-eng | ready |
| Algorithmic Data, QA | `~/github/Algorithmitic-Data-/datasets/qa.jsonl` | 1,095 | qa | same | ready |
| Algorithmic Data, retrieval | `~/github/Algorithmitic-Data-/datasets/retrieval.jsonl` | 1,176 | passages | same | reference |
| hugo voice, handwritten | `~/hugo/training/datasets/hugo-voice-handwritten.jsonl` | 27 | messages | venode voice | ready |

`normalize_messages` in `scripts/common.py` already converts instruction/output to
messages, so the Algorithmic SFT set ingests directly. It is knowledge, not agentic
tool-use, so it supplements the trajectories in A, it does not replace them.

## C. Curated engineering knowledge (convert)

| Source | Path | Status |
|---|---|---|
| LESSONS.md across repos (8) | `~/mara`, `~/hugo/cli`, `~/Egenta`, `~/github/{cli-skills,reflex,ai-engineering-library,hugo}` | convert to instruction pairs |
| Egenta memory (71 files) | `~/.claude/projects/-home-keletonik/memory/` | reference only, personal and business data, do NOT push |
| AI-engineering corpus | `~/github/ai-engineering-library` | reference / retrieval |

The LESSONS files are real defect-and-fix engineering reasoning, high signal once
converted to instruction pairs. The memory directory is personal, it stays local.

## D. Security domain data (reference)

| Source | Path | Size | Use |
|---|---|---|---|
| SecLists | `~/SecLists` | 2.5G | payloads, wordlists, the security domain surface. Reference and retrieval, public data, never copied in |

## E. Configs and personas (reusable now)

| Source | Path |
|---|---|
| QLoRA 7B config | `~/hugo/training/configs/lora-7b.yaml` |
| Egenta configs | `~/Egenta/configs/*.yaml` |
| hugo Modelfiles | `~/hugo/runtime/Modelfile.*` |
| mara persona | `~/mara/src/core/persona.ts` |

## Own code repos (code-data, use with care)

`~/hugo`, `~/mara`, `~/manus`, `~/venode` are our own code and can seed repo-aware
coding examples, but they carry their own secrets, treat exactly like section A,
redact first. `~/nanoGPT`, `~/stable-diffusion-webui` are third-party, reference only.

## Build order

1. Finish the Egenta redactor (Phase 3), it is the gate for sections A and the own-code repos.
2. Ingest section B now: `python scripts/collect_dataset.py --config configs/datasets.coding-security.yaml`.
3. Redact + convert section A into messages-jsonl, the agentic core of the set.
4. Convert section C lessons to instruction pairs.
5. Generate targeted agentic data: run mara on Opus 4.8 over a coding + security task
   set, keep the verified passes (the keystone eval doubles as the data factory).
6. Train Qwen3-14B QLoRA on the merged set via HF Jobs, eval before and after.
