"""S12 durable admission over real PostgreSQL (gate §7.2): all-or-nothing, quota, duplicates, RLS."""
from __future__ import annotations

import asyncio
import json
import dataclasses

import asyncpg
import pytest

from adapters.postgres.activation import PostgresActivationReader
from adapters.postgres.admission import PostgresExecutionAdmission
from adapters.postgres.confirmation_records import PostgresConsumedConfirmationReader
from adapters.postgres.registry import PostgresBindingVersionReader, PostgresKernelOpMetadataReader
from bootstrap import build_runner
from contracts import codec
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import Plan
from engine.stages.s0_entry.handler import EntryRequest
from engine.stages.s12_entry.admission import admit_run
from tests_postgres.test_end_to_end import ChainModel, EchoIntentModel

A, B = "tenant-a", "tenant-b"
OBSERVE = ("UPDATE kernel_ops SET observation_method = 'get_contact', observation_identifier_field = 'id'"
           " WHERE kernel_op_id = 'crm.contact_create'",)
WORKSPACE_A = "tenant-a.ws"


async def _certified(db, model, tenant=A, request_id=None):
    runner = build_runner(db, model)
    entry = EntryRequest(
        raw_payload={"message": "contact.list"}, entry_channel="api", tenant_id=tenant,
        workspace_id=f"{tenant}.ws", user_id=f"{tenant}.user", membership_id=f"{tenant}.member",
        conversation_id="conv-1", connection_id=f"{tenant}.conn", request_id=request_id)
    result = await runner.run(entry)
    assert (result.status.value, result.final_stage) == ("NORMAL", "S11"), (result.reason, result.final_stage)
    return result.final_state


def _admit(db, state, **kw):
    # a run resumed after a confirmation is checked against the stored confirmation row (gate C20)
    return admit_run(state, bindings=PostgresBindingVersionReader(db), activation=PostgresActivationReader(db),
                     metadata=PostgresKernelOpMetadataReader(db), admitter=kw.get("admitter", PostgresExecutionAdmission(db)),
                     runtime_instance_id=kw.get("runtime", "runtime-1"),
                     confirmations=PostgresConsumedConfirmationReader(db))


async def _count(db, tenant, table, where="true"):
    async with db.tenant_transaction(tenant) as c:
        return await c.fetchval(f"SELECT count(*) FROM {table} WHERE {where}")


READ = EchoIntentModel()
CHAIN = ChainModel(("contact.create", {"name": "Ana"}), ("contact.list", {}))


def test_a_certified_read_run_is_admitted_and_left_running(pg):
    async def body(db):
        state = await _certified(db, READ)
        out = await _admit(db, state)
        async with db.tenant_transaction(A) as c:
            run = dict(await c.fetchrow("SELECT * FROM execution_runs"))
            manifest = dict(await c.fetchrow("SELECT * FROM execution_manifests"))
            steps = [dict(r) for r in await c.fetch("SELECT * FROM execution_steps")]
            owner = dict(await c.fetchrow("SELECT * FROM execution_ownership"))
            moves = [(r["entity_type"], r["from_state"], r["to_state"]) for r in
                     await c.fetch("SELECT * FROM state_transitions ORDER BY transition_id")]
        return state, out, run, manifest, steps, owner, moves
    state, out, run, manifest, steps, owner, moves = pg(body)
    ctx, m = state.execution_context, state.execution_manifest
    assert (out.status, out.execution_id, out.run_status) == ("ADMITTED", state.plan.execution_id, "running")
    assert (run["status"], run["request_id"], run["tenant_id"], run["workspace_id"], run["user_id"],
            run["actor_type"], run["actor_id"], run["task_id"], run["conversation_id"], run["trace_id"]) == \
        ("running", ctx.request_id, A, "tenant-a.ws", "tenant-a.user", "user", "tenant-a.user",
         ctx.task_id, "conv-1", ctx.trace_id)
    assert run["started_at"] is not None and run["plan_id"] == state.plan.plan.id
    assert (manifest["plan_hash"], manifest["capability_version"], manifest["binding_version"],
            manifest["auth_result_id"], manifest["trace_id"]) == \
        (m.plan_hash, m.capability_version, m.binding_version, m.auth_result_id, m.trace_id)
    assert len(steps) == 1 and steps[0]["status"] == "pending"
    assert steps[0]["step_id"] == f"{state.plan.execution_id}:{state.plan.plan.steps[0].id}"
    assert (steps[0]["resolved_binding_id"], steps[0]["effective_mutation"], steps[0]["kernel_op_id"]) == \
        (state.frozen_binding_identity.binding_id, "R", "crm.contact_list")
    assert (owner["runtime_instance_id"], owner["worker_id"], owner["lease_id"], owner["fencing_token"]) == \
        ("runtime-1", None, None, 0)
    # the run row exists before its steps, so its creation is logged first (C24 history in real order)
    assert moves == [("run", None, "pending"), ("step", None, "pending"), ("run", "pending", "running")]


