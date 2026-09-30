"""
Canonical Pipeline Stage Registry — SINGLE SOURCE OF TRUTH for all S0–S15 stage definitions.

This module is the authoritative reference for:
- Stage IDs (S0–S15)
- Stage names (snake_case, matching FINAL_ARCHITECTURE.md)
- Stage responsibilities
- Cordon points
- Allowed callers
- LLM call flags
- Output contracts

No other module may define, rename, or reorder stages.
All documentation, tests, CI checks, and tracing metadata derive from this registry.

Source of truth: FINAL_ARCHITECTURE.md §11 "The 16-Stage Pipeline"
"""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass, field
from typing import FrozenSet, Sequence


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Plane(enum.StrEnum):
    """The four planes of the three-plane execution model."""
    CONTROL = "control"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    RESPONSE = "response"


class StageOutcome(enum.StrEnum):
    """Possible outcomes after a stage completes."""
    CONTINUE = "continue"          # Proceed to next stage
    CORDON = "cordon"              # Short-circuit: stop execution
    RETRY = "retry"                # Retry this stage
    DELEGATE = "delegate"          # Delegate to another stage/plane
    FAILED = "failed"              # Terminal failure
    COMPLETED = "completed"        # Successful completion (for terminal stages)


class StageStatus(enum.StrEnum):
    """
    Canonical stage completion status (DATA_CONTRACTS.md §3).

    This is the authority on whether a stage succeeded, was denied,
    needs clarification, or encountered an error. StageOutcome is an
    internal routing enum used by the pipeline runner; it is NOT canonical.
    """
    NORMAL = "NORMAL"              # Stage completed normally, continue pipeline
    CLARIFY = "CLARIFY"            # Stage needs human clarification before proceeding
    DENY = "DENY"                  # Stage rejected execution — do not proceed
    ERROR = "ERROR"                # Stage encountered an unexpected error
    PROBE = "PROBE"                # Stage outcome UNKNOWN — requires probing before decision


# ---------------------------------------------------------------------------
# Mapping: StageOutcome (routing) → StageStatus (canonical)
# ---------------------------------------------------------------------------

OUTCOME_TO_STATUS: types.MappingProxyType = types.MappingProxyType({
    StageOutcome.CONTINUE: StageStatus.NORMAL,
    StageOutcome.CORDON: StageStatus.DENY,
    StageOutcome.RETRY: StageStatus.ERROR,
    StageOutcome.DELEGATE: StageStatus.CLARIFY,
    StageOutcome.FAILED: StageStatus.ERROR,
    StageOutcome.COMPLETED: StageStatus.NORMAL,
})


# ---------------------------------------------------------------------------
# Stage Contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageContract:
    """
    Immutable contract for a single pipeline stage.

    This is the canonical definition. No other module may define stages
    independently. All stage-specific logic must reference this contract.
    """
    stage_id: str                   # "S0" .. "S15"
    name: str                       # snake_case name, matches FINAL_ARCHITECTURE.md
    display_name: str               # Human-readable name
    plane: Plane                    # Which plane this stage belongs to
    description: str                # What this stage does
    responsibilities: tuple[str, ...]  # What this stage is responsible for
    input_contract: str             # What this stage expects as input
    output_contract: str            # What this stage produces
    is_cordon: bool = False         # Can this stage short-circuit execution?
    cordon_outcome: str | None = None  # What outcome a cordon produces
    calls_llm: bool = False         # Does this stage make an LLM call?
    mutates_state: bool = True      # Does this stage mutate execution state?
    allowed_callers: FrozenSet[str] = field(default_factory=frozenset)
    forbidden_duplicates: FrozenSet[str] = field(default_factory=frozenset)
    test_categories: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Canonical Stage Definitions — 16 stages S0–S15
# Source: FINAL_ARCHITECTURE.md §11
# ---------------------------------------------------------------------------
#
# IMPORTANT: These names and responsibilities are the authoritative definitions.
# Any discrepancy between this registry and documentation is a defect in the
# documentation.
#
# The pipeline sequence is:
#   S0 (Entry/Parse) → S1 (Normalize) → S2 (Intent Analysis) →
#   S3 (Capability Discovery) → S4 (Graph Classification) →
#   S5 (Provider Resolution) → S6 (Task Profile Assembly) →
#   S7 (Path Routing) → S8 (Safety Gate) → S9 (Plan Creation) →
#   S10 (Confirmation) → S11 (Plan Validation) →
#   S12 (Execute) → S13 (Validate Result) → S14 (Dead Letter) →
#   S15 (Response Formatting)
# ---------------------------------------------------------------------------

