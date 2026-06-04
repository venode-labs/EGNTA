"""Phase 1 eval: the parser must extract sane structure from the real captured
transcripts. No test-framework dependency, run directly and gate on exit code:

    python observer/test_transcript.py

This is the eval that ships with Phase 1 (per the agentic discipline: evals in
phase 1, not later). Later phases extend it with synthetic fixtures and
adversarial inputs.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript as T  # noqa: E402

SESSIONS = Path.home() / "clilogs" / "claude-logs" / "sessions"


def test_synthetic() -> list[str]:
    """Edge-case fixture: malformed lines, tool errors, and every injected
    variant, parsed from a controlled transcript so behaviour is pinned even if
    the real captures change. Returns a list of failure strings."""
    rows = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "working"},
            {"type": "tool_use", "name": "Write", "input": {"path": "x"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "1", "is_error": True, "content": "boom"},
        ]}},
        {"type": "user", "message": {"role": "user", "content": "no, do it the other way"}},
        {"type": "user", "message": {"role": "user", "content": "Base directory for this skill: /x\nbody"}},
        {"type": "user", "message": {"role": "user", "content": "# Update Config Skill\nModify settings."}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/check</command-name>"}},
    ]
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "2026-06-04-synthsess.jsonl"
        with f.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write("{ this is not json\n")  # malformed line must be skipped, not fatal

        s = T.parse(f, meta={"cwd": "/home/keletonik/github/venode", "reason": "clear", "ts": "T"})
        expect = {
            "session_id from name": s.session_id == "synthsess",
            "malformed line skipped": s.n_events == len(rows),
            "one human turn": s.n_user_msgs == 1,
            "three injected": s.n_injected == 3,
            "one correction": len(s.corrections) == 1,
            "one tool error": s.n_tool_errors == 1,
            "Write counted": s.tool_counts.get("Write") == 1,
            "index cwd attached": s.cwd.endswith("venode"),
            "index reason attached": s.end_reason == "clear",
        }
        for name, ok in expect.items():
            if not ok:
                fails.append(f"synthetic: {name}")
    return fails


def main() -> int:
    failures: list[str] = test_synthetic()
    print("ok  synthetic fixture" if not failures else "FAIL synthetic fixture")

    files = sorted(SESSIONS.glob("*.jsonl"))
    if not files:
        print(f"(no real transcripts in {SESSIONS}, synthetic only)")
        if failures:
            print("FAIL:")
            for x in failures:
                print("  -", x)
            return 1
        print("PASS: synthetic fixture held")
        return 0

    for f in files:
        s = T.parse(f)
        checks = {
            "session_id parsed": bool(s.session_id),
            "events counted": s.n_events > 0,
            "assistant messages present": s.n_assistant_msgs > 0,
            "tool_uses consistent": s.n_tool_uses == sum(s.tool_counts.values()),
            "events list populated": len(s.events) > 0,
            "user_messages are strings": all(isinstance(x, str) for x in s.user_messages),
            "tool_errors <= tool_results": s.n_tool_errors <= s.n_tool_results,
            # Regression: injected messages (hook feedback, skill bodies, slash
            # markers) must not be counted as human turns or flagged corrections.
            "no injected in corrections": not any(
                c.lower().startswith(("stop hook feedback", "base directory for this skill", "caveat:"))
                or "<command-" in c.lower() for c in s.corrections
            ),
        }
        for name, ok in checks.items():
            if not ok:
                failures.append(f"{f.name}: {name}")
        print(f"ok  {s.session_id}: events={s.n_events} tools={s.n_tool_uses} "
              f"users={s.n_user_msgs} errors={s.n_tool_errors} corrections={len(s.corrections)}")

    if failures:
        print("FAIL:")
        for x in failures:
            print("  -", x)
        return 1
    print(f"PASS: {len(files)} transcript(s) parsed, all structural checks held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
