"""
S3 Capability Discovery — find registered capabilities matching the intent.

Source: FINAL_ARCHITECTURE.md §11, §14, RUNBOOK R-Q/R-U
Owner: S3 / Capability Discovery

Candidates come ONLY from the capability registry (injected). Nothing the LLM returned
(IntentResult.parameters) can add, remove or describe a capability: risk, mutation and
cost are registry facts (A4). The LLM output is used only to score.
"""
from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.capability import CapabilityMetadata, CapabilityRegistry
from contracts.stage_outputs import CapabilityMatch as CapabilityMatchOutput
from contracts.stage_registry import StageStatus
from constants import MUTATION_READ

logger = logging.getLogger(__name__)

NO_CAPABILITY = "no_capability"
NO_MATCH_ID = "none"


def _score_capability(
    capability: CapabilityMetadata,
    intent_ops: set[str],
    intent_text: str,
) -> CapabilityMatchOutput:
    """Score a capability against the intent. Deterministic — no LLM calls."""
    score = 0.0
    reasons: list[str] = []

    matching_ops = intent_ops & set(capability.tags)
    if matching_ops:
        score += 0.5
        reasons.append(f"operation_match: {sorted(matching_ops)}")

    words = intent_text.split()
    if any(word in capability.name.lower() for word in words):
        score += 0.3
        reasons.append("name_match")
    if any(word in capability.description.lower() for word in words):
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
        risk_rule=capability.risk_rule,
        risk_implied=capability.risk_implied,
    )


async def handle(state: PipelineState, registry: CapabilityRegistry | None) -> PipelineState:
    """
    S3 handler: discover, score and rank capabilities from the registry.

    Writes the best match with `candidate_count` = number of distinct active capabilities
    the registry returned. No candidates -> a "none" placeholder and CLARIFY no_capability.
    A registry failure propagates (the runner records ERROR); it is never papered over.
    """
    intent = state.intent_result
    ctx = state.execution_context
    if intent is None or ctx is None:
        raise ValueError("S3 requires S0 and S2 outputs")
    if registry is None:
        return state.with_status(StageStatus.DENY, "capability_registry_unavailable")

    intent_ops = set(intent.operations)
    intent_text = " ".join(str(v) for v in (intent.parameters or {}).values()).lower()

    discovered = await registry.discover(
        {"intent_type": intent.intent_type, "operations": tuple(intent.operations),
         "text": intent_text},
        ctx.tenant_id,
    )

    # Deduplicate by capability_id (best score wins); inactive capabilities never match.
    best: dict[str, CapabilityMatchOutput] = {}
    for cap in discovered:
        if not cap.is_active:
            continue
        scored = _score_capability(cap, intent_ops, intent_text)
        if cap.capability_id not in best or scored.score > best[cap.capability_id].score:
            best[cap.capability_id] = scored

    if not best:
        logger.warning("S3: no capability candidates")
        state = state.with_stage_output("S3", CapabilityMatchOutput(
            capability_id=NO_MATCH_ID, name=NO_MATCH_ID, score=0.0, risk_floor=1.0,
            mutation_type=MUTATION_READ, candidate_count=0,
        ))
        return state.with_status(StageStatus.CLARIFY, NO_CAPABILITY)

    ranked = sorted(best.values(), key=lambda m: (-m.score, m.capability_id))
    top = CapabilityMatchOutput(**{**ranked[0].__dict__, "candidate_count": len(ranked)})
    logger.info("S3 scored %d capabilities (top score: %.2f)", len(ranked), top.score)
    return state.with_stage_output("S3", top)
