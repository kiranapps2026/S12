"""
Stage Output Types — frozen dataclasses for PipelineState fields.

Every PipelineState field has a concrete frozen dataclass type. This is the
IMPLEMENTATION CONTRACT — types are defined, handlers construct them, and
PipelineState.with_stage_output() accepts them.

S12–S15 types live in their own modules (out of scope for S0–S11).

Source: DATA_CONTRACTS.md §2, PIPELINE_STAGES.md §11, §13
Owner: Pipeline / Stage Outputs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# S1 — Normalized Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizedInput:
    """
    Output of S1 — the normalized/sanitized input.
    """
    sanitized_input: dict[str, Any]
    patterns_detected: tuple[str, ...] = field(default_factory=tuple)
    was_modified: bool = False
    has_critical_injection: bool = False
    timestamp: float = 0.0
    text: str = ""                                         # the user's message after S1: NFC, trimmed,
                                                           # references resolved, sanitized (what S2 reads)
    entities: dict[str, Any] = field(default_factory=dict)      # advisory: dates/emails/files/names
    references: dict[str, str] = field(default_factory=dict)    # reference as written -> what it stood for


# ---------------------------------------------------------------------------
# S2 — Intent Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntentResult:
    """
    Structured result of intent analysis from S2.
    """
    intent_type: str                       # e.g., "read", "write", "query", "compute"
    target_entities: tuple[str, ...]       # What the user wants to act on
    operations: tuple[str, ...]            # What operations are requested
    parameters: dict                       # Extracted parameters for capabilities
    is_workflow: bool = False              # True if multi-step workflow detected
    confidence: float = 1.0                # 0.0-1.0 confidence in decomposition
    raw_llm_output: str = ""               # Raw LLM response for audit
    attempt: int = 1                       # Which attempt (1 or 2)


# ---------------------------------------------------------------------------
# S3 — Capability Match
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityMatch:
    """
    Output of S3 — matched capability with relevance score.
    """
    capability_id: str
    name: str
    score: float
    risk_floor: float
    mutation_type: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    match_reasons: tuple[str, ...] = field(default_factory=tuple)
    estimated_cost_units: int = 1  # Budget cost per step (S6 reads this)
    risk_rule: float = 0.0  # Policy-derived risk (S5 uses in max formula)
    risk_implied: float = 0.0  # Context-implied risk (S5 uses in max formula)
    candidate_count: int = 1  # Distinct capabilities the registry returned (S4/S7 read this)





# ---------------------------------------------------------------------------
# S4 — Graph Analysis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphAnalysis:
    """
    Output of S4 — execution graph analysis result.
    """
    complexity: str                        # SINGLE_STEP, LINEAR, BRANCH, DAG, WORKFLOW
    is_workflow: bool
    candidate_count: int
    join_mode: str = "all"
    execution_steps: tuple[dict, ...] = field(default_factory=tuple)
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# S9 — Plan and Step (DATA_CONTRACTS.md §4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepOutputReference:
    """Reference to a specific output from a previous step."""
    step_id: str                    # Which step produced this output
    output_field: str               # Which field in the step's result
    field_type: str                 # Expected type for validation


@dataclass(frozen=True)
class StepParameterBinding:
    """Binds a step's input parameter to a previous step's output."""
    step_id: str                    # Target step
    parameter: str                  # Target parameter name
    source: StepOutputReference     # Where the value comes from


@dataclass(frozen=True)
class Step:
    """
    Single step in a Plan.

    Source: DATA_CONTRACTS.md §4
    """
    id: str                         # Step identifier
    kernel_op_id: str               # e.g. "ghl.contact_create"
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    mutation: str = "R"             # R | W | D | IRREVERSIBLE
    risk: float = 0.0               # 0.0–1.0 (consumed from S5 effective_risk)
    cost: int = 1                   # Budget cost units
    retry_policy: dict[str, Any] = field(default_factory=dict)
    inverse: str | None = None      # Inverse kernel_op_id for rollback
    timeout: int = 30               # Max seconds


@dataclass(frozen=True)
class Plan:
    """
    Execution plan — matches DATA_CONTRACTS.md §4 field for field.

    Immutable collections (R8): tuples instead of lists.
    """
    id: str                         # UUID — generated at S9
    steps: tuple[Step, ...] = field(default_factory=tuple)
    join_mode: str = "all"   # all | any | threshold
    budget_reserved: int = 1
    created_at: float = 0.0         # Unix timestamp (float)
    confirmations: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# S9 output wrapper — PlanCreationResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanCreationResult:
    """
    S9's complete output: the Plan plus its identity hashes.

    execution_id and plan_hash live beside the Plan, not inside it.
    This matches the spec's Plan (which has no execution_id or plan_hash)
    while giving downstream stages and S10 confirmation the values they need.
    """
    plan: Plan
    plan_hash: str                  # SHA-256 of the canonical Plan digest
    execution_id: str               # Distinct from request_id


# ---------------------------------------------------------------------------
# S11 — Validation Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    """
    Output of S11 — plan validation result.

    Source: PIPELINE_STAGES.md §13
    """
    is_valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
