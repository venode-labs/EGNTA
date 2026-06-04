# Dataset card: cs-dataset-v1

Coding + cyber-security SFT set for the Qwen3-14B specialisation. Assembled
04/06/2026 by `scripts/collect_dataset.py configs/datasets.coding-security.yaml`.
The data files live under `datasets/processed/` and are gitignored, this card and
the config are the committed record.

## Snapshot

- Total: 1,266 rows. Train 1,200, eval 66 (frozen, never trained on; 5% split, seed 3407).
- Format: messages-jsonl (`{messages, source, license, notes}`), deduped by message fingerprint.

## Source mix

| Source | Rows | Type | Domain | Redaction |
|---|---|---|---|---|
| algorithmic-sft | 1,228 | instruction/output | maths, ML, LLM science, agents, prompt-eng | not secret-bearing |
| hugo-voice | 27 | messages | venode house voice | not secret-bearing |
| claude-code-sessions | 11 | messages | real coding-agent trajectories (tool use) | redacted via redactor.py, audit-clean (0 leaks) |

## Redaction and safety

The 11 trajectories are the only secret-derived source. Each passed
`observer/redactor.py` and `scripts/redact_audit.py` (redact then re-scan, zero
leaks). The assembled train file audits clean. The raw transcripts and the
processed data never leave the box (gitignored).

## Honest limits

- Knowledge-heavy: the algorithmic SFT set dominates (97% of rows). Only 11 rows
  are genuine agentic tool-use, so this v1 leans knowledge, not agent behaviour.
- Codex rollouts (a second trajectory source) are not included, their schema
  differs from Claude Code and they need a dedicated converter.
- Tool calls are serialised into the assistant text and tool results folded into
  user turns with a `[tool result]` marker, faithful enough for SFT, not native
  tool_call structure.

## Next

Grow the agentic share: a codex converter, plus the eval-task-factory pass (run
the best model over `eval/cases` and keep the verified trajectories).
