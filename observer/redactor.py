"""Egenta Phase 3: the redactor. The wall between raw session logs and the deep
brain (Claude, Phase 4). Nothing reaches the network until it has passed through
here.

The job is one-directional and paranoid: strip secrets, keys, tokens, `.env`
values, credentials in URLs, private hosts and addresses, emails, and the local
username out of any text before it can be sent off the box. It over-redacts on
purpose. A redacted excerpt that lost a little useful context is fine; a leaked
key is not. Replacements are typed placeholders like `[REDACTED:aws-key]` so the
deep brain still sees the shape of what was there.

Stdlib only. No network, no writes (a `--check` CLI reports counts without ever
printing the secret). Test it hard before Phase 4 trusts it: `test_redactor.py`.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass

# Order matters: the most specific, highest-confidence patterns run first, so a
# private-key block or a labelled token is caught before a broad catch-all can
# mangle it. Each entry is (type, compiled pattern, group-to-redact or 0 for the
# whole match). The replacement is always [REDACTED:<type>].
_RULES: list[tuple[str, re.Pattern, int]] = [
    # Whole PEM private-key blocks, header to footer.
    ("private-key",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), 0),
    # Provider API keys and tokens with distinctive prefixes.
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), 0),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}"), 0),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"), 0),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), 0),
    # Credentials carried in a URL: scheme://user:pass@host -> redact user:pass.
    ("url-credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s:@]+(?=@)"), 0),
    # Authorization / Bearer headers.
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"), 0),
    ("authorization", re.compile(r"(?im)^\s*authorization\s*:\s*\S+.*$"), 0),
    # Any KEY=VALUE / KEY: VALUE where the key name smells secret: redact VALUE.
    ("secret-assignment",
     re.compile(r"(?im)\b(\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|APIKEY|API_KEY|AUTH)\w*)"
                r"\s*[:=]\s*([^\s'\"]{4,}|'[^']*'|\"[^\"]*\")"), 2),
    # Emails.
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0),
    # Private and loopback IPv4.
    ("private-ip",
     re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}"
                r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|127(?:\.\d{1,3}){3})\b"), 0),
    # Local home paths leak the username: /home/<user> or /Users/<user>.
    ("home-user", re.compile(r"(?<=/home/)[^/\s]+|(?<=/Users/)[^/\s]+"), 0),
    # Broad catch-all: a long mixed-case-plus-digits token reads as a secret.
    # Deliberately skips pure hex (git shas, hashes stay useful) and short tokens.
    ("high-entropy",
     re.compile(r"\b(?=[A-Za-z0-9_+/-]{32,}\b)(?=[^\s]*[A-Z])(?=[^\s]*[a-z])(?=[^\s]*\d)"
                r"[A-Za-z0-9_+/-]{32,}\b"), 0),
]


@dataclass
class RedactResult:
    text: str
    counts: Counter  # type -> number redacted

    @property
    def total(self) -> int:
        return sum(self.counts.values())


_PLACEHOLDER = re.compile(r"\[REDACTED:[a-z-]+\]")


def _scrub_segment(seg: str, counts: Counter) -> str:
    for kind, pat, group in _RULES:
        def _sub(m, kind=kind, group=group):
            counts[kind] += 1
            if group == 0:
                return f"[REDACTED:{kind}]"
            # Keep the key name, redact only the value group.
            whole, val = m.group(0), m.group(group)
            return whole.replace(val, f"[REDACTED:{kind}]", 1)
        seg = pat.sub(_sub, seg)
    return seg


def redact(text: str) -> RedactResult:
    """Run every rule in order. Returns the scrubbed text and a per-type count.
    Never raises on normal input; a non-string is coerced to one.

    Idempotent: existing `[REDACTED:...]` placeholders are protected from the
    rules, so re-redacting already-redacted text finds nothing new. The deep
    brain's tripwire relies on this, a second pass returning a non-zero count
    must mean a genuinely missed secret, not a placeholder re-matching itself."""
    if not isinstance(text, str):
        text = str(text)
    counts: Counter = Counter()
    out, last = [], 0
    for m in _PLACEHOLDER.finditer(text):
        out.append(_scrub_segment(text[last:m.start()], counts))
        out.append(m.group(0))  # keep the placeholder untouched
        last = m.end()
    out.append(_scrub_segment(text[last:], counts))
    return RedactResult(text="".join(out), counts=counts)


def redact_excerpt(session, max_msgs: int = 8, max_corrections: int = 5) -> tuple[str, Counter]:
    """Build the redacted excerpt the deep brain is allowed to see from a parsed
    Session: the facts (already non-sensitive counts), a sample of human messages,
    and the correction candidates. Every free-text field is redacted. The repo
    path is redacted too, since it can carry the username or a client name."""
    repo = redact(session.cwd or "unknown").text
    facts = (
        f"repo: {repo}\n"
        f"class-signals: events={session.n_events} human={session.n_user_msgs} "
        f"assistant={session.n_assistant_msgs} tool_uses={session.n_tool_uses} "
        f"mutations={session.n_mutations} tool_errors={session.n_tool_errors} "
        f"corrections={len(session.corrections)}\n"
        f"top tools: {', '.join(f'{k}:{v}' for k, v in session.tool_counts.most_common(6)) or 'none'}"
    )
    counts: Counter = Counter()
    msgs = []
    for m in session.user_messages[:max_msgs]:
        r = redact(m)
        counts.update(r.counts)
        msgs.append(f"- {r.text}")
    corrs = []
    for c in session.corrections[:max_corrections]:
        r = redact(c)
        counts.update(r.counts)
        corrs.append(f"- {r.text}")
    excerpt = (
        f"FACTS\n{facts}\n\n"
        f"HUMAN MESSAGES (sample, redacted)\n{chr(10).join(msgs) or '(none)'}\n\n"
        f"CORRECTION CANDIDATES (redacted)\n{chr(10).join(corrs) or '(none)'}\n"
    )
    return excerpt, counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Egenta redactor: scrub secrets from text.")
    ap.add_argument("file", nargs="?", help="file to redact (default: stdin)")
    ap.add_argument("--check", action="store_true",
                    help="report only the count per type, never print the redacted text or the secret")
    args = ap.parse_args(argv)

    text = open(args.file, encoding="utf-8", errors="replace").read() if args.file else sys.stdin.read()
    result = redact(text)
    if args.check:
        if not result.total:
            print("redact-check: clean, nothing to redact")
        else:
            print(f"redact-check: {result.total} item(s) would be redacted")
            for kind, n in sorted(result.counts.items()):
                print(f"  {kind}: {n}")
        return 0
    sys.stdout.write(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
