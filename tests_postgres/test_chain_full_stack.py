"""D1 journeys: a multi-capability chain from S0 through S11, durable admission and the S12 step loop,
over real PostgreSQL, with a scripted provider and a scripted independent verifier.

Ported to the certified loop (CONF-035) with the dependencies of tests_postgres/test_step_loop.py (see its
docstring and its findings P1-F1..F6)."""
from __future__ import annotations

import json

from adapters.postgres.admission_snapshot import PostgresAdmissionSnapshot
from bootstrap import build_runner
from engine.stages.s0_entry.handler import EntryRequest
from engine.stages.s12_execute.loop import run_execution
from tests_postgres.seed import CHAIN_CATALOG_SQL
from tests_postgres.test_admission import A, _admit, _certified, _count
from tests_postgres.test_end_to_end import ChainModel
from tests_postgres.test_step_loop import WORKER, Adapter, Verify, _deps, _rows, _summary

CREATE_LIST = ChainModel(("contact.create", {"name": "Ana Silva"}), ("contact.list", {}))
CREATE_DELETE = ChainModel(("contact.create", {"name": "Ana Silva"}), ("contact.delete", {"id": "c-1"}))


async def _through_confirmation(db, model):
    """S0..S11 for a chain that needs confirmation: run, then the user's approving reply."""
    runner = build_runner(db, model)
    entry = EntryRequest(raw_payload={"message": "x"}, entry_channel="api", tenant_id=A,
                         workspace_id="tenant-a.ws", user_id="tenant-a.user", membership_id="tenant-a.member",
                         conversation_id="conv-1", connection_id="tenant-a.conn")
    first = await runner.run(entry)
    assert (first.status.value, first.reason) == ("CLARIFY", "confirmation_required"), first.reason
    done = await runner.reply(A, first.final_state.confirmation.confirmation.confirmation_id,
                              "tenant-a.user", True)
    assert (done.status.value, done.final_stage) == ("NORMAL", "S11")
    return first, done.final_state


def test_create_then_list_runs_from_the_request_to_completed_steps(pg):
    async def body(db):
        state = await _certified(db, CREATE_LIST)
        out = await _admit(db, state)
        adapter, verify = Adapter(), Verify("PASS")
        result = await run_execution(_deps(db, adapter, verify), A, out.execution_id)
        return state, out, result, adapter.calls, verify.seen, await _rows(db)
    state, out, result, calls, verified, (run, steps, budget, _) = pg(body, *WORKER, *CHAIN_CATALOG_SQL)
    assert out.status == "ADMITTED" and run["status"] == "completed"     # budget_spent: finding P1-F1
    assert [c[1] for c in calls] == ["crm.contact_create", "crm.contact_list"]
    assert verified == ["step-1", "step-2"]                 # every step is asked (finding P1-F6)
    assert [b["status"] for b in budget] == ["committed", "committed"]
    assert json.loads(steps[0]["undo_token"])["inverse_kernel_op_id"] == "crm.contact_delete"
    assert steps[1]["undo_token"] is None
    assert run["status"] == "completed"


def test_create_then_delete_needs_confirmation_and_the_delete_is_verified_by_absence(pg):
    async def body(db):
        first, state = await _through_confirmation(db, CREATE_DELETE)
        ops = first.final_state.confirmation.confirmation.operations
        out = await _admit(db, state)
        verify = Verify("PASS")
        result = await run_execution(_deps(db, Adapter(), verify), A, out.execution_id)
        # the certified loop hands its verifier the step, not the Verifier: read the frozen verifiers instead
        async with db.tenant_transaction(A) as c:
            frozen = json.loads(await c.fetchval("SELECT verifiers FROM execution_plans WHERE execution_id = $1",
                                                 out.execution_id))
        seen = [(v["step_id"], v["expected_state"]) for v in frozen if v["step_id"] in verify.seen]
        return ops, out, result, seen, await _rows(db)
    ops, out, result, seen, (run, steps, budget, _) = pg(body, *WORKER, *CHAIN_CATALOG_SQL)
    assert [(o["kernel_op_id"], o["mutation"]) for o in ops] == [("crm.contact_create", "W"), ("crm.contact_delete", "D")]
    assert ops[1]["params"] == {"id": "c-1"} and [o["undoable"] for o in ops] == [True, False]
    assert run["status"] == "completed"
    assert seen == [("step-1", {"exists": True, "properties": {"name": "Ana Silva"}}), ("step-2", {"exists": False})]
    assert [b["cost"] for b in budget] == [3, 5]


def test_a_delete_that_the_verifier_finds_still_present_leaves_a_partial_run(pg):
    async def body(db):
        _, state = await _through_confirmation(db, CREATE_DELETE)
        out = await _admit(db, state)

        async def by_step(step, binding, result):
            return "PASS" if step.id == "step-1" else "FAIL"
        result = await run_execution(_deps(db, Adapter(), by_step), A, out.execution_id)
        return result, await _rows(db)
    result, (run, steps, budget, _) = pg(body, *WORKER, *CHAIN_CATALOG_SQL)
    assert run["status"] == "partial"                     # budget_spent: finding P1-F1
    assert _summary(steps) == [("step-1", "completed", None), ("step-2", "failed", None)]
    assert [b["status"] for b in budget] == ["committed", "released"]
    assert steps[0]["undo_token"] is not None          # the completed create can be undone (S13, later)


def test_the_kill_switch_engaged_between_admission_and_execution_cancels_the_chain(pg):
    async def body(db):
        state = await _certified(db, CREATE_LIST)
        out = await _admit(db, state)
        async with db.transaction() as c:
            await c.execute("UPDATE system_settings SET kill_switch_engaged = true")
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, Verify(), admission=PostgresAdmissionSnapshot(db)), A,
                                     out.execution_id)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, _, _, _) = pg(body, *WORKER, *CHAIN_CATALOG_SQL)
    assert (run["status"], run["terminal_reason"], calls) == ("cancelled", "kill_switch_engaged", [])


def test_without_registry_observation_data_a_mutating_chain_is_refused_at_s12_entry(pg):
    async def body(db):
        state = await _certified(db, CREATE_LIST)
        return await _admit(db, state), await _count(db, A, "execution_runs")
    out, runs = pg(body)                              # the default seed has no observation methods
    assert (out.status, out.reason, runs) == ("DENIED", "verifier_metadata_unavailable", 0)


def test_the_registry_reports_the_inverse_the_step_carries(pg):
    async def body(db):
        state = await _certified(db, CREATE_LIST)
        return [(s.kernel_op_id, s.inverse) for s in state.plan.plan.steps]
    assert pg(body, *WORKER, *CHAIN_CATALOG_SQL) == [("crm.contact_create", "crm.contact_delete"), ("crm.contact_list", None)]
