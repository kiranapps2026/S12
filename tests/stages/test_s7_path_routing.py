"""
GOLDEN TEST FILE (OWNER). Pinned by hash; the agent must not edit it.
Rulings: runbook R-Q (S7 routing table, first match wins), R-N (unmatched → clarify).
Fixture contract: see tests/stages/test_s6_task_profile.py header.
"""
import pytest

from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import run_stage, state_ready_for


def _decision(out):
    d = out.decision
    return getattr(d, "value", d)


ROUTES = [  # id, scenario kwargs, expected decision, expected reason
    ("fast",             dict(risk=0.2,  steps=1, graph="simple",  confidence=0.95), "fast",     None),
    ("simple_risky",     dict(risk=0.6,  steps=1, graph="simple",  confidence=0.95), "workflow", None),
    ("chain",            dict(risk=0.2,  steps=3, graph="chain",   confidence=0.8),  "workflow", None),
    ("chain_high_risk",  dict(risk=0.9,  steps=2, graph="chain",   confidence=0.8),  "workflow", None),
    ("above_threshold",  dict(risk=0.97, steps=1, graph="simple",  confidence=0.95), "deny",     "risk_above_threshold"),
    ("low_confidence",   dict(risk=0.2,  steps=1, graph="simple",  confidence=0.4),  "clarify",  "low_confidence"),
    ("mid_confidence",   dict(risk=0.2,  steps=1, graph="simple",  confidence=0.6),  "clarify",  "unmatched_route"),
    ("complex",          dict(risk=0.2,  steps=7, graph="complex", confidence=0.95), "clarify",  "complex_not_supported"),
    ("six_steps_chain",  dict(risk=0.2,  steps=6, graph="chain",   confidence=0.95), "clarify",  "complex_not_supported"),
    ("multi_capability", dict(risk=0.2,  steps=2, graph="chain",   confidence=0.95, capabilities=2),
                                                                                     "clarify",  "multi_capability_not_supported"),
]


@pytest.mark.parametrize("case", ROUTES, ids=[c[0] for c in ROUTES])
def test_s7_routing_table(case):
    _, kwargs, decision, reason = case
    sc = make_scenario(**kwargs)
    out = run_stage("S7", state_ready_for("S7", sc), sc).path_decision
    assert (_decision(out), out.reason) == (decision, reason)


def test_s7_never_emits_agentic():
    for _, kwargs, _, _ in ROUTES:
        sc = make_scenario(**kwargs)
        out = run_stage("S7", state_ready_for("S7", sc), sc).path_decision
        assert _decision(out) != "agentic"


def test_s7_threshold_unavailable_denies():
    sc = make_scenario(risk=0.2, steps=1, graph="simple", confidence=0.95, risk_deny_threshold=None)
    out = run_stage("S7", state_ready_for("S7", sc), sc).path_decision
    assert (_decision(out), out.reason) == ("deny", "risk_threshold_unavailable")


UNMATCHED = [
    ("confidence_0_6_simple", dict(risk=0.2, steps=1, graph="simple", confidence=0.6)),
    ("confidence_0_65_chain", dict(risk=0.2, steps=3, graph="chain",  confidence=0.65)),
    ("confidence_missing",    dict(risk=0.2, steps=1, graph="simple", confidence=None)),
]


@pytest.mark.parametrize("case", UNMATCHED, ids=[c[0] for c in UNMATCHED])
def test_s7_unmatched_combination_clarifies(case):
    _, kwargs = case
    sc = make_scenario(**kwargs)
    out = run_stage("S7", state_ready_for("S7", sc), sc).path_decision
    assert _decision(out) == "clarify"
