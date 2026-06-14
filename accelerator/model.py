"""Canonical data shapes for the EGNTA discovery accelerator.

The whole engine speaks one intermediate, the event-log shape that the
process-mining field standardised on (case id, activity, timestamp [, resource]),
extended with the source system and an entity fully-qualified name so cross-source
synthesis is possible. Every read-only connector normalises its source into this
before any mining or agent reasoning happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    case_id: str
    activity: str
    ts: float                 # epoch seconds, UTC
    resource: str = ""
    source_system: str = ""   # CRM, finance, tickets, calendar, ...
    entity_fqn: str = ""      # resolvable citation target, e.g. "crm.deal.4471"


@dataclass(frozen=True)
class Entity:
    fqn: str                  # primary key, e.g. "crm.deal.4471"
    kind: str                 # deal, invoice, ticket, person, system, ...
    name: str = ""
    source_system: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """One entry in the prioritised pain register. Every finding must cite a
    resolvable evidence_fqn (an entity or a metric row) or it is dropped."""
    kind: str                 # bottleneck | rework | control-gap | recording-error | ...
    title: str
    key: str                  # the matchable attribute (activity or "a->b" transition)
    severity: float           # 0..1, normalised cost signal
    frequency: float          # 0..1, how often it occurs
    fixability: float         # 0..1, how tractable a fix is
    evidence_fqn: str         # citation; empty means ungrounded (gated out)
    confidence: float = 1.0

    @property
    def score(self) -> float:
        """Pain register score: frequency x cost x fixability (RICE-like)."""
        return round(self.frequency * self.severity * self.fixability, 4)


@dataclass(frozen=True)
class AnswerItem:
    """One planted, labelled defect in the synthetic corpus, the ground truth a
    finding is matched against."""
    kind: str
    key: str
    detail: str = ""
