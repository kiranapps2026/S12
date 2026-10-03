"""Adapter interface for S12 execution (gate C4, C32, CONF-021).

Defines the contracts that every provider adapter and guard component must honour:
call metadata, probe/observe contracts, error classes, and the BudgetStateError that
the guard raises when a reservation is missing or not LOCKED.

Nothing in this module imports from ``adapters.*`` or ``engine.*``; the dependency
direction is strictly downward, so S8 provider adapters can import it without a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from contracts.frozen_binding import FrozenBindingIdentity
from contracts.execution_context import ExecutionContext
from contracts.step_execution import AdapterResult


# ------------------------------------------------------------------ metadata ----------------------------------------------------------------

@dataclass(frozen=True)
class CallMeta:
    """Ties one adapter or probe call to its idempotency, attempt and tenant."""
    idempotency_key: str            # caller-chosen unique key (often request_id:step_id)
    attempt_id: str                 # "att-{runtime_instance_id}-{attempt}"
    provider_call_id: str           # monotonic counter or UUID per execution
    tenant_id: str                  # used for credential lookup and audit


# ------------------------------------------------------------------ probe / observe ----------------------------------------------------------

class ProbeOutcome(StrEnum):
    """What a provider probe returns (gate C32: exactly these values)."""
    EXECUTED_SUCCESS = "EXECUTED_SUCCESS"
    EXECUTED_FAILURE = "EXECUTED_FAILURE"
    NOT_EXECUTED = "NOT_EXECUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Observation:
    """What a provider observe call returns (WORKER_LIFECYCLE §9)."""
    attempt: int
    observed_at: float              # epoch seconds
    provider_response_code: int | None = None
    observed_state: dict | None = None  # compared keys' match results only, never provider values (DR-60)
    matches_expected: bool | None = None
    error: str | None = None


# ------------------------------------------------------------------ error classes -----------------------------------------------------------

class ErrorClass(StrEnum):
    """Normalised adapter outcome categories (C32)."""
    NOT_DISPATCHED = "not_dispatched"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    ADAPTER_DEFECT = "adapter_defect"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    RETRY_STORM = "retry_storm"


RETRYABLE: frozenset[ErrorClass] = frozenset({
    ErrorClass.NOT_DISPATCHED,
    ErrorClass.RATE_LIMITED,
    ErrorClass.SERVER_ERROR,
})


# ------------------------------------------------------------------ adapter protocol --------------------------------------------------------

@runtime_checkable
class BaseAdapter(Protocol):
    """Provider adapter contract (PROVIDER_ADAPTERS §1, C32).

    An adapter MAY omit ``probe`` or ``observe``: the guard supplies the BaseAdapter default.
    ``call`` MAY raise: the guard converts any escaping exception to ``adapter_defect``.
    """

    async def call(
        self,
        kernel_op_id: str,
        params: dict,
        binding: FrozenBindingIdentity,
        context: ExecutionContext,
        *,
        call_meta: CallMeta | None = None,
    ) -> AdapterResult:
        """Execute one operation. Return AdapterResult; never raise (guard catches)."""
        ...  # pragma: no cover — protocol stub

    async def probe(
        self,
        kernel_op_id: str,
        params: dict,
        binding: FrozenBindingIdentity,
        context: ExecutionContext,
        *,
        call_meta: CallMeta,
    ) -> ProbeOutcome:
        """Probe without side effects. Default: INCONCLUSIVE."""
        return ProbeOutcome.INCONCLUSIVE

    async def observe(
        self,
        kernel_op_id: str,
        observation_spec: dict,
        binding: FrozenBindingIdentity,
        context: ExecutionContext,
    ) -> Observation:
        """Observe provider state without side effects. Default: not supported."""
        return Observation(attempt=0, observed_at=0.0, error="observe_not_supported")


# ------------------------------------------------------------------ credential provider -----------------------------------------------------

class CredentialProvider(Protocol):
    """Source of provider credentials (S6: credentials only through this channel)."""

    async def credential(self, tenant_id: str, connection_id: str | None) -> str:
        """Return the credential string for this tenant/connection. Never raise."""
        ...  # pragma: no cover — protocol stub

    async def credential_valid(self, tenant_id: str, connection_id: str | None) -> bool:
        """Cheap local check that the connection's credential is usable (CONF-030): present, not expired or revoked.

        M14's live authorization calls it before every step; it must not make a provider round trip. Anything other
        than ``True`` revokes the step (``credential_invalid``)."""
        ...  # pragma: no cover — protocol stub


# ------------------------------------------------------------------ guard errors ------------------------------------------------------------

class BudgetStateError(Exception):
    """Raised by BudgetTracker when the reservation is missing or not LOCKED (C31)."""


# ------------------------------------------------------------------ guarded call ------------------------------------------------------------

@dataclass(frozen=True)
class GuardedCall:
    """Everything the ReliabilityGuard needs for one adapter call (C4)."""
    kernel_op_id: str
    params: dict
    binding: FrozenBindingIdentity
    context: ExecutionContext
    call_meta: CallMeta
    step_id: str
    reservation_id: str | None
    attempt: int
    timeout_s: float

    def __post_init__(self) -> None:
        # a guarded call is self-consistent or it cannot be built (C9, C34, C37)
        if self.call_meta.tenant_id != self.context.tenant_id:
            raise ValueError("call_meta.tenant_id differs from the context's tenant")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        if not self.timeout_s > 0:
            raise ValueError("timeout_s must be > 0")
