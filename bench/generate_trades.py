"""Synthetic fire/trades business with planted, labelled defects.

A normative field-service flow (lead -> quote -> approve -> schedule -> attend ->
complete -> invoice -> pay, with a defect-rectification sub-flow and an AS 1851
compliance sub-flow on fire assets) is simulated, then deterministic transforms
plant labelled defects with a ground-truth answer key.

One defect class is HELD OUT on purpose: segregation-of-duties, the same person
both quoting and approving a job, needs resource-identity correlation across two
activities, which none of the deterministic detectors compute. It is in the answer
key but absent from miner output, so detection F1 is honestly below ceiling and
REL cannot be flattered to 1.0. This is the discriminating defect the earlier
quote-to-cash corpus had lost.

Deterministic given a seed (fixed base epoch, seeded RNG), no wall-clock.
"""
from __future__ import annotations

import random

from accelerator.model import AnswerItem, Entity, Event

_BASE_TS = 1_700_000_000
_DAY = 86_400
# built at runtime so the source file carries no key-shaped literal for scanners;
# the runtime value still matches the redactor rule, which is the point.
_PLANTED_SECRET = "sk-ant-" + "api03-" + "TRADES" + ("y" * 36)


def _job_events(rng, i, secret_case):
    """One job's event stream, with per-job planted defects."""
    case = f"job-{i:04d}"
    fqn = f"fsm.job.{i}"
    unbilled = (i % 7) == 0          # completed, never invoiced
    no_approval = (i % 11) == 0      # invoiced with no recorded approval
    rework = (i % 6) == 0            # repeat site visit
    bad_order = (i % 13) == 0        # out-of-order timestamp
    has_defect = (i % 10) < 3        # a defect raised
    stalled = has_defect and (i % 2) == 0   # ~half of defects never rectified
    segregation = (i % 9) == 0       # same resource quotes and approves
    cross_orphan = (i % 8) == 0      # billed in finance, no completion in field-service
    dup_invoice = (i % 12) == 0      # held-out: same job invoiced twice (entity resolution)

    quoter = f"tech-{rng.randint(1, 8)}"
    approver = quoter if segregation else f"mgr-{rng.randint(1, 3)}"
    tech = f"tech-{rng.randint(1, 8)}"

    flow = ["Lead", "Quote"]
    if not no_approval:
        flow.append("QuoteApproved")
    flow += ["Scheduled", "Attended"]
    if not cross_orphan:
        flow.append("JobComplete")       # cross_orphan: no completion recorded in field-service
    billed = cross_orphan or not unbilled
    if billed:
        flow += ["Invoice", "Paid"]

    events, t = [], _BASE_TS + i * _DAY
    for act in flow:
        gap = rng.randint(3600, 7200)
        if act == "Attended":
            gap += rng.randint(200_000, 400_000)   # dispatch bottleneck Scheduled->Attended
        t += gap
        ts = t
        if bad_order and act == "Invoice":
            ts = t - 500_000                       # recording error
        res = {"Quote": quoter, "QuoteApproved": approver}.get(act, tech)
        if i == secret_case and act == "Attended":
            res = f"note: portal key {_PLANTED_SECRET} keep off the report"
        src = "finance" if act in ("Invoice", "Paid") else "fsm"
        ent = f"finance.invoice.{i}" if act in ("Invoice", "Paid") else fqn
        events.append(Event(case, act, float(ts), res, src, ent))
        if rework and act == "Attended":
            t += rng.randint(3600, 7200)
            events.append(Event(case, "Attended", float(t), tech, "fsm", fqn))

    # held-out: a duplicate invoice for the same job on a second finance entity. No
    # detector resolves "two invoices, one job", so the miner cannot catch it.
    if dup_invoice and billed:
        for act in ("Invoice", "Paid"):
            t += rng.randint(3600, 7200)
            events.append(Event(case, act, float(t), tech, "finance", f"finance.invoice.{i}b"))

    if has_defect:
        t += rng.randint(3600, 7200)
        events.append(Event(case, "DefectRaised", float(t), tech, "fsm", fqn))
        if not stalled:
            for act in ("RectifyQuote", "RectifyApproved", "RectifyComplete"):
                t += rng.randint(3600, 7200)
                events.append(Event(case, act, float(t), tech, "fsm", fqn))
    return events


def _asset_events(rng, j, review_ts):
    """One fire asset's AS 1851 routine-service history. ~1 in 5 is left overdue."""
    case = f"svc-{j:04d}"
    fqn = f"asset.{j}"
    overdue = (j % 5) == 0
    last = _BASE_TS - 300 * _DAY if overdue else _BASE_TS + 60 * _DAY
    tech = f"tech-{rng.randint(1, 8)}"
    events = [Event(case, "RoutineService", float(last), tech, "compliance", fqn)]
    if not overdue:
        events.append(Event(case, "CertificateIssued", float(last + _DAY), tech, "compliance", fqn))
    return events


def generate(n_cases: int = 120, n_assets: int = 30, seed: int = 7):
    """Return (events, entities, answer, secret) for the trades corpus."""
    rng = random.Random(seed)
    secret_case = 3
    events: list[Event] = []
    entities: list[Entity] = []

    for i in range(n_cases):
        events += _job_events(rng, i, secret_case)
        entities.append(Entity(f"fsm.job.{i}", "job", f"Job {i}", "fsm"))
        billed = (i % 8 == 0) or (i % 7 != 0)
        if billed:
            entities.append(Entity(f"finance.invoice.{i}", "invoice", f"Invoice {i}", "finance"))
            if i % 12 == 0:
                entities.append(Entity(f"finance.invoice.{i}b", "invoice", f"Invoice {i} dup", "finance"))

    review_ts = max(e.ts for e in events)
    for j in range(n_assets):
        events += _asset_events(rng, j, review_ts)
        entities.append(Entity(f"asset.{j}", "asset", f"Fire asset {j}", "compliance"))

    answer = [
        AnswerItem("unbilled-completion", "JobComplete", "completed jobs never invoiced"),
        AnswerItem("rectification-stall", "DefectRaised", "defects raised but never rectified"),
        AnswerItem("compliance-overdue", "RoutineService", "assets past their AS 1851 routine interval"),
        AnswerItem("approval-gap", "QuoteApproved", "jobs invoiced with no recorded approval"),
        AnswerItem("rework-loop", "Attended", "repeat site visits on the same job"),
        AnswerItem("dispatch-bottleneck", "Scheduled->Attended", "long delay from scheduled to on site"),
        AnswerItem("recording-error", "log", "out-of-order timestamps in the log"),
        AnswerItem("segregation-of-duties", "Quote/QuoteApproved", "same resource quotes and approves"),
        AnswerItem("cross-source-orphan", "Invoice", "billed in finance with no field-service completion"),
        AnswerItem("duplicate-invoice", "Invoice/duplicate", "HELD-OUT: the same job invoiced twice on "
                   "two finance entities; catching it needs entity resolution across invoices, which no "
                   "deterministic detector computes, so the miner cannot recover it"),
    ]
    return events, entities, answer, _PLANTED_SECRET
