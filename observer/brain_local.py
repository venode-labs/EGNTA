"""Egenta Phase 2: the local triage brain.

Feeds a parsed Session to the local model (Ollama) and gets back a triage
verdict, salience, a session class, and a rule-drift judgement plus a one-line
note. Raw session text is allowed here because the local model runs on this box
and nothing leaves it (per the system prompt's brain_routing). The deep brain
(Claude, redacted) is a later phase.

Deterministic facts (counts, errors, correction snippets) come from Phase 1.
The model only adds judgement on top, so a model that is down or talks nonsense
degrades to a 'pending' record with the facts intact, never a crash.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"  # nosemgrep: insecure-request-object  loopback, Ollama serves no TLS
DEFAULT_MODEL = os.environ.get("EGENTA_LOCAL_MODEL", "qwen2.5:3b")
CLASSES = {"build", "debug", "config", "research", "admin", "trivial", "other"}

_INSTRUCTION = (
    "You triage one Claude Code coding session for a meta-learning agent that "
    "wants to improve how the agent works. Read the facts and samples, then "
    "return ONLY a JSON object with these keys:\n"
    '  "session_class": one of build, debug, config, research, admin, trivial, other,\n'
    '  "rule_drift": true if the agent looked like it broke its own rules or '
    "needed correcting, else false,\n"
    '  "notes": one short sentence, the single most useful thing to learn.\n'
    "No prose outside the JSON. Salience is scored separately from the facts, "
    "do not return it."
)


def _deterministic_salience(session) -> float:
    """How much there is to learn from a session, scored from the Phase 1 facts
    rather than asked of the model. A 3B model gives near-uniform salience, the
    facts discriminate: corrections and tool errors are the richest signal, a
    busy session is worth more than a quiet one, and a long run the human barely
    steered is worth a look. Reproducible and model-independent."""
    score = 0.0
    score += min(0.5, 0.25 * len(session.corrections))
    score += min(0.3, 0.08 * session.n_tool_errors)
    score += min(0.15, 0.01 * session.n_mutations)
    if session.n_user_msgs == 0 and session.n_assistant_msgs > 20:
        score += 0.1
    return round(min(1.0, score), 2)


def _call_ollama(prompt: str, model: str, timeout: float) -> str:
    # Loopback only. Refuse anything that is not the local Ollama endpoint, so a
    # mangled OLLAMA_URL can never make urllib read a file:// path or reach a
    # remote host. http to 127.0.0.1 is correct here, Ollama serves no TLS.
    parsed = urllib.parse.urlparse(OLLAMA_URL)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError(f"refusing non-local Ollama URL: {OLLAMA_URL!r}")
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    req = urllib.request.Request(  # nosemgrep: insecure-request-object
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep: dynamic-urllib-use-detected
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("response", "")


def _build_prompt(session) -> str:
    facts = (
        f"repo: {session.cwd or 'unknown'}\n"
        f"end_reason: {session.end_reason or 'unknown'}\n"
        f"events: {session.n_events}, human messages: {session.n_user_msgs}, "
        f"assistant messages: {session.n_assistant_msgs}\n"
        f"tool uses: {session.n_tool_uses}, file mutations: {session.n_mutations}, "
        f"tool errors: {session.n_tool_errors}, corrections (crude): {len(session.corrections)}\n"
        f"top tools: {', '.join(f'{k}:{v}' for k, v in session.tool_counts.most_common(6)) or 'none'}"
    )
    humans = "\n".join(f"- {m}" for m in session.user_messages[:8]) or "(none captured)"
    corrections = "\n".join(f"- {c}" for c in session.corrections[:5]) or "(none flagged)"
    return (
        f"{_INSTRUCTION}\n\n"
        f"FACTS\n{facts}\n\n"
        f"HUMAN MESSAGES (sample)\n{humans}\n\n"
        f"CORRECTION CANDIDATES\n{corrections}\n"
    )


def _base_record(session, model: str) -> dict:
    return {
        "id": session.session_id,
        "ts": session.index_ts,
        "brain": f"local:{model}",
        "salience": _deterministic_salience(session),
        "session_class": "",
        "signals": {
            "corrections": len(session.corrections),
            "errors": session.n_tool_errors,
            "rule_drift": False,
            "notes": "",
        },
        "repo": session.cwd,
        "model": model,
        "status": "pending",
        "reason": "",
        "facts": {
            "events": session.n_events,
            "human": session.n_user_msgs,
            "injected": session.n_injected,
            "assistant": session.n_assistant_msgs,
            "tool_uses": session.n_tool_uses,
            "mutations": session.n_mutations,
            "tool_errors": session.n_tool_errors,
        },
    }


def triage(session, model: str | None = None, timeout: float = 60.0) -> dict:
    model = model or DEFAULT_MODEL
    rec = _base_record(session, model)
    try:
        verdict = json.loads(_call_ollama(_build_prompt(session), model, timeout))
        cls = str(verdict.get("session_class", "")).strip().lower()
        rec["session_class"] = cls if cls in CLASSES else "other"
        rec["signals"]["rule_drift"] = bool(verdict.get("rule_drift", False))
        rec["signals"]["notes"] = " ".join(str(verdict.get("notes", "")).split())[:300]
        rec["status"] = "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        rec["reason"] = f"{type(exc).__name__}: {exc}"[:200]
    return rec
