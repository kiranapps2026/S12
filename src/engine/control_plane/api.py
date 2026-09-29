"""
Control Plane API routes — S0-S11 pipeline endpoints.

Source: COMPONENTS_BLUEPRINT.md, FINAL_ARCHITECTURE.md §36
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from db.session import get_db
from contracts.stage_registry import PIPELINE_SEQUENCE

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response Models ---

class ExecuteRequest(BaseModel):
    """Request to execute a pipeline."""
    input_data: dict[str, Any] = Field(..., description="Input data for execution")
    conversation_id: str | None = Field(None, description="Conversation ID for context")
    connection_id: str | None = Field(None, description="Connection ID for provider access")
    execution_mode: str = Field("standard", description="Execution mode: standard, workflow, adaptive")


class ExecuteResponse(BaseModel):
    """Response from pipeline execution."""
    execution_id: str
    trace_id: str
    status: str
    outcome: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    is_cordoned: bool = False
    cordon_reason: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    stages_loaded: int
    contracts_valid: bool


# --- Endpoints ---

@router.post("/execute", response_model=ExecuteResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_pipeline(
    request: ExecuteRequest,
    db=Depends(get_db),
) -> ExecuteResponse:
    """
    Execute the full pipeline (S0-S15).

    Creates an execution run and processes it through all stages.
    """
    import uuid
    import time

    from engine.control_plane.pipeline import PipelineEngine
    from engine.observability.ledger import EventLedger

    # Generate execution identifiers
    execution_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    ledger = EventLedger(db)
    pipeline = PipelineEngine(db, ledger)

    try:
        context = await pipeline.execute(execution_id, trace_id)
    except Exception as e:
        logger.error("Pipeline execution failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "PIPELINE_FAILED", "message": str(e)},
        )

    return ExecuteResponse(
        execution_id=execution_id,
        trace_id=trace_id,
        status="completed",
        outcome=context.error or "success",
        is_cordoned=context.is_cordoned,
        cordon_reason=context.cordon_reason,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check system health and contract validity."""
    from contracts.stage_registry import validate_stage_order

    try:
        validate_stage_order()
        contracts_valid = True
    except AssertionError:
        contracts_valid = False

    return HealthResponse(
        status="healthy",
        stages_loaded=len(PIPELINE_SEQUENCE),
        contracts_valid=contracts_valid,
    )


@router.get("/stages")
async def list_stages() -> dict[str, Any]:
    """List all pipeline stages."""
    from contracts.stage_registry import PIPELINE_SEQUENCE, StageContract, get_stage_registry

    return {
        "stages": [
            {
                "id": stage_id,
                "name": get_stage_registry()[stage_id].display_name,
                "description": get_stage_registry()[stage_id].description,
            }
            for stage_id in PIPELINE_SEQUENCE
        ],
        "cordon_points": ["S7", "S8", "S10", "S11"],
        "llm_call_stages": ["S2"],
    }
