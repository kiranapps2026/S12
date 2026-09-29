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
from contracts.stage_outputs import CapabilityMatch, IntentResult
from tests.fixtures.scenarios import (
    make_scenario as _make_scenario, Scenario,
    _intent_text, ScenarioRegistry,
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
    """Run S0->S1->S2 with scenario-aware MockLLMProvider.

    The mock LLM receives the scenario's configuration and produces
    an IntentResult with candidates and step count in parameters.
    Real handlers produce every output.
    """
    from engine.stages.s0_entry.handler import handle as s0_handle
    from engine.stages.s1_normalize.handler import handle as s1_handle
    from engine.stages.s2_intent_analysis.handler import (
        handle as s2_handle,
        MockLLMProvider,
    )

    entry = _create_entry_request()
    s0 = asyncio.run(s0_handle(entry))
    state = PipelineState(
        execution_context=s0.execution_context,
        entry_request=s0.entry_request,
    )
    s1 = asyncio.run(s1_handle(state))
    state = s1

    # Scenario-configured mock LLM: produces intent, confidence, workflow flag,
    # and carries capability candidates + step count in IntentResult.parameters
    mock_llm = _ScenarioDrivenLLM(scenario)
    s2 = asyncio.run(s2_handle(state, llm=mock_llm))
    return s2


class _ScenarioDrivenLLM:
    """Mock LLM whose output is configured entirely by the Scenario.

    Produces an IntentResult with:
      - intent_type derived from scenario.mutation
      - confidence from scenario.confidence
      - step count in parameters for S4
    """

    def __init__(self, scenario: Scenario):
        self._scenario = scenario

    async def analyze_intent(self, sanitized_input: dict) -> IntentResult:
        sc = self._scenario

        # Intent type from mutation
        intent_map = {
            "R": "read", "READ": "read",
            "W": "write", "WRITE": "write",
            "D": "delete", "DELETE": "delete",
            "IRREVERSIBLE": "write",
        }
        intent_type = intent_map.get(sc.mutation, "unknown")
        ops_map = {
            "read": ["query"], "write": ["create"], "delete": ["delete"],
        }
        operations = ops_map.get(intent_type, ["query"])

        # Build parameters: carries candidates (for S3) and step count (for S4)
        # The LLM says only what the user asked for; capabilities come from the registry.
        params: dict[str, Any] = {
            "message": _intent_text(sc.mutation),
            "steps": sc.steps,
        }

        return IntentResult(
            intent_type=intent_type,
            target_entities=["default"],
            operations=operations,
            parameters=params,
            is_workflow=False,
            confidence=sc.confidence,
            raw_llm_output=f"[mock] intent_type={intent_type}, steps={sc.steps}",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_S8_KILL_SWITCH_OFF = None  # deps are built per call; see _s8_deps


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
        "S5": lambda st: s5(st, ScenarioRegistry(scenario)),
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
            now: float) -> str:
    """Call the production store's conditional consume; returns its result code."""
    return scenario.confirmation_store.consume(
        confirmation_id, user_id=user_id, plan_hash=plan_hash, now=now)


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
