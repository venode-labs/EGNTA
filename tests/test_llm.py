"""Keyless gates for the LLM layer: the client parses, the grounded synthesis drops
ungrounded findings and never regresses below the deterministic miner (safety net),
and the baseline parser works. Runs in CI with no key via the mock client."""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from accelerator import llm, pii, warehouse  # noqa: E402
from accelerator.model import Event  # noqa: E402
from bench import baselines, generate  # noqa: E402


def _warehouse():
    ev, ents, ans, _ = generate.generate(n_cases=40, seed=7)
    d = tempfile.mkdtemp()
    c = warehouse.connect(pathlib.Path(d) / "e.db")
    warehouse.init_schema(c)
    warehouse.upsert_entities(c, ents)
    clean = [Event(e.case_id, e.activity, e.ts, pii.scrub(e.resource)[0], e.source_system, e.entity_fqn)
             for e in ev]
    warehouse.insert_events(c, clean)
    return c


def test_client_mock_parses():
    c = llm.Client(mock=True, mock_reply='{"findings":[{"kind":"bottleneck"}]}')
    assert c.complete_json("s", "u") == {"findings": [{"kind": "bottleneck"}]}
    assert c.mock is True  # no key -> mock


def test_synthesis_is_grounded_and_has_safety_net():
    c = _warehouse()
    client = llm.Client(mock=True, mock_reply=(
        '{"findings":[{"kind":"bottleneck","key":"Quote->Approve",'
        '"evidence_fqn":"metric.bottleneck.Quote->Approve","severity":0.8,'
        '"frequency":0.5,"fixability":0.6}]}'))
    fs = baselines.egnta_llm(c, client)
    assert fs, "synthesis returned no findings"
    assert all(warehouse.citation_resolves(c, f.evidence_fqn) for f in fs), "ungrounded finding survived"
    # safety net: the other deterministic defects are still present
    assert {"bottleneck", "control-gap", "rework", "recording-error"} <= {f.kind for f in fs}


def test_synthesis_drops_ungrounded():
    c = _warehouse()
    client = llm.Client(mock=True, mock_reply='{"findings":[{"kind":"x","key":"y","evidence_fqn":"does.not.exist"}]}')
    fs = baselines.egnta_llm(c, client)
    # the bogus citation is dropped; only the safety-net deterministic findings remain, all grounded
    assert all(f.evidence_fqn != "does.not.exist" for f in fs)
    assert all(warehouse.citation_resolves(c, f.evidence_fqn) for f in fs)


def test_llm_baseline_parses():
    c = _warehouse()
    client = llm.Client(mock=True, mock_reply='{"findings":[{"kind":"bottleneck","key":"Quote->Approve","evidence_fqn":"crm.deal.1"}]}')
    fs = baselines.llm_baseline(c, client)
    assert len(fs) == 1 and fs[0].kind == "bottleneck"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS: {len(fns)} llm-layer tests")
