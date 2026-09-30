"""Ports of the S12 step loop: what it needs from providers, verification, live state and storage."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_outputs import Step
from contracts.verifier import Verifier


class FencedOut(Exception):
    """This Worker Runtime no longer owns the execution: stop all work on it at once."""


@dataclass(frozen=True)
class StepCall:
    tenant_id: str
    execution_id: str
    step: Step
    binding: FrozenBindingIdentity
    verifier: Verifier | None
    attempt: int


@dataclass(frozen=True)
class AdapterResult:
    """What an adapter (through the guard) reports. It is the worker's CLAIM, never trusted as truth."""
    status: str                              # "ok" | "error" | "timeout"
    retryable: bool = False                  # only meaningful for "error"
    error_class: str | None = None           # e.g. "adapter_defect", "circuit_open", "client_error"
    data: dict = field(default_factory=dict)


class StepAdapter(Protocol):
    async def call(self, call: StepCall) -> AdapterResult:
        """Execute one step against the provider. May raise: the guard converts that to adapter_defect."""


PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


class StepVerification(Protocol):
    async def verify(self, verifier: Verifier, result: AdapterResult) -> str:
        """PASS, FAIL or UNKNOWN, from an independent observation (never from `result.data`)."""


@dataclass(frozen=True)
class Revoked:
    reason: str                              # "kill_switch_engaged" | "authorization_revoked"


class LiveAuthorization(Protocol):
    async def check(self, *, tenant_id: str, workspace_id: str, user_id: str, connection_id: str | None,
                    binding: FrozenBindingIdentity) -> Revoked | None:
        """None = still allowed. Fail closed: state that cannot be read is Revoked."""
