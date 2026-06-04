"""Phase 5 eval: the write gate and proposal queue. Everything runs in a temp
home so a real file is never touched. The properties that matter: Egenta-internal
artifacts auto-write, everything else queues and writes nothing outside Egenta,
CLAUDE.md is denied even on approval, and approve/reject move proposals and apply
only what a human signed off. Run directly, gate on exit code:

    python observer/test_gate.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as G  # noqa: E402


def main() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        G.HOME = home
        G.EGENTA = home / "Egenta"

        # classify: inside Egenta auto, skills/bin queue, CLAUDE.md deny.
        if G.classify(G.EGENTA / "lessons" / "x.md") != "auto":
            fails.append("Egenta path not auto")
        if G.classify(home / ".claude" / "skills" / "x" / "SKILL.md") != "queue":
            fails.append("skill path not queued")
        if G.classify(home / ".local" / "bin" / "x.sh") != "queue":
            fails.append("bin path not queued")
        if G.classify(home / ".claude" / "CLAUDE.md") != "deny":
            fails.append("CLAUDE.md not denied")

        # lesson auto-writes inside Egenta.
        r = G.write_or_queue({"type": "lesson", "title": "anchor rule", "body": "always anchor"}, "f1")
        if r["action"] != "written" or not (G.EGENTA / "lessons" / "findings.md").exists():
            fails.append(f"lesson not written: {r}")
        if "always anchor" not in (G.EGENTA / "lessons" / "findings.md").read_text():
            fails.append("lesson body missing")

        # training auto-writes inside Egenta.
        r = G.write_or_queue({"type": "training", "title": "pair", "body": '{"in":1}'}, "f1")
        if r["action"] != "written" or not (G.EGENTA / "datasets" / "proposed.jsonl").exists():
            fails.append(f"training not written: {r}")

        # skill + script queue, and write NOTHING outside Egenta.
        rs = G.write_or_queue({"type": "skill", "title": "My Helper", "rationale": "why",
                               "body": "---\nname: my-helper\n---\nbody"}, "f1")
        rc = G.write_or_queue({"type": "script", "title": "do thing", "body": "echo hi"}, "f1")
        if rs["action"] != "queued" or rc["action"] != "queued":
            fails.append(f"skill/script not queued: {rs} {rc}")
        if (home / ".claude" / "skills").exists() or (home / ".local" / "bin").exists():
            fails.append("queuing wrote outside Egenta")
        if len(G.list_pending()) != 2:
            fails.append(f"pending count wrong: {len(G.list_pending())}")
        if not (G.EGENTA / "proposals" / "index.md").exists():
            fails.append("no index written")

        # deterministic id: same artifact queues to the same id, no duplicate.
        rc2 = G.write_or_queue({"type": "script", "title": "do thing", "body": "echo hi"}, "f1")
        if rc2["id"] != rc["id"] or len(G.list_pending()) != 2:
            fails.append("non-deterministic id or duplicate proposal")

        # approve the skill: applies to the real target, moves to approved.
        ap = G.approve(rs["id"])
        skill_file = home / ".claude" / "skills" / "my-helper" / "SKILL.md"
        if ap["action"] != "applied" or not skill_file.exists():
            fails.append(f"approve did not apply: {ap}")
        if "name: my-helper" not in skill_file.read_text():
            fails.append("approved skill body wrong")
        if (G.EGENTA / "proposals" / "pending" / f"{rs['id']}.md").exists():
            fails.append("approved proposal still pending")
        if not (G.EGENTA / "proposals" / "approved" / f"{rs['id']}.md").exists():
            fails.append("approved proposal not archived")

        # reject the script: moves to rejected with the reason.
        rj = G.reject(rc["id"], "not worth a binary")
        if rj["action"] != "rejected":
            fails.append(f"reject failed: {rj}")
        rejected = (G.EGENTA / "proposals" / "rejected" / f"{rc['id']}.md")
        if not rejected.exists() or "not worth a binary" not in rejected.read_text():
            fails.append("rejection reason not recorded")
        if G.list_pending():
            fails.append(f"pending not empty after approve+reject: {len(G.list_pending())}")

        # a proposal whose target is CLAUDE.md is refused even on approve.
        pend = G._proposals_dir("pending")
        import json as _json
        meta = {"id": "deny1", "target": str(home / ".claude" / "CLAUDE.md"), "body": "x", "status": "pending"}
        (pend / "deny1.md").write_text(f"# x\n<!-- egenta-proposal\n{_json.dumps(meta)}\n-->\n")
        dn = G.approve("deny1")
        if dn["action"] != "refused" or (home / ".claude" / "CLAUDE.md").exists():
            fails.append(f"CLAUDE.md not refused on approve: {dn}")

    if fails:
        print("FAIL:")
        for x in fails:
            print("  -", x)
        return 1
    print("PASS: gate auto-writes inside Egenta, queues the rest writing nothing outside, "
          "approve applies, reject archives, CLAUDE.md refused even on approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
