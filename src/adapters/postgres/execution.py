"""Execution repository for the S12 loop: load an admitted run, and make every state change through a
fenced, validated, logged write.

Every write goes through adapters.postgres.fencing.fenced_write (gate C5, C25): in the SAME transaction the
execution_ownership row is locked and must still name this Worker Runtime and its fence token, otherwise FencedOut
and nothing is written. Every move is checked against the canonical transition tables before it is applied and is
recorded through adapters.postgres.transition_log. Every query filters on tenant_id (C34).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write
from adapters.postgres.transition_log import log_transition
from contracts import codec
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import Plan
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

    def holder(self, tenant_id: str, execution_id: str) -> FenceHolder:
        return FenceHolder(tenant_id=tenant_id, execution_id=execution_id, runtime_instance_id=self._runtime,
                           fence_token=self._token)

    async def load(self, tenant_id: str, execution_id: str) -> LoadedExecution | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            run = await c.fetchrow("SELECT * FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2",
                                   tenant_id, execution_id)
            if run is None:
                return None
            plan_row = await c.fetchrow("SELECT * FROM execution_plans WHERE tenant_id = $1 AND execution_id = $2",
                                        tenant_id, execution_id)
            step_rows = await c.fetch("SELECT * FROM execution_steps WHERE tenant_id = $1 AND execution_id = $2",
                                      tenant_id, execution_id)
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
                                    " WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id)

    async def transition_step(self, tenant_id: str, execution_id: str, step_id: str, to: str, *,
                              reason: str, terminal_reason: str | None = None, error: str | None = None,
                              attempt: int | None = None, data: dict | None = None,
                              undo_token: str | None = None, duration_ms: int | None = None) -> None:
        async def write(c) -> None:
            current = await c.fetchval("SELECT status FROM execution_steps WHERE tenant_id = $1 AND step_id = $2"
                                       " FOR UPDATE", tenant_id, step_id)
            transitions.check_step(current, to)
            await c.execute(
                "UPDATE execution_steps SET status = $3, terminal_reason = COALESCE(terminal_reason, $4),"
                " error = COALESCE($5, error), attempt = COALESCE($6, attempt), data = COALESCE($7, data),"
                " undo_token = COALESCE($8, undo_token), duration_ms = COALESCE($9, duration_ms)"
                " WHERE tenant_id = $1 AND step_id = $2", tenant_id, step_id, to, terminal_reason, error, attempt,
                None if data is None else json.dumps(data), undo_token, duration_ms)
            await self._log(c, tenant_id, execution_id, "step", step_id, current, to, reason)
        await fenced_write(self._db, self.holder(tenant_id, execution_id), write)

    async def mark_dispatched(self, tenant_id: str, execution_id: str, step_id: str, attempt: int) -> None:
        """The dispatch marker (C35): written BEFORE the adapter call, so a crash can tell whether the
        provider may have been reached."""
        async def write(c) -> None:
            await c.execute("UPDATE execution_steps SET dispatched_attempt = $3, attempt = $3"
                            " WHERE tenant_id = $1 AND step_id = $2", tenant_id, step_id, attempt)
        await fenced_write(self._db, self.holder(tenant_id, execution_id), write)

    async def transition_run(self, tenant_id: str, execution_id: str, to: str, *, reason: str,
                             terminal_reason: str | None = None, budget_spent: int | None = None,
                             duration_ms: int | None = None) -> None:
        async def write(c) -> None:
            current = await c.fetchval("SELECT status FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2"
                                       " FOR UPDATE", tenant_id, execution_id)
            transitions.check_run(current, to)
            await c.execute(
                "UPDATE execution_runs SET status = $3, terminal_reason = $4, budget_spent = COALESCE($5, budget_spent),"
                " duration_ms = COALESCE($6, duration_ms), completed_at = now() WHERE tenant_id = $1 AND execution_id = $2",
                tenant_id, execution_id, to, terminal_reason, budget_spent, duration_ms)
            await self._log(c, tenant_id, execution_id, "run", execution_id, current, to, reason)
        await fenced_write(self._db, self.holder(tenant_id, execution_id), write)

    async def _log(self, c, tenant_id, execution_id, machine, entity_id, old, new, reason) -> None:
        await log_transition(c, tenant_id=tenant_id, machine=machine, entity_id=entity_id, from_state=old,
                             to_state=new, reason=reason, runtime_instance_id=self._runtime,
                             fence_token=self._token, execution_id=execution_id)


# ---- the loop's store (gate §8; every write fenced by the caller's holder, validated, logged) ----------------------

@dataclass(frozen=True)
class LoadedStep:
    step_id: str
    plan_step_id: str
    index: int
    status: str
    reservation_id: str | None
    attempt: int = 0
    dispatched_attempt: int | None = None
    kernel_op_id: str | None = None


@dataclass(frozen=True)
class LoadedRun:
    execution_id: str
    tenant_id: str
    workspace_id: str
    user_id: str
    request_id: str
    trace_id: str
    actor_type: str
    connection_id: str | None
    run_status: str
    plan: Plan | None
    plan_intact: bool
    bindings: dict
    steps: dict
    owner_runtime: str
    owner_token: int
    verifiers: dict


class PostgresExecutionStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self, tenant_id: str, execution_id: str) -> LoadedRun | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            run = await c.fetchrow("SELECT * FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2",
                                   tenant_id, execution_id)
            if run is None:
                return None
            plan_row = await c.fetchrow("SELECT * FROM execution_plans WHERE tenant_id = $1 AND execution_id = $2",
                                        tenant_id, execution_id)
            step_rows = await c.fetch("SELECT * FROM execution_steps WHERE tenant_id = $1 AND execution_id = $2",
                                      tenant_id, execution_id)
            owner = await c.fetchrow("SELECT runtime_instance_id, fencing_token FROM execution_ownership"
                                     " WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id)
        if plan_row is None or owner is None:
            raise LookupError(f"execution {execution_id} was not admitted (no plan or ownership row)")
        plan, bindings = _decode_plan(plan_row, None, {r["plan_step_id"] for r in step_rows})
        position = {s.id: i for i, s in enumerate(plan.steps)} if plan is not None else {}
        return LoadedRun(
            execution_id=execution_id, tenant_id=tenant_id, workspace_id=run["workspace_id"], user_id=run["user_id"],
            request_id=run["request_id"], trace_id=run["trace_id"], actor_type=run["actor_type"],
            connection_id=run["connection_id"], run_status=run["status"], plan=plan, plan_intact=plan is not None,
            bindings=bindings,
            steps={r["plan_step_id"]: LoadedStep(r["step_id"], r["plan_step_id"], position.get(r["plan_step_id"], -1),
                                                 r["status"], r["reservation_id"], r["attempt"],
                                                 r["dispatched_attempt"], r["kernel_op_id"]) for r in step_rows},
            owner_runtime=owner["runtime_instance_id"], owner_token=owner["fencing_token"],
            verifiers=_decode_verifiers(plan_row["verifiers"]) if plan is not None else {})

    async def cancel_requested(self, tenant_id: str, execution_id: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as c:
            return bool(await c.fetchval("SELECT cancel_requested_at IS NOT NULL FROM execution_runs"
                                         " WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id))

    async def _step(self, c, holder: FenceHolder, step_id: str, to: str, reason: str, terminal_reason, error,
                    undo_token) -> None:
        current = await c.fetchval("SELECT status FROM execution_steps WHERE tenant_id = $1 AND step_id = $2"
                                   " AND execution_id = $3 FOR UPDATE", holder.tenant_id, step_id,
                                   holder.execution_id)
        transitions.validate("step", current, to, reason=reason)
        await c.execute("UPDATE execution_steps SET status = $3, terminal_reason = COALESCE(terminal_reason, $4),"
                        " error = COALESCE($5, error), undo_token = COALESCE($6, undo_token)"
                        " WHERE tenant_id = $1 AND step_id = $2", holder.tenant_id, step_id, to, terminal_reason,
                        error, undo_token)
        await log_transition(c, tenant_id=holder.tenant_id, machine="step", entity_id=step_id, from_state=current,
                             to_state=to, reason=reason, runtime_instance_id=holder.runtime_instance_id,
                             fence_token=holder.fence_token, execution_id=holder.execution_id)

    async def transition_step(self, holder: FenceHolder, step_id: str, to: str, *, reason: str,
                              terminal_reason: str | None = None, error: str | None = None,
                              undo_token: str | None = None, budget=None, reservation_id: str | None = None,
                              budget_move: str | None = None, budget_reason: str | None = None) -> None:
        """One fenced transaction: the step move and, when given, its reservation's move (I-3 and C3 guards)."""
        async def write(c):
            await self._step(c, holder, step_id, to, reason, terminal_reason, error, undo_token)
            if budget_move is not None:
                await getattr(budget, budget_move)(holder, reservation_id, reason=budget_reason, connection=c)
        await fenced_write(self._db, holder, write)

    async def transition_run(self, holder: FenceHolder, to: str, *, reason: str,
                             terminal_reason: str | None = None) -> None:
        async def write(c):
            current = await c.fetchval("SELECT status FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2"
                                       " FOR UPDATE", holder.tenant_id, holder.execution_id)
            transitions.validate("run", current, to, reason=reason)
            await c.execute("UPDATE execution_runs SET status = $3, terminal_reason = $4, completed_at = now()"
                            " WHERE tenant_id = $1 AND execution_id = $2", holder.tenant_id, holder.execution_id, to,
                            terminal_reason)
            await log_transition(c, tenant_id=holder.tenant_id, machine="run", entity_id=holder.execution_id,
                                 from_state=current, to_state=to, reason=reason,
                                 runtime_instance_id=holder.runtime_instance_id, fence_token=holder.fence_token,
                                 execution_id=holder.execution_id)
        await fenced_write(self._db, holder, write)



def _decode_verifiers(raw) -> dict:
    return {v.step_id: v for v in codec.decode(tuple[Verifier, ...], json.loads(raw))}


def _decode_plan(plan_row, manifest_hash: str | None, step_ids: set) -> tuple[Plan | None, dict]:
    try:
        plan = codec.decode(Plan, json.loads(plan_row["canonical_plan"]))
        digest = canonical_plan_digest(plan)
        distinct = codec.decode(tuple[FrozenBindingIdentity, ...], json.loads(plan_row["frozen_bindings"]))
        index = json.loads(plan_row["step_binding_index"])
        bindings = {sid: distinct[i] for sid, i in index.items()}
    except (KeyError, IndexError, TypeError, ValueError):
        return None, {}
    if digest != plan_row["plan_hash"] or (manifest_hash is not None and digest != manifest_hash):
        return None, {}
    if {s.id for s in plan.steps} != step_ids or set(bindings) != step_ids:
        return None, {}
    return plan, bindings
