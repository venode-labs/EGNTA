# Egenta build roadmap

The rename and the system prompt are done. This is the order to build the agent
itself. Each phase is shippable on its own and leaves the repo in a working
state.

## Phase 1, capture and cursor  [DONE 04/06/2026]

- `observer/egenta.py` entrypoint: takes a lock, reads a cursor file, finds
  transcripts in `~/clilogs/claude-logs/sessions/` newer than the cursor. DONE,
  single-instance flock, XDG-state cursor (read-only, no advance by default).
- Parse the `*.jsonl` transcript into a session model: ordered events, tool
  calls, errors, human messages (injected skill/hook/command messages filtered
  out), crude correction signal. DONE in `observer/transcript.py`.
- Eval ships with the phase: `observer/test_transcript.py`, passes on the 3 real
  captured transcripts. Read-only proven, no writes, no model calls.
- `index.ndjson` is read and joined by session id, enriching each session with
  `cwd` (the repo it ran in) and end `reason`. DONE.
- Open for later: turn-level grouping and the genuine-vs-injected refinement move
  to the Phase 2 local brain (the prefix/title filter is best-effort).

## Phase 2, local triage brain  [DONE 04/06/2026]

- Ollama call wired via urllib (`observer/brain_local.py`, loopback-guarded),
  model `qwen2.5:3b` default with `$EGENTA_LOCAL_MODEL` override. DONE.
- The model returns session class, rule_drift, and a one-line note. Salience is
  computed deterministically from the facts (`_deterministic_salience`), because
  a 3B model scored it as uniform noise. Raw text to the local model only.
- One triage record per session appended to `journal/triage.ndjson`
  (`observer/journal.py`, dedupe by session id, append-only). Degrades to a
  `pending` record if the model is down, never crashes.
- `egenta.py --triage [--new] [--force] [--model]` drives it; default scan stays
  read-only. Eval: `observer/test_brain.py` (hermetic, stubs the HTTP call).

## Phase 3, redactor

- A standalone scrubber: secrets, keys, tokens, `.env` values, private hosts,
  business and personal data, out before anything reaches the deep brain.
- `redact-check` mode for dry runs. Test it hard before Phase 4. The redactor is
  the wall between raw logs and the Claude API.

## Phase 4, deep brain and escalation

- Claude API call on redacted excerpts only, gated behind the salience
  threshold and the cross-session recurrence rule.
- Produces root-cause findings and drafts the four artifact types.
- Every finding stamped with the brain that made it.

## Phase 5, write gate and queue

- Auto-write inside `~/Egenta` only.
- Queue everything else as one markdown file per proposal in `proposals/`, plus
  an index. Build the approve/reject path: approved proposals get applied,
  rejected ones get archived with the reason fed back as a signal.
- Never auto-edit `~/.claude/CLAUDE.md`, never push, never install a skill
  silently.

## Phase 6, daemon

- Inotify watch on the sessions dir for closed transcripts, plus a heartbeat
  timer for cross-session sweeps.
- Install `observer/egenta.service` as a systemd user unit. Reconcile the cursor
  on start.

## Phase 7, training arm

- Turn validated, scrubbed sessions into fine-tune datasets in `datasets/` using
  the existing collect and validate scripts.
- Build a config under `configs/`. Training runs stay deferred until explicitly
  started.

## Outstanding ops

- GitHub rename: the remote is still `venode-labs/QLORA`. Rename the repo to
  `Egenta` on GitHub, then `git remote set-url origin
  https://github.com/venode-labs/Egenta.git`. Needs gh auth for the venode-labs
  org, not available in the session that did the local rename.
- The working tree has no commits yet. First commit lands once Phase 1 is real,
  on `main`, authored as Kaspar.
