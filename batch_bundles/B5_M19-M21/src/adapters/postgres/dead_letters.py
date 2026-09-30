"""Dead-letter records (gate §11, C21, C27, C29, D4, D5; Appendix A.6; invariants I11, I12).

A record is for review and evidence; it is not the step state DEAD_LETTER (§11). ``create`` writes one for an
execution (``origin = execution``) inside the run's fence; ``create_rollback`` writes one for a failed inverse of a
terminal run (``origin = rollback``, ``retry_mode = NONE``, C27), with no fence because the run has no owner any more.
Evidence is never empty (I11) and never holds provider bodies, exception text or credentials (§21 S6): callers pass
codes and counts. ``permanent`` and ``unknown_unresolved`` records raise an alert: a ``dead_letter_alert`` event in the
same transaction and an ERROR log line (§11; the delivery channel is out of scope).

Lifecycle moves are validated against Appendix A.6 and logged. A resolution changes only the record, the step's LOCKED
reservation (EXECUTED / UNDETERMINED / abandoned → COMMITTED, NOT_EXECUTED → RELEASED; C21, D4) and the ledger; it never
changes the run or the step (D4).
"""
from __future__ import annotations

import json
import logging
import types
import uuid
from dataclasses import dataclass

import asyncpg

from adapters.postgres.budget_reserver import settle_dead_letter_reservation
from adapters.postgres.database import Database
from adapters.postgres.execution_events import insert_event
from adapters.postgres.fencing import FenceHolder, fenced_write
from adapters.postgres.transition_log import log_transition
from contracts.execution_states import DeadLetterErrorType as ErrorType
from contracts.execution_states import DeadLetterOrigin as Origin
from contracts.execution_states import DeadLetterStatus as D
from contracts.execution_states import ReservationState as B
from contracts.execution_states import ResolutionOutcome as Resolution
from contracts.execution_states import RetryMode
from engine.stages.s12_execute import transitions

logger = logging.getLogger(__name__)

MACHINE = "dead_letter"
CREATED = "created"
ALERT_EVENT = "dead_letter_alert"
_ALERTING = frozenset({ErrorType.PERMANENT, ErrorType.UNKNOWN_UNRESOLVED})
_BUDGET = types.MappingProxyType({Resolution.EXECUTED: (B.COMMITTED, "dead_letter_resolved_executed"),
                                  Resolution.NOT_EXECUTED: (B.RELEASED, "dead_letter_resolved_not_executed"),
                                  Resolution.UNDETERMINED: (B.COMMITTED, "dead_letter_resolved_undetermined")})

_INSERT = ("INSERT INTO dead_letters (dead_letter_id, tenant_id, execution_id, step_id, kernel_op_id, reservation_id,"
           " attempt_id, episode_id, error, error_type, mutation_type, context, retry_mode, origin)"
           " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13, $14)")
_LOCK = ("SELECT d.*, r.trace_id FROM dead_letters d JOIN execution_runs r ON r.tenant_id = d.tenant_id"
         " AND r.execution_id = d.execution_id WHERE d.tenant_id = $1 AND d.dead_letter_id = $2 FOR UPDATE OF d")
_TRACE = "SELECT trace_id FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2"


@dataclass(frozen=True)
class DeadLetterRecord:
    dead_letter_id: str
    tenant_id: str
    execution_id: str
    step_id: str
    kernel_op_id: str
    reservation_id: str | None
    attempt_id: str | None
    episode_id: str | None
    error_type: str
    retry_mode: str
    origin: str
    status: str
    resolution_outcome: str | None
    retry_count: int
    max_retries: int
    evidence: dict


def _record(row) -> DeadLetterRecord:
    context = row["context"]
    return DeadLetterRecord(
        row["dead_letter_id"], row["tenant_id"], row["execution_id"], row["step_id"], row["kernel_op_id"],
        row["reservation_id"], row["attempt_id"], row["episode_id"], row["error_type"], row["retry_mode"],
        row["origin"], row["status"], row["resolution_outcome"], row["retry_count"], row["max_retries"],
        json.loads(context) if isinstance(context, str) else dict(context))


def _checked(error_type: str, retry_mode: str, error: str, evidence: dict) -> tuple[ErrorType, RetryMode]:
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("a dead letter needs evidence (I11)")
    if not error:
        raise ValueError("a dead letter needs an error code")
    return ErrorType(error_type), RetryMode(retry_mode)