def test_a_chain_is_admitted_with_one_step_row_per_step_its_own_binding_and_its_verifiers(pg):
    async def body(db):
        state = await _certified(db, CHAIN)
        out = await _admit(db, state)
        async with db.tenant_transaction(A) as c:
            steps = [dict(r) for r in await c.fetch("SELECT * FROM execution_steps ORDER BY plan_step_id")]
            plan = dict(await c.fetchrow("SELECT * FROM execution_plans"))
        return state, out, steps, plan
    state, out, steps, plan = pg(body, *OBSERVE)
    assert out.status == "ADMITTED"
    assert [(s["kernel_op_id"], s["resolved_binding_id"], s["effective_mutation"]) for s in steps] == \
        [("crm.contact_create", "bind.contact.create", "W"), ("crm.contact_list", "bind.contact.list", "R")]
    assert steps[0]["request_fingerprint"] != steps[1]["request_fingerprint"]
    bindings = json.loads(plan["frozen_bindings"])
    assert [b["binding_id"] for b in bindings] == ["bind.contact.create", "bind.contact.list"]
    assert json.loads(plan["step_binding_index"]) == {"step-1": 0, "step-2": 1}
    verifiers = json.loads(plan["verifiers"])
    assert [v["kernel_op_id"] for v in verifiers] == ["crm.contact_create"]          # the read has none
    assert verifiers[0]["expected_state"] == {"exists": True, "properties": {"name": "Ana"}}


def test_the_stored_plan_reloads_to_the_exact_plan_and_its_hash(pg):
    async def body(db):
        state = await _certified(db, CHAIN)
        await _admit(db, state)
        async with db.tenant_transaction(A) as c:
            row = await c.fetchrow("SELECT canonical_plan, plan_hash FROM execution_plans")
        return state, row
    state, row = pg(body, *OBSERVE)
    reloaded = codec.decode(Plan, json.loads(row["canonical_plan"]))
    assert reloaded == state.plan.plan
    assert canonical_plan_digest(reloaded) == row["plan_hash"] == state.execution_manifest.plan_hash


def test_a_second_admission_of_the_same_request_returns_the_existing_run_and_writes_nothing(pg):
    async def body(db):
        state = await _certified(db, READ)
        first, second = await _admit(db, state), await _admit(db, state)
        return first, second, await _count(db, A, "execution_runs"), await _count(db, A, "execution_steps")
    first, second, runs, steps = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
                                    " limit_value) VALUES ('q', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 5)")
    assert (first.status, second.status) == ("ADMITTED", "DUPLICATE")
    assert second.execution_id == first.execution_id and second.run_status == "running"
    assert (runs, steps) == (1, 1)


def test_the_quota_is_used_once_per_run_at_tenant_then_workspace_level(pg):
    async def body(db):
        state = await _certified(db, READ)
        await _admit(db, state)
        async with db.tenant_transaction(A) as c:
            return {r["quota_id"]: r["used_count"] for r in await c.fetch("SELECT * FROM operation_quotas")}
    used = pg(body,
              "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end, limit_value)"
              " VALUES ('tenant-q', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 5)",
              "INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, period_start, period_end, limit_value)"
              " VALUES ('ws-q', 'tenant-a', 'tenant-a.ws', now() - interval '1 day', now() + interval '1 day', 5)",
              "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end, limit_value)"
              " VALUES ('past-q', 'tenant-a', now() - interval '3 day', now() - interval '2 day', 5)")
    assert used == {"tenant-q": 1, "ws-q": 1, "past-q": 0}


