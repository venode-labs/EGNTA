"""Egenta Phase 1: parse a captured Claude Code session transcript into a
structured, read-only Session model. Stdlib only. No network, no writes.

Transcripts live at ~/clilogs/claude-logs/sessions/<date>-<session_id>.jsonl,
one JSON object per line, written by the SessionEnd capture hook. Event shapes
vary (user, assistant, system, mode, attachment, ...), so every field is read
defensively, a malformed line is skipped rather than fatal.

This is the capture layer only. Classifying what matters in a session is the
local brain's job in Phase 2; here we just extract faithful structure and a few
crude counts, each labelled as crude.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Tools whose use changes the world, tracked as a coarse 'how active was this
# session' signal. Mirrors the mutating set the discipline Stop hook keys on.
_MUTATING = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Crude marker of the user correcting or overriding the agent. Phase 1 counts
# only, the local brain does real classification in Phase 2. Anchored to the
# start of the message to cut the worst false positives.
_CORRECTION = re.compile(
    r"^\s*(no\b|stop\b|wrong\b|don'?t\b|do not\b|actually\b|instead\b|undo\b|revert\b|that'?s not\b|not what\b)",
    re.I,
)

# A 'user' role event is not always a human turn. Skill bodies, slash-command
# markers, hook feedback and system reminders all arrive role=user. These are
# injected, not Kaspar, so they must not count as human messages or trip the
# correction signal. Detection is prefix/marker based, deliberately
# conservative, the local brain refines this in Phase 2.
_INJECTED_PREFIXES = (
    "base directory for this skill:",
    "stop hook feedback:",
    "caveat:",
    "[request interrupted",
)
_INJECTED_MARKERS = (
    "<command-name>",
    "<command-message>",
    "<system-reminder>",
    "<local-command-stdout>",
)
# A skill body injected as a user message often opens with a markdown title like
# '# Update Config Skill'. Narrow on purpose, a title ending in 'Skill', to avoid
# swallowing a genuine human heading. Best-effort, the Phase 2 brain refines it.
_SKILL_TITLE = re.compile(r"^#\s+[\w][\w /+.-]{0,40}\bskill\b", re.I)


def _is_injected(text: str) -> bool:
    t = text.lstrip()
    low = t[:64].lower()
    if any(low.startswith(p) for p in _INJECTED_PREFIXES):
        return True
    if _SKILL_TITLE.match(t):
        return True
    head = t[:400].lower()
    return any(tok in head for tok in _INJECTED_MARKERS)


@dataclass
class Event:
    """One modelled event in transcript order. Non-message events (mode,
    attachment, ...) are counted in the Session but not turned into Events."""
    role: str          # 'user' or 'assistant'
    kind: str          # 'text' | 'tool_use' | 'tool_result'
    name: str = ""     # tool name, for tool_use
    is_error: bool = False
    summary: str = ""  # short, whitespace-collapsed, truncated


@dataclass
class Session:
    path: str
    session_id: str
    date: str
    cwd: str = ""          # from index.ndjson: the directory the session ran in
    end_reason: str = ""   # from index.ndjson: clear | resume | other | ...
    index_ts: str = ""     # from index.ndjson: session-end timestamp
    n_events: int = 0
    n_user_msgs: int = 0        # genuine human turns (injected messages excluded)
    n_injected: int = 0         # skill bodies, slash-command markers, hook feedback
    n_assistant_msgs: int = 0
    n_tool_results: int = 0
    n_tool_errors: int = 0      # reliable: tool_result with is_error true
    tool_counts: Counter = field(default_factory=Counter)
    events: list[Event] = field(default_factory=list)
    user_messages: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)  # crude heuristic

    @property
    def n_tool_uses(self) -> int:
        return sum(self.tool_counts.values())

    @property
    def n_mutations(self) -> int:
        return sum(v for k, v in self.tool_counts.items() if k in _MUTATING)


def _text_of(content) -> str:
    """Flatten message content (str, or a list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        return " ".join(parts)
    return ""


def _trunc(s: str, n: int = 200) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse_name(filename: str) -> tuple[str, str]:
    """<YYYY-MM-DD>-<session_id>.jsonl -> (date, session_id)."""
    stem = filename[:-6] if filename.endswith(".jsonl") else filename
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)$", stem)
    return (m.group(1), m.group(2)) if m else ("", stem)


def load_index(sessions_dir) -> dict[str, dict]:
    """Read index.ndjson into {session_id: {ts, cwd, reason, ...}}. The capture
    hook writes one line per session end. Missing or malformed file yields {}."""
    f = Path(sessions_dir) / "index.ndjson"
    out: dict[str, dict] = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = o.get("session_id")
        if sid:
            out[sid] = o  # last entry for a session wins
    return out


def parse(path, meta: dict | None = None) -> Session:
    p = Path(path)
    date, sid = _parse_name(p.name)
    s = Session(path=str(p), session_id=sid, date=date)
    if meta:
        s.cwd = str(meta.get("cwd", "") or "")
        s.end_reason = str(meta.get("reason", "") or "")
        s.index_ts = str(meta.get("ts", "") or "")

    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # a malformed line is skipped, never fatal
            s.n_events += 1

            msg = obj.get("message", obj)
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content")

            if role == "assistant":
                s.n_assistant_msgs += 1
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        btype = b.get("type")
                        if btype == "tool_use":
                            name = b.get("name", "?")
                            s.tool_counts[name] += 1
                            s.events.append(Event(
                                "assistant", "tool_use", name=name,
                                summary=_trunc(json.dumps(b.get("input", {}), default=str), 120),
                            ))
                        elif btype == "text":
                            s.events.append(Event("assistant", "text", summary=_trunc(b.get("text", ""))))
                else:
                    txt = _text_of(content)
                    if txt:
                        s.events.append(Event("assistant", "text", summary=_trunc(txt)))

            elif role == "user":
                tool_results = (
                    [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                    if isinstance(content, list) else []
                )
                if tool_results:
                    for b in tool_results:
                        s.n_tool_results += 1
                        err = bool(b.get("is_error"))
                        if err:
                            s.n_tool_errors += 1
                        body = b.get("content", "")
                        body_txt = body if isinstance(body, str) else _text_of(body)
                        s.events.append(Event("user", "tool_result", is_error=err,
                                              summary=_trunc(body_txt, 120)))
                else:
                    txt = _text_of(content)
                    if txt.strip():
                        if _is_injected(txt):
                            s.n_injected += 1
                            s.events.append(Event("user", "injected", summary=_trunc(txt)))
                        else:
                            s.n_user_msgs += 1
                            s.user_messages.append(_trunc(txt, 300))
                            s.events.append(Event("user", "text", summary=_trunc(txt)))
                            if _CORRECTION.search(txt):
                                s.corrections.append(_trunc(txt, 200))
    return s