# Control Plane Stages -------------------------------------------------------

S0 = StageContract(
    stage_id="S0",
    name="entry_parse",
    display_name="Entry/Parse",
    plane=Plane.CONTROL,
    description="Parse incoming request, extract identity, trace, and context from entry point.",
    responsibilities=(
        "Parse incoming request (API, webhook, schedule, MCP)",
        "Extract or generate trace_id (UUID v4)",
        "Extract or generate request_id (UUID v4, serves as IdempotencyKey)",
        "Extract conversation_id from entry context",
        "Extract connection_id from request metadata",
        "Create ExecutionContext (frozen dataclass)",
        "Validate tenant identification",
        "Assign monotonic timestamp (server-authoritative)",
        "Initialize ExecutionLedger with entry record",
    ),
    input_contract="Raw request (JSON, webhook payload, schedule trigger, MCP call)",
    output_contract="ExecutionContext (frozen, immutable after creation)",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"gateway", "api_server", "webhook_handler", "scheduler", "mcp_server"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "processor"}),
    test_categories=("pipeline-stages", "identity-creation", "idempotency"),
)

S1 = StageContract(
    stage_id="S1",
    name="normalize",
    display_name="Normalize",
    plane=Plane.CONTROL,
    description="Normalize and sanitize all inputs. Detect injection attacks.",
    responsibilities=(
        "Apply DataSanitizer to all text inputs",
        "Detect injection patterns (SQL, prompt injection, code injection, etc.)",
        "Apply severity classification and action mapping",
        "Normalize parameter formats",
        "Validate parameter types against capability schemas",
        "Reject or sanitize malicious input",
    ),
    input_contract="ExecutionContext with raw user input",
    output_contract="ExecutionContext with sanitized parameters",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S0", "gateway"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "injection-defense", "security-boundaries"),
)

S2 = StageContract(
    stage_id="S2",
    name="intent_analysis",
    display_name="Intent Analysis",
    plane=Plane.CONTROL,
    description="The ONLY unconditional LLM call. Decompose user intent into structured intent object.",
    responsibilities=(
        "Call LLM with sanitized intent (max 2 attempts: primary + retry)",
        "Decompose user intent into structured Intent object",
        "Identify target entities and operations",
        "Determine if task is single-step or multi-step (WORKFLOW detection)",
        "Extract parameters for capability matching",
        "Record LLM usage for billing",
        "Produce IntentResult",
    ),
    input_contract="ExecutionContext with sanitized parameters",
    output_contract="IntentResult (structured intent with entities, operations, parameters)",
    calls_llm=True,
    mutates_state=True,
    allowed_callers=frozenset({"S1"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "S4", "S5"}),
    test_categories=("pipeline-stages", "llm-calls", "billing"),
)

S3 = StageContract(
    stage_id="S3",
    name="capability_discovery",
    display_name="Capability Discovery",
    plane=Plane.CONTROL,
    description="Discover available capabilities matching the decomposed intent.",
    responsibilities=(
        "Query Capability Registry for matching capabilities",
        "Score capabilities against intent parameters",
        "Return ranked list of candidate capabilities",
        "Filter by tenant capability grants (RLS)",
        "Include capability metadata (risk, cost, mutation type, provider requirements)",
    ),
    input_contract="IntentResult",
    output_contract="List[CapabilityMetadata] — ranked candidate capabilities",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S2"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "S5"}),
    test_categories=("pipeline-stages", "capability-registry"),
)

S4 = StageContract(
    stage_id="S4",
    name="graph_classification",
    display_name="Graph Classification",
    plane=Plane.CONTROL,
    description="Classify execution graph complexity and determine decomposition strategy.",
    responsibilities=(
        "Analyze dependency graph of required operations",
        "Classify complexity: SINGLE_STEP, LINEAR, BRANCH, DAG, WORKFLOW",
        "Determine if multi-step decomposition is required",
        "Build step dependency graph for multi-step plans",
        "Define param bindings between steps (step-2 params from step-1 output)",
        "Produce ExecutionGraph",
    ),
    input_contract="IntentResult + CapabilityMetadata candidates",
    output_contract="ExecutionGraph (step dependency graph with param bindings)",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S3"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "graph-classification"),
)

