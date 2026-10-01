"""Provider adapter interface for S12 (gate C32; PROVIDER_ADAPTERS §1 additive interface; CONF-021)."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from contracts.execution_context import ExecutionContext
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.step_execution import AdapterResult


@dataclass(frozen=True)
class CallMeta:
    idempotency_key: str
    attempt_id: str
    provider_call_id: str
    tenant_id: str


class ProbeOutcome(StrEnum):
    EXECUTED_SUCCESS = "EXECUTED_SUCCESS"
    EXECUTED_FAILURE = "EXECUTED_FAILURE"
    NOT_EXECUTED = "NOT_EXECUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Observation:
    attempt: int
    observed_at: float
    provider_response_code: int
    observed_state: dict | None
    matches_expected: bool | None
    error: str | None


class ErrorClass(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    ADAPTER_DEFECT = "adapter_defect"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    RETRY_STORM = "retry_storm"


RETRYABLE = frozenset({ErrorClass.NOT_DISPATCHED, ErrorClass.RATE_LIMITED, ErrorClass.SERVER_ERROR})


class BudgetStateError(Exception):
    """The step's reservation is missing, belongs to another step or is not LOCKED (C31): an invariant violation."""


class CredentialProvider(Protocol):
    async def credential(self, tenant_id: str, connection_id: str | None) -> str: ...

    async def credential_valid(self, tenant_id: str, connection_id: str | None) -> bool: ...


class BaseAdapter(ABC):
    @abstractmethod
    async def call(self, kernel_op_id: str, params: dict, binding: FrozenBindingIdentity, context: ExecutionContext,
                   *, call_meta: CallMeta | None = None) -> AdapterResult: ...

    async def probe(self, kernel_op_id: str, params: dict, binding: FrozenBindingIdentity, context: ExecutionContext,
                    *, call_meta: CallMeta) -> ProbeOutcome:
        return ProbeOutcome.INCONCLUSIVE

    async def observe(self, kernel_op_id: str, observation_spec: dict[str, Any], binding: FrozenBindingIdentity,
                      context: ExecutionContext) -> Observation:
        return Observation(attempt=1, observed_at=time.time(), provider_response_code=0, observed_state=None,
                           matches_expected=None, error="observe_not_supported")


@dataclass(frozen=True)
class GuardedCall:
    kernel_op_id: str
    params: dict
    binding: FrozenBindingIdentity
    context: ExecutionContext
    call_meta: CallMeta
    step_id: str
    reservation_id: str
    attempt: int
    timeout_s: float

    def __post_init__(self) -> None:
        # fail closed: a call is built for exactly one tenant (C34), one numbered attempt and a real deadline
        if self.call_meta.tenant_id != self.context.tenant_id:
            raise ValueError("call_meta and context name different tenants")
        if self.attempt < 1:
            raise ValueError(f"attempt must be 1 or more, got {self.attempt!r}")
        if not self.timeout_s > 0:
            raise ValueError(f"timeout_s must be positive, got {self.timeout_s!r}")
