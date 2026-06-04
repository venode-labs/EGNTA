#!/usr/bin/env python
"""Self-test for convert_transcripts. A synthetic transcript carrying a planted
key and an injected system-reminder must come out redacted, noise-free, with the
user, assistant, and tool turns intact and the tool call captured. The planted key
is obviously fake. Run directly: python scripts/test_convert.py"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import convert_transcripts as convert  # noqa: E402

# Matches the anthropic-key rule (sk-ant-...{20,}) but is plainly fake.
FAKE_KEY = "sk-ant-api03-" + "Z9x" * 20


def _line(role, content):
    return json.dumps({"type": role, "message": {"role": role, "content": content}})


def main() -> None:
    lines = [
        _line("user", "<system-reminder>\nSTANDING RULE: do the thing</system-reminder>"),
        _line("user", f"deploy with key {FAKE_KEY} please"),
        _line("assistant", [
            {"type": "text", "text": "Running the build."},
            {"type": "tool_use", "id": "t1", "name": "run_shell", "input": {"command": "npm run build"}},
        ]),
        _line("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "build ok"}]),
        _line("assistant", [{"type": "text", "text": "Done."}]),
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write("\n".join(lines))
        path = pathlib.Path(fh.name)

    try:
        rows = convert.convert(path, source="test", min_turns=1)
    finally:
        path.unlink()

    assert len(rows) == 1, f"expected 1 trajectory, got {len(rows)}"
    blob = json.dumps(rows[0]["messages"])

    assert FAKE_KEY not in blob, "RAW KEY LEAKED INTO OUTPUT"
    assert "[REDACTED:anthropic-key]" in blob, "planted key was not redacted"
    assert "STANDING RULE" not in blob, "injected system-reminder survived"
    roles = [m["role"] for m in rows[0]["messages"]]
    assert {"user", "assistant", "tool"} <= set(roles), f"missing roles, got {roles}"
    assert "run_shell" in blob, "tool call was not captured into the assistant turn"

    print("PASS: convert redacts the planted key, drops injected noise, keeps user/assistant/tool turns")


if __name__ == "__main__":
    main()
