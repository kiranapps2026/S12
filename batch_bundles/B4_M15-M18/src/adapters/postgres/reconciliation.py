"""Reconciliation episodes (gate §9, C18, C19; Appendix A.7): one step_reconciliations row per uncertainty."""
from __future__ import annotations

import json
import uuid

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write
from adapters.postgres.transition_log import log_transition
from contracts.execution_states import ReconciliationKind as K
from contracts.execution_states import ReconciliationOutcome as O
from contracts.execution_states import ReconciliationStatus as E
from engine.stages.s12_execute import transitions

MACHINE = "episode"
OPENED = "opened"


class PostgresEpisodes:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def _log(self, c, holder, episode_id, old, new, reason):
        await log_transition(c, tenant_id=holder.tenant_id, machine=MACHINE, entity_id=episode_id, from_state=old,
                             to_state=new, reason=reason, runtime_instance_id=holder.runtime_instance_id,
                             fence_token=holder.fence_token, execution_id=holder.execution_id)

    async def _open(self, c, holder, step_id, kind) -> str:
        transitions.validate(MACHINE, None, E.PENDING_PROBE, reason=OPENED)
        episode_id = str(uuid.uuid4())
        await c.execute("INSERT INTO step_reconciliations (episode_id, tenant_id, execution_id, step_id, kind, status)"
                        " VALUES ($1, $2, $3, $4, $5, $6)", episode_id, holder.tenant_id, holder.execution_id,
                        step_id, kind, E.PENDING_PROBE)
        await self._log(c, holder, episode_id, E.NONE, E.PENDING_PROBE, OPENED)
        return episode_id

    async def _move(self, c, holder, episode_id, to, reason, *, outcome=None, evidence=None, close=False):
        row = await c.fetchrow("SELECT kind, status, closed_at FROM step_reconciliations WHERE tenant_id = $1"
                               " AND episode_id = $2 FOR UPDATE", holder.tenant_id, episode_id)
        transitions.validate(MACHINE, row["status"], to, reason=reason, closed=row["closed_at"] is not None)
        if outcome == O.NOT_EXECUTED and row["kind"] == K.VERIFICATION:
            raise ValueError("a VERIFICATION episode cannot end NOT_EXECUTED: the adapter answered (C19)")
        started = 1 if to == E.RECONCILING else 0
        await c.execute("UPDATE step_reconciliations SET status = $3, attempts = attempts + $4,"
                        " outcome = COALESCE($5, outcome), evidence = COALESCE($6::jsonb, evidence),"
                        " closed_at = CASE WHEN $7 THEN now() ELSE closed_at END"
                        " WHERE tenant_id = $1 AND episode_id = $2", holder.tenant_id, episode_id, to, started,
                        outcome, None if evidence is None else json.dumps(evidence, sort_keys=True), close)
        await self._log(c, holder, episode_id, row["status"], to, reason)

    async def find_open(self, tenant_id: str, step_id: str):
        """The step's open episode (``closed_at`` unset), or None: recovery continues it (§13 step 3)."""
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchrow("SELECT episode_id, kind, status, attempts FROM step_reconciliations"
                                    " WHERE tenant_id = $1 AND step_id = $2 AND closed_at IS NULL", tenant_id, step_id)

    async def open(self, holder: FenceHolder, *, step_id: str, kind: str) -> str:
        async def write(c):
            return await self._open(c, holder, step_id, kind)
        return await fenced_write(self._db, holder, write)

    async def start_attempt(self, holder: FenceHolder, episode_id: str) -> None:
        async def write(c):
            await self._move(c, holder, episode_id, E.RECONCILING, "attempt_started")
        await fenced_write(self._db, holder, write)

    async def inconclusive(self, holder: FenceHolder, episode_id: str) -> None:
        async def write(c):
            await self._move(c, holder, episode_id, E.PENDING_PROBE, "inconclusive")
        await fenced_write(self._db, holder, write)

    async def close(self, holder: FenceHolder, episode_id: str, *, status: str, outcome: str, reason: str,
                    evidence: dict | None = None) -> None:
        async def write(c):
            await self._move(c, holder, episode_id, status, reason, outcome=outcome, evidence=evidence, close=True)
        await fenced_write(self._db, holder, write)

    async def open_and_close(self, holder: FenceHolder, *, step_id: str, kind: str, status: str, outcome: str,
                             reason: str, evidence: dict | None = None) -> str:
        """Ledger-hit, no-dispatch-marker and read re-execution episodes: opened and closed in one transaction."""
        async def write(c):
            episode_id = await self._open(c, holder, step_id, kind)
            await self._move(c, holder, episode_id, E.RECONCILING, "attempt_started")
            await self._move(c, holder, episode_id, status, reason, outcome=outcome, evidence=evidence, close=True)
            return episode_id
        return await fenced_write(self._db, holder, write)

    async def exhaust(self, holder: FenceHolder, episode_id: str) -> None:
        """Status stays pending_probe; closed with outcome EXHAUSTED (not a transition, A.7)."""
        async def write(c):
            await c.execute("UPDATE step_reconciliations SET outcome = 'EXHAUSTED', closed_at = now()"
                            " WHERE tenant_id = $1 AND episode_id = $2 AND closed_at IS NULL",
                            holder.tenant_id, episode_id)
        await fenced_write(self._db, holder, write)
