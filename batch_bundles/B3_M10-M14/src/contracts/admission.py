"""Durable admission of a certified plan (gate §7.2): the run, manifest, plan, steps and ownership
are written in ONE transaction, with the run's quota consumed, or nothing is written."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.pipeline_state import PipelineState
from contracts.verifier import Verifier

ADMITTED = "ADMITTED"
DUPLICATE = "DUPLICATE"
DENIED = "DENIED"


@dataclass(frozen=True)
class AdmissionOutcome:
    status: str                              # ADMITTED | DUPLICATE | DENIED
    execution_id: str | None = None
    run_status: str | None = None            # the run's status (RUNNING when admitted)
    reason: str | None = None                # set when DENIED
    retry_after_ms: int | None = None        # soft quota exhausted


class ExecutionAdmitter(Protocol):
    async def admit(self, state: PipelineState, verifiers: tuple[Verifier, ...],
                    runtime_instance_id: str) -> AdmissionOutcome:
        """All-or-nothing. Raise DependencyUnavailable if the database cannot be used (nothing written)."""