class PostgresDeadLetters:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def _insert(self, c, *, tenant_id, execution_id, step_id, kernel_op_id, error_type, retry_mode, error,
                      evidence, reservation_id, attempt_id, episode_id, mutation, origin, runtime, token) -> str:
        transitions.validate(MACHINE, None, D.PENDING, reason=CREATED)
        dead_letter_id = str(uuid.uuid4())
        await c.execute(_INSERT, dead_letter_id, tenant_id, execution_id, step_id, kernel_op_id, reservation_id,
                        attempt_id, episode_id, error, error_type, mutation, json.dumps(evidence, sort_keys=True),
                        retry_mode, origin)
        await log_transition(c, tenant_id=tenant_id, machine=MACHINE, entity_id=dead_letter_id, from_state=None,
                             to_state=D.PENDING, reason=CREATED, runtime_instance_id=runtime, fence_token=token,
                             execution_id=execution_id)
        if error_type in _ALERTING:
            trace_id = await c.fetchval(_TRACE, tenant_id, execution_id)
            await insert_event(c, tenant_id=tenant_id, execution_id=execution_id, trace_id=trace_id, kind=ALERT_EVENT,
                               payload={"dead_letter_id": dead_letter_id, "error_type": str(error_type),
                                        "error": error}, step_id=step_id, runtime_instance_id=runtime,
                               fence_token=token)
            logger.error("dead letter alert", extra={"tenant_id": tenant_id, "execution_id": execution_id,
                                                     "step_id": step_id, "dead_letter_id": dead_letter_id,
                                                     "error_type": str(error_type), "trace_id": trace_id})
        return dead_letter_id

    async def create(self, holder: FenceHolder, *, step_id: str, kernel_op_id: str, error_type: str, retry_mode: str,
                     error: str, evidence: dict, reservation_id: str | None = None, attempt_id: str | None = None,
                     episode_id: str | None = None, mutation: str = "R") -> str:
        et, mode = _checked(error_type, retry_mode, error, evidence)

        async def write(c):
            return await self._insert(c, tenant_id=holder.tenant_id, execution_id=holder.execution_id,
                                      step_id=step_id, kernel_op_id=kernel_op_id, error_type=et, retry_mode=mode,
                                      error=error, evidence=evidence, reservation_id=reservation_id,
                                      attempt_id=attempt_id, episode_id=episode_id, mutation=mutation,
                                      origin=Origin.EXECUTION, runtime=holder.runtime_instance_id,
                                      token=holder.fence_token)
        return await fenced_write(self._db, holder, write)

    async def create_rollback(self, tenant_id: str, *, execution_id: str, step_id: str, kernel_op_id: str,
                              error_type: str, error: str, evidence: dict, mutation: str) -> str:
        et, _ = _checked(error_type, RetryMode.NONE, error, evidence)
        async with self._db.tenant_transaction(tenant_id) as c:
            return await self._insert(c, tenant_id=tenant_id, execution_id=execution_id, step_id=step_id,
                                      kernel_op_id=kernel_op_id, error_type=et, retry_mode=RetryMode.NONE,
                                      error=error, evidence=evidence, reservation_id=None, attempt_id=None,
                                      episode_id=None, mutation=mutation, origin=Origin.ROLLBACK, runtime=None,
                                      token=None)

    async def get(self, tenant_id: str, dead_letter_id: str) -> DeadLetterRecord | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await c.fetchrow(_LOCK.replace(" FOR UPDATE OF d", ""), tenant_id, dead_letter_id)
        return None if row is None else _record(row)

    async def _move(self, c: asyncpg.Connection, row, to: D, reason: str, *, outcome: Resolution | None = None,
                    retried: bool = False) -> None:
        transitions.validate(MACHINE, row["status"], to, reason=reason)
        if to in (D.RESOLVED, D.ABANDONED) and outcome is None:
            raise ValueError("a resolution needs its outcome (C21)")
        await c.execute("UPDATE dead_letters SET status = $3, resolved = $4, resolution_outcome = COALESCE($5,"
                        " resolution_outcome), retry_count = retry_count + $6, updated_at = now()"
                        " WHERE tenant_id = $1 AND dead_letter_id = $2", row["tenant_id"], row["dead_letter_id"], to,
                        to in (D.RESOLVED, D.ABANDONED), None if outcome is None else str(outcome), 1 if retried else 0)
        await log_transition(c, tenant_id=row["tenant_id"], machine=MACHINE, entity_id=row["dead_letter_id"],
                             from_state=row["status"], to_state=to, reason=reason, runtime_instance_id=None,
                             fence_token=None, execution_id=row["execution_id"])
        if to in (D.RESOLVED, D.ABANDONED) and row["reservation_id"] is not None:
            target, budget_reason = (_BUDGET[outcome] if to == D.RESOLVED
                                     else (B.COMMITTED, "dead_letter_abandoned"))
            await settle_dead_letter_reservation(c, tenant_id=row["tenant_id"], reservation_id=row["reservation_id"],
                                                 to=target, reason=budget_reason)

    async def _locked(self, c, tenant_id, dead_letter_id):
        row = await c.fetchrow(_LOCK, tenant_id, dead_letter_id)
        if row is None:
            raise LookupError(f"no dead letter {dead_letter_id}")
        return row

    async def start_retry(self, tenant_id: str, dead_letter_id: str) -> DeadLetterRecord:
        """pending → retrying; only for retry_mode PROBE or VERIFY (A.6, D5). NONE raises, nothing written."""
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await self._locked(c, tenant_id, dead_letter_id)
            if row["retry_mode"] not in (RetryMode.PROBE, RetryMode.VERIFY):
                raise ValueError(f"dead letter {dead_letter_id} has retry_mode {row['retry_mode']}: no retry (D5)")
            await self._move(c, row, D.RETRYING, "retry_started")
            return _record(await self._locked(c, tenant_id, dead_letter_id))

    async def retry_inconclusive(self, tenant_id: str, dead_letter_id: str) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            await self._move(c, await self._locked(c, tenant_id, dead_letter_id), D.PENDING, "retry_inconclusive",
                             retried=True)

    async def resolve(self, tenant_id: str, dead_letter_id: str, outcome: str) -> None:
        """A human resolution (from pending) or a retry's (from retrying), with the outcome it established."""
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await self._locked(c, tenant_id, dead_letter_id)
            reason = "human_resolved" if row["status"] == D.PENDING else "retry_resolved"
            await self._move(c, row, D.RESOLVED, reason, outcome=Resolution(outcome))

    async def abandon(self, tenant_id: str, dead_letter_id: str, outcome: str = Resolution.UNDETERMINED) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            await self._move(c, await self._locked(c, tenant_id, dead_letter_id), D.ABANDONED,
                             "abandoned_after_retries", outcome=Resolution(outcome), retried=True)