S5 = StageContract(
    stage_id="S5",
    name="provider_resolution",
    display_name="Provider Resolution",
    plane=Plane.CONTROL,
    description="Resolve capabilities to specific provider adapters. Freeze binding.",
    responsibilities=(
        "Resolve each step to a specific provider adapter",
        "Apply selection criteria: capability match, health, locality score",
        "Compute effective_risk = max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)",
        "Create FrozenBindingIdentity (immutable after this point)",
        "Capture policy versions in FrozenBindingIdentity",
        "Set selection_rank for tie-breaking",
        "Resolve is NOT re-run during failover",
    ),
    input_contract="ExecutionGraph + CapabilityMetadata",
    output_contract="FrozenBindingIdentity (immutable, sole downstream resolution artifact)",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S4"}),
    forbidden_duplicates=frozenset({"S6", "adapter", "worker", "failover"}),
    test_categories=("pipeline-stages", "resolution", "risk-calculation", "frozen-binding"),
)

S6 = StageContract(
    stage_id="S6",
    name="task_profile_assembly",
    display_name="Task Profile Assembly",
    plane=Plane.CONTROL,
    description="Assemble the complete task profile from FrozenBindingIdentity.",
    responsibilities=(
        "Read FrozenBindingIdentity (does NOT compute risk — risk is already frozen)",
        "Assemble TaskProfile with all execution parameters",
        "Include provider, adapter_class, capability_id, kernel_op_id",
        "Include effective_risk, mutation_type, cost estimates",
        "Include timeout, retry_policy, budget requirements",
        "Build complete execution plan with step sequence",
        "Produce SafetyResult with mutation classification",
    ),
    input_contract="FrozenBindingIdentity",
    output_contract="TaskProfile + SafetyResult + ExecutionPlan",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S5"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "task-profile", "safety-classification"),
)

# Cordon Points --------------------------------------------------------------

S7 = StageContract(
    stage_id="S7",
    name="path_routing",
    display_name="Path Routing",
    plane=Plane.CONTROL,
    description="Determine execution path. Route or terminate based on viability.",
    responsibilities=(
        "Evaluate execution path viability",
        "Route to STANDARD, WORKFLOW, or EMERGENCY path",
        "Apply path decision rules (STANDARD/WORKFLOW/EMERGENCY)",
        "Cordon if path is not viable",
    ),
    input_contract="TaskProfile + SafetyResult",
    output_contract="PathDecision",
    is_cordon=True,
    cordon_outcome="FAILED",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S6"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "cordon-points", "path-routing"),
)

S8 = StageContract(
    stage_id="S8",
    name="safety_gate",
    display_name="Safety Gate",
    plane=Plane.CONTROL,
    description="Enforce mutation safety. Pre-execution budget precheck. Confirmation checkpoint.",
    responsibilities=(
        "Run MutationSafetyGate checks",
        "Evaluate mutation safety (READ/IDEMPOTENT_WRITE/NON_IDEMPOTENT_WRITE/DELETE/IRREVERSIBLE)",
        "Precheck budget availability (NO reservation at S8 — reservation at S12 only)",
        "Apply safety gate rules (KILL_SWITCH, MAX_RETRIES, CONFIRMATION_REQUIRED)",
        "Cordon if safety gate fails",
        "Prepare confirmation if required",
    ),
    input_contract="TaskProfile + PathDecision",
    output_contract="SafetyResult (confirmed/rejected)",
    is_cordon=True,
    cordon_outcome="DEAD_LETTER",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S7"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "S10"}),
    test_categories=("pipeline-stages", "cordon-points", "mutation-safety"),
)

S9 = StageContract(
    stage_id="S9",
    name="plan_creation",
    display_name="Plan Creation",
    plane=Plane.CONTROL,
    description="Create the execution plan with all steps, parameters, and binding.",
    responsibilities=(
        "Create ExecutionPlan with ordered steps",
        "Bind each step to FrozenBindingIdentity",
        "Set step parameters from IntentResult",
        "Define step dependencies for multi-step plans",
        "Set step timeouts based on TaskProfile",
        "Assign retry_policy per step",
        "Hash plan for integrity verification",
    ),
    input_contract="TaskProfile + SafetyResult",
    output_contract="ExecutionPlan (hashable, frozen)",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S8"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "plan-creation"),
)

