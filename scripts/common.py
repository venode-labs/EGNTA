import hashlib
import json
from pathlib import Path
from typing import Any


VALID_ROLES = {"system", "user", "assistant"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_path(path: str | Path) -> Path:
    p = Path(path).expanduser()  # honour ~ in config paths
    if p.is_absolute():
        return p
    return repo_root() / p


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc


def normalize_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(row.get("messages"), list):
        messages = row["messages"]
    elif isinstance(row.get("conversations"), list):
        role_map = {"human": "user", "gpt": "assistant", "bot": "assistant"}
        messages = []
        for item in row["conversations"]:
            raw_role = str(item.get("role", item.get("from", ""))).lower().strip()
            messages.append(
                {
                    "role": role_map.get(raw_role, raw_role),
                    "content": item.get("value", item.get("content", "")),
                }
            )
    elif "instruction" in row and "output" in row:
        prompt = str(row["instruction"]).strip()
        if row.get("input"):
            prompt = f"{prompt}\n\n{row['input']}".strip()
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": row["output"]},
        ]
    elif "prompt" in row and ("response" in row or "completion" in row):
        messages = [
            {"role": "user", "content": row["prompt"]},
            {"role": "assistant", "content": row.get("response", row.get("completion"))},
        ]
    else:
        raise ValueError(
            "unsupported row shape; expected messages, conversations, instruction/output, "
            "or prompt/response"
        )

    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", "")).lower().strip()
        content = message.get("content", "")
        if role not in VALID_ROLES:
            raise ValueError(f"message {index} has invalid role {role!r}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"message {index} has empty content")
        normalized.append({"role": role, "content": content.strip()})

    validate_messages(normalized)
    return normalized


def validate_messages(messages: list[dict[str, str]]) -> None:
    if len(messages) < 2:
        raise ValueError("conversation must contain at least two messages")
    if not any(message["role"] == "assistant" for message in messages):
        raise ValueError("conversation must contain at least one assistant message")
    if messages[-1]["role"] != "assistant":
        raise ValueError("conversation should end with an assistant message for SFT")


def fingerprint_messages(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_jsonl_record(handle, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
