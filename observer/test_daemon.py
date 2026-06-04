"""Phase 6 eval: the daemon sweep. Hermetic, the two brains and the gate are
stubbed, no Ollama, no API, no real writes. Proves one sweep triages a new
transcript, escalates and gates a salient one, advances the cursor, and does not
re-process; and that the kill-switch idles the loop. Run directly:

    python observer/test_daemon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import egenta as E  # noqa: E402
import brain_local  # noqa: E402
import brain_deep  # noqa: E402
import gate  # noqa: E402
import journal  # noqa: E402

TRANSCRIPT = (
    '{"message":{"role":"user","content":"build the thing"}}\n'
    '{"message":{"role":"assistant","content":[{"type":"text","text":"ok"},'
    '{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}\n'
    '{"message":{"role":"user","content":[{"type":"tool_result","is_error":false,"content":"files"}]}}\n'
)


def main() -> int:
    import tempfile
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        sessions = root / "sessions"; sessions.mkdir()
        state = root / "state"; state.mkdir()
        (sessions / "2026-06-04-testsess.jsonl").write_text(TRANSCRIPT)

        # Hermetic stubs. Journal functions are stubbed in-memory: a default arg
        # value is bound at def-time, so patching DEFAULT_JOURNAL alone would not
        # redirect them and the sweep would write the real journal.
        gate_calls, records, findings = [], [], []
        brain_local.triage = lambda s, model=None: {"id": s.session_id, "salience": 0.9,
                                                     "status": "ok", "session_class": "build",
                                                     "signals": {"rule_drift": False, "notes": ""}}
        brain_deep.analyse = lambda sess, recs, **k: {"status": "ok", "artifacts": [
            {"type": "lesson", "title": "t", "body": "b"}]}
        gate.write_or_queue = lambda art, finding_id="": gate_calls.append((art["type"], finding_id))
        journal.append_record = lambda rec, **k: records.append(rec)
        journal.append_finding = lambda rec, **k: findings.append(rec)
        journal.already_triaged = lambda sid, **k: any(r.get("id") == sid for r in records)

        # One sweep: scans, processes, escalates, gates, advances the cursor.
        summary = E.process_new(sessions, state, deep=True, model=None, advance=True)
        if not (summary["scanned"] == 1 and summary["processed"] == 1
                and summary["escalated"] == 1 and summary["artifacts"] == 1):
            fails.append(f"sweep summary wrong: {summary}")
        if gate_calls != [("lesson", "testsess")]:
            fails.append(f"gate not called as expected: {gate_calls}")
        if E._read_cursor(state) != "2026-06-04-testsess.jsonl":
            fails.append(f"cursor not advanced: {E._read_cursor(state)!r}")
        if len(findings) != 1:
            fails.append(f"finding not journalled: {len(findings)}")

        # Second sweep: cursor is past the only file, nothing to do.
        summary2 = E.process_new(sessions, state, deep=True, model=None, advance=True)
        if summary2["scanned"] != 0 or summary2["processed"] != 0:
            fails.append(f"re-processed after cursor advance: {summary2}")

        # already_triaged guard: even with the cursor reset, a triaged session is skipped.
        (state / "cursor.json").unlink()
        summary3 = E.process_new(sessions, state, deep=True, model=None, advance=False)
        if summary3["scanned"] != 1 or summary3["processed"] != 0:
            fails.append(f"already-triaged session not skipped: {summary3}")

        # deep=False: triages but never escalates or gates. Fresh state so the
        # session runs again instead of being skipped as already triaged.
        records.clear()
        (state / "cursor.json").unlink(missing_ok=True)
        gate_calls.clear()
        summary4 = E.process_new(sessions, state, deep=False, model=None, advance=True)
        if summary4["processed"] != 1 or summary4["escalated"] != 0 or gate_calls:
            fails.append(f"deep=False still escalated/gated: {summary4} {gate_calls}")

        # Kill-switch idles the daemon loop: process_new is not called.
        class _Stop(Exception):
            pass

        ticks = {"slept": 0, "processed": False}

        def fake_sleep(_):
            ticks["slept"] += 1
            raise _Stop()

        orig_sleep, orig_pn, orig_ks = E.time.sleep, E.process_new, E.KILL_SWITCH
        E.time.sleep = fake_sleep
        E.process_new = lambda *a, **k: ticks.__setitem__("processed", True) or {"processed": 0}
        E.KILL_SWITCH = root / ".egenta-paused"
        E.KILL_SWITCH.write_text("")  # paused
        try:
            E.run_daemon(sessions, state, deep=True, model=None, poll=0.01)
        except _Stop:
            pass
        if ticks["processed"]:
            fails.append("daemon processed despite kill-switch")
        # Remove the switch: now it processes.
        E.KILL_SWITCH.unlink()
        ticks["processed"] = False
        try:
            E.run_daemon(sessions, state, deep=True, model=None, poll=0.01)
        except _Stop:
            pass
        if not ticks["processed"]:
            fails.append("daemon did not process after kill-switch removed")
        E.time.sleep, E.process_new, E.KILL_SWITCH = orig_sleep, orig_pn, orig_ks

    if fails:
        print("FAIL:")
        for x in fails:
            print("  -", x)
        return 1
    print("PASS: daemon sweep triages+escalates+gates, advances cursor, skips done, kill-switch idles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
