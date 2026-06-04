"""Phase 2 eval: the local brain's parsing, clamping, class validation, and
graceful degrade, plus journal dedupe. The Ollama HTTP call is stubbed, no
network. Run directly, gate on exit code:

    python observer/test_brain.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript as T  # noqa: E402
import brain_local  # noqa: E402
import journal  # noqa: E402


def _session() -> T.Session:
    s = T.Session(path="x", session_id="sX", date="2026-06-04",
                  cwd="/home/keletonik/github/venode", end_reason="clear", index_ts="T")
    s.n_events = 100
    s.n_user_msgs = 5
    s.n_assistant_msgs = 40
    s.tool_counts = Counter({"Bash": 10, "Edit": 3})
    s.n_tool_errors = 2
    s.corrections = ["no, do it differently"]
    s.user_messages = ["build the thing"]
    return s


def main() -> int:
    fails: list[str] = []
    orig = brain_local._call_ollama

    # Class normalises to lower case; salience is deterministic from the facts
    # (1 correction 0.25 + 2 errors 0.16 + 3 mutations 0.03 = 0.44), not the model.
    brain_local._call_ollama = lambda *a, **k: json.dumps(
        {"session_class": "BUILD", "rule_drift": True, "notes": "x"})
    r = brain_local.triage(_session())
    if not (r["status"] == "ok" and r["salience"] == 0.44
            and r["session_class"] == "build" and r["signals"]["rule_drift"] is True):
        fails.append(f"normalise/salience: {r}")

    # An unknown class falls back to 'other'.
    brain_local._call_ollama = lambda *a, **k: json.dumps(
        {"salience": 0.2, "session_class": "frobnicate"})
    r = brain_local.triage(_session())
    if r["session_class"] != "other":
        fails.append(f"class fallback: {r['session_class']}")

    # A non-JSON response degrades to pending (json.loads raises, caught), no crash,
    # and salience stays deterministic.
    brain_local._call_ollama = lambda *a, **k: "this is not json at all"
    r = brain_local.triage(_session())
    if not (r["status"] == "pending" and r["salience"] == 0.44):
        fails.append(f"non-json degrade: {r}")

    # Model down: pending, no raise, deterministic signals still present.
    def boom(*a, **k):
        raise urllib.error.URLError("down")

    brain_local._call_ollama = boom
    r = brain_local.triage(_session())
    if not (r["status"] == "pending" and r["reason"] and r["signals"]["corrections"] == 1
            and r["salience"] == 0.44):
        fails.append(f"degrade: {r}")

    brain_local._call_ollama = orig

    # Salience discriminates: a busy, error-heavy session outscores a quiet one.
    quiet = T.Session(path="q", session_id="q", date="2026-06-04")
    quiet.n_assistant_msgs = 5
    busy = T.Session(path="b", session_id="b", date="2026-06-04")
    busy.n_tool_errors = 5
    busy.tool_counts = Counter({"Edit": 40})
    busy.corrections = ["no", "wrong"]
    if brain_local._deterministic_salience(busy) <= brain_local._deterministic_salience(quiet):
        fails.append("salience does not discriminate busy vs quiet")

    # Journal: an 'ok' record counts as triaged, a 'pending' one does not.
    with tempfile.TemporaryDirectory() as d:
        journal.append_record({"id": "ok1", "status": "ok"}, journal_dir=d)
        journal.append_record({"id": "p1", "status": "pending"}, journal_dir=d)
        if not journal.already_triaged("ok1", journal_dir=d):
            fails.append("ok record not detected as triaged")
        if journal.already_triaged("p1", journal_dir=d):
            fails.append("pending record wrongly counted as triaged")
        if journal.already_triaged("absent", journal_dir=d):
            fails.append("absent id wrongly counted as triaged")

    if fails:
        print("FAIL:")
        for x in fails:
            print("  -", x)
        return 1
    print("PASS: brain_local clamp/normalise/fallback/degrade + journal dedupe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
