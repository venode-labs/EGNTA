#!/usr/bin/env python
"""Convert Claude Code / Codex transcripts into redacted messages-jsonl training
rows. Each transcript becomes one trajectory of ordered user, assistant, and tool
turns, with every content field passed through the redactor first. Injected skill,
hook, and system-reminder noise is dropped so the model learns from genuine turns.

Output matches the shape collect_dataset.py ingests: {messages, source, license,
notes}. Defence in depth: each field is redacted, then a per-row self-check refuses
to write any trajectory whose joined content still trips the redactor."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "observer"))
from redactor import redact  # noqa: E402

_INJECTED = (
    "<system-reminder>",
    "Base directory for this skill",
    "STANDING RULE",
    "DISCIPLINE GATE",
    "Caveat: The messages below",
    "<command-name>",
    "<command-message>",
    "[SYSTEM NOTIFICATION",
    "<local-command-stdout>",
)


def _is_injected(text: str) -> bool:
    head = text.lstrip()[:200]
    return any(marker in head for marker in _INJECTED)


def _flatten_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        )
    return ""


def _blocks(content):
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def transcript_to_messages(path: pathlib.Path) -> list[dict]:
    msgs: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = obj.get("message", obj)
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")

        if role == "assistant":
            texts, tools = [], []
            for b in _blocks(content):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    texts.append(b["text"])
                elif b.get("type") == "tool_use":
                    args = json.dumps(b.get("input", {}), ensure_ascii=False)
                    tools.append(f"→ {b.get('name', 'tool')}({args})")
            body = "\n".join([*texts, *tools]).strip()
            if body:
                msgs.append({"role": "assistant", "content": body})

        elif role == "user":
            results = [
                b for b in _blocks(content)
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            if results:
                for b in results:
                    rc = b.get("content", "")
                    rc = rc if isinstance(rc, str) else _flatten_text(rc)
                    if rc.strip():
                        msgs.append({"role": "tool", "content": rc.strip()[:4000]})
            else:
                text = _flatten_text(content).strip()
                if text and not _is_injected(text):
                    msgs.append({"role": "user", "content": text})
    return msgs


def convert(root: pathlib.Path, source: str, min_turns: int) -> list[dict]:
    files = sorted(p for p in root.rglob("*.jsonl") if p.is_file()) if root.is_dir() else [root]
    rows: list[dict] = []
    for path in files:
        if path.name == "index.ndjson":
            continue
        redacted = [
            {"role": m["role"], "content": redact(m["content"]).text}
            for m in transcript_to_messages(path)
        ]
        if len(redacted) < min_turns:
            continue
        if redact("\n".join(m["content"] for m in redacted)).total:
            print(f"SKIP {path.name}: residual secret after redaction", file=sys.stderr)
            continue
        rows.append({
            "messages": redacted,
            "source": source,
            "license": "internal",
            "notes": f"redacted trajectory from {path.name}",
        })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert redacted transcripts to messages-jsonl.")
    ap.add_argument("path", help="transcript file or directory")
    ap.add_argument("--source", default="claude-code")
    ap.add_argument("--min-turns", type=int, default=4)
    ap.add_argument("-o", "--out", default="-", help="output jsonl (default stdout)")
    args = ap.parse_args(argv)

    rows = convert(pathlib.Path(args.path).expanduser(), args.source, args.min_turns)
    handle = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if handle is not sys.stdout:
        handle.close()
    print(f"convert: {len(rows)} trajectories from {args.path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
