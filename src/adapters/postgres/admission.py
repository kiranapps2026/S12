"""Durable admission (gate §7.2): one transaction writes the quota use, the run, its manifest, the
frozen plan, one row per step and the ownership record, then moves the run PENDING -> RUNNING.

All or nothing: any failure (including an exhausted quota or a concurrent duplicate) rolls the
whole transaction back. Tenant-scoped by row-level security; the tenant is the state's own.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

from adapters.postgres.database import Database
from adapters.postgres.transition_log import log_transition
from contracts import codec
from contracts.admission import ADMITTED, DENIED, DUPLICATE, AdmissionOutcome
from contracts.execution_states import ExecutionStatus, StepState
from contracts.pipeline_state import PipelineState
from contracts.verifier import Verifier
from engine.stages.plan_steps import plan_step_bindings
from engine.stages.s12_execute import transitions

QUOTA_EXHAUSTED = "quota_exhausted"
CREATED = "created"                 # Appendix A: creation reason of a run and of a step
ADMITTED_REASON = "admitted"        # Appendix A.1: pending -> running at admission
SOFT_QUOTA_ATTEMPTS = 3
SOFT_QUOTA_BACKOFF_SECONDS = 0.05
SOFT_QUOTA_RETRY_AFTER_MS = 1000


class _Exhausted(Exception):
    def __init__(self, hard: bool) -> None:
        self.hard = hard


class _Duplicate(Exception):
    pass


def _json(value) -> str:
    return json.dumps(codec.encode(value), sort_keys=True)


def _fingerprint(kernel_op_id: str, params: dict) -> str:
    """Diagnostics only (gate C33): SHA-256 of canonical JSON {kernel_op_id, params}."""
    body = json.dumps({"kernel_op_id": kernel_op_id, "params": params}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _step_bindings(state: PipelineState):
    """(binding for each plan step in order, distinct bindings in first-seen order)."""
    steps = state.plan.plan.steps
    if state.frozen_binding_identity is not None:
        per_step = (state.frozen_binding_identity,) * len(steps)
    else:
        mapped = plan_step_bindings(state)
        if mapped is None or len(mapped) != len(steps):
            raise ValueError("plan steps do not map onto the frozen bindings")
        per_step = tuple(item.binding for item in mapped)
    distinct = tuple({b.binding_id: b for b in per_step}.values())
    return per_step, distinct


class PostgresExecutionAdmission:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def admit(self, state: PipelineState, verifiers: tuple[Verifier, ...],
                    runtime_instance_id: str) -> AdmissionOutcome:
        ctx = state.execution_context
        for attempt in range(1, SOFT_QUOTA_ATTEMPTS + 1):
            try:
                return await self._attempt(state, verifiers, runtime_instance_id)
            except _Duplicate:
                return await self._existing(ctx.tenant_id, ctx.request_id)
            except _Exhausted as exhausted:
                if exhausted.hard:
                    return AdmissionOutcome(DENIED, reason=QUOTA_EXHAUSTED)
                if attempt == SOFT_QUOTA_ATTEMPTS:
                    return AdmissionOutcome(DENIED, reason=QUOTA_EXHAUSTED,
                                            retry_after_ms=SOFT_QUOTA_RETRY_AFTER_MS)
                await asyncio.sleep(SOFT_QUOTA_BACKOFF_SECONDS * attempt)
        raise AssertionError("unreachable")

    async def _existing(self, tenant_id: str, request_id: str) -> AdmissionOutcome:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT execution_id, status FROM execution_runs WHERE tenant_id = $1 AND request_id = $2",
                tenant_id, request_id)
        return AdmissionOutcome(DUPLICATE, row["execution_id"], row["status"])

    async def _attempt(self, state: PipelineState, verifiers, runtime_instance_id: str) -> AdmissionOutcome:
        ctx, manifest, plan_result = state.execution_context, state.execution_manifest, state.plan
        plan = plan_result.plan
        per_step, distinct = _step_bindings(state)
        execution_id, tenant = plan_result.execution_id, ctx.tenant_id
        created = datetime.fromtimestamp(manifest.created_at or 0.0, timezone.utc)

        async def log(c, machine: str, entity_id: str, old: str | None, new: str, reason: str) -> None:
            """Every creation and move is validated against Appendix A and written by the one log writer (C24)."""
            transitions.validate(machine, old, new, reason=reason)
            await log_transition(c, tenant_id=tenant, machine=machine, entity_id=entity_id, from_state=old,
                                 to_state=new, reason=reason, runtime_instance_id=runtime_instance_id,
                                 fence_token=None, execution_id=execution_id)

        async with self._db.tenant_transaction(tenant) as c:
            # 1. duplicate check: the same request is never admitted twice
            existing = await c.fetchrow(
                "SELECT execution_id, status FROM execution_runs WHERE tenant_id = $1 AND request_id = $2",
                tenant, ctx.request_id)
            if existing is not None:
                return AdmissionOutcome(DUPLICATE, existing["execution_id"], existing["status"])

            # 2. quota: one use per run, tenant level then workspace level
            for workspace in (None, ctx.workspace_id):
                rows = await c.fetch(
                    "SELECT quota_id, is_hard FROM operation_quotas"
                    " WHERE tenant_id = $1 AND resource_type = 'executions'"
                    "   AND workspace_id IS NOT DISTINCT FROM $2"
                    "   AND period_start <= now() AND period_end > now() ORDER BY quota_id FOR UPDATE",
                    tenant, workspace)
                for quota in rows:
                    used = await c.fetchval(
                        "UPDATE operation_quotas SET used_count = used_count + 1"
                        " WHERE quota_id = $1 AND tenant_id = $2 AND period_start <= now()"
                        "   AND period_end > now() AND used_count < limit_value RETURNING quota_id",
                        quota["quota_id"], tenant)
                    if used is None:
                        raise _Exhausted(hard=quota["is_hard"])

            # 3. the run (PENDING) — the unique (tenant, request) index settles a concurrent duplicate
            inserted = await c.fetchval(
                "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id,"
                " workspace_id, conversation_id, plan_id, status, actor_type, actor_id, connection_id)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$11,'user',$5,$10)"
                " ON CONFLICT (tenant_id, request_id) DO NOTHING RETURNING execution_id",
                execution_id, ctx.request_id, ctx.trace_id, ctx.task_id, ctx.user_id, tenant,
                ctx.workspace_id, ctx.conversation_id, plan.id, ctx.connection_id, ExecutionStatus.PENDING.value)
            if inserted is None:
                raise _Duplicate()
            await log(c, "run", execution_id, None, ExecutionStatus.PENDING.value, CREATED)

            # 4. manifest (byte-identical to S11's), frozen plan, steps, ownership
            await c.execute(
                "INSERT INTO execution_manifests (execution_id, tenant_id, trace_id, plan_hash,"
                " capability_version, binding_version, policy_version, risk_policy_version,"
                " authorization_version, auth_result_id, worker_runtime_version, model_version, created_at)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                execution_id, tenant, manifest.trace_id, manifest.plan_hash, manifest.capability_version,
                manifest.binding_version, manifest.policy_version, manifest.risk_policy_version,
                manifest.authorization_version, manifest.auth_result_id, manifest.worker_runtime_version,
                manifest.model_version, created)
            index = {b.binding_id: i for i, b in enumerate(distinct)}
            await c.execute(
                "INSERT INTO execution_plans (execution_id, tenant_id, plan_hash, canonical_plan,"
                " frozen_bindings, step_binding_index, verifiers) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7::jsonb)",
                execution_id, tenant, plan_result.plan_hash, _json(plan), _json(distinct),
                json.dumps({s.id: index[b.binding_id] for s, b in zip(plan.steps, per_step)}, sort_keys=True),
                _json(verifiers))
            for step, binding in zip(plan.steps, per_step):
                step_id = f"{execution_id}:{step.id}"
                await c.execute(
                    "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, plan_id,"
                    " kernel_op_id, resolved_binding_id, effective_risk, effective_mutation,"
                    " request_fingerprint, status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    step_id, step.id, execution_id, tenant, plan.id, step.kernel_op_id, binding.binding_id,
                    binding.effective_risk, binding.effective_mutation,
                    _fingerprint(step.kernel_op_id, step.params), StepState.PENDING.value)
                await log(c, "step", step_id, None, StepState.PENDING.value, CREATED)
            await c.execute(
                "INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id)"
                " VALUES ($1,$2,$3)", execution_id, tenant, runtime_instance_id)

            # 5. PENDING -> RUNNING (§7.2 step 3, Appendix A.1 reason "admitted")
            await log(c, "run", execution_id, ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value, ADMITTED_REASON)
            await c.execute(
                "UPDATE execution_runs SET status = $3, started_at = now()"
                " WHERE tenant_id = $1 AND execution_id = $2", tenant, execution_id, ExecutionStatus.RUNNING.value)
        return AdmissionOutcome(ADMITTED, execution_id, ExecutionStatus.RUNNING.value)
