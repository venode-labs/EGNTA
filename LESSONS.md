# EGNTA build lessons

Dev lessons from building EGNTA itself. Distinct from `lessons/LESSONS.md`,
which is EGNTA's learned rules about the Claude sessions it observes. Newest
first.

## 15/06/2026, "enforced" means on a live code path, not "implemented and tested"

**What broke.** Wrote that the egress allowlist was an "enforced" read-only layer (3 of
5), the same week I overclaimed a precision number. The function is real and tested, but
nothing calls it at runtime: the only connector is file-based, so no egress routes through
it, and the engine's own model API call is a legitimate POST to an allowlisted host that
the check would wrongly refuse. "Enforced" overclaimed parity with the SQL and tool
guards, which are actually on the code path.

**Root cause.** Conflating "the policy function exists and passes tests" with "the policy
guards live traffic". A tested decision function with no call site is not enforcement.

**Fix.** Reworded readonly.py, README and ARCHITECTURE to "two actively enforced on the
code path, one implemented-and-tested policy awaiting the first live-HTTP connector, two
stubs". Did NOT wire it into the LLM client, that would wrongly block the legitimate POST.

**Guard.** Standing rule: claim a control is "enforced" only when there is a runtime call
site that exercises it; a tested-but-uncalled policy is "implemented and tested", not
enforced. Pairs with the precision lesson below: verify the claim, do not round it up.

## 15/06/2026, a bottleneck detector must not pool sub-flow transitions

**What broke.** The trades dispatch-bottleneck detector ran over every transition in
the log, so the compliance sub-flow's normal one-day RoutineService to
CertificateIssued gap read as a bottleneck against the tight job-step median. One
false positive, gated precision 0.875 not 1.0, and I had written precision 1.0 into the
README and EVAL-METHOD before verifying. F1 0.933, not the 0.875 the docs claimed.

**Root cause.** A "this stage is slow" detector only makes sense within one cadence.
Mixing the job-execution flow with the compliance and rectification sub-flows in one
median pool flags a normal sub-flow gap as slow.

**Fix.** dispatch-bottleneck now scores only transitions where both activities are in
the job-execution flow (`_JOB_FLOW`); compliance and rectification cadences are
excluded. Precision back to 1.0, F1 0.933. Docs corrected to the real numbers.

**Guard.** `test_trades_pipeline_grounds_and_beats_naive` now asserts gated precision
== 1.0, so a sub-flow transition leaking into the bottleneck pool fails CI. And the
standing lesson: never write a metric into the docs before running the bench that
produces it.

## 2026-06-04, converter output must satisfy the trainer's contract

**What broke.** Assembling the coding-security set rejected all 11 transcript
trajectories. Three separate causes surfaced only by running collect_dataset:
(1) `resolve_path` did not expand `~`, so a `~/github/...` source path became
`EGNTA/~/github/...` and failed; (2) the trainer's `normalize_messages` allows
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

## 15/06/2026, discovery accelerator eval: relative-improvement metrics are flattered by a strong baseline
- **What happened:** on the easy 4-defect corpus, EGNTA scored REL 1.0 vs a naive single-LLM, which looked like a clean 50%+ win. It was an artefact: the baseline was near ceiling (F1 0.889) so the tiny absolute gain (+0.111) inflated to REL 1.0.
- **Root cause:** relative error reduction (F1_e - F1_b)/(1 - F1_b) has a vanishing denominator against a strong baseline, so a near-zero absolute gain reads as a huge ratio.
- **Fix:** the runner prints abs_f1_delta_gated next to REL; a HELD-OUT defect (a second bottleneck the deterministic miner cannot report) was added to make detection-F1 discriminating. On that corpus the honest result is REL 0.444 (target NOT met).
- **Guard:** EVAL-METHOD.md pre-registers the metric, reports absolute delta + gated/ungated, and forbids the "50% better" claim without the held-out corpus. Never headline a ratio metric without its absolute delta and a held-out test.

## 15/06/2026, single-pass LLM synthesis cannot cleanly resolve the precision/recall tradeoff by prompting
- **What happened:** told to flag all standout bottlenecks, the synthesis caught the held-out defect (recall 1.0) but over-flagged (precision 0.71, F1 below baseline); tightened to "2x median", it went precise (P 1.0) but missed the held-out (recall 0.8). Neither cleared 50%.
- **Root cause:** prompt tuning trades precision for recall on a tool-less single pass; it cannot reliably do both on held-out defects.
- **Guard:** stop tuning against an in-house answer key (grade-your-own-homework). Reliable held-out detection needs a conformance-based detector or multi-pass synthesis, logged as the real next step, not a tuning knob.

## 15/06/2026, Windows CI: SQLite handle left open inside a TemporaryDirectory
- **What happened:** test_citation_resolves (and the run.py error path) opened a SQLite connection inside `with tempfile.TemporaryDirectory()` and did not close it; Windows cannot delete a file held open, so tempdir cleanup raised PermissionError [WinError 32]. Linux/macOS allowed it, so it was invisible until the cross-OS matrix ran.
- **Root cause:** an open file handle outlives its temp dir on Windows; POSIX unlink-while-open masks the bug.
- **Fix:** close DB connections in try/finally before the TemporaryDirectory exits (tests/test_engine.py, bench/run.py).
- **Guard:** the cross-OS CI matrix (ubuntu/macOS/windows) in discovery-ci.yml catches this class; always close a handle before its temp file is cleaned up.
