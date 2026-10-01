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
    try:
        if record.retry_mode == RetryMode.PROBE:
            answer = await probe(record)
            try:
                probe_outcome = ProbeOutcome(answer)
            except ValueError:
                probe_outcome = None
            if probe_outcome in _EXECUTED or str(answer) in {e.name for e in _EXECUTED}:
                await dead_letters.resolve(tenant_id, dead_letter_id, Resolution.EXECUTED)
                return D.RESOLVED
            if probe_outcome == ProbeOutcome.NOT_EXECUTED or answer == "NOT_EXECUTED":
                await dead_letters.resolve(tenant_id, dead_letter_id, Resolution.NOT_EXECUTED)
                return D.RESOLVED
        elif record.retry_mode == RetryMode.VERIFY:
            verdict = await reverify(record)
            if verdict in (Verdict.PASS, Verdict.FAIL):
                await dead_letters.resolve(tenant_id, dead_letter_id, Resolution.EXECUTED)
                return D.RESOLVED
    except Exception:  # noqa: BLE001 — an answer that cannot be had is inconclusive
        pass
    if record.retry_count + 1 >= record.max_retries:
        await dead_letters.abandon(tenant_id, dead_letter_id, Resolution.UNDETERMINED)
        return D.ABANDONED
    await dead_letters.retry_inconclusive(tenant_id, dead_letter_id)
    return D.PENDING
