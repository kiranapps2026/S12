"""What a pipeline run returns to its caller."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from supragents.contracts.outputs import Confirmation, ExecutionManifest
from supragents.contracts.state import Halt, PipelineState


class RunOutcome(StrEnum):
    COMPLETED = "completed"                  # S11 issued an ExecutionManifest
    STOPPED = "stopped"                      # a stage halted the run (see ``halt``)
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # S10 waits for the user's reply


@dataclass(frozen=True)
class RunResult:
    outcome: RunOutcome
    state: PipelineState

    @property
    def halt(self) -> Halt | None:
        return self.state.halt

    @property
    def manifest(self) -> ExecutionManifest | None:
        return self.state.execution_manifest

    @property
    def pending_confirmation(self) -> Confirmation | None:
        if self.outcome is not RunOutcome.AWAITING_CONFIRMATION:
            return None
        return self.state.confirmation_check.confirmation
