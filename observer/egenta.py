"""Egenta Phase 1 entrypoint: locate and parse Claude Code session transcripts,
print a read-only summary. Proves the capture/read path.

Deterministic capture workflow, NOT an agent loop (that arrives in Phase 4 with
the deep brain). Read-only, Tier 1: it reads the session logs and prints, it
never writes the logs, never advances any cursor by default, and makes no model
or network calls. Single-instance lock and cursor read are in place so the
daemon (Phase 6) can build straight on top.

Run:
    python observer/egenta.py                 # scan all transcripts, print
    python observer/egenta.py --new           # only those after the cursor
    python observer/egenta.py --json          # machine-readable
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript as T  # noqa: E402
import brain_local  # noqa: E402
import brain_deep  # noqa: E402
import gate  # noqa: E402
import journal  # noqa: E402

DEFAULT_SESSIONS = Path.home() / "clilogs" / "claude-logs" / "sessions"
KILL_SWITCH = Path.home() / "Egenta" / ".egenta-paused"


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    d = Path(base) / "egenta"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _acquire_lock(state: Path):
    """Single-instance guard via a non-blocking flock. The returned handle must
    stay open for the process lifetime, closing it releases the lock."""
    fh = open(state / "egenta.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.stderr.write("egenta: another instance holds the lock, exiting.\n")
        sys.exit(3)
    return fh


def _read_cursor(state: Path) -> str:
    f = state / "cursor.json"
    if not f.exists():
        return ""
    try:
        return json.loads(f.read_text()).get("last", "")
    except (json.JSONDecodeError, OSError):
        return ""


def find_transcripts(sessions_dir: Path) -> list[Path]:
    # Filenames sort chronologically (<YYYY-MM-DD>-<id>), so name order is fine.
    return sorted(sessions_dir.glob("*.jsonl"))


def _summarise(s: T.Session) -> str:
    top = ", ".join(f"{k}:{v}" for k, v in s.tool_counts.most_common(6)) or "none"
    lines = [
        f"  {s.session_id}  ({s.date or 'no-date'}{', ' + s.end_reason if s.end_reason else ''})",
        f"    repo: {s.cwd or 'unknown'}",
        f"    events {s.n_events}  human {s.n_user_msgs}  injected {s.n_injected}  assistant {s.n_assistant_msgs}"
        f"  tool-uses {s.n_tool_uses}  mutations {s.n_mutations}  tool-errors {s.n_tool_errors}",
        f"    tools: {top}",
        f"    corrections (crude heuristic): {len(s.corrections)}",
    ]
    if s.corrections:
        lines.append(f"      e.g. {s.corrections[0]}")
    return "\n".join(lines)


def _run_triage(sessions, force: bool, model) -> int:
    done = skipped = pending = 0
    for s in sessions:
        if not force and journal.already_triaged(s.session_id):
            skipped += 1
            continue
        rec = brain_local.triage(s, model=model)
        journal.append_record(rec)
        if rec["status"] == "ok":
            done += 1
            print(f"  triaged {s.session_id}  salience={rec['salience']}  class={rec['session_class']}"
                  f"  drift={rec['signals']['rule_drift']}  {rec['signals']['notes']}")
        else:
            pending += 1
            print(f"  pending {s.session_id}  ({rec['reason']})")
    print(f"triage: {done} ok, {pending} pending, {skipped} already done"
          f"  ->  ~/Egenta/journal/triage.ndjson")
    return 0


def _write_cursor(state: Path, last_name: str) -> None:
    """Advance the cursor. Only the daemon writes it; the one-shot scan stays
    read-only. Atomic via a temp file so a crash mid-write can't corrupt it."""
    if not last_name:
        return
    tmp = state / "cursor.json.tmp"
    tmp.write_text(json.dumps({"last": last_name}))
    tmp.replace(state / "cursor.json")


def _process_session(s, deep: bool, model) -> dict:
    """Triage one session, journal it, and if it is worth the cost, run the deep
    brain on redacted text and queue or write whatever it drafts. Returns a small
    summary. Never raises on a single bad session; the daemon must keep running."""
    out = {"id": s.session_id, "triaged": False, "escalated": False, "artifacts": 0}
    try:
        rec = brain_local.triage(s, model=model)
        journal.append_record(rec)
        out["triaged"] = True
        out["salience"] = rec.get("salience")
        if deep and brain_deep.should_escalate(rec):
            finding = brain_deep.analyse([s], [rec])
            journal.append_finding(finding)
            out["escalated"] = True
            out["finding_status"] = finding.get("status")
            for art in finding.get("artifacts", []):
                gate.write_or_queue(art, finding_id=s.session_id)
                out["artifacts"] += 1
    except Exception as exc:  # a daemon survives one bad session
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def process_new(sessions_dir: Path, state: Path, deep: bool, model, advance: bool) -> dict:
    """One sweep: parse transcripts after the cursor, process the untriaged ones,
    advance the cursor. The unit the daemon loops and the test exercises once."""
    cursor = _read_cursor(state)
    files = [f for f in find_transcripts(sessions_dir) if not cursor or f.name > cursor]
    index = T.load_index(sessions_dir)
    summary = {"scanned": len(files), "processed": 0, "escalated": 0, "artifacts": 0}
    last = cursor
    for f in files:
        s = T.parse(f, index.get(T._parse_name(f.name)[1]))
        if not journal.already_triaged(s.session_id):
            r = _process_session(s, deep, model)
            summary["processed"] += 1
            summary["escalated"] += int(r.get("escalated", False))
            summary["artifacts"] += r.get("artifacts", 0)
        last = f.name
    if advance and last:
        _write_cursor(state, last)
    summary["cursor"] = last
    return summary