@pytest.mark.parametrize("level", ["tenant", "workspace"])
def test_an_exhausted_hard_quota_denies_and_rolls_everything_back(pg, level):
    async def body(db):
        state = await _certified(db, READ)
        out = await _admit(db, state)
        async with db.tenant_transaction(A) as c:
            used = {r["quota_id"]: r["used_count"] for r in await c.fetch("SELECT * FROM operation_quotas")}
        return out, used, [await _count(db, A, t) for t in
                           ("execution_runs", "execution_steps", "execution_manifests", "execution_plans",
                            "execution_ownership", "state_transitions")]
    ws = "'tenant-a.ws'" if level == "workspace" else "NULL"
    full = ("INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, period_start, period_end,"
            f" limit_value, used_count) VALUES ('full', 'tenant-a', {ws}, now() - interval '1 hour',"
            " now() + interval '1 day', 3, 3)")
    out, used, counts = pg(
        body,
        "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end, limit_value, used_count)"
        f" VALUES ('open', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 5, 0)",
        full)
    assert (out.status, out.reason, out.retry_after_ms) == ("DENIED", "quota_exhausted", None)
    assert counts == [0] * 6                                             # nothing written
    assert used["open"] == 0                                             # the tenant-level use was rolled back too


def test_an_exhausted_soft_quota_is_retried_then_denied_with_retry_after(pg):
    async def body(db):
        state = await _certified(db, READ)
        import time
        t0 = time.monotonic()
        out = await _admit(db, state)
        return out, time.monotonic() - t0, await _count(db, A, "execution_runs")
    out, elapsed, runs = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
                            " limit_value, used_count, is_hard) VALUES ('soft', 'tenant-a', now() - interval '1 hour',"
                            " now() + interval '1 day', 1, 1, false)")
    assert (out.status, out.reason, out.retry_after_ms) == ("DENIED", "quota_exhausted", 1000)
    assert runs == 0 and 0.1 <= elapsed < 2


def test_a_soft_quota_that_frees_up_during_the_retries_admits_the_run(pg):
    async def body(db):
        state = await _certified(db, READ)
        async def free():
            await asyncio.sleep(0.03)
            async with db.tenant_transaction(A) as c:
                await c.execute("UPDATE operation_quotas SET limit_value = 2")
        freeing = asyncio.create_task(free())
        out = await _admit(db, state)
        await freeing
        return out
    out = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
             " limit_value, used_count, is_hard) VALUES ('soft', 'tenant-a', now() - interval '1 hour',"
             " now() + interval '1 day', 1, 1, false)")
    assert out.status == "ADMITTED"


def test_concurrent_admissions_of_one_request_create_exactly_one_run_and_use_the_quota_once(pg):
    async def body(db):
        state = await _certified(db, READ)
        outs = await asyncio.gather(*[_admit(db, state) for _ in range(6)])
        async with db.tenant_transaction(A) as c:
            used = await c.fetchval("SELECT used_count FROM operation_quotas")
        return outs, used, await _count(db, A, "execution_runs"), await _count(db, A, "execution_steps")
    outs, used, runs, steps = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
                                 " limit_value) VALUES ('q', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 9)")
    assert sorted(o.status for o in outs) == ["ADMITTED"] + ["DUPLICATE"] * 5
    assert (used, runs, steps) == (1, 1, 1)


def test_concurrent_runs_cannot_exceed_the_quota(pg):
    async def body(db):
        states = [await _certified(db, READ) for _ in range(6)]
        outs = await asyncio.gather(*[_admit(db, s) for s in states])
        async with db.tenant_transaction(A) as c:
            used = await c.fetchval("SELECT used_count FROM operation_quotas")
        return outs, used, await _count(db, A, "execution_runs")
    outs, used, runs = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
                          " limit_value) VALUES ('q', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 3)")
    assert sorted(o.status for o in outs) == ["ADMITTED"] * 3 + ["DENIED"] * 3
    assert (used, runs) == (3, 3)


def test_a_failure_in_the_middle_rolls_back_the_quota_and_every_row(pg):
    async def body(db):
        state = await _certified(db, READ)
        ghost = dataclasses.replace(state, execution_context=dataclasses.replace(state.execution_context,
                                                                                 user_id="ghost-user"))
        out = await _admit(db, ghost)                       # the run row's foreign key to users fails
        async with db.tenant_transaction(A) as c:
            used = await c.fetchval("SELECT used_count FROM operation_quotas")
        return out, used, await _count(db, A, "execution_runs")
    out, used, runs = pg(body, "INSERT INTO operation_quotas (quota_id, tenant_id, period_start, period_end,"
                         " limit_value) VALUES ('q', 'tenant-a', now() - interval '1 day', now() + interval '1 day', 5)")
    assert (out.status, out.reason, used, runs) == ("DENIED", "admission_unavailable", 0, 0)


