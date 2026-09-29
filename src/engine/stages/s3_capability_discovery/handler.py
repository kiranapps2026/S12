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


async def _best_match(registry: CapabilityRegistry, tenant_id: str, intent_type: str,
                      operations: tuple[str, ...], parameters: dict) -> CapabilityMatchOutput | None:
    """The top-ranked active capability for one intent, with `candidate_count` set; None if the
    registry offers no candidate. A registry failure propagates."""
    intent_ops = set(operations) | {intent_type}
    intent_text = " ".join(str(v) for v in (parameters or {}).values()).lower()
    discovered = await registry.discover(
        {"intent_type": intent_type, "operations": tuple(operations), "text": intent_text}, tenant_id)

    # Deduplicate by capability_id (best score wins); inactive capabilities never match.
    best: dict[str, CapabilityMatchOutput] = {}
    for cap in discovered:
        if not cap.is_active:
            continue
        scored = _score_capability(cap, intent_ops, intent_text)
        if cap.capability_id not in best or scored.score > best[cap.capability_id].score:
            best[cap.capability_id] = scored
    if not best:
        return None
    ranked = sorted(best.values(), key=lambda m: (-m.score, m.capability_id))
    logger.info("S3 scored %d capabilities (top score: %.2f)", len(ranked), ranked[0].score)
    return CapabilityMatchOutput(**{**ranked[0].__dict__, "candidate_count": len(ranked)})


def _none_match() -> CapabilityMatchOutput:
    return CapabilityMatchOutput(
        capability_id=NO_MATCH_ID, name=NO_MATCH_ID, score=0.0, risk_floor=1.0,
        mutation_type=MUTATION_READ, candidate_count=0)


async def handle(state: PipelineState, registry: CapabilityRegistry | None) -> PipelineState:
    """
    S3 handler: discover, score and rank capabilities from the registry.

    One-intent plan: writes the best match with `candidate_count` = number of distinct active
    capabilities the registry returned. Several intents (M2a, R-AB): one match per intent, written
    as `capability_matches` (the singular field stays None). No candidates for any intent -> a
    "none" placeholder and CLARIFY no_capability. A registry failure propagates (the runner records
    ERROR); it is never papered over.
    """
    intent = state.intent_result
    ctx = state.execution_context
    if intent is None or ctx is None:
        raise ValueError("S3 requires S0 and S2 outputs")
    if registry is None:
        return state.with_status(StageStatus.DENY, "capability_registry_unavailable")

    if len(intent.steps) > 1:
        matches: list[CapabilityMatchOutput] = []
        for step in intent.steps:
            match = await _best_match(registry, ctx.tenant_id, step.intent, (step.intent,), step.parameters)
            matches.append(match if match is not None else _none_match())
        state = state.with_stage_output("S3", capability_matches=tuple(matches))
        if any(m.candidate_count == 0 for m in matches):
            logger.warning("S3: no capability candidates for a step")
            return state.with_status(StageStatus.CLARIFY, NO_CAPABILITY)
        return state

    top = await _best_match(registry, ctx.tenant_id, intent.intent_type, tuple(intent.operations),
                            intent.parameters)
    if top is None:
        logger.warning("S3: no capability candidates")
        state = state.with_stage_output("S3", _none_match())
        return state.with_status(StageStatus.CLARIFY, NO_CAPABILITY)
    return state.with_stage_output("S3", top)
