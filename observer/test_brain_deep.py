"""Phase 4 eval: the deep brain. Hermetic, the Claude API is stubbed, no network.
The two assertions that matter: what gets SENT is redacted, and the tripwire
refuses to send when a secret slips the first pass. Plus gating, finding shape,
artifact cleaning, and graceful degrade. Run directly, gate on exit code:

    python observer/test_brain_deep.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_deep as D  # noqa: E402
import redactor  # noqa: E402
import transcript as T  # noqa: E402


def _session(secret_msg: str) -> T.Session:
    s = T.Session(path="x", session_id="s1", date="2026-06-04", cwd="/home/keletonik/repo")
    s.n_assistant_msgs = 30
    s.user_messages = [secret_msg]
    s.corrections = ["no, wrong"]
    s.tool_counts = Counter({"Bash": 5})
    return s


def main() -> int:
    fails: list[str] = []
    orig_call = D._call_claude
    orig_excerpt = redactor.redact_excerpt

    # 1. What is sent is redacted. Capture the assembled user prompt.
    sent = {}

    def capture(system, user, model, api_key, timeout):
        sent["user"] = user
        sent["system"] = system
        return json.dumps({"root_cause": "rc", "confidence": 0.8,
                           "artifacts": [{"type": "lesson", "title": "t", "rationale": "r", "body": "b"}]})

    D._call_claude = capture
    sess = _session("my key is sk-ant-api03-LEAKEDAAAA1111BBBB2222CCCC use it")
    rec = {"id": "s1", "salience": 0.9}
    finding = D.analyse([sess], [rec], api_key="test-key")
    if "sk-ant-api03-LEAKEDAAAA1111BBBB2222CCCC" in sent.get("user", ""):
        fails.append("RAW SECRET WAS SENT to the API, redaction failed")
    if "[REDACTED:" not in sent.get("user", ""):
        fails.append("sent prompt has no redaction marker")
    if not (finding["status"] == "ok" and finding["root_cause"] == "rc"
            and finding["confidence"] == 0.8 and len(finding["artifacts"]) == 1):
        fails.append(f"finding shape wrong: {finding}")

    # 2. Tripwire: simulate the first redaction pass MISSING a secret. analyse
    # must re-scan, see it, and refuse to send.
    called = {"sent": False}

    def boom(*a, **k):
        called["sent"] = True
        raise AssertionError("should not have been called")

    redactor.redact_excerpt = lambda s, **k: ("leak sk-ant-api03-STILLHERE9999AAAA8888BBBB now", Counter())
    D._call_claude = boom
    finding = D.analyse([sess], [rec], api_key="test-key")
    if called["sent"]:
        fails.append("tripwire FAILED: call was made despite a leak")
    if finding["status"] != "blocked":
        fails.append(f"tripwire did not block: {finding['status']} {finding['reason']}")
    redactor.redact_excerpt = orig_excerpt

    # 3. Escalation gate.
    if not D.should_escalate({"salience": 0.6}):
        fails.append("did not escalate a salient session")
    if D.should_escalate({"salience": 0.1}, recurrence=0):
        fails.append("escalated a low-salience one-off")
    if not D.should_escalate({"salience": 0.1}, recurrence=3):
        fails.append("did not escalate a recurring signal")

    # 4. Artifact cleaning: unknown type dropped, list capped at 3.
    D._call_claude = lambda *a, **k: json.dumps({
        "root_cause": "x", "confidence": 5,  # out of range -> clamped to 1.0
        "artifacts": [
            {"type": "script", "title": "a", "body": "b"},
            {"type": "frobnicate", "title": "bad"},      # dropped
            {"type": "skill", "title": "c", "body": "d"},
            {"type": "lesson", "title": "e", "body": "f"},
            {"type": "training", "title": "g", "body": "h"},  # over cap of 3
        ]})
    finding = D.analyse([_session("clean message")], [{"id": "s1", "salience": 0.9}], api_key="k")
    if finding["confidence"] != 1.0:
        fails.append(f"confidence not clamped: {finding['confidence']}")
    types = [a["type"] for a in finding["artifacts"]]
    if "frobnicate" in types or len(finding["artifacts"]) > 3:
        fails.append(f"artifact cleaning wrong: {types}")

    # 5. Degrade: no key -> pending, no send.
    D._call_claude = boom
    called["sent"] = False
    finding = D.analyse([_session("x")], [{"id": "s1", "salience": 0.9}], api_key="")
    if called["sent"] or finding["status"] != "pending" or not finding["reason"]:
        fails.append(f"no-key degrade wrong: {finding}")

    # 6. API down -> pending, no crash.
    def down(*a, **k):
        import urllib.error
        raise urllib.error.URLError("down")

    D._call_claude = down
    finding = D.analyse([_session("x")], [{"id": "s1", "salience": 0.9}], api_key="k")
    if finding["status"] != "pending" or not finding["reason"]:
        fails.append(f"api-down degrade wrong: {finding}")

    D._call_claude = orig_call

    if fails:
        print("FAIL:")
        for x in fails:
            print("  -", x)
        return 1
    print("PASS: deep brain redacts before send, tripwire blocks leaks, gates/cleans/degrades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
