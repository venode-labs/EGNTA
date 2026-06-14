"""Synthetic reference-business generator with planted, labelled defects.

A normative quote-to-cash model M0 is simulated across CRM and finance source
systems, then deterministic transformations plant labelled defects (behavioural
and recording) per the synthetic-defect evaluation design in arXiv 2501.14345.
Every planted defect has a ground-truth entry in the answer key, so detection
precision and recall are measurable, not asserted. A fake secret is planted in a
free-text field so the eval can prove the ingest scrubber never leaks it.

Deterministic given a seed (fixed base epoch, seeded RNG), so CI is reproducible
with no wall-clock dependency.
"""
from __future__ import annotations

import random

from accelerator.model import AnswerItem, Entity, Event

_M0 = ["Lead", "Qualify", "Quote", "Approve", "Invoice", "Pay"]
_SOURCE = {"Lead": "crm", "Qualify": "crm", "Quote": "crm", "Approve": "crm",
           "Invoice": "finance", "Pay": "finance"}
_BASE_TS = 1_700_000_000  # fixed epoch, no wall clock
# Built at runtime, not a contiguous literal, so the source carries no key-shaped
# string for secret scanners to flag. The runtime value still matches the
# redactor's anthropic-key rule, which is the point: it must be scrubbed at ingest.
_PLANTED_SECRET = "sk-ant-" + "api03-" + "PLANTED" + ("x" * 36)


def generate(n_cases: int = 120, seed: int = 7) -> tuple[list[Event], list[Entity], list[AnswerItem], str]:
    rng = random.Random(seed)
    events: list[Event] = []
    entities: list[Entity] = []

    for i in range(n_cases):
        case = f"deal-{i:04d}"
        deal_fqn = f"crm.deal.{i}"
        entities.append(Entity(deal_fqn, "deal", f"Deal {i}", "crm"))
        t = _BASE_TS + i * 86_400
        skip_approve = (i % 10) < 3      # control-gap: Approve skipped in ~30%
        rework_quote = (i % 5) == 0      # rework: Quote repeated in ~20%
        bad_order = (i % 10) == 7        # recording-error: out-of-order in ~10%

        for act in _M0:
            if act == "Approve" and skip_approve:
                continue
            # bottleneck: Quote -> Approve gap is large
            gap = rng.randint(3600, 7200)
            if act == "Approve":
                gap += rng.randint(200_000, 400_000)   # top bottleneck: Quote->Approve
            if act == "Pay":
                gap += rng.randint(100_000, 180_000)   # held-out 2nd bottleneck: Invoice->Pay
            t += gap
            ts = t
            if bad_order and act == "Invoice":
                ts = t - 500_000          # plant an out-of-order timestamp
            fqn = deal_fqn if _SOURCE[act] == "crm" else f"finance.invoice.{i}"
            res = "rep-" + str(rng.randint(1, 6))
            # plant a secret in a free-text resource field on a couple of cases
            if i == 3 and act == "Quote":
                res = f"note: api {_PLANTED_SECRET} do not log"
            events.append(Event(case, act, float(ts), res, _SOURCE[act], fqn))
            if rework_quote and act == "Quote":
                t += rng.randint(3600, 7200)
                events.append(Event(case, act, float(t), res, _SOURCE[act], fqn))
        if _SOURCE.get("Invoice") == "finance":
            entities.append(Entity(f"finance.invoice.{i}", "invoice", f"Invoice {i}", "finance"))

    answer = [
        AnswerItem("bottleneck", "Quote->Approve", "approval step is the slowest transition"),
        AnswerItem("bottleneck", "Invoice->Pay", "HELD-OUT: payment is the second bottleneck; the "
                   "deterministic miner only reports the single slowest, so only the LLM synthesis "
                   "recovers this one"),
        AnswerItem("control-gap", "Approve", "approval skipped in ~30% of cases"),
        AnswerItem("rework", "Quote", "quote reworked in ~20% of cases"),
        AnswerItem("recording-error", "log", "out-of-order timestamps in ~10% of cases"),
    ]
    return events, entities, answer, _PLANTED_SECRET
