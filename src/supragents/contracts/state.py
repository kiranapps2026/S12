"""PipelineState — the write-once accumulator passed from stage to stage.

Rules enforced here, so no stage can break them:
- each field is owned by exactly one stage and written once;
- values are type-checked on write;
- a stop (``halt``) is recorded once and never cleared.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from supragents.contracts.context import CONTEXT_REPLACEMENT_WHITELIST, ExecutionContext
from supragents.contracts.entry import EntryRequest
from supragents.contracts.errors import ContractViolation
from supragents.contracts.outputs import (
    CapabilityMatch,
    ConfirmationCheck,
    ExecutionManifest,
    FrozenBindingIdentity,
    GraphAnalysis,
    IntentResult,
    NormalizedInput,
    PathRouting,
    PlanCreationResult,
    SafetyResult,
    TaskProfile,
    ValidationResult,
)
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.vocabulary import StageStatus

STAGE_SEQUENCE: tuple[str, ...] = (
    "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11",
)

FIELD_OWNER = MappingProxyType({
    "execution_context": "S0",
    "normalized_input": "S1",
    "intent_result": "S2",
    "capability_match": "S3",
    "graph_analysis": "S4",
    "frozen_binding": "S5",
    "task_profile": "S6",
    "path_routing": "S7",
    "safety_result": "S8",
    "plan_result": "S9",
    "confirmation_check": "S10",
    "validation_result": "S11",
    "execution_manifest": "S11",
})

FIELD_TYPE = MappingProxyType({
    "execution_context": ExecutionContext,
    "normalized_input": NormalizedInput,
    "intent_result": IntentResult,
    "capability_match": CapabilityMatch,
    "graph_analysis": GraphAnalysis,
    "frozen_binding": FrozenBindingIdentity,
    "task_profile": TaskProfile,
    "path_routing": PathRouting,
    "safety_result": SafetyResult,
    "plan_result": PlanCreationResult,
    "confirmation_check": ConfirmationCheck,
    "validation_result": ValidationResult,
    "execution_manifest": ExecutionManifest,
})


@dataclass(frozen=True)
class Halt:
    """Why and where the run stopped. ``status`` is never NORMAL."""

    stage: str
    status: StageStatus
    reason: str


@dataclass(frozen=True)
class PipelineState:
    entry_request: EntryRequest
    confirmation_reply: ConfirmationReply | None = None
    execution_context: ExecutionContext | None = None
    normalized_input: NormalizedInput | None = None
    intent_result: IntentResult | None = None
    capability_match: CapabilityMatch | None = None
    graph_analysis: GraphAnalysis | None = None
    frozen_binding: FrozenBindingIdentity | None = None
    task_profile: TaskProfile | None = None
    path_routing: PathRouting | None = None
    safety_result: SafetyResult | None = None
    plan_result: PlanCreationResult | None = None
    confirmation_check: ConfirmationCheck | None = None
    validation_result: ValidationResult | None = None
    execution_manifest: ExecutionManifest | None = None
    halt: Halt | None = None

    def with_output(self, stage: str, **fields: Any) -> PipelineState:
        """Record ``stage``'s own outputs. Raises ContractViolation on any rule breach."""
        for name, value in fields.items():
            self._check_writable(stage, name, value)
        return replace(self, **fields)

    def with_reply(self, reply: ConfirmationReply) -> PipelineState:
        """Attach the user's confirmation reply to a run suspended before S10."""
        if self.confirmation_check is not None or self.halt is not None:
            raise ContractViolation("a reply can only resume a run suspended before S10")
        return replace(self, confirmation_reply=reply)

    def with_context(self, stage: str, **fields: Any) -> PipelineState:
        """Replace whitelisted ExecutionContext fields (S2: task_id; S8: auth fields)."""
        allowed = CONTEXT_REPLACEMENT_WHITELIST.get(stage, frozenset())
        disallowed = set(fields) - allowed
        if disallowed:
            raise ContractViolation(f"{stage} may not replace context fields {sorted(disallowed)}")
        if self.execution_context is None:
            raise ContractViolation(f"{stage}: no execution context to replace")
        return replace(self, execution_context=replace(self.execution_context, **fields))

    def halted(self, stage: str, status: StageStatus, reason: str) -> PipelineState:
        """Stop the run at ``stage``. The runner reads ``halt`` after every stage."""
        if status is StageStatus.NORMAL:
            raise ContractViolation(f"{stage}: a halt cannot have status NORMAL")
        if self.halt is not None:
            raise ContractViolation(f"{stage}: run already halted at {self.halt.stage}")
        return replace(self, halt=Halt(stage=stage, status=status, reason=reason))

    def _check_writable(self, stage: str, name: str, value: object) -> None:
        owner = FIELD_OWNER.get(name)
        if owner is None:
            raise ContractViolation(f"{stage}: unknown field {name!r}")
        if owner != stage:
            raise ContractViolation(f"{stage} may not write {name!r} (owner {owner})")
        if getattr(self, name) is not None:
            raise ContractViolation(f"{stage}: {name!r} is write-once and already set")
        if not isinstance(value, FIELD_TYPE[name]):
            raise ContractViolation(
                f"{stage}: {name!r} expects {FIELD_TYPE[name].__name__}, got {type(value).__name__}"
            )
