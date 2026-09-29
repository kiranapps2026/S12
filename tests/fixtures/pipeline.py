"""
Pipeline journey helper — run real handlers S0..stage_id in order.

Source: R-H (runbook): journeys use real handlers, not hand-built state.
"""
from __future__ import annotations

import asyncio
from typing import Any

from contracts.pipeline_state import PipelineState, PRE_EXECUTION_SEQUENCE


def run_through(
    stage_id: str,
    request: dict | None = None,
    deps: dict | None = None,
) -> PipelineState:
    """
    Run real handlers S0..stage_id and return the final PipelineState.

    Args:
        stage_id: Target stage (e.g. "S2").
        request: Raw request dict. Defaults to a minimal read request.
        deps: Optional dependency dict (unused by S0–S7; S8+ use it).

    Returns:
        PipelineState as stage_id leaves it.
    """
    if request is None:
        request = {"message": "test", "entry_channel": "api"}

    # S0: Entry -> ExecutionContext
    from engine.stages.s0_entry.handler import EntryRequest, handle as s0_handle
    entry = EntryRequest(
        raw_payload=request,
        entry_channel=request.get("entry_channel", "api"),
        tenant_id=request.get("tenant_id", "tenant-1"),
        user_id=request.get("user_id", "user-1"),
        conversation_id=request.get("conversation_id"),
        connection_id=request.get("connection_id"),
    )
    state = asyncio.run(s0_handle(entry))
    # S0 now returns PipelineState directly (R-X), with entry_request already set

    target_idx = PRE_EXECUTION_SEQUENCE.index(stage_id)

    # S1: Normalize — reads raw payload from state.entry_request (R-X)
    if target_idx >= 1:
        from engine.stages.s1_normalize.handler import handle as s1_handle
        state = asyncio.run(s1_handle(state))

    # S2: Intent Analysis
    if target_idx >= 2:
        from engine.stages.s2_intent_analysis.handler import handle as s2_handle
        from engine.stages.s2_intent_analysis.handler import MockLLMProvider
        llm = MockLLMProvider()
        state = asyncio.run(s2_handle(state, llm=llm))

    # S3: Capability Discovery
    if target_idx >= 3:
        from engine.stages.s3_capability_discovery.handler import handle as s3_handle
        state = asyncio.run(s3_handle(state))

    # S4: Graph Classification
    if target_idx >= 4:
        from engine.stages.s4_graph_classification.handler import handle as s4_handle
        state = asyncio.run(s4_handle(state))

    # S5: Provider Resolution
    if target_idx >= 5:
        from engine.stages.s5_provider_resolution.handler import handle as s5_handle
        state = asyncio.run(s5_handle(state))

    # S6: Task Profile Assembly
    if target_idx >= 6:
        from engine.stages.s6_task_profile_assembly.handler import handle as s6_handle
        state = asyncio.run(s6_handle(state))

    # S7: Path Decision
    if target_idx >= 7:
        from engine.stages.s7_path_decision.handler import handle as s7_handle
        state = asyncio.run(s7_handle(state))

    # S8: Safety Gate (needs deps)
    if target_idx >= 8:
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        from contracts.kernel_policy import KernelPolicy
        from tests.fixtures.deps import make_s8_deps
        policy = KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=0.95)
        s8_deps = deps if deps is not None else make_s8_deps(kill_switch=False)
        state = asyncio.run(s8_handle(state, s8_deps))

    # S9: Plan Creation
    if target_idx >= 9:
        from engine.stages.s9_plan_creation.handler import handle as s9_handle
        state = asyncio.run(s9_handle(state))

    # S10: Confirmation
    if target_idx >= 10:
        from engine.stages.s10_confirmation.handler import handle as s10_handle
        state = asyncio.run(s10_handle(state))

    # S11: Plan Validation
    if target_idx >= 11:
        from engine.stages.s11_plan_validation.handler import handle as s11_handle
        state = asyncio.run(s11_handle(state))

    return state
