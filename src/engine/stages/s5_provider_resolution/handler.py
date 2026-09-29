"""
S5 Provider Resolution — resolve the matched capability to one binding and freeze it.

THIS IS THE ONE AND ONLY SOURCE OF effective_risk AND effective_mutation.
After S5 they are immutable in FrozenBindingIdentity.

Source: FINAL_ARCHITECTURE.md §11, §22, RUNBOOK R-E/R-O
Owner: S5 / Provider Resolution

The binding (provider, adapter, kernel operation, versions) is read from the capability
registry's binding rows — nothing is hard-coded and nothing comes from the LLM. Fail
closed: no active binding, an incomplete binding or a non-canonical mutation is a DENY.
"""
from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.capability import CapabilityRegistry
from contracts.kernel_policy import PolicyVersions
from contracts.stage_outputs import CapabilityMatch
from contracts.stage_registry import StageStatus
from contracts.errors import ContractViolationError, ResolutionError

logger = logging.getLogger(__name__)

CANONICAL_MUTATIONS = frozenset({"R", "W", "D", "IRREVERSIBLE"})


async def handle(state: PipelineState, registry: CapabilityRegistry | None,
                 policy_versions: PolicyVersions | None) -> PipelineState:
    """
    S5 handler: pick the best active binding, compute effective_risk once, freeze.

    effective_risk = max(risk_floor, risk_rule, risk_implied, binding.effective_risk).
    S5 also records the tenant/workspace/effective policy versions (from the run scope) on
    the ExecutionContext (S5 whitelist, R-E).
    """
    match = state.capability_match
    ctx = state.execution_context
    if match is None:
        raise ResolutionError("No CapabilityMatch from S3")
    if not isinstance(match, CapabilityMatch):
        raise ContractViolationError(
            f"S5 requires a CapabilityMatch from S3, got {type(match).__name__}",
            stage_id="S5", field="capability_match",
            expected_type="CapabilityMatch", actual_type=type(match).__name__,
        )
    if ctx is None:
        raise ContractViolationError("S5 requires the S0 ExecutionContext", stage_id="S5")
    if registry is None:
        return state.with_status(StageStatus.DENY, "capability_registry_unavailable")
    if policy_versions is None:
        return state.with_status(StageStatus.DENY, "policy_versions_unavailable")

    if match.mutation_type not in CANONICAL_MUTATIONS:
        return state.with_status(StageStatus.DENY, "invalid_mutation")

    rows = [b for b in await registry.list_bindings(match.capability_id)
            if b.is_active and b.capability_id == match.capability_id]
    if not rows:
        return state.with_status(StageStatus.DENY, "no_binding")
    row = min(rows, key=lambda b: (b.selection_rank, b.binding_id))
    if not (row.provider and row.adapter_class and row.kernel_op_id and row.engine_module):
        return state.with_status(StageStatus.DENY, "binding_incomplete")

    frozen = FrozenBindingIdentity(
        binding_id=row.binding_id,
        capability_id=match.capability_id,
        kernel_op_id=row.kernel_op_id,
        provider=row.provider,
        engine_module=row.engine_module,
        adapter_class=row.adapter_class,
        effective_risk=max(match.risk_floor, match.risk_rule, match.risk_implied,
                           row.effective_risk),
        effective_mutation=match.mutation_type,
        resolved_at_stage="S5",
        selection_rank=row.selection_rank,
        capability_version=row.capability_version,
        binding_version=row.binding_version,
        risk_policy_version=row.risk_policy_version,
        authorization_version=row.authorization_version,
    )

    state = state.replace_context(
        "S5",
        tenant_policy_version_id=policy_versions.tenant_policy_version_id,
        workspace_policy_version_id=policy_versions.workspace_policy_version_id,
        policy_version_id=policy_versions.policy_version_id,
    )
    logger.info("S5: resolved binding %s: risk=%.4f, mutation=%s",
                frozen.binding_id, frozen.effective_risk, frozen.effective_mutation)
    return state.with_stage_output("S5", frozen)