def test_a_pause_set_after_s11_is_caught_by_the_entry_safety_net(pg):
    async def body(db):
        state = await _certified(db, READ)
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE tenants SET paused_until = now() + interval '1 hour'")
        out = await _admit(db, state)
        return out, await _count(db, A, "execution_runs")
    out, runs = pg(body)
    assert (out.status, out.reason, runs) == ("DENIED", "tenant_paused", 0)


def test_a_mutating_plan_without_an_observation_method_is_denied_and_nothing_is_written(pg):
    async def body(db):
        state = await _certified(db, CHAIN)
        out = await _admit(db, state)
        return out, await _count(db, A, "execution_runs")
    out, runs = pg(body)                                    # no OBSERVE setup
    assert (out.status, out.reason, runs) == ("DENIED", "verifier_metadata_unavailable", 0)


def test_no_admitter_or_runtime_instance_denies(pg):
    async def body(db):
        state = await _certified(db, READ)
        return (await _admit(db, state, admitter=None), await _admit(db, state, runtime=""),
                await _count(db, A, "execution_runs"))
    none, blank, runs = pg(body)
    assert (none.reason, blank.reason, runs) == ("admission_unavailable", "admission_unavailable", 0)


def test_a_database_that_cannot_be_used_denies(pg):
    class Down:
        async def admit(self, *a, **k):
            from contracts.errors import DependencyUnavailable
            raise DependencyUnavailable("db down")

    async def body(db):
        return await _admit(db, await _certified(db, READ), admitter=Down())
    assert pg(body).reason == "admission_unavailable"


def test_admitted_rows_are_invisible_to_another_tenant(pg):
    async def body(db):
        await _admit(db, await _certified(db, READ))
        return [await _count(db, B, t) for t in ("execution_runs", "execution_steps", "execution_manifests",
                                                  "execution_plans", "execution_ownership", "state_transitions")]
    assert pg(body) == [0] * 6


def test_the_same_request_id_in_two_tenants_is_two_runs(pg):
    async def body(db):
        outs = [await _admit(db, await _certified(db, READ, t, request_id="same-request")) for t in (A, B)]
        return outs, await _count(db, A, "execution_runs"), await _count(db, B, "execution_runs")
    outs, a, b = pg(body)
    assert [o.status for o in outs] == ["ADMITTED", "ADMITTED"] and (a, b) == (1, 1)


def test_the_manifest_and_the_frozen_plan_can_never_be_updated(pg):
    async def body(db):
        await _admit(db, await _certified(db, READ))
        errors = []
        for sql in ("UPDATE execution_manifests SET plan_hash = 'x'", "UPDATE execution_plans SET plan_hash = 'x'"):
            try:
                async with db.tenant_transaction(A) as c:
                    await c.execute(sql)
                errors.append(None)
            except asyncpg.PostgresError as exc:
                errors.append(str(exc))
        return errors
    assert all("immutable" in (e or "") for e in pg(body))


def test_a_run_cannot_be_written_for_another_tenant(pg):
    async def body(db):
        state = await _certified(db, READ)
        try:
            async with db.tenant_transaction(B) as c:
                await c.execute("INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id,"
                                " tenant_id, workspace_id, conversation_id, status, actor_id) VALUES"
                                " ('x','r','t','k','tenant-a.user','tenant-a','tenant-a.ws','c','pending','u')")
            return "written"
        except asyncpg.PostgresError:
            return "refused"
    assert pg(body) == "refused"


def test_step_risk_is_copied_from_the_frozen_binding_never_from_the_plan(pg):
    """Even a plan whose step disagrees with its binding (re-hashed consistently) is stored with the
    BINDING's values: S12 never recomputes them (gate §7.2). (A skewed mutation is stopped earlier:
    the verifier metadata check refuses a step whose mutation differs from the registry's.)"""
    async def body(db):
        state = await _certified(db, READ)
        step = dataclasses.replace(state.plan.plan.steps[0], risk=0.99)
        plan = dataclasses.replace(state.plan.plan, steps=(step,))
        digest = canonical_plan_digest(plan)
        skewed = dataclasses.replace(
            state, plan=dataclasses.replace(state.plan, plan=plan, plan_hash=digest),
            execution_manifest=dataclasses.replace(state.execution_manifest, plan_hash=digest))
        out = await _admit(db, skewed)
        async with db.tenant_transaction(A) as c:
            row = await c.fetchrow("SELECT effective_risk, effective_mutation FROM execution_steps")
        return state, out, row
    state, out, row = pg(body)
    assert out.status == "ADMITTED"
    assert (row["effective_risk"], row["effective_mutation"]) == \
        (state.frozen_binding_identity.effective_risk, "R")
