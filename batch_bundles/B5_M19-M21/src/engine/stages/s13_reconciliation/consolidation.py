"""S13 consolidation table (gate §10 as corrected by C8; C13, C22, I13; ruling CONF-034).

Pure: from the steps' final states to the run's terminal state and outcome. CANCELLED and SKIPPED steps count as not
completed; a run with a CANCELLED step is never COMPLETED (I13). A step cancelled ``run_dead_lettered`` means the run
was dead-lettered (a DEAD_LETTER step, or a plan that failed its integrity check, CONF-034).
"""
from __future__ import annotations

from collections.abc import Iterable

from contracts.execution_states import ConsolidationOutcome as Outcome
from contracts.execution_states import ExecutionStatus as R
from contracts.execution_states import StepState as S
from contracts.execution_states import StepTerminalReason as T

TERMINAL_STEPS = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED, S.SKIPPED, S.DEAD_LETTER})


def consolidation_outcome(steps: Iterable[tuple[str, str | None]]) -> tuple[R, Outcome]:
    """``steps``: (status, terminal_reason) of every step. Raises ValueError while any step is not terminal."""
    steps = list(steps)
    if not steps or any(status not in TERMINAL_STEPS for status, _ in steps):
        raise ValueError("consolidation needs every step terminal")
    if any(status == S.DEAD_LETTER or (status == S.CANCELLED and reason == T.RUN_DEAD_LETTERED)
           for status, reason in steps):
        return R.DEAD_LETTER, Outcome.FAILURE
    completed = sum(1 for status, _ in steps if status == S.COMPLETED)
    unsuccessful = sum(1 for status, _ in steps if status in (S.FAILED, S.CANCELLED))
    if completed and not unsuccessful:
        return R.COMPLETED, Outcome.SUCCESS
    if completed:
        return R.PARTIAL, Outcome.PARTIAL
    return R.FAILED, Outcome.FAILURE
