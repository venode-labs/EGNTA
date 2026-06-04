# Egenta build lessons

Dev lessons from building Egenta itself. Distinct from `lessons/LESSONS.md`,
which is Egenta's learned rules about the Claude sessions it observes. Newest
first.

## 2026-06-04 — converter output must satisfy the trainer's contract

**What broke.** Assembling the coding-security set rejected all 11 transcript
trajectories. Three separate causes surfaced only by running collect_dataset:
(1) `resolve_path` did not expand `~`, so a `~/github/...` source path became
`Egenta/~/github/...` and failed; (2) the trainer's `normalize_messages` allows
only system/user/assistant roles, so the converter's `tool` role rows were all
marked `bad`; (3) one trajectory ended on a tool result, but SFT requires the
last turn to be the assistant.

**Root cause.** The converter was written to a sensible-looking shape without
checking the exact contract the trainer enforces. A transcript is not training
data until it validates against the same `normalize_messages` the trainer runs.

**Fix.** `resolve_path` now `expanduser()`s. The converter folds tool results into
user turns with a `[tool result]` marker, merges consecutive same-role turns, and
trims any trailing non-assistant turn. All 11 trajectories now ingest.

**Guard.** `scripts/test_convert.py` asserts the contract: no tool role,
alternating turns, ends on assistant, planted secret redacted, injected noise
dropped. A future converter change that breaks the trainer contract fails it.

**General rule.** When producing training data, validate every row against the
exact `normalize_messages`/role/alternation/end-on-assistant contract the trainer
enforces, before declaring it ready. Run the assembler, do not eyeball the shape.

## 2026-06-04

- **'user' role does not mean a human turn.** The Phase 1 parser counted skill
  bodies ('Base directory for this skill:'), slash-command markers
  ('<command-name>'), system reminders, and 'Stop hook feedback:' as human
  messages, because all of them arrive with role=user in the transcript. This
  over-counted human turns by roughly 3 to 5 times and tripped the crude
  correction heuristic on a Stop-hook message. Fix: `_is_injected()` in
  `observer/transcript.py` filters these by prefix/marker, `n_user_msgs` is now
  human-only with a separate `n_injected`, and corrections skip injected text.
  Guard: a regression check in `observer/test_transcript.py` ('no injected in
  corrections') fails if they ever leak back in. Phase 2's local brain will do
  proper turn classification; this is the conservative capture-layer filter.
- **A second /check found two more: index.ndjson was in scope but unread, and a
  non-prefixed skill body leaked the injected filter.** The ROADMAP Phase 1 text
  said to parse `index.ndjson`; the first build only used the filename, dropping
  `cwd` (the repo a session ran in) and end `reason`, both genuinely useful. And
  `# Update Config Skill` (a skill body without the `Base directory` prefix) was
  still counted as human. Fix: `load_index()` joins the index by session id and
  `parse(meta=...)` attaches cwd/reason/ts; a narrow `_SKILL_TITLE` marker catches
  `# ... Skill` titles. Guard: a synthetic edge-case fixture in
  `observer/test_transcript.py` pins malformed-line skipping, error counting, all
  injected variants, and index enrichment, so the eval no longer leans on the real
  captures alone. Lesson: re-read the literal phase scope during check, 'good
  enough' had quietly dropped a named input.
- **Phase 2: asking a 3B model for a 0-1 salience score gave uniform noise.** The
  first triage build let the local model (qwen2.5:3b) judge salience; live, every
  session came back 0.75, class debug, drift true, no discrimination. Root cause:
  a small model cannot reliably score an abstract 0-1 'learnability' number.
  Fix: `_deterministic_salience()` computes salience from the Phase 1 facts
  (corrections, tool errors, mutations, unsteered length), the model is kept only
  for the qualitative bits it can do, class, rule_drift, a one-line note. Salience
  is now reproducible and survives a model outage. Guard: a discrimination
  assertion in `observer/test_brain.py` (a busy, error-heavy session must outscore
  a quiet one). Lesson: give the LLM the judgement it is good at, compute the
  numbers from facts.
- **A third /check: error-handling I wrote but never exercised, plus unsanitised
  notes.** `triage` caught a bad model response via `JSONDecodeError` (a subclass
  of the `ValueError` it already handles), but no test drove a non-JSON response,
  and the model's free-text `notes` were stored raw, so a newline would split the
  one-line journal record and the console output. Confirmed the degrade path live
  (a bogus model gives a 404 then a `pending` record, no crash), added a non-JSON
  test, and collapse whitespace in `notes`. Lesson: exercise the failure branch
  you wrote, an untested except clause is a guess.

## 2026-06-04 (observer completion)

- **test_transcript ran against live ~/clilogs data, so a new interrupted session broke it.**
  The Phase-1 eval parses every real captured transcript and asserted `assistant messages present`
  on each. A 13-event session that ended before the assistant replied (1 user message, 0 assistant)
  failed it. Root cause: the assertion encoded a false invariant; a real session can have no
  assistant turn. Fix: assert the true parser invariant instead, tool uses only come from assistant
  turns, so `n_assistant_msgs > 0 or n_tool_uses == 0`. Guard: the invariant holds for every real
  session including interrupted ones. Live-data evals stay non-deterministic, so their assertions
  must be invariants, not assumptions about typical content.
