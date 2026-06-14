# EGNTA discovery accelerator, architecture

EGNTA is Venode Labs' read-only client-discovery accelerator. Deployed into a
client business, it maps how the business actually runs and returns a prioritised
pain register plus an AI/process recommendation framework. It never writes to or
changes any client system. It serves any business as a configurable engine, not a
per-client rebuild.

## The load-bearing inversion

Do not let an autonomous agent loose on live client systems. Instead:

```
read-only connectors  ->  canonical warehouse  ->  deterministic mining  ->  Claude reasoners
   (normalise each        (per-engagement,         (citeable metrics         (reason OVER the
    source to the          SQLite now /             written as rows)           warehouse only,
    event-log shape)       Postgres in prod)                                   never live creds)
```

The LLM never touches a live client credential or system. It reasons over a
warehouse of already-extracted, already-redacted, already-mined facts. This fixes
the cost (no token spend scaling with business size), the security objection (no
broad live access), and the read-only guarantee at once.

## Vertical packs and the connector boundary

The engine is vertical-configurable. A vertical pack (`accelerator/verticals/`) pins three
things: the canonical activity vocabulary, the synonym map a connector normalises raw
source statuses through, and the domain defect detectors. The first pack is fire,
construction and service trades (`verticals/trades.py`), with nine detectors the generic
miner cannot express: unbilled completion, rectification stall, overdue AS 1851
compliance, approval gap, repeat-visit rework, dispatch bottleneck, segregation of duties
(same resource quotes and approves), cross-source orphan (billed in finance with no
field-service completion, the join the single-system miners do not do), and recording error.
Shipping the semantic layer with the product is what lets discovery run on a real export
without a bespoke per-client modelling phase first.

Connectors (`accelerator/connectors/`) are the one boundary where a raw source becomes
canonical events. `csv_export.py` reads a ServiceM8, simPRO or Uptick CSV or JSON export,
maps each row through the vertical synonym table, and yields the `Event` shape. It is
read-only by nature: it opens the file for reading and never writes the source. A live
read-only API connector (needing client OAuth) is the next increment.

## Canonical shape

Every connector normalises its source into the event-log shape the process-mining
field standardised on, extended for cross-source work:

`Event(case_id, activity, ts, resource, source_system, entity_fqn)`

plus an `entities` graph keyed by a resolvable `fqn`. Cross-source synthesis over
this shape is the differentiator the event-log-only incumbents (PM4Py, bupaR,
Apromore, ProM) do not attempt.

## Read-only enforcement

Five defence-in-depth layers are designed. Two are actively enforced on the code path:

1. **SELECT-only warehouse handle** (`warehouse.connect(read_only=True)`, `PRAGMA
   query_only`). Writes raise. Tested.
2. **Read-only tool guard** (`readonly.read_only_tool_guard`, the shape of the
   Claude Agent SDK PreToolUse hook): denies write HTTP verbs, non-SELECT SQL,
   and any mutating tool, default-deny on unknown. Tested.

A third is implemented and tested but not yet on a live path:

3. **Egress allowlist policy** (`readonly.egress_allowlist_check`): the decision
   function that refuses a write HTTP verb or a non-allowlisted host for client-source
   egress. It becomes active when a live-HTTP connector routes through it; the only
   connector today is file-based, so nothing routes through it yet. Tested.

Two require live infrastructure and are explicit stubs that raise rather than
pretend (`readonly.require_readonly_oauth_scope`):

4. Client read-only OAuth scopes per connector (needs a live OAuth provider).
5. Per-engagement network isolation (needs infrastructure).

The last three are not claimed as actively guarding traffic until they are on a path.

## Ingest scrubbing

`accelerator/pii.py` composes the hardened `observer/redactor.py` credential wall
with a PII pass (phone, payment cards via Luhn). Person-name detection needs a
model and is a flagged stub, not faked. Scrubbing runs at the ingest boundary
before anything reaches the warehouse; the benchmark plants a secret and asserts
zero leak on every run.

## Licence split

PM4Py is AGPL-3.0 (viral over a network service). EGNTA ships a clean-room miner
(`accelerator/mining.py`) reimplemented from the published algorithms. PM4Py is a
development and CI eval oracle only, never shipped in the distributable and never
conveyed to a user over a network.

## Stack

One language: Python. The Claude Agent SDK has first-class Python PreToolUse hooks
and `can_use_tool`; the redactor and the whole mining/eval stack are Python; a
TS split would put a process boundary between the agent and every deterministic
tool it leans on for no gain. SQLite now, dockerised Postgres with a SELECT-only
role for production parity. GitHub Actions CI. Terraform for infra, deliberately
boring, iteration 2.