def run_daemon(sessions_dir: Path, state: Path, deep: bool, model, poll: float) -> int:
    """Resident loop: reconcile the cursor on start, then sweep on a poll timer.
    Stdlib polling rather than inotify keeps the dependency surface at zero, and
    session transcripts close rarely enough that a short poll is cheap. The
    kill-switch file idles the loop without killing the unit."""
    print(f"egenta daemon: watching {sessions_dir}, poll {poll}s, deep={'on' if deep else 'off'}")
    while True:
        if KILL_SWITCH.exists():
            print("egenta daemon: paused (kill-switch present), idling")
        else:
            summary = process_new(sessions_dir, state, deep, model, advance=True)
            if summary["processed"]:
                print(f"egenta daemon: processed {summary['processed']}, "
                      f"escalated {summary['escalated']}, artifacts {summary['artifacts']}, "
                      f"cursor -> {summary['cursor']}")
        time.sleep(poll)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Egenta Phase 1: read-only session transcript scan.")
    ap.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS)
    ap.add_argument("--new", action="store_true", help="only transcripts after the saved cursor (by filename)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON instead of text")
    ap.add_argument("--triage", action="store_true", help="run the local triage brain, append to the journal")
    ap.add_argument("--force", action="store_true", help="re-triage sessions already recorded in the journal")
    ap.add_argument("--model", default=None, help="local model name (default qwen2.5:3b or $EGENTA_LOCAL_MODEL)")
    ap.add_argument("--daemon", action="store_true", help="resident loop: watch the sessions dir, process new transcripts")
    ap.add_argument("--once", action="store_true", help="one daemon sweep (process new transcripts), then exit")
    ap.add_argument("--deep", action="store_true", help="enable the deep brain (auto-on when ANTHROPIC_API_KEY is set)")
    ap.add_argument("--poll", type=float, default=60.0, help="daemon poll interval in seconds (default 60)")
    ap.add_argument("--no-advance", action="store_true", help="do not advance the cursor (dry --once)")
    args = ap.parse_args(argv)

    if not args.sessions_dir.is_dir():
        sys.stderr.write(f"egenta: no sessions dir at {args.sessions_dir}\n")
        return 2

    state = _state_dir()
    _lock = _acquire_lock(state)  # held for process lifetime
    cursor = _read_cursor(state)

    # Daemon and single-sweep modes: triage, escalate, gate, advance the cursor.
    if args.daemon or args.once:
        deep = args.deep or bool(os.environ.get("ANTHROPIC_API_KEY"))
        if args.daemon:
            return run_daemon(args.sessions_dir, state, deep, args.model, args.poll)
        summary = process_new(args.sessions_dir, state, deep, args.model, advance=not args.no_advance)
        print(json.dumps(summary, indent=2) if args.json else
              f"egenta once: scanned {summary['scanned']}, processed {summary['processed']}, "
              f"escalated {summary['escalated']}, artifacts {summary['artifacts']}, cursor {summary['cursor']}")
        return 0

    files = find_transcripts(args.sessions_dir)
    if args.new and cursor:
        files = [f for f in files if f.name > cursor]

    index = T.load_index(args.sessions_dir)
    sessions = [T.parse(f, index.get(T._parse_name(f.name)[1])) for f in files]

    if args.triage:
        return _run_triage(sessions, args.force, args.model)

    if args.json:
        print(json.dumps([
            {
                "session_id": s.session_id, "date": s.date, "cwd": s.cwd, "end_reason": s.end_reason,
                "events": s.n_events,
                "user_msgs": s.n_user_msgs, "injected": s.n_injected, "assistant_msgs": s.n_assistant_msgs,
                "tool_uses": s.n_tool_uses, "mutations": s.n_mutations,
                "tool_errors": s.n_tool_errors, "tools": dict(s.tool_counts),
                "corrections": len(s.corrections),
            }
            for s in sessions
        ], indent=2))
    else:
        header = f"egenta phase-1 scan: {len(sessions)} transcript(s) in {args.sessions_dir}"
        if args.new:
            header += f" (after cursor {cursor or '<none>'})"
        print(header)
        for s in sessions:
            print(_summarise(s))
        print("  (read-only: no cursor advance, no writes, no model calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
