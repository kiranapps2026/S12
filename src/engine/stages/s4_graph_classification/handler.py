"""
S4 Graph Classification — classify execution graph complexity.

Source: FINAL_ARCHITECTURE.md §11, §15
Owner: S4 / Graph Classification
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.stage_registry import StageOutcome
from contracts.stage_outputs import GraphAnalysis

logger = logging.getLogger(__name__)


class GraphComplexity:
    """Execution graph complexity levels (R-P canonical values)."""
    SINGLE_STEP = "simple"
    LINEAR = "chain"
    BRANCH = "complex"
    DAG = "complex"
    WORKFLOW = "complex"


def _build_execution_steps(candidate_count: int, complexity: str) -> tuple[dict, ...]:
    """Build default execution_steps from candidate count and complexity."""
    if complexity == "simple":
        return ({"step_id": "step-1", "params": {}, "depends_on": [], "retry_policy": {}},)
    elif complexity == "chain":
        steps = []
        for i in range(max(1, candidate_count)):
            steps.append({
                "step_id": f"step-{i + 1}",
                "params": {},
                "depends_on": [] if i == 0 else [f"step-{i}"],
                "retry_policy": {},
            })
        return tuple(steps)
    else:
        # complex: produce 3 steps
        return (
            {"step_id": "step-1", "params": {}, "depends_on": [], "retry_policy": {}},
            {"step_id": "step-2", "params": {}, "depends_on": ["step-1"], "retry_policy": {}},
            {"step_id": "step-3", "params": {}, "depends_on": ["step-2"], "retry_policy": {}},
        )


def _build_dependencies(steps: tuple[dict, ...]) -> dict[str, tuple[str, ...]]:
    """Build dependencies map from execution_steps."""
    deps = {}
    for step in steps:
        deps[step["step_id"]] = tuple(step.get("depends_on", []))
    return deps


async def handle(state: PipelineState) -> PipelineState:
    """
    S4 handler: classify execution graph complexity.

    Reads intent_result (S2) and capability_match (S3) from PipelineState.
    Returns updated PipelineState with graph_analysis set (includes execution_steps).

    Graph shape is derived from IntentResult:
      - parameters["steps"] (explicit step count from mock LLM / real LLM)
      - is_workflow flag → always complex
      - step count: 1 → simple, 2-5 → chain, 6+ → complex
    """
    intent_result = state.intent_result
    capability_match = state.capability_match

    if intent_result is not None:
        is_workflow = intent_result.is_workflow
        intent_params = intent_result.parameters or {}
        explicit_steps = intent_params.get("steps")
    else:
        is_workflow = False
        explicit_steps = None

    # Count candidates (from S3's CapabilityMatch or list)
    candidate_count = 0
    if capability_match is not None:
        if isinstance(capability_match, list):
            candidate_count = len(capability_match)
        elif hasattr(capability_match, "capability_id"):
            candidate_count = 1

    # Derive complexity: explicit step count first, then candidate count
    if is_workflow:
        complexity = GraphComplexity.WORKFLOW  # "complex"
        step_count = max(explicit_steps or 3, 3)
    elif explicit_steps is not None:
        step_count = max(1, int(explicit_steps))
        if step_count == 1:
            complexity = GraphComplexity.SINGLE_STEP  # "simple"
        elif step_count <= 5:
            complexity = GraphComplexity.LINEAR  # "chain"
        else:
            complexity = GraphComplexity.DAG  # "complex"
    elif candidate_count == 0:
        complexity = GraphComplexity.SINGLE_STEP  # "simple"
        step_count = 1
    elif candidate_count == 1:
        complexity = GraphComplexity.LINEAR  # "chain"
        step_count = 1
    else:
        complexity = GraphComplexity.BRANCH  # "complex"
        step_count = candidate_count

    execution_steps = _build_execution_steps(step_count, complexity)
    dependencies = _build_dependencies(execution_steps)

    logger.info("S4 classified graph: %s (workflow=%s, candidates=%d, steps=%d)",
                complexity, is_workflow, candidate_count, len(execution_steps))

    output = GraphAnalysis(
        complexity=complexity,
        is_workflow=is_workflow,
        candidate_count=candidate_count,
        join_mode="all",
        execution_steps=execution_steps,
        dependencies=dependencies,
    )

    return state.with_stage_output("S4", output)
