"""The eight S8 checks, in PIPELINE_STAGES §10 order.

Each check returns None when it passes, or the denial reason. A port that raises is
treated as "cannot decide" and denies with ``<check>_unavailable`` (fail closed).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from supragents.contracts.context import ExecutionContext
from supragents.contracts.outputs import FrozenBindingIdentity, TaskProfile
from supragents.contracts.vocabulary import CircuitState, RecordStatus
from supragents.pipeline.deps import PipelineDeps


@dataclass(frozen=True)
class SafetyInputs:
    context: ExecutionContext
    profile: TaskProfile
    binding: FrozenBindingIdentity
    now: float


Check = Callable[[SafetyInputs, PipelineDeps], Awaitable[str | None]]


def _active(status: RecordStatus, name: str) -> str | None:
    return None if status is RecordStatus.ACTIVE else f"{name}_inactive"


async def user_active(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    return _active(await deps.authorization.user_status(inputs.context.tenant_id, inputs.context.user_id), "user")


async def tenant_active(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    return _active(await deps.authorization.tenant_status(inputs.context.tenant_id), "tenant")


async def connection_active(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    connection = await deps.authorization.connection_state(
        inputs.context.tenant_id, inputs.context.connection_id
    )
    if connection.expires_at is not None and connection.expires_at <= inputs.now:
        return "connection_expired"
    return _active(connection.status, "connection")


async def capability_granted(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    granted = await deps.authorization.has_grant(
        inputs.context.tenant_id, inputs.context.user_id, inputs.binding.capability_id
    )
    return None if granted is True else "capability_denied"


async def resource_scope(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    context = inputs.context
    in_scope = await deps.authorization.workspace_in_scope(
        context.tenant_id, context.user_id, context.workspace_id, context.membership_id
    )
    return None if in_scope is True else "resource_scope_denied"


async def circuit_breaker(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    state = await deps.circuit_breaker.state(inputs.binding.provider)
    return "circuit_open" if state is CircuitState.OPEN else None


async def budget_available(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    enough = await deps.authorization.budget_available(inputs.context.tenant_id, inputs.profile.cost)
    return None if enough is True else "budget_exceeded"


async def mutation_safety(inputs: SafetyInputs, deps: PipelineDeps) -> str | None:
    permitted = await deps.mutation_policy.permits(
        inputs.context.tenant_id, inputs.binding.effective_mutation, inputs.binding.effective_risk
    )
    return None if permitted is True else "mutation_not_permitted"


CHECKS: tuple[tuple[str, Check], ...] = (
    ("user_active", user_active),
    ("tenant_active", tenant_active),
    ("connection_active", connection_active),
    ("capability_granted", capability_granted),
    ("resource_scope", resource_scope),
    ("circuit_breaker", circuit_breaker),
    ("budget_available", budget_available),
    ("mutation_safety", mutation_safety),
)
