"""Thin Claude client for the synthesis layer.

Host-pinned stdlib urllib to api.anthropic.com (no third-party SDK, matches the
observer's transport discipline). The key is read at runtime from the pass vault
(`vault get anthropic/api-key`), never from source or an argument. Static system
context is prompt-cached. A deterministic mock mode lets the parsing and retry
logic be unit-tested with no key and no spend.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

_HOST = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"
_MAX_RESP = 8 * 1024 * 1024   # 8 MiB ceiling on a response body; a 2048-token reply is tiny
DEFAULT_MODEL = "claude-sonnet-4-6"
SYNTH_MODEL = "claude-opus-4-8"   # final synthesis pass only


def _vault_key() -> str:
    """Read the key from the pass vault, then env, else empty (-> mock)."""
    try:
        out = subprocess.run(["vault", "get", "anthropic/api-key"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def _extract_json(text: str):
    """Tolerant JSON extraction: fenced block, then first {...} span."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b != -1 and b > a:
            text = text[a:b + 1]
    return json.loads(text)


class Client:
    def __init__(self, model: str = DEFAULT_MODEL, mock: bool = False, mock_reply: str = "{}"):
        self.model = model
        self._key = "" if mock else _vault_key()
        self.mock = mock or not self._key
        self.mock_reply = mock_reply
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def complete(self, system: str, user: str, max_tokens: int = 2048,
                 temperature: float = 0.0, retries: int = 3) -> str:
        # temperature 0 by default: the product leans on reproducibility, so the
        # synthesis pass should be as stable as the model allows (not bit-exact across
        # model versions, but no sampling jitter run to run).
        self.calls += 1
        if self.mock:
            return self.mock_reply
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # system as a cacheable content block: the static instruction is reused
            # across every call in a run, so cache it.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(_HOST, data=body, method="POST", headers={
            "x-api-key": self._key,
            "anthropic-version": _VERSION,
            "content-type": "application/json",
        })
        # the URL is the pinned _HOST https constant in the Request, never user-derived,
        # so the dynamic-urllib file:// scheme risk does not apply here.
        if not _HOST.startswith("https://"):  # defence in depth: refuse a non-https host
            raise RuntimeError("model host must be https")
        last = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:  # nosemgrep: dynamic-urllib-use-detected
                    raw = resp.read(_MAX_RESP + 1)
                if len(raw) > _MAX_RESP:
                    raise RuntimeError("anthropic response exceeded the size cap")
                data = json.loads(raw)
                usage = data.get("usage", {})
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
                parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                return "".join(parts)
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                    delay = 2 ** attempt
                    ra = e.headers.get("retry-after") if e.headers else None  # honour server cooldown
                    if ra and str(ra).isdigit():
                        delay = min(int(ra), 60)
                    time.sleep(delay)
                    continue
                raise
            except urllib.error.URLError as e:
                last = e
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError(f"anthropic call failed: {last}")

    def complete_json(self, system: str, user: str, **kw):
        return _extract_json(self.complete(system, user, **kw))
