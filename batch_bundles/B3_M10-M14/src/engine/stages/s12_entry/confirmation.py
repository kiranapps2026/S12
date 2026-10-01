"""S12 entry: the consumed confirmation must belong to the run being admitted (gate C20).

S10 saves the confirmation before the run exists, so the store has no foreign key to execution_runs. S12 entry closes
that gap: when the plan needed a confirmation, its store row must be ``consumed`` and carry this run's execution_id,
plan_hash and tenant; otherwise the run is denied with ``confirmation_mismatch``. A store that cannot be read denies
with ``confirmation_unavailable`` (fail closed; ruling CONF-018). Nothing is written.
"""
from __future__ import annotations

import logging

from contracts.confirmation_record import ConsumedConfirmationReader
from contracts.execution_states import ConfirmationStatus
from contracts.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

CONFIRMATION_MISMATCH = "confirmation_mismatch"
CONFIRMATION_UNAVAILABLE = "confirmation_unavailable"


async def confirmation_denial(state: PipelineState, reader: ConsumedConfirmationReader | None) -> str | None:
    outcome = state.confirmation
    if outcome is None or not outcome.required:
        return None
    if outcome.confirmation is None or state.plan is None or state.execution_manifest is None \
            or state.execution_context is None:
        return CONFIRMATION_MISMATCH
    if reader is None:
        return CONFIRMATION_UNAVAILABLE
    try:
        row = await reader.read(outcome.confirmation.confirmation_id, tenant_id=state.execution_context.tenant_id)
    except Exception:  # noqa: BLE001 — fail closed
        logger.exception("S12 entry: confirmation store unavailable")
        return CONFIRMATION_UNAVAILABLE
    if (row is None or row.status != ConfirmationStatus.CONSUMED.value
            or row.execution_id != state.plan.execution_id
            or row.plan_hash != state.execution_manifest.plan_hash):
        return CONFIRMATION_MISMATCH
    return None
