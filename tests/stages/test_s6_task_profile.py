"""
GOLDEN TEST FILE (OWNER). Pinned by hash; the agent must not edit it.
Rulings: runbook R-V (S6 formula), R-O (TaskProfile fields).

Fixture contract (implemented by the agent in tests/fixtures/, NOT here):
  make_scenario(mutation="R", risk=0.1, risk_floor=None, risk_rule=None, risk_implied=None,
                cost=1, steps=1, graph="simple", confidence=0.95, capabilities=1,
                risk_deny_threshold=0.95) -> Scenario
  state_ready_for(stage_id, scenario) -> PipelineState produced by running the REAL
      handlers of every stage before stage_id, with dependencies built from the scenario.
  run_stage(stage_id, state, scenario) -> PipelineState returned by the REAL production
      handler of stage_id, called with dependencies built from the scenario. It must not
      do anything else.
  tamper(state, **fields) -> PipelineState (dataclasses.replace), negative tests only.
"""
import pytest

from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import run_stage, state_ready_for

CASES = [  # id, mutation, risk, cost_per_step, steps, expected requires_confirmation
    ("irreversible",            "IRREVERSIBLE", 0.1, 1, 1, True),
    ("delete_cost_6",           "D",            0.3, 6, 1, True),
    ("delete_cost_5_boundary",  "D",            0.3, 5, 1, False),
    ("write_cost_6_not_delete", "W",            0.3, 6, 1, False),
    ("total_cost_21",           "W",            0.3, 7, 3, True),
    ("total_cost_20_boundary",  "W",            0.3, 5, 4, False),
    ("risk_0_8",                "R",            0.8, 1, 1, True),
    ("risk_0_7_boundary",       "R",            0.7, 1, 1, False),
    ("nothing_triggers",        "R",            0.3, 1, 1, False),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_s6_confirmation_table(case):
    _, mutation, risk, cost, steps, expected = case
    sc = make_scenario(mutation=mutation, risk=risk, cost=cost, steps=steps,
                       graph="simple" if steps == 1 else "chain",
                       confidence=0.95 if steps == 1 else 0.8)
    state = state_ready_for("S6", sc)
    tp = run_stage("S6", state, sc).task_profile
    fb = state.frozen_binding_identity
    assert tp.requires_confirmation is expected
    assert tp.cost == cost * steps
    assert tp.risk == fb.effective_risk
    assert tuple(tp.mutations) == (fb.effective_mutation,) * steps


def test_s6_copies_risk_and_mutations_from_frozen_binding():
    sc = make_scenario(mutation="D", risk_floor=0.2, risk_rule=0.9, risk_implied=0.1)
    state = state_ready_for("S6", sc)
    fb = state.frozen_binding_identity
    assert fb.effective_risk == 0.9          # the scenario really produces risk 0.9
    tp = run_stage("S6", state, sc).task_profile
    assert (tp.risk, tuple(tp.mutations)) == (0.9, ("D",))
