"""PipelineRunner — the one execution path for S0–S11 (FINAL_ARCHITECTURE I-029).

The runner alone decides whether the run continues: it stops on any halt, suspends
when S10 is waiting for the user, and turns an unexpected exception into an ERROR
halt, so a failure can never be mistaken for success.
"""
from __future__ import annotations

import logging
import time

from supragents.contracts.entry import EntryRequest
from supragents.contracts.events import StageEvent
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import ConfirmationStatus, StageStatus
from supragents.observability.stage_log import log_stage
from supragents.pipeline.deps import PipelineDeps
from supragents.pipeline.result import RunOutcome, RunResult
from supragents.pipeline.stages import STAGES, StageHandler
from supragents.ports.runtime import EventSink

logger = logging.getLogger("supragents.pipeline")
_RESUME_STAGE = "S10"


class PipelineRunner:
    def __init__(self, deps: PipelineDeps, events: EventSink) -> None:
        self._deps = deps
        self._events = events

    async def run(self, entry: EntryRequest) -> RunResult:
        return await self._run_from(PipelineState(entry_request=entry), "S0")

    async def resume(self, suspended: RunResult, reply: ConfirmationReply) -> RunResult:
        """Continue a run that S10 suspended, with the user's reply."""
        if suspended.resume_state is None:
            raise ValueError("only a run awaiting confirmation can be resumed")
        return await self._run_from(suspended.resume_state.with_reply(reply), _RESUME_STAGE)

    async def _run_from(self, state: PipelineState, first_stage: str) -> RunResult:
        stage_ids = [stage_id for stage_id, _ in STAGES]
        for stage_id, handler in STAGES[stage_ids.index(first_stage):]:
            before = state
            state = await self._execute(stage_id, handler, state)
            if state.halt is not None:
                return RunResult(RunOutcome.STOPPED, state)
            if _awaiting_confirmation(stage_id, state):
                return RunResult(RunOutcome.AWAITING_CONFIRMATION, state, resume_state=before)
        return RunResult(RunOutcome.COMPLETED, state)

    async def _execute(self, stage_id: str, handler: StageHandler, state: PipelineState) -> PipelineState:
        started = time.monotonic()
        try:
            result = await handler(state, self._deps)
        except Exception as error:
            logger.exception("stage=%s raised %s", stage_id, type(error).__name__)
            result = state.halted(stage_id, StageStatus.ERROR, f"internal_error:{type(error).__name__}")
        event = _event(stage_id, result, (time.monotonic() - started) * 1000)
        log_stage(event)
        try:
            await self._events.emit(event)
        except Exception:
            logger.exception("stage=%s ledger write failed", stage_id)
            if result.halt is None:
                result = result.halted(stage_id, StageStatus.ERROR, "ledger_unavailable")
        return result


def _awaiting_confirmation(stage_id: str, state: PipelineState) -> bool:
    return (stage_id == _RESUME_STAGE
            and state.confirmation_check.status is ConfirmationStatus.PENDING)


def _event(stage_id: str, state: PipelineState, duration_ms: float) -> StageEvent:
    context = state.execution_context
    halt = state.halt if state.halt is not None and state.halt.stage == stage_id else None
    return StageEvent(
        trace_id=context.trace_id if context else None,
        request_id=context.request_id if context else None,
        tenant_id=context.tenant_id if context else None,
        stage=stage_id,
        status=halt.status if halt else StageStatus.NORMAL,
        reason=halt.reason if halt else None,
        duration_ms=duration_ms,
    )