S10 = StageContract(
    stage_id="S10",
    name="confirmation",
    display_name="Confirmation",
    plane=Plane.CONTROL,
    description="Present D/IRREVERSIBLE operations to user for explicit approval.",
    responsibilities=(
        "Scan plan for D/IRREVERSIBLE mutations",
        "Generate confirmation token (single-use, 5-min expiry)",
        "Build confirmation message listing exact operations",
        "Wait for user callback (YES/NO/MODIFY)",
        "Consume token atomically on confirmation",
        "YES → S11, NO → S15, expired → S15",
        "Confirmation is CONSUMED at S10, not S12",
    ),
    input_contract="Plan + ExecutionContext",
    output_contract="Confirmation (consumed at S10) or CANCELLED signal",
    is_cordon=True,
    cordon_outcome="CANCELLED",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S9"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "S12"}),
    test_categories=("pipeline-stages", "cordon-points", "hitl-confirmation"),
)

S11 = StageContract(
    stage_id="S11",
    name="plan_validation",
    display_name="Plan Validation",
    plane=Plane.CONTROL,
    description="Final validation. Verify S9 plan_hash. Freeze ExecutionManifest.",
    responsibilities=(
        "Verify S9-authoritative plan_hash against canonical plan representation",
        "Validate plan completeness (all steps have bindings, all params valid)",
        "Create ExecutionManifest with all version stamps",
        "Produce ValidationResult (is_valid + failed_check + reason)",
        "Persist frozen manifest to execution_manifests table",
        "Lock manifest — read-only for S12+",
        "Cordon with StageStatus.DENY if authorization fails",
    ),
    input_contract="Plan + Confirmation",
    output_contract="ExecutionManifest (frozen, written to DB) + ValidationResult",
    is_cordon=True,
    cordon_outcome="FAILED",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S10"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "S0"}),
    test_categories=("pipeline-stages", "cordon-points", "authorization", "execution-manifest"),
)

# Execution Plane ------------------------------------------------------------

S12 = StageContract(
    stage_id="S12",
    name="execute",
    display_name="Execute with Reliability Guard",
    plane=Plane.EXECUTION,
    description="Execute the plan with full reliability guard. Admission control → Select → Lease → Execute → Checkpoint → Verify → Commit/DLQ.",
    responsibilities=(
        "Run 11 admission gates BEFORE any resource acquisition",
        "Select worker based on FrozenBindingIdentity",
        "Acquire execution lease (atomic, monotonic)",
        "Reserve budget (S12 ONLY — S8 is precheck only)",
        "Execute steps through adapter (5-layer reliability guard)",
        "Handle UNKNOWN outcomes (probe before commit)",
        "Checkpoint execution state",
        "Commit budget on success, release on failure",
        "Route failures to Dead Letter Queue",
    ),
    input_contract="ExecutionManifest",
    output_contract="ExecutionResult + LedgerEvents",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S11"}),
    forbidden_duplicates=frozenset({"adapter", "worker", "direct_call"}),
    test_categories=("pipeline-stages", "reliability", "budget", "lease", "adapter-contracts"),
)

# Verification Plane ---------------------------------------------------------

S13 = StageContract(
    stage_id="S13",
    name="validate_result",
    display_name="Validate Result",
    plane=Plane.VERIFICATION,
    description="Independent verification of execution outcome. Progressive verification layers.",
    responsibilities=(
        "Run 6 progressive verification layers: SCHEMA, DETERMINISTIC, PROVIDER_STATE, SEMANTIC, BUSINESS_RULE, HUMAN",
        "Verifier independently observes provider state (NOT adapter self-report)",
        "Compare observation with expected state from ExecutionManifest",
        "Bounded: max 3 attempts, 1s apart, 5s timeout per attempt",
        "Observation failures (network, timeout) → UNKNOWN, never FAIL",
        "Only contradictory observation data → FAIL",
        "All layers must PASS for COMPLETED",
        "Any FAIL → DEAD_LETTER with full evidence",
    ),
    input_contract="ExecutionResult + ExecutionManifest",
    output_contract="VerificationResult (overall) + LayerResult per layer",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S12"}),
    forbidden_duplicates=frozenset({"adapter", "post_execution_ad_hoc"}),
    test_categories=("pipeline-stages", "verification", "unknown-paths", "failure-modes"),
)

S14 = StageContract(
    stage_id="S14",
    name="dead_letter",
    display_name="Dead Letter",
    plane=Plane.VERIFICATION,
    description="Process dead letter outcomes. Retry scheduler with mutation awareness.",
    responsibilities=(
        "Route failures to Dead Letter Queue",
        "Block IRREVERSIBLE mutations from retry",
        "Block non-idempotent mutations from retry",
        "Schedule retry for idempotent failures",
        "Preserve full execution trace in DeadLetter record",
        "Allow manual replay from DLQ",
        "Emit DEAD_LETTER event to ledger",
    ),
    input_contract="ExecutionResult (FAILED/DEAD_LETTER)",
    output_contract="DeadLetter record + optional retry schedule",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S12", "S13"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "dlq-routing", "retry-paths", "failure-modes"),
)

