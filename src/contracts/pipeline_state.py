"""
PipelineState — typed accumulator for the S0–S11 pipeline.

Each stage produces its output via with_stage_output(), which validates
ownership, write-once, and type. S11 is the only stage with two owned fields:
execution_manifest (primary) and validation_result (secondary).

Source: DATA_CONTRACTS.md §2 (ExecutionContext ownership model),
         PIPELINE_STAGES.md §11 (stage output contracts)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import types
from typing import Any, TYPE_CHECKING

from contracts.execution_context import ExecutionContext
from contracts.errors import ContractViolationError
from contracts.stage_registry import StageOutcome, StageStatus

if TYPE_CHECKING:
    from contracts.entry import EntryRequest

# ---------------------------------------------------------------------------
# Stage-to-field ownership mapping
# ---------------------------------------------------------------------------

#: Each stage S0–S11 owns exactly one PipelineState field. S11 owns two:
#: execution_manifest (primary) and validation_result (secondary).
#: S0 writes execution_context via with_stage_output; S2/S5/S8 may also
#: update selected context fields via replace_context (R-M).
STAGE_OUTPUT_FIELD = types.MappingProxyType({
    "S0": "execution_context",        # S0 creates the initial context
    "S1": "normalized_input",         # S1 produces NormalizedInput
    "S2": "intent_result",            # S2 produces IntentResult
    "S3": "capability_match",         # S3 produces CapabilityMatch
    "S4": "graph_analysis",           # S4 produces GraphAnalysis
    "S5": "frozen_binding_identity",  # S5 produces FrozenBindingIdentity
    "S6": "task_profile",             # S6 produces TaskProfile
    "S7": "path_decision",            # S7 produces PathDecision
    "S8": "safety_result",            # S8 produces SafetyResult
    "S9": "plan",                     # S9 produces PlanCreationResult
    "S10": "confirmation",            # S10 produces Confirmation
    "S11": "execution_manifest",      # S11 produces ExecutionManifest (primary)
})

#: The execution sequence — S0 through S11 in order.
PRE_EXECUTION_SEQUENCE: tuple[str, ...] = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")

#: S11's secondary output field — the only stage with two outputs.
S11_SECONDARY_FIELD: str = "validation_result"

#: All fields S11 may write (primary + secondary).
S11_OWNED_FIELDS: tuple[str, ...] = (
    STAGE_OUTPUT_FIELD["S11"],
    S11_SECONDARY_FIELD,
)

#: Controlled context replacement whitelist (R-M).
#: Only these stages may call replace_context, and only for these fields.
CONTEXT_REPLACEMENT_WHITELIST: types.MappingProxyType[str, frozenset[str]] = types.MappingProxyType({
    "S2": frozenset({"task_id"}),
    "S5": frozenset({"tenant_policy_version_id", "workspace_policy_version_id", "policy_version_id"}),
    "S8": frozenset({"auth_passed", "auth_result_id"}),
})

# ---------------------------------------------------------------------------
# Runtime type registry for isinstance checks.
#
# Imports are deferred to function scope to avoid circular imports at module
# load time: stage_outputs.py/execution_manifest.py may import PipelineState.
# ---------------------------------------------------------------------------

_FIELD_TYPE_MODULES = types.MappingProxyType({
    "execution_context": "contracts.execution_context",
    "normalized_input": "contracts.stage_outputs",
    "intent_result": "contracts.stage_outputs",
    "capability_match": "contracts.stage_outputs",
    "graph_analysis": "contracts.stage_outputs",
    "frozen_binding_identity": "contracts.frozen_binding",
    "task_profile": "contracts.safety",
    "path_decision": "contracts.safety",
    "safety_result": "contracts.safety",
    "plan": "contracts.stage_outputs",
    "confirmation": "contracts.execution_manifest",
    "execution_manifest": "contracts.execution_manifest",
    "validation_result": "contracts.stage_outputs",
})

_FIELD_TYPE_NAMES = types.MappingProxyType({
    "execution_context": "ExecutionContext",
    "normalized_input": "NormalizedInput",
    "intent_result": "IntentResult",
    "capability_match": "CapabilityMatch",
    "graph_analysis": "GraphAnalysis",
    "frozen_binding_identity": "FrozenBindingIdentity",
    "task_profile": "TaskProfile",
    "path_decision": "PathRoutingResult",
    "safety_result": "SafetyResult",
    "plan": "PlanCreationResult",
    "confirmation": "ConfirmationOutcome",
    "execution_manifest": "ExecutionManifest",
    "validation_result": "ValidationResult",
})


def _resolve_field_type(field_name: str) -> type | None:
    """Return the runtime class for a PipelineState field, or None if unavailable."""
    module_name = _FIELD_TYPE_MODULES.get(field_name)
    class_name = _FIELD_TYPE_NAMES.get(field_name)
    if not module_name or not class_name:
        return None
    try:
        import importlib
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError):
        return None


@dataclass(frozen=True)
class PipelineState:
    """
    Immutable accumulator for the S0–S11 pipeline.

    Each field is owned by exactly one stage. Stages produce new PipelineState
    instances via `with_stage_output()` — the original is never mutated.

    Fields default to None. A field becomes non-None after its owning stage
    completes successfully. Once set, it cannot be overwritten.
    """

    execution_context: ExecutionContext | None = None
    entry_request: EntryRequest | None = None       # R-X: S0 owns both
    normalized_input: NormalizedInput | None = None
    intent_result: IntentResult | None = None
    capability_match: CapabilityMatch | None = None
    graph_analysis: GraphAnalysis | None = None
    frozen_binding_identity: FrozenBindingIdentity | None = None
    task_profile: TaskProfile | None = None
    path_decision: PathDecision | None = None
    safety_result: SafetyResult | None = None
    plan: PlanCreationResult | None = None
    confirmation: ConfirmationOutcome | None = None
    execution_manifest: ExecutionManifest | None = None
    validation_result: ValidationResult | None = None

    # Result of the stage that ran last. The runner reads only these two fields to
    # decide whether to continue; a stage that refuses sets DENY/CLARIFY/ERROR here.
    stage_status: StageStatus | None = None
    deny_reason: str | None = None

    def with_status(self, status: StageStatus, reason: str | None = None) -> PipelineState:
        """Record the running stage's result. Non-NORMAL statuses stop the run."""
        if status is StageStatus.NORMAL and reason is not None:
            raise ContractViolationError("A NORMAL status carries no reason.")
        return replace(self, stage_status=status, deny_reason=reason)

    def with_stage_output(self, stage_id: str, value: object = None, **fields: Any) -> PipelineState:
        """
        Record a stage's output(s) in this PipelineState.

        Two calling conventions:

        1. Single value: `with_stage_output("S5", binding)` — the stage's
           single owned field is set to ``value``.
        2. Named fields: `with_stage_output("S11", execution_manifest=m, validation_result=v)`
           — S11 (the only stage with two fields) writes both atomically.

        Args:
            stage_id: The stage producing this output (e.g. "S11")
            value: The single output value (when the stage owns one field).
            **fields: Named field=value pairs (when the stage owns multiple fields).

        Returns:
            A NEW PipelineState with the fields recorded.

        Raises:
            ValueError: If stage_id is unknown, field is not owned by the
                        stage, field is already set, or value type is wrong.
        """
        if stage_id not in STAGE_OUTPUT_FIELD:
            raise ContractViolationError(
                f"Unknown stage '{stage_id}'. "
                f"Valid stages: {sorted(STAGE_OUTPUT_FIELD.keys())}",
                stage_id=stage_id,
            )

        # Determine which fields this stage is allowed to write
        if stage_id == "S11":
            allowed_fields = set(S11_OWNED_FIELDS)
        else:
            allowed_fields = {STAGE_OUTPUT_FIELD[stage_id]}

        # R-T: a stage may write only after the previous stage's output exists.
        idx = PRE_EXECUTION_SEQUENCE.index(stage_id)
        if idx > 0:
            prev_field = STAGE_OUTPUT_FIELD[PRE_EXECUTION_SEQUENCE[idx - 1]]
            if getattr(self, prev_field) is None:
                raise ContractViolationError(
                    f"{stage_id} cannot write before {PRE_EXECUTION_SEQUENCE[idx - 1]} "
                    f"has written '{prev_field}'.",
                    stage_id=stage_id,
                )

        # Build the dict of fields to set
        updates: dict[str, Any] = {}

        if value is not None:
            # Single-value convention: value maps to the stage's primary field
            if fields:
                raise ValueError(
                    "Cannot use both value= and named fields. "
                    "Use value= for single-field stages, named fields for multi-field (S11)."
                )
            primary_field = STAGE_OUTPUT_FIELD[stage_id]
            updates[primary_field] = value
        else:
            # Named-fields convention: **fields contains the explicit field=value pairs
            updates = dict(fields)

        # Validate each field
        for field_name, new_value in updates.items():
            if stage_id == "S11" and field_name == "execution_manifest" and new_value is None:
                continue  # R-F: the one permitted None (S11 denial)
            if field_name not in allowed_fields:
                raise ContractViolationError(
                    f"Field '{field_name}' is not owned by {stage_id}. "
                    f"Owned fields: {sorted(allowed_fields)}.",
                    stage_id=stage_id,
                    field=field_name,
                )
            current = getattr(self, field_name)
            if current is not None:
                raise ContractViolationError(
                    f"Cannot overwrite field '{field_name}': already set to "
                    f"{current!r}. Fields are write-once.",
                    stage_id=stage_id,
                    field=field_name,
                )

            # Runtime type check — deferred import avoids circular module load.
            expected = _resolve_field_type(field_name)
            if expected is not None and not isinstance(new_value, expected):
                raise ContractViolationError(
                    f"Field '{field_name}' expects type {expected.__name__}, "
                    f"got {type(new_value).__name__}.",
                    stage_id=stage_id,
                    field=field_name,
                    expected_type=expected.__name__,
                    actual_type=type(new_value).__name__,
                )

        return replace(self, stage_status=StageStatus.NORMAL, deny_reason=None, **updates)

    def get_stage_output(self, stage_id: str) -> object | None:
        """Get the output for a given stage. Returns None if stage hasn't run."""
        if stage_id not in STAGE_OUTPUT_FIELD:
            raise ValueError(f"Unknown stage '{stage_id}'")
        return getattr(self, STAGE_OUTPUT_FIELD[stage_id])

    def has_stage_completed(self, stage_id: str) -> bool:
        """Check if a stage has produced its output."""
        return self.get_stage_output(stage_id) is not None

    def validate_replace(self, field_name: str, new_value: object, allowed_fields: frozenset[str]) -> object:
        """
        Controlled replacement of a PipelineState field (R-M).

        S2/S5/S8 use this to update ExecutionContext-derived fields.
        The allowed_fields whitelist is enforced per-stage.

        Args:
            field_name: The field to replace.
            new_value: The new value.
            allowed_fields: Whitelist of fields this stage may replace.

        Returns:
            The validated new value (caller then calls with_stage_output).

        Raises:
            ValueError: If field_name is not in allowed_fields.
        """
        if field_name not in allowed_fields:
            raise ValueError(
                f"Cannot replace '{field_name}': not in allowed_fields "
                f"{sorted(allowed_fields)}"
            )
        current = getattr(self, field_name)
        if current is not None and current != new_value:
            raise ValueError(
                f"Cannot replace '{field_name}': already set to "
                f"{current!r} — write-once."
            )
        return new_value

    def replace_context(self, stage_id: str, **fields: Any) -> PipelineState:
        """
        Controlled replacement of ExecutionContext-derived fields (R-M).

        Only S2, S5, and S8 may call this, and only for their whitelisted fields:
        - S2: task_id
        - S5: tenant_policy_version_id, workspace_policy_version_id, policy_version_id
        - S8: auth_passed, auth_result_id

        Raises ContractViolationError if:
        - stage_id is not in CONTEXT_REPLACEMENT_WHITELIST
        - any field is not in that stage's allowed set
        """
        if stage_id not in CONTEXT_REPLACEMENT_WHITELIST:
            raise ContractViolationError(
                f"Cannot replace context fields from stage '{stage_id}': "
                f"not in whitelist {sorted(CONTEXT_REPLACEMENT_WHITELIST)}.",
                stage_id=stage_id,
            )
        allowed = CONTEXT_REPLACEMENT_WHITELIST[stage_id]
        for field_name in fields:
            if field_name not in allowed:
                raise ContractViolationError(
                    f"Cannot replace context field '{field_name}': not allowed "
                    f"for stage '{stage_id}'. Allowed: {sorted(allowed)}.",
                    stage_id=stage_id,
                    field=field_name,
                )
        current_ctx = self.execution_context
        if current_ctx is None:
            raise ContractViolationError(
                "Cannot replace context: execution_context is None.",
                stage_id=stage_id,
            )
        new_ctx = replace(current_ctx, **fields)
        return replace(self, execution_context=new_ctx)
