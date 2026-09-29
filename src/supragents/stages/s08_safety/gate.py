"""S8 stage handler. On allow it records auth_passed and auth_result_id (ruling R-M)."""
from __future__ import annotations

import uuid

from supragents.contracts.outputs import SafetyResult
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.deps import PipelineDeps
from supragents.stages.s08_safety.checks import CHECKS, SafetyInputs

STAGE = "S8"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    failure = await _first_failure(state, deps)
    result_id = str(uuid.uuid4())
    if failure is not None:
        check, reason = failure
        state = state.with_output(STAGE, safety_result=SafetyResult(
            allowed=False, result_id=result_id, reason=reason, failed_check=check,
        ))
        return state.halted(STAGE, StageStatus.DENY, reason)
    state = state.with_output(STAGE, safety_result=SafetyResult(allowed=True, result_id=result_id))
    return state.with_context(STAGE, auth_passed=True, auth_result_id=result_id)


async def _first_failure(state: PipelineState, deps: PipelineDeps) -> tuple[str, str] | None:
    """(check, reason) of the first failing check, the kill switch always first."""
    try:
        policy = await deps.policy.current(state.execution_context.tenant_id)
    except Exception:
        return "kill_switch", "kill_switch_unavailable"
    if policy.kill_switch_engaged is not False:
        return "kill_switch", "kill_switch_engaged"
    inputs = SafetyInputs(
        context=state.execution_context,
        profile=state.task_profile,
        binding=state.frozen_binding,
        now=deps.clock.now(),
    )
    for name, check in CHECKS:
        try:
            reason = await check(inputs, deps)
        except Exception:
            reason = f"{name}_unavailable"
        if reason is not None:
            return name, reason
    return None
