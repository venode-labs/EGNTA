"""Ingest-boundary scrubber for untrusted client content.

The observer redactor is a hardened CREDENTIAL wall (API keys, tokens, PEM, env
secrets). EGNTA also ingests client business content, which carries personal
data the credential wall does not touch. This module composes the redactor with
a PII pass (phone numbers, payment-card numbers via Luhn) so the boundary covers
both. Person-name detection is deliberately NOT attempted by regex here: it needs
a model and is a known gap, flagged rather than faked.

Stdlib only. Reuses observer/redactor.py verbatim; never weakens it.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observer"))
import redactor  # noqa: E402  (the credential wall, reused as-is)

# Run before the credential wall so a card or phone is caught before the broad
# high-entropy rule can mangle it into a generic placeholder.
_PII_RULES: list[tuple[str, re.Pattern]] = [
    # International and AU phone numbers (loose, over-redacts on purpose).
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?!\d)")),
]

# the digit separator allows whitespace (space, tab, newline) and hyphen, so a card
# split across a newline inside a quoted multi-line CSV cell is still caught; _luhn
# strips non-digits before validating, so the embedded newline does not break the check.
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ \t\r\n-]?){13,19}(?!\d)")


def _luhn(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _scrub_cards(text: str, counts: Counter) -> str:
    def sub(m):
        if _luhn(m.group(0)):
            counts["payment-card"] += 1
            return "[REDACTED:payment-card]"
        return m.group(0)
    return _CARD_CANDIDATE.sub(sub, text)


def scrub(text: str) -> tuple[str, Counter]:
    """Scrub PII then credentials. Returns (clean_text, counts_by_type)."""
    if not isinstance(text, str):
        text = str(text)
    counts: Counter = Counter()
    text = _scrub_cards(text, counts)
    for kind, pat in _PII_RULES:
        def sub(m, kind=kind):
            counts[kind] += 1
            return f"[REDACTED:{kind}]"
        text = pat.sub(sub, text)
    cred = redactor.redact(text)          # the credential wall, unchanged
    counts.update(cred.counts)
    return cred.text, counts


# Known gap, stated not hidden: regex cannot reliably catch person names. Iteration
# 2 adds a model-based PII/NER pass for names and addresses before any client
# free-text reaches the warehouse or the model.
NAME_DETECTION = "STUB: person-name PII needs a model-based NER pass (iteration 2)"
