"""Dead-letter retry (gate D5, §11; Appendix A.6).

A retry never re-executes a step: the run is terminal. What it may do is fixed by the record's ``retry_mode``:
``PROBE`` asks the provider probe only, ``VERIFY`` re-runs only the verification layers not yet PASS (never the probe,
never the adapter), ``NONE`` has no automatic retry (``start_retry`` refuses; the record leaves ``pending`` only by a
human resolution). An inconclusive answer returns the record to ``pending``; after ``max_retries`` it is abandoned with
outcome UNDETERMINED (the budget is then committed, conservative, D4).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from contracts.adapter_interface import ProbeOutcome
from contracts.execution_states import DeadLetterStatus as D
from contracts.execution_states import ResolutionOutcome as Resolution
from contracts.execution_states import RetryMode
from contracts.verification import Verdict

_EXECUTED = frozenset({ProbeOutcome.EXECUTED_SUCCESS, ProbeOutcome.EXECUTED_FAILURE})


async def retry_dead_letter(tenant_id: str, dead_letter_id: str, *, dead_letters,
                            probe: Callable[[object], Awaitable[ProbeOutcome]],
                            reverify: Callable[[object], Awaitable[str]]) -> str:
    """One retry. Returns the record's status afterwards. ``probe`` and ``reverify`` receive the DeadLetterRecord."""
    record = await dead_letters.start_retry(tenant_id, dead_letter_id)      # NONE raises here, nothing written
    outcome = None
    try:
        if record.retry_mode == RetryMode.PROBE:
            answer = await probe(record)
            if answer in _EXECUTED:
                outcome = Resolution.EXECUTED
            elif answer == ProbeOutcome.NOT_EXECUTED:
                outcome = Resolution.NOT_EXECUTED
        else:
            verdict = await reverify(record)
            if verdict in (Verdict.PASS, Verdict.FAIL):
                outcome = Resolution.EXECUTED          # the operation ran; the verdict is about its effect
    except Exception:  # noqa: BLE001 — an answer that cannot be had is inconclusive
        outcome = None
    if outcome is not None:
        await dead_letters.resolve(tenant_id, dead_letter_id, outcome)
        return D.RESOLVED
    if record.retry_count + 1 >= record.max_retries:
        await dead_letters.abandon(tenant_id, dead_letter_id, Resolution.UNDETERMINED)
        return D.ABANDONED
    await dead_letters.retry_inconclusive(tenant_id, dead_letter_id)
    return D.PENDING
