"""Execution repository for the S12 loop: load an admitted run, and make every state change through a
fenced, validated, logged write.

fenced_write (gate C25, single runtime until leases exist): each write first checks, in the SAME
transaction, that execution_ownership still names this Worker Runtime and its fencing token; otherwise
it raises FencedOut and nothing is written. Every move is checked against the canonical transition
tables before it is applied and is recorded in state_transitions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from adapters.postgres.database import Database
from contracts import codec
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_outputs import Plan
from contracts.step_execution import FencedOut
from contracts.verifier import Verifier
from engine.stages.s12_execute import transitions


@dataclass(frozen=True)
class StepRow:
    step_id: str
    plan_step_id: str
    status: str
    attempt: int
    reservation_id: str | None


@dataclass(frozen=True)
class LoadedExecution:
    execution_id: str
    tenant_id: str
    workspace_id: str
    user_id: str
    connection_id: str | None
    run_status: str
    cancel_requested: bool
    plan: Plan
    plan_hash: str
    bindings: dict            # plan step id -> FrozenBindingIdentity
    verifiers: dict           # plan step id -> Verifier
    steps: dict               # plan step id -> StepRow


class PostgresExecutionRepository:
    def __init__(self, database: Database, runtime_instance_id: str, fencing_token: int = 0) -> None:
        self._db, self._runtime, self._token = database, runtime_instance_id, fencing_token

    async def load(self, tenant_id: str, execution_id: str) -> LoadedExecution | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            run = await c.fetchrow("SELECT * FROM execution_runs WHERE execution_id = $1", execution_id)
            if run is None:
                return None
            plan_row = await c.fetchrow("SELECT * FROM execution_plans WHERE execution_id = $1", execution_id)
            step_rows = await c.fetch("SELECT * FROM execution_steps WHERE execution_id = $1", execution_id)
        plan = codec.decode(Plan, json.loads(plan_row["canonical_plan"]))
        distinct = codec.decode(tuple[FrozenBindingIdentity, ...], json.loads(plan_row["frozen_bindings"]))
        index = json.loads(plan_row["step_binding_index"])
        verifiers = codec.decode(tuple[Verifier, ...], json.loads(plan_row["verifiers"]))
        return LoadedExecution(
            execution_id=execution_id, tenant_id=tenant_id, workspace_id=run["workspace_id"], user_id=run["user_id"],
            connection_id=run["connection_id"], run_status=run["status"],
            cancel_requested=run["cancel_requested_at"] is not None,
            plan=plan, plan_hash=plan_row["plan_hash"],
            bindings={sid: distinct[i] for sid, i in index.items()},
            verifiers={v.step_id: v for v in verifiers},
            steps={r["plan_step_id"]: StepRow(r["step_id"], r["plan_step_id"], r["status"], r["attempt"],
                                              r["reservation_id"]) for r in step_rows})

    async def cancel_requested(self, tenant_id: str, execution_id: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchval("SELECT cancel_requested_at IS NOT NULL FROM execution_runs"
                                    " WHERE execution_id = $1", execution_id)

    async def _fence(self, c, execution_id: str) -> None:
        row = await c.fetchrow("SELECT runtime_instance_id, fencing_token FROM execution_ownership"
                               " WHERE execution_id = $1 FOR SHARE", execution_id)
        if row is None or row["runtime_instance_id"] != self._runtime or row["fencing_token"] != self._token:
            raise FencedOut(execution_id)

    async def transition_step(self, tenant_id: str, execution_id: str, step_id: str, to: str, *,
                              reason: str, terminal_reason: str | None = None, error: str | None = None,
                              attempt: int | None = None, data: dict | None = None,
                              undo_token: str | None = None, duration_ms: int | None = None) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            await self._fence(c, execution_id)
            current = await c.fetchval("SELECT status FROM execution_steps WHERE step_id = $1 FOR UPDATE", step_id)
            transitions.check_step(current, to)
            await c.execute(
                "UPDATE execution_steps SET status = $2, terminal_reason = COALESCE(terminal_reason, $3),"
                " error = COALESCE($4, error), attempt = COALESCE($5, attempt), data = COALESCE($6, data),"
                " undo_token = COALESCE($7, undo_token), duration_ms = COALESCE($8, duration_ms)"
                " WHERE step_id = $1", step_id, to, terminal_reason, error, attempt,
                None if data is None else json.dumps(data), undo_token, duration_ms)
            await self._log(c, tenant_id, "step", step_id, current, to, reason)

    async def mark_dispatched(self, tenant_id: str, execution_id: str, step_id: str, attempt: int) -> None:
        """The dispatch marker (C35): written BEFORE the adapter call, so a crash can tell whether the
        provider may have been reached."""
        async with self._db.tenant_transaction(tenant_id) as c:
            await self._fence(c, execution_id)
            await c.execute("UPDATE execution_steps SET dispatched_attempt = $2, attempt = $2 WHERE step_id = $1",
                            step_id, attempt)

    async def transition_run(self, tenant_id: str, execution_id: str, to: str, *, reason: str,
                             terminal_reason: str | None = None, budget_spent: int | None = None,
                             duration_ms: int | None = None) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            await self._fence(c, execution_id)
            current = await c.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1 FOR UPDATE",
                                       execution_id)
            transitions.check_run(current, to)
            await c.execute(
                "UPDATE execution_runs SET status = $2, terminal_reason = $3, budget_spent = COALESCE($4, budget_spent),"
                " duration_ms = COALESCE($5, duration_ms), completed_at = now() WHERE execution_id = $1",
                execution_id, to, terminal_reason, budget_spent, duration_ms)
            await self._log(c, tenant_id, "run", execution_id, current, to, reason)

    async def _log(self, c, tenant_id, kind, entity_id, old, new, reason) -> None:
        await c.execute(
            "INSERT INTO state_transitions (tenant_id, entity_type, entity_id, from_state, to_state, reason,"
            " runtime_instance_id, fence_token) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            tenant_id, kind, entity_id, old, new, reason, self._runtime, self._token)
