"""Egenta Phase 5: the write gate and proposal queue.

The deep brain drafts artifacts. This is the only thing allowed to act on them,
and it acts under one rule: Egenta writes freely inside its own home, and asks
for everything else. A lesson or a dataset row lands straight in `~/Egenta`. A
skill, a script bound for `~/.local/bin`, anything outside Egenta, becomes a
queued proposal, one markdown file a human reads, that does nothing until it is
explicitly approved.

Hard nevers, even on approval: never write `~/.claude/CLAUDE.md`, never run a
git push, never execute a drafted script. The gate only ever writes files. The
worst an approved proposal can do is place a file at a path a human signed off.

Stdlib only. Deterministic proposal ids (hash of the content) so a re-run does
not duplicate a proposal and tests are stable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HOME = Path.home()
EGENTA = HOME / "Egenta"

# Always refused, even with an approval. CLAUDE.md is the operator's own law,
# Egenta proposes changes to it in prose but never writes it.
def _deny_paths() -> list[Path]:
    return [(HOME / ".claude" / "CLAUDE.md").resolve()]


# Where each artifact type wants to go, and whether it appends. Skills and
# binaries sit outside Egenta on purpose, so they always queue.
def _target_for(artifact: dict) -> tuple[Path, bool]:
    t = artifact.get("type", "")
    slug = _slug(artifact.get("title", "untitled"))
    if t == "lesson":
        return EGENTA / "lessons" / "findings.md", True          # inside Egenta -> auto
    if t == "training":
        return EGENTA / "datasets" / "proposed.jsonl", True       # inside Egenta -> auto
    if t == "script":
        return HOME / ".local" / "bin" / f"{slug}.sh", False      # outside -> queue
    if t == "skill":
        return HOME / ".claude" / "skills" / slug / "SKILL.md", False  # outside -> queue
    return EGENTA / "proposals" / "misc" / f"{slug}.txt", False


def _slug(title: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower()).strip("-")
    return (s or "untitled")[:48]


def _resolve(p) -> Path:
    return Path(p).expanduser().resolve()


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def classify(target) -> str:
    """auto (write now, inside Egenta), deny (never), or queue (ask a human)."""
    t = _resolve(target)
    if any(t == d for d in _deny_paths()):
        return "deny"
    return "auto" if _inside(t, EGENTA) else "queue"


def _proposal_id(artifact: dict, finding_id: str) -> str:
    key = f"{finding_id}|{artifact.get('type')}|{artifact.get('title')}|{artifact.get('body')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _proposals_dir(sub: str) -> Path:
    d = EGENTA / "proposals" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_proposal_md(pid: str, artifact: dict, target: Path, finding_id: str) -> Path:
    meta = {"id": pid, "type": artifact.get("type"), "title": artifact.get("title"),
            "target": str(target), "finding": finding_id, "status": "pending",
            "body": artifact.get("body", "")}
    md = (
        f"# Proposal {pid}: {artifact.get('title', '')}\n\n"
        f"- type: {artifact.get('type')}\n- target: `{target}`\n- finding: {finding_id}\n"
        f"- status: pending\n\n"
        f"## Why\n\n{artifact.get('rationale', '')}\n\n"
        f"## Drafted change\n\n```\n{artifact.get('body', '')}\n```\n\n"
        f"<!-- egenta-proposal\n{json.dumps(meta)}\n-->\n"
    )
    f = _proposals_dir("pending") / f"{pid}.md"
    f.write_text(md, encoding="utf-8")
    _reindex()
    return f


def _read_meta(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    marker = "<!-- egenta-proposal\n"
    i = text.find(marker)
    if i == -1:
        return {}
    j = text.find("\n-->", i)
    try:
        return json.loads(text[i + len(marker):j])
    except (json.JSONDecodeError, ValueError):
        return {}


def _reindex() -> None:
    lines = ["# Egenta proposals\n"]
    for sub in ("pending", "approved", "rejected"):
        d = EGENTA / "proposals" / sub
        items = sorted(d.glob("*.md")) if d.is_dir() else []
        lines.append(f"\n## {sub} ({len(items)})\n")
        for f in items:
            m = _read_meta(f)
            lines.append(f"- `{m.get('id', f.stem)}` {m.get('type', '?')}: {m.get('title', f.stem)} "
                         f"-> `{m.get('target', '?')}`")
    (EGENTA / "proposals").mkdir(parents=True, exist_ok=True)
    (EGENTA / "proposals" / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_or_queue(artifact: dict, finding_id: str = "") -> dict:
    """Apply an Egenta-internal artifact now, queue anything else as a proposal.
    Never writes outside Egenta here, the worst case is a proposal markdown."""
    target, append = _target_for(artifact)
    decision = classify(target)
    body = artifact.get("body", "")
    if decision == "auto":
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8") as fh:
            if append:
                fh.write(f"\n<!-- {artifact.get('type')}: {artifact.get('title')} ({finding_id}) -->\n")
            fh.write(body if body.endswith("\n") else body + "\n")
        return {"action": "written", "target": str(target), "type": artifact.get("type")}
    if decision == "deny":
        return {"action": "denied", "target": str(target), "reason": "CLAUDE.md is never auto-written"}
    pid = _proposal_id(artifact, finding_id)
    path = _write_proposal_md(pid, artifact, target, finding_id)
    return {"action": "queued", "id": pid, "target": str(target), "proposal": str(path)}


def list_pending() -> list[dict]:
    d = EGENTA / "proposals" / "pending"
    return [_read_meta(f) for f in sorted(d.glob("*.md"))] if d.is_dir() else []


def approve(pid: str) -> dict:
    """Apply a queued proposal to its target, the one place an out-of-Egenta
    write is allowed, because a human asked for it. Still refuses the hard
    nevers. Never runs anything, only writes the file."""
    src = _proposals_dir("pending") / f"{pid}.md"
    if not src.exists():
        return {"action": "error", "reason": f"no pending proposal {pid}"}
    meta = _read_meta(src)
    target = _resolve(meta.get("target", ""))
    if classify(target) == "deny":
        return {"action": "refused", "reason": "target is on the never-write list", "target": str(target)}
    # The drafted body is taken from the machine-readable metadata, not re-parsed
    # from the human markdown, so a body containing a code fence applies intact.
    text = src.read_text(encoding="utf-8")
    body = meta.get("body", "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    dst = _proposals_dir("approved") / f"{pid}.md"
    dst.write_text(text.replace("status: pending", "status: approved")
                   .replace('"status": "pending"', '"status": "approved"'), encoding="utf-8")
    src.unlink()
    _reindex()
    return {"action": "applied", "target": str(target), "id": pid}


def reject(pid: str, reason: str = "") -> dict:
    src = _proposals_dir("pending") / f"{pid}.md"
    if not src.exists():
        return {"action": "error", "reason": f"no pending proposal {pid}"}
    text = src.read_text(encoding="utf-8")
    dst = _proposals_dir("rejected") / f"{pid}.md"
    dst.write_text(text.replace("status: pending", f"status: rejected\n- reason: {reason}")
                   .replace('"status": "pending"', '"status": "rejected"'), encoding="utf-8")
    src.unlink()
    _reindex()
    return {"action": "rejected", "id": pid, "reason": reason}
