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


def _build_execution_steps(step_count: int, complexity: str) -> tuple[dict, ...]:
    """Build a linear chain of `step_count` steps (one step when the graph is simple)."""
    count = 1 if complexity == "simple" else max(1, step_count)
    return tuple(
        {
            "step_id": f"step-{i + 1}",
            "params": {},
            "depends_on": [] if i == 0 else [f"step-{i}"],
            "retry_policy": {},
        }
        for i in range(count)
    )


def _build_dependencies(steps: tuple[dict, ...]) -> dict[str, tuple[str, ...]]:
    """Build dependencies map from execution_steps."""
    deps = {}
    for step in steps:
        deps[step["step_id"]] = tuple(step.get("depends_on", []))
    return deps


MAX_STEPS = 50  # sanity bound on the LLM-suggested step count


def _step_count(intent) -> int:
    """Step count suggested by S2. It shapes the plan only: risk, mutation and cost
    per step come from the frozen binding. Anything unusable counts as one step."""
    raw = (intent.parameters or {}).get("steps") if intent is not None else None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return 1
    return min(raw, MAX_STEPS)


async def handle(state: PipelineState) -> PipelineState:
    """
    S4 handler: classify execution graph shape (simple | chain | complex).

    1 step -> simple, 2-5 -> chain, 6+ -> complex (R-P / R-Q). The candidate count is
    S3's (registry-derived), never read from LLM output.
    """
    intent_result = state.intent_result
    capability_match = state.capability_match
    if intent_result is None or capability_match is None:
        raise ValueError("S4 requires S2 and S3 outputs")

    step_count = _step_count(intent_result)
    if step_count == 1:
        complexity = GraphComplexity.SINGLE_STEP
    elif step_count <= 5:
        complexity = GraphComplexity.LINEAR
    else:
        complexity = GraphComplexity.DAG
    is_workflow = step_count > 1 or bool(intent_result.is_workflow)

    execution_steps = _build_execution_steps(step_count, complexity)
    dependencies = _build_dependencies(execution_steps)

    logger.info("S4 classified graph: %s (workflow=%s, candidates=%d, steps=%d)",
                complexity, is_workflow, capability_match.candidate_count, len(execution_steps))

    return state.with_stage_output("S4", GraphAnalysis(
        complexity=complexity,
        is_workflow=is_workflow,
        candidate_count=capability_match.candidate_count,
        join_mode="all",
        execution_steps=execution_steps,
        dependencies=dependencies,
    ))