# Response Plane -------------------------------------------------------------

S15 = StageContract(
    stage_id="S15",
    name="response_formatting",
    display_name="Response Formatting",
    plane=Plane.RESPONSE,
    description="Format and deliver response to the caller.",
    responsibilities=(
        "Format response for entry channel (Telegram, API, webhook, MCP)",
        "Include execution status, outcome, and summary",
        "Include error details for failures",
        "Include verification evidence for completed tasks",
        "Emit response event to ledger",
        "Update execution_runs with final status",
    ),
    input_contract="ExecutionResult + VerificationResult",
    output_contract="Formatted response for caller",
    calls_llm=False,
    mutates_state=True,
    allowed_callers=frozenset({"S13", "S14"}),
    forbidden_duplicates=frozenset({"adapter", "worker"}),
    test_categories=("pipeline-stages", "response-formatting"),
)


# Build immutable registry after all S0–S15 are defined.
# MappingProxyType is the public interface; the inner dict is never exposed.
STAGE_REGISTRY: types.MappingProxyType[str, StageContract] = types.MappingProxyType({
    "S0": S0, "S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5,
    "S6": S6, "S7": S7, "S8": S8, "S9": S9, "S10": S10, "S11": S11,
    "S12": S12, "S13": S13, "S14": S14, "S15": S15,
})

# ---------------------------------------------------------------------------
# Pipeline Sequence
# ---------------------------------------------------------------------------

PIPELINE_SEQUENCE: tuple[str, ...] = tuple(STAGE_REGISTRY.keys())
"""Canonical pipeline sequence: S0 → S1 → ... → S15"""

CORDON_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.is_cordon
)
"""Stages that can short-circuit execution: S7, S8, S10, S11"""

LLM_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.calls_llm
)
"""Stages that make LLM calls: S2"""

CONTROL_PLANE_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.plane == Plane.CONTROL
)
"""Control plane stages: S0–S11"""

EXECUTION_PLANE_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.plane == Plane.EXECUTION
)
"""Execution plane stages: S12"""

VERIFICATION_PLANE_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.plane == Plane.VERIFICATION
)
"""Verification plane stages: S13, S14"""

RESPONSE_PLANE_STAGES: FrozenSet[str] = frozenset(
    stage.stage_id for stage in STAGE_REGISTRY.values() if stage.plane == Plane.RESPONSE
)
"""Response plane stages: S15"""


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_stage(stage_id: str) -> StageContract:
    """Get the canonical contract for a stage. Raises KeyError if not found."""
    if stage_id not in STAGE_REGISTRY:
        raise KeyError(
            f"Unknown stage '{stage_id}'. "
            f"Valid stages: {sorted(STAGE_REGISTRY.keys())}"
        )
    return STAGE_REGISTRY[stage_id]


def get_next_stage(stage_id: str) -> str | None:
    """Get the next stage in the pipeline. Returns None for S15."""
    idx = PIPELINE_SEQUENCE.index(stage_id)
    if idx + 1 < len(PIPELINE_SEQUENCE):
        return PIPELINE_SEQUENCE[idx + 1]
    return None


def get_plane_stages(plane: Plane) -> tuple[StageContract, ...]:
    """Get all stages in a plane, in pipeline order."""
    return tuple(
        STAGE_REGISTRY[sid] for sid in PIPELINE_SEQUENCE
        if STAGE_REGISTRY[sid].plane == plane
    )


def validate_stage_order() -> None:
    """
    Validate the stage registry at import time.

    This catches:
    - Missing stages
    - Duplicate stage IDs
    - Out-of-order stages
    """
    expected_ids = [f"S{i}" for i in range(16)]
    actual_ids = list(STAGE_REGISTRY.keys())

    assert actual_ids == expected_ids, (
        f"Stage order mismatch. Expected {expected_ids}, got {actual_ids}"
    )

    # Verify cordon stages
    assert CORDON_STAGES == frozenset({"S7", "S8", "S10", "S11"}), (
        f"Cordon stages mismatch: {CORDON_STAGES}"
    )

    # Verify LLM stages
    assert LLM_STAGES == frozenset({"S2"}), (
        f"LLM stages mismatch: {LLM_STAGES}"
    )


# Validate on import
validate_stage_order()
