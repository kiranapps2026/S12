"""S5 Provider Resolution: select and freeze one binding; compute risk and mutation once.

Selection is deterministic: priority, then created_at, then binding_id (DATA_CONTRACTS §6).
"""
from __future__ import annotations

from supragents.contracts.outputs import FrozenBindingIdentity
from supragents.contracts.registry import BindingRow, CapabilityMetadata, KernelOperation
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus, TruthState
from supragents.pipeline.deps import PipelineDeps
from supragents.policy.risk import effective_mutation, effective_risk

STAGE = "S5"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    capability = state.capability_match.capability
    rows = await deps.registry.bindings_for(state.execution_context.tenant_id, capability.capability_id)
    ranked = sorted(
        (row for row in rows if row.is_active and row.capability_id == capability.capability_id),
        key=lambda row: (row.priority, row.created_at, row.binding_id),
    )
    if not ranked:
        return state.halted(STAGE, StageStatus.CLARIFY, "provider_unavailable")
    kernel_op = await deps.registry.kernel_operation(ranked[0].kernel_op_id)
    if kernel_op is None or kernel_op.truth_state is not TruthState.PRODUCTION_ENABLED:
        return state.halted(STAGE, StageStatus.CLARIFY, "kernel_operation_unavailable")
    return state.with_output(STAGE, frozen_binding=_freeze(capability, ranked[0], kernel_op))


def _freeze(
    capability: CapabilityMetadata, binding: BindingRow, kernel_op: KernelOperation
) -> FrozenBindingIdentity:
    return FrozenBindingIdentity(
        binding_id=binding.binding_id,
        capability_id=capability.capability_id,
        kernel_op_id=kernel_op.kernel_op_id,
        provider=binding.provider,
        engine_module=binding.engine_module,
        adapter_class=binding.adapter_class,
        effective_risk=effective_risk(capability, kernel_op),
        effective_mutation=effective_mutation(capability, kernel_op),
        cost_per_step=kernel_op.cost,
        timeout_seconds=kernel_op.timeout_seconds,
        retry_safety=kernel_op.retry_safety,
        inverse=kernel_op.inverse,
        selection_rank=0,
    )
