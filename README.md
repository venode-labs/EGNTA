# Egenta

An always-on agent that observes how Claude Code and other command-line AI
agents operate on this machine, then turns what it sees into improvements.

Egenta watches, logs, studies, and improves. It is the autonomous successor to
the supervised `/retro` loop: instead of distilling lessons by hand at the end
of a session, Egenta runs as a resident daemon and does it continuously. The
measure of success is simple. The agent it watches makes fewer of the same
mistakes over time, and you step in less.

## The loop

1. Observe how the watched agent worked, tool call by tool call.
2. Log what happened, with evidence tied to session ids and turns.
3. Study why it went well or badly, root cause not symptom.
4. Improve the next run by producing one artifact: a script, a skill, a lesson,
   or training data.

## Output arms

| Arm | What it is | Home | Gate |
|-----|------------|------|------|
| script | automation that kills a repeated manual step | `scripts/` | auto in-repo, `~/.local/bin` is queued |
| skill | a new or amended skill for the watched agent | `proposals/skills/` | draft auto, install queued |
| lesson | a durable rule | `lessons/LESSONS.md` | auto in-repo, CLAUDE.md edits queued |
| training program | observed sessions turned into fine-tune data | `datasets/`, `configs/` | data auto, training run deferred |

The training arm is the original workspace this repo grew from. It still uses
QLoRA, quantised low-rank adapters, as the fine-tuning method. Egenta scrubs
observed sessions into datasets and feeds that pipeline. Training runs stay
deferred until explicitly started.

## Brain

Hybrid by design.

- Local brain (`hugo` / Ollama, Qwen) triages raw transcripts continuously.
  Cheap, and raw text never leaves the machine.
- Deep brain (Claude API) handles root cause, cross-session synthesis, and
  artifact drafting, on redacted excerpts only.

Escalation from local to deep happens only when a session scores high on
salience or a pattern repeats. Most sessions never touch the deep brain.

## Write authority

Hard gate, the centre of Egenta's safety.

- Auto, write without asking, only inside this repo: journal, lessons, draft
  skills, datasets, configs, and `scripts/`.
- Queue, draft and wait for approval, for anything outside this repo or anything
  high impact: `~/.claude/CLAUDE.md`, installed skills, `~/.local/bin` scripts,
  and any git commit or push to any repository.

Egenta never auto-edits the watched agent's rulebook, never pushes, and never
installs a skill silently.

## Privacy

- Raw transcripts never leave the machine. Only redacted excerpts reach the
  Claude API.
- Secrets, keys, tokens, private hosts, business and personal data are redacted
  before any deep-brain call and never written to the journal, a lesson, or a
  dataset.

## Layout

```text
prompts/        Egenta's system prompt
observer/       Daemon entrypoint and watchers (build in progress)
journal/        Append-only ndjson findings
lessons/        LESSONS.md, the durable rules Egenta has learnt
proposals/      Queued high-impact changes awaiting approval
scripts/        Training and dataset scripts, plus Egenta's own automation
configs/        Training and dataset build configs
datasets/       Ignored local dataset workspace, except samples
```

## Status

Renamed from the QLoRA training workspace on 04/06/2026 and repurposed. The
system prompt and the training arm are in place. The observer daemon, the
redactor, the brain router, and the queue tooling are the next build, see
`ROADMAP.md`. The remote is still `venode-labs/QLORA` on GitHub until the repo
is renamed there.

## Training arm, quick reference

```bash
uv sync
uv run python scripts/validate_dataset.py datasets/samples/smoke.jsonl
uv run python scripts/collect_dataset.py configs/datasets.example.yaml
uv run python scripts/train.py configs/smoke-test.yaml
```

Training needs a working CUDA GPU because Unsloth QLoRA is CUDA-focused. Keep
raw dumps out of git, track source and licence for every dataset, deduplicate
before training, and never train on private data unless it is allowed and
scrubbed.
