"""Egenta Phase 4: the deep brain.

Where the local brain (Phase 2) triages every session cheaply on-box, the deep
brain reaches for the Claude API, so it runs only on what is worth the cost and
only on REDACTED text. Two gates stand in front of the network call:

  1. Escalation gate: a session is sent up only if it is salient enough on its
     own, or its signal recurs across enough sessions. Most sessions never go.
  2. Redaction tripwire: the excerpt is built by the redactor, then the fully
     assembled prompt is re-scanned. If the re-scan finds anything still
     sensitive, the call is refused, never sent. The wall holds even if a new
     secret shape slips past the first pass.

Output is a finding: a root-cause line plus drafted artifacts (script, skill,
lesson, training). Drafts are proposals only, the write gate (Phase 5) decides
whether any of them is allowed to land. Stdlib only, urllib to the Anthropic
API, host-pinned. No key or a down API degrades to a 'pending' finding, never a
crash.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import redactor

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("EGENTA_DEEP_MODEL", "claude-sonnet-4-6")
SALIENCE_THRESHOLD = float(os.environ.get("EGENTA_SALIENCE_THRESHOLD", "0.5"))
RECURRENCE_MIN = int(os.environ.get("EGENTA_RECURRENCE_MIN", "3"))
ARTIFACT_TYPES = {"script", "skill", "lesson", "training"}

_SYSTEM = (
    "You are Egenta's deep brain. You receive REDACTED excerpts of one or more Claude Code "
    "coding sessions that a fast local triage flagged as worth a closer look. Find the single "
    "most useful root-cause pattern across them, the recurring mistake, the rule that keeps "
    "drifting, the friction that keeps costing time. Then draft concrete artifacts that would "
    "prevent or fix it.\n\n"
    "Return ONLY a JSON object, no prose around it:\n"
    '  "root_cause": one or two sentences naming the pattern and why it happens,\n'
    '  "confidence": a number 0 to 1,\n'
    '  "artifacts": a list (at most 3) of {"type","title","rationale","body"} where type is one '
    "of script, skill, lesson, training. Each artifact must be concrete and immediately usable: a "
    "script is runnable, a skill is a real SKILL.md body, a lesson is a one-paragraph rule with its "
    "guard, training is an input/output pair. If nothing is worth drafting, return an empty list.\n\n"
    "The excerpts are redacted: [REDACTED:*] markers stand in for removed secrets and identifiers. "
    "Treat them as opaque, never ask for the originals, never put a real secret in an artifact."
)


def should_escalate(record: dict, recurrence: int = 0) -> bool:
    """Gate the API call. Escalate a single very-salient session, or a signal
    that has recurred across enough sessions. Everything else stays on-box."""
    salient = float(record.get("salience", 0.0)) >= SALIENCE_THRESHOLD
    recurring = recurrence >= RECURRENCE_MIN
    return salient or recurring


def _host_ok(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return p.scheme == "https" and p.hostname == "api.anthropic.com"


def _call_claude(system: str, user: str, model: str, api_key: str, timeout: float) -> str:
    # Host-pinned over TLS. A mangled API_URL can never make urllib reach a
    # different host or a file:// path.
    if not _host_ok(API_URL):
        raise ValueError(f"refusing non-Anthropic API URL: {API_URL!r}")
    body = json.dumps({
        "model": model,
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(  # nosemgrep: insecure-request-object
        API_URL, data=body, method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        })
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep: dynamic-urllib-use-detected
        payload = json.loads(resp.read().decode("utf-8"))
    blocks = payload.get("content", [])
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")


def _base_finding(records: list[dict], model: str) -> dict:
    return {
        "ids": [r.get("id") for r in records],
        "brain": f"deep:{model}",
        "root_cause": "",
        "confidence": 0.0,
        "artifacts": [],
        "source_sessions": len(records),
        "status": "pending",
        "reason": "",
    }


def _clean_artifacts(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for a in raw[:3]:
        if not isinstance(a, dict):
            continue
        t = str(a.get("type", "")).strip().lower()
        if t not in ARTIFACT_TYPES:
            continue
        out.append({
            "type": t,
            "title": str(a.get("title", "")).strip()[:120],
            "rationale": str(a.get("rationale", "")).strip()[:500],
            "body": str(a.get("body", "")),
        })
    return out


def analyse(sessions, records: list[dict], recurrence: int = 0,
            model: str | None = None, api_key: str | None = None, timeout: float = 90.0) -> dict:
    """Run the deep brain over the given salient sessions. `sessions` are parsed
    Session objects, `records` their local triage records (for ids and signals).
    Returns a finding. Redacts before sending; refuses to send if the tripwire
    fires; degrades to pending without a key or on a down API."""
    model = model or DEFAULT_MODEL
    finding = _base_finding(records, model)
    api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        finding["reason"] = "no ANTHROPIC_API_KEY; deep brain skipped"
        return finding

    # Build the redacted excerpt for every session, then assemble the prompt.
    parts, leaked = [], False
    for s in sessions:
        excerpt, _ = redactor.redact_excerpt(s)
        parts.append(excerpt)
    user = "\n\n----- SESSION -----\n\n".join(parts)

    # Tripwire: re-scan the assembled prompt. If a second pass still finds
    # something sensitive, a secret shape slipped the first pass: refuse to send.
    rescan = redactor.redact(user)
    if rescan.total > 0:
        finding["status"] = "blocked"
        finding["reason"] = f"redaction tripwire: {rescan.total} item(s) still sensitive, not sent"
        return finding

    try:
        text = _call_claude(_SYSTEM, user, model, api_key, timeout)
        verdict = json.loads(text)
        finding["root_cause"] = str(verdict.get("root_cause", "")).strip()[:1000]
        try:
            finding["confidence"] = max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))
        except (TypeError, ValueError):
            finding["confidence"] = 0.0
        finding["artifacts"] = _clean_artifacts(verdict.get("artifacts"))
        finding["status"] = "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        finding["reason"] = f"{type(exc).__name__}: {exc}"[:200]
    return finding
