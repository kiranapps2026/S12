"""
Test fixture infrastructure — scenario-driven, no fabricated outputs.

R-T (scenarios configure inputs only; real handlers produce every output).

  make_scenario(mutation, risk, ...) → Scenario
  state_ready_for(stage_id, scenario) → PipelineState (real S0..stage-1 handlers)
  run_stage(stage_id, state, scenario) → PipelineState (real handler)
  tamper(state, **fields) → PipelineState (negative tests only)
"""
from __future__ import annotations

import asyncio
from typing import Any

from contracts.pipeline_state import PipelineState, PRE_EXECUTION_SEQUENCE
from tests.fixtures.scenarios import (
    make_scenario as _make_scenario, Scenario,
    ScenarioRegistry,
)


# ---------------------------------------------------------------------------
# Scenario builder (thin re-export)
# ---------------------------------------------------------------------------

def make_scenario(
    mutation: str = "R",
    risk: float = 0.1,
    risk_floor: float | None = None,
    risk_rule: float | None = None,
    risk_implied: float | None = None,
    cost: int = 1,
    steps: int = 1,
    graph: str = "simple",
    confidence: float = 0.95,
    capabilities: int = 1,
    risk_deny_threshold: float = 0.95,
) -> Scenario:
    """Build a Scenario that configures the fixture registry, bindings, and mock LLM."""
    return _make_scenario(
        mutation=mutation,
        risk=risk,
        risk_floor=risk_floor,
        risk_rule=risk_rule,
        risk_implied=risk_implied,
        cost=cost,
        steps=steps,
        graph=graph,
        confidence=confidence,
        capabilities=capabilities,
        risk_deny_threshold=risk_deny_threshold,
    )


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _create_entry_request(
    tenant_id: str = "tenant-1", user_id: str = "user-1",
    conversation_id: str = "conv-1", connection_id: str = "conn-1",
) -> Any:
    """Create a minimal EntryRequest for S0."""
    from engine.stages.s0_entry.handler import EntryRequest
    return EntryRequest(
        raw_payload={"message": "test"},
        entry_channel="api",
        tenant_id=tenant_id,
        workspace_id="ws-1",
        conversation_id=conversation_id,
        connection_id=connection_id,
        user_id=user_id,
    )


def _run_s0_s2(scenario: Scenario) -> PipelineState:
    """Run S0->S1->S2 with the scenario-driven intent model. Real handlers produce every output."""
    from engine.stages.s0_entry.handler import handle as s0_handle
    from engine.stages.s1_normalize.handler import handle as s1_handle
    from engine.stages.s2_intent_analysis.handler import handle as s2_handle

    state = asyncio.run(s0_handle(_create_entry_request()))
    state = asyncio.run(s1_handle(state))
    state = asyncio.run(s2_handle(state, ScenarioIntentModel(scenario), ScenarioRegistry(scenario)))
    if scenario.confidence is None:
        # S2 rejects a missing confidence, so it can never reach S7 through the real S2. S7 must
        # still treat a missing value as CLARIFY (R-N, defence in depth): this is the one place
        # the fixture removes it after S2, to exercise that branch.
        import dataclasses
        state = dataclasses.replace(
            state, intent_result=dataclasses.replace(state.intent_result, confidence=None))
    return state


class ScenarioIntentModel:
    """Fixture IntentModel whose JSON answer is configured entirely by the Scenario.

    intent: the registry's (single) known intent, or `intent` if given (canned answers);
    confidence: scenario.confidence; parameters.items: `steps` empty items.
    """

    def __init__(self, scenario: Scenario, intent: str | None = None, raw: str | None = None):
        self._scenario, self._intent, self._raw = scenario, intent, raw
        self.calls: list[tuple] = []

    async def complete(self, text, intents, feedback):
        import json
        from contracts.intent_model import IntentCompletion
        self.calls.append((text, intents, feedback))
        sc = self._scenario
        intent = self._intent or (intents[0] if intents else "unknown")
        body = self._raw if self._raw is not None else json.dumps({
            "intent": intent, "confidence": 0.9 if sc.confidence is None else sc.confidence,
            "parameters": {"items": [{} for _ in range(sc.steps)]},
        })
        return IntentCompletion(text=body, model="test-model", total_tokens=10)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

from contracts.kernel_policy import PolicyVersions

POLICY_VERSIONS = PolicyVersions("policy-1", "policy-1", "policy-1")


