"""Phase 3 eval: the redactor. The wall is only as good as its test, so this is
hard. Every secret below is fake but shaped like the real thing. The critical
property: after redaction, not one raw secret value survives in the output. We
also prove the redactor does NOT eat benign content (git shas, prose, code), and
that the session-excerpt builder redacts every free-text field. Run directly,
gate on exit code:

    python observer/test_redactor.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redactor as R  # noqa: E402
import transcript as T  # noqa: E402

# (label, secret string that must vanish, expected redaction type)
SECRETS = [
    ("anthropic", "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF1234567", "anthropic-key"),
    ("openai", "sk-AAAABBBBCCCCDDDDEEEEFFFF1234567890", "openai-key"),
    ("aws", "AKIAIOSFODNN7EXAMPLE", "aws-key"),
    ("github", "ghp_AAAABBBBCCCCDDDDEEEEFFFF1111222233334444", "github-token"),
    ("github-pat", "github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ012345", "github-pat"),
    ("slack", "xoxb-1234567890-abcdefghijklmnopqr", "slack-token"),
    ("google", "AIzaSyA1234567890abcdefghijklmnopqrstuv", "google-key"),
    ("email", "kaspar@venode.ai", "email"),
    ("private-ip-192", "192.168.1.107", "private-ip"),
    ("private-ip-10", "10.0.0.5", "private-ip"),
    ("loopback", "127.0.0.1", "private-ip"),
]

# Benign content the redactor must leave alone.
BENIGN = [
    "1931545abcdef0123456789abcdef0123456789a",   # 40-char git sha, pure hex
    "the quick brown fox jumps over the lazy dog",
    "def _deterministic_salience(session):",
    "commit 908d267 add pdf docx pptx",
]


def main() -> int:
    fails: list[str] = []

    # 1. Each secret vanishes and is counted under the right type.
    for label, secret, kind in SECRETS:
        res = R.redact(f"the value is {secret} ok")
        if secret in res.text:
            fails.append(f"{label}: raw secret survived -> {res.text!r}")
        if res.counts.get(kind, 0) < 1:
            fails.append(f"{label}: not counted as {kind} -> {dict(res.counts)}")
        if "[REDACTED:" not in res.text:
            fails.append(f"{label}: no placeholder emitted")

    # 2. A blob with every secret at once: zero raw values survive.
    blob = "\n".join(s for _, s, _ in SECRETS)
    res = R.redact(blob)
    for label, secret, _ in SECRETS:
        if secret in res.text:
            fails.append(f"blob: {label} survived combined redaction")

    # 3. Secret-in-assignment redacts the value, may keep the key name.
    res = R.redact("DB_PASSWORD=hunter2hunter2value")
    if "hunter2hunter2value" in res.text:
        fails.append(f"assignment value survived: {res.text!r}")
    res = R.redact("export MY_API_TOKEN='abc123def456ghi'")
    if "abc123def456ghi" in res.text:
        fails.append(f"quoted assignment value survived: {res.text!r}")

    # 4. URL credentials scrubbed, host kept.
    res = R.redact("clone https://kaspar:s3cr3tpassword@git.internal.example/repo.git")
    if "s3cr3tpassword" in res.text or "kaspar:s3" in res.text:
        fails.append(f"url credentials survived: {res.text!r}")

    # 5. Bearer / Authorization headers scrubbed.
    res = R.redact("Authorization: Bearer abcdefGHIJ1234567890klmnopQRST")
    if "abcdefGHIJ1234567890klmnopQRST" in res.text:
        fails.append(f"bearer token survived: {res.text!r}")

    # 6. Home path leaks the username -> redacted, path shape kept.
    res = R.redact("see /home/keletonik/secret/notes.txt")
    if "keletonik" in res.text:
        fails.append(f"username survived in path: {res.text!r}")
    if "/home/" not in res.text:
        fails.append("path shape destroyed")

    # 7. High-entropy catch-all gets a mixed token, leaves pure-hex shas alone.
    res = R.redact("token Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2Yz34 end")
    if "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2Yz34" in res.text:
        fails.append("high-entropy token survived")

    # 8. Benign content is preserved verbatim.
    for b in BENIGN:
        res = R.redact(b)
        if res.text != b:
            fails.append(f"benign content altered: {b!r} -> {res.text!r}")

    # 9. Non-string input does not crash.
    if R.redact(12345).text != "12345":
        fails.append("non-string input not coerced")

    # 10. redact_excerpt scrubs every free-text field of a Session.
    s = T.Session(path="x", session_id="s1", date="2026-06-04",
                  cwd="/home/keletonik/github/venode")
    s.n_assistant_msgs = 30
    s.user_messages = ["my key is sk-ant-api03-ZZZZYYYYXXXXWWWW1234567 use it",
                       "email me at kaspar@venode.ai"]
    s.corrections = ["no, the host is 192.168.1.50"]
    s.tool_counts = Counter({"Bash": 3})
    excerpt, counts = R.redact_excerpt(s)
    for bad in ("sk-ant-api03-ZZZZYYYYXXXXWWWW1234567", "kaspar@venode.ai", "192.168.1.50", "keletonik"):
        if bad in excerpt:
            fails.append(f"excerpt leaked {bad!r}")
    if counts.get("anthropic-key", 0) < 1 or counts.get("email", 0) < 1:
        fails.append(f"excerpt counts wrong: {dict(counts)}")

    # 11. Idempotence: re-redacting redacted text finds nothing new and is stable.
    # The deep-brain tripwire relies on this (a placeholder must not re-match).
    once = R.redact(blob + " /home/keletonik/x kaspar@venode.ai").text
    twice = R.redact(once)
    if twice.total != 0 or twice.text != once:
        fails.append(f"not idempotent: second pass redacted {twice.total} more, changed={twice.text != once}")

    if fails:
        print("FAIL:")
        for x in fails:
            print("  -", x)
        return 1
    print(f"PASS: redactor scrubs {len(SECRETS)} secret types + assignments/urls/headers/paths, "
          f"preserves benign content, excerpt builder leaks nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
