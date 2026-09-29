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
    _intent_text, _build_capability_dicts,
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
      - candidates (capability dicts) in parameters for S3
      - step count in parameters for S4
      - is_workflow flag
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
        params: dict[str, Any] = {
            "message": _intent_text(sc.mutation),
            "steps": sc.steps,
        }
        if sc.capabilities > 1:
            params["multi_capability"] = True
        # Candidates go in parameters — S3 reads them from there
        params["candidates"] = _build_capability_dicts(sc)

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

def state_ready_for(stage_id: str, scenario: Scenario) -> PipelineState:
    """Run real handlers S0..stage-1, then return the PipelineState.

    Scenario configures: mock LLM output, capability metadata (mutation, cost,
    risk components), step count, graph shape.
    Real handlers produce every output. No dataclasses.replace for outputs.
    """
    target_idx = PRE_EXECUTION_SEQUENCE.index(stage_id)

    # S0->S1->S2: mock LLM produces scenario-configured IntentResult (with candidates + steps)
    state = _run_s0_s2(scenario)

    # S3: real handler produces CapabilityMatch from candidates in IntentResult.parameters
    if target_idx > 3:
        from engine.stages.s3_capability_discovery.handler import handle as s3_handle
        state = asyncio.run(s3_handle(state))

    # S4: real handler derives graph from intent.parameters["steps"] and is_workflow
    if target_idx > 4:
        from engine.stages.s4_graph_classification.handler import handle as s4_handle
        state = asyncio.run(s4_handle(state))

    # S5: real handler produces FrozenBindingIdentity
    if target_idx > 5:
        from engine.stages.s5_provider_resolution.handler import handle as s5_handle
        state = asyncio.run(s5_handle(state))

    # S6: real handler produces TaskProfile
    if target_idx > 6:
        from engine.stages.s6_task_profile_assembly.handler import handle as s6_handle
        state = asyncio.run(s6_handle(state))

    # S7: real handler produces PathDecision
    if target_idx > 7:
        from engine.stages.s7_path_decision.handler import handle as s7_handle
        from contracts.kernel_policy import KernelPolicy
        threshold = scenario.risk_deny_threshold
        policy = KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=threshold)
        state = asyncio.run(s7_handle(state, policy=policy))

    # S8: real handler produces SafetyResult
    if target_idx > 8:
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        from tests.fixtures.deps import make_s8_deps
        s8_deps = make_s8_deps(kill_switch=False)
        state = asyncio.run(s8_handle(state, s8_deps))

    # S9: real handler produces PlanCreationResult
    if target_idx > 9:
        from engine.stages.s9_plan_creation.handler import handle as s9_handle
        state = asyncio.run(s9_handle(state))

    # S10: real handler produces Confirmation
    if target_idx > 10:
        from engine.stages.s10_confirmation.handler import handle as s10_handle
        state = asyncio.run(s10_handle(state))

    # S11: real handler produces ExecutionManifest + ValidationResult
    if target_idx >= 11:
        from engine.stages.s11_plan_validation.handler import handle as s11_handle
        state = asyncio.run(s11_handle(state))

    return state


def run_stage(stage_id: str, state: PipelineState, scenario: Scenario) -> PipelineState:
    """Run the REAL production handler for stage_id. No fabrication."""
    stage = stage_id.upper()

    if stage == "S6":
        from engine.stages.s6_task_profile_assembly.handler import handle as s6_handle
        return asyncio.run(s6_handle(state))

    elif stage == "S7":
        from engine.stages.s7_path_decision.handler import handle as s7_handle
        from contracts.kernel_policy import KernelPolicy
        threshold = scenario.risk_deny_threshold
        policy = KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=threshold)
        return asyncio.run(s7_handle(state, policy=policy))

    elif stage == "S9":
        from engine.stages.s9_plan_creation.handler import handle as s9_handle
        return asyncio.run(s9_handle(state))

    else:
        raise ValueError(f"run_stage: unsupported stage_id '{stage_id}'")


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