def _s8_deps():
    from tests.fixtures.deps import make_s8_deps
    return make_s8_deps(kill_switch=False)


def _policy(scenario: Scenario):
    from contracts.kernel_policy import KernelPolicy
    return KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=scenario.risk_deny_threshold)


def _stage_runners(scenario: Scenario):
    """stage_id -> callable(state) running the REAL production handler."""
    from engine.stages.s3_capability_discovery.handler import handle as s3
    from engine.stages.s4_graph_classification.handler import handle as s4
    from engine.stages.s5_provider_resolution.handler import handle as s5
    from engine.stages.s6_task_profile_assembly.handler import handle as s6
    from engine.stages.s7_path_decision.handler import handle as s7
    from engine.stages.s8_safety_gate.handler import handle as s8
    from engine.stages.s9_plan_creation.handler import handle as s9
    from engine.stages.s10_confirmation.handler import handle as s10
    from engine.stages.s11_plan_validation.handler import handle as s11
    return {
        "S3": lambda st: s3(st, ScenarioRegistry(scenario)),
        "S4": lambda st: s4(st),
        "S5": lambda st: s5(st, ScenarioRegistry(scenario), POLICY_VERSIONS),
        "S6": lambda st: s6(st),
        "S7": lambda st: s7(st, policy=_policy(scenario)),
        "S8": lambda st: s8(st, _s8_deps()),
        "S9": lambda st: s9(st),
        "S10": lambda st: s10(st, scenario.confirmation_store),
        "S11": lambda st: s11(st),
    }


def state_ready_for(stage_id: str, scenario: Scenario) -> PipelineState:
    """Run real handlers S0..stage-1 and return the state as `stage_id` receives it.

    A stage that stops the run (deny / clarify / error) makes the request unable to reach
    `stage_id`; that is reported with the stage and reason instead of continuing. The one
    exception is S10's "confirmation_required" pause, which S11 tests build on.
    """
    from contracts.stage_registry import StageStatus

    target_idx = PRE_EXECUTION_SEQUENCE.index(stage_id)
    state = _run_s0_s2(scenario)
    runners = _stage_runners(scenario)
    for sid in PRE_EXECUTION_SEQUENCE[3:target_idx]:
        state = asyncio.run(runners[sid](state))
        paused = sid == "S10" and state.deny_reason == "confirmation_required"
        if state.stage_status is not StageStatus.NORMAL and not paused:
            raise AssertionError(
                f"state_ready_for({stage_id}): {sid} stopped the run: "
                f"{state.stage_status} / {state.deny_reason}")
    return state


def run_stage(stage_id: str, state: PipelineState, scenario: Scenario) -> PipelineState:
    """Run the REAL production handler for stage_id. No fabrication.

    The returned PipelineState carries `stage_status` and `deny_reason`.
    """
    runners = _stage_runners(scenario)
    sid = stage_id.upper()
    if sid not in runners:
        raise ValueError(f"run_stage: unsupported stage_id '{stage_id}'")
    return asyncio.run(runners[sid](state))


def consume(scenario: Scenario, confirmation_id: str, *, user_id: str, plan_hash: str,
            now: float, tenant_id: str | None = None) -> str:
    """Call the production store's conditional consume; returns its result code."""
    tenant_id = tenant_id or "tenant-1"
    return asyncio.run(scenario.confirmation_store.consume(
        confirmation_id, tenant_id=tenant_id, user_id=user_id, plan_hash=plan_hash, now=now))


def tamper(state: PipelineState, **fields) -> PipelineState:
    """Create a modified PipelineState using dataclasses.replace.

    For negative tests only.
    """
    import dataclasses
    return dataclasses.replace(state, **fields)


# ---------------------------------------------------------------------------
# Backward-compat helpers (test_s0_s11_certification.py imports these)
# ---------------------------------------------------------------------------

def _make_s2_state() -> PipelineState:
    """Run real S0..S2 with a default scenario and return the state.

    No fabrication — real handlers produce every output.
    """
    return state_ready_for("S3", make_scenario(mutation="W", risk=0.3, steps=3, graph="chain"))


def state_ready_for_s8() -> PipelineState:
    """Run real S0..S7 and return the PipelineState as S7 leaves it."""
    return state_ready_for("S8", make_scenario(mutation="W", risk=0.3, steps=3, graph="chain"))
