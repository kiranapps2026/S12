"""
S3 Capability Discovery — find capabilities matching the decomposed intent.

Source: FINAL_ARCHITECTURE.md §11, §14
Owner: S3 / Capability Discovery
"""

from __future__ import annotations

import logging
from typing import Any

from contracts.pipeline_state import PipelineState
from contracts.capability import CapabilityMetadata
from contracts.stage_outputs import CapabilityMatch as CapabilityMatchOutput
from constants import MUTATION_READ, MUTATION_WRITE, MUTATION_DELETE, MUTATION_IRREVERSIBLE

logger = logging.getLogger(__name__)


def _score_capability(
    capability: CapabilityMetadata,
    intent_ops: set[str],
    intent_text: str,
) -> CapabilityMatchOutput:
    """Score a capability against intent parameters. Deterministic — no LLM calls."""
    score = 0.0
    reasons: list[str] = []

    cap_tags = set(capability.tags)
    matching_ops = intent_ops & cap_tags
    if matching_ops:
        score += 0.5
        reasons.append(f"operation_match: {matching_ops}")

    name_lower = capability.name.lower()
    if any(word in name_lower for word in intent_text.split()):
        score += 0.3
        reasons.append("name_match")

    desc_lower = capability.description.lower()
    if any(word in desc_lower for word in intent_text.split()):
        score += 0.2
        reasons.append("description_match")

    return CapabilityMatchOutput(
        capability_id=capability.capability_id,
        name=capability.name,
        score=min(score, 1.0),
        risk_floor=capability.risk_floor,
        mutation_type=capability.mutation_type,
        tags=tuple(capability.tags),
        match_reasons=tuple(reasons),
        estimated_cost_units=capability.estimated_cost_units,
        risk_rule=getattr(capability, "risk_rule", 0.0),
        risk_implied=getattr(capability, "risk_implied", 0.0),
    )


def _build_capability_metadata(meta: dict[str, Any]) -> CapabilityMetadata:
    """Reconstruct CapabilityMetadata from a metadata dict."""
    return CapabilityMetadata(
        capability_id=meta["capability_id"],
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        namespace=meta.get("namespace", ""),
        input_schema=meta.get("input_schema", {}),
        output_schema=meta.get("output_schema", {}),
        risk_floor=meta.get("risk_floor", 0.0),
        mutation_type=meta.get("mutation_type", MUTATION_READ),
        tags=meta.get("tags", []),
        estimated_cost_units=meta.get("estimated_cost_units", 1),
        risk_rule=meta.get("risk_rule", 0.0),
        risk_implied=meta.get("risk_implied", 0.0),
    )


async def handle(state: PipelineState) -> PipelineState:
    """
    S3 handler: score and rank capability candidates.

    Reads intent from PipelineState.intent_result (S2 output), scores candidates
    deterministically. Candidates come from intent.parameters['candidates'] if
    provided (no metadata on ExecutionContext post-R0).
    Returns updated PipelineState with CapabilityMatch set.
    """
    intent_result = state.intent_result
    if intent_result is None:
        raise ValueError("No IntentResult from S2")

    intent = intent_result
    intent_ops = set(intent.operations)
    intent_params = intent.parameters
    if "operations" in intent_params:
        intent_ops.update(intent_params["operations"])
    intent_text = " ".join(str(v) for v in intent_params.values()).lower()

    # Candidates come from intent.parameters (not ExecutionContext.metadata — R1/B5)
    candidates_meta = intent_params.get("candidates", [])
    candidates = [_build_capability_metadata(c) for c in candidates_meta]

    if not candidates:
        logger.warning("S3: no capability candidates")
        return state.with_stage_output("S3", CapabilityMatchOutput(
            capability_id="none",
            name="none",
            score=0.0,
            risk_floor=1.0,
            mutation_type=MUTATION_READ,
        ))

    scored = [_score_capability(c, intent_ops, intent_text) for c in candidates]
    scored.sort(key=lambda m: m.score, reverse=True)

    logger.info(
        "S3 scored %d capabilities (top score: %.2f)",
        len(scored), scored[0].score if scored else 0.0,
    )

    top = scored[0]
    return state.with_stage_output("S3", top)
