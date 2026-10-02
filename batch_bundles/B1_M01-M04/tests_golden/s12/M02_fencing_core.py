"""M2 golden — fenced_write(), repositories, transition log, settings (gate commit C part 2). Owner-pinned.

Gate v10: C5 (fenced_write, FencedOut), C24 (reason on every transition, log columns), C25 (per-execution fence, no
session middleware), C34 (every repository query filters on tenant_id), C37 (timeout ordering), §21 S1 (one settings
object from the environment), S3 (no module state). Invariant I5 starts here (tests_golden/fixtures/invariants.py).

Interface this file fixes:
  * ``adapters.postgres.fencing``:
      ``FenceHolder(tenant_id, execution_id, runtime_instance_id, fence_token)`` (frozen dataclass);
      ``async fenced_write(database, holder, write)`` opens ONE tenant transaction, checks
      ``execution_ownership.fencing_token = holder.fence_token AND runtime_instance_id = holder.runtime_instance_id``
      for ``holder.execution_id`` while locking that row against a concurrent takeover, then returns
      ``await write(connection)``. No matching row → ``contracts.step_execution.FencedOut``; ``write`` is not called.
      An exception from ``write`` rolls everything back.
  * ``adapters.postgres.transition_log.log_transition(connection, *, tenant_id, machine, entity_id, from_state,
      to_state, reason, runtime_instance_id, fence_token, execution_id=None)`` inserts exactly one row.
  * ``engine.stages.s12_execute.settings.ExecutionSettings``: fields ``adapter_client_timeout_s``, ``step_timeout_s``,
      ``probe_timeout_s``, ``lease_ttl_s``, ``lease_renewal_interval_s``; ``ExecutionSettings.from_env(mapping)`` reads
      ``S12_ADAPTER_CLIENT_TIMEOUT_S``, ``S12_STEP_TIMEOUT_S``, ``S12_PROBE_TIMEOUT_S``, ``S12_LEASE_TTL_S``,
      ``S12_LEASE_RENEWAL_INTERVAL_S``; a violation of C37 raises ``ValueError`` at construction.
"""
from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests_golden.fixtures.code_scan import ROOT, frozen_changes, s12_files, sql_statements
from tests_golden.fixtures.invariants import assert_system_invariants, transition_problems

T = "golden-tenant"
RUNTIME = "runtime-A"


async def _seed(schema, execution_id: str, token: int = 7, runtime: str = RUNTIME) -> None:
    await schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id)"
        " VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1') ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('golden-ws', $1, 'w')"
                         " ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ('golden-user', $1, 'active')"
                         " ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute(
        "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
        " conversation_id, status, actor_type, actor_id, budget_spent)"
        " VALUES ($1, $1, 'tr', 'task', 'golden-user', $2, 'golden-ws', 'conv', 'pending', 'user', 'golden-user', 0)",
        execution_id, T, tenant=T)
    await schema.execute(
        "INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token, checkpoint_sequence,"
        " updated_at) VALUES ($1, $2, $3, $4, 0, now())", execution_id, T, runtime, token, tenant=T)


def _holder(execution_id: str, token: int = 7, runtime: str = RUNTIME):
    from adapters.postgres.fencing import FenceHolder
    return FenceHolder(tenant_id=T, execution_id=execution_id, runtime_instance_id=runtime, fence_token=token)


def _mark(execution_id: str):
    async def write(connection):
        await connection.execute("UPDATE execution_runs SET budget_spent = budget_spent + 1 WHERE execution_id = $1",
                                 execution_id)
        return "written"
    return write


async def _spent(schema, execution_id: str) -> int:
    return await schema.fetchval("SELECT budget_spent FROM execution_runs WHERE execution_id = $1", execution_id,
                                 tenant=T)


# --- fenced_write ----------------------------------------------------------------------------------------------

def test_current_holder_writes(db_schema, run):
    from adapters.postgres.fencing import fenced_write
    run(_seed(db_schema, "fw-ok"))
    assert run(fenced_write(db_schema.database(), _holder("fw-ok"), _mark("fw-ok"))) == "written"
    assert run(_spent(db_schema, "fw-ok")) == 1


@pytest.mark.parametrize("token,runtime", [(6, RUNTIME), (8, RUNTIME), (7, "runtime-B")])
def test_stale_or_foreign_holder_is_fenced_out_and_writes_nothing(db_schema, run, token, runtime):
    from adapters.postgres.fencing import fenced_write
    from contracts.step_execution import FencedOut
    execution_id = f"fw-stale-{token}-{runtime}"
    run(_seed(db_schema, execution_id))
    called = []

    async def write(connection):
        called.append(True)
        await _mark(execution_id)(connection)

    with pytest.raises(FencedOut):
        run(fenced_write(db_schema.database(), _holder(execution_id, token, runtime), write))
    assert called == [] and run(_spent(db_schema, execution_id)) == 0


def test_no_ownership_row_is_fenced_out(db_schema, run):
    from adapters.postgres.fencing import fenced_write
    from contracts.step_execution import FencedOut
    run(_seed(db_schema, "fw-none"))
    run(db_schema.execute("DELETE FROM execution_ownership WHERE execution_id = 'fw-none'", tenant=T))
    with pytest.raises(FencedOut):
        run(fenced_write(db_schema.database(), _holder("fw-none"), _mark("fw-none")))


def test_other_tenant_holder_is_fenced_out(db_schema, run):
    from adapters.postgres.fencing import FenceHolder, fenced_write
    from contracts.step_execution import FencedOut
    run(_seed(db_schema, "fw-tenant"))
    other = FenceHolder(tenant_id="someone-else", execution_id="fw-tenant", runtime_instance_id=RUNTIME, fence_token=7)
    with pytest.raises(FencedOut):
        run(fenced_write(db_schema.database(), other, _mark("fw-tenant")))
    assert run(_spent(db_schema, "fw-tenant")) == 0


def test_failing_write_rolls_back(db_schema, run):
    from adapters.postgres.fencing import fenced_write
    run(_seed(db_schema, "fw-rollback"))

    async def write(connection):
        await _mark("fw-rollback")(connection)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run(fenced_write(db_schema.database(), _holder("fw-rollback"), write))
    assert run(_spent(db_schema, "fw-rollback")) == 0


def test_takeover_waits_for_an_open_fenced_write_then_fences_the_old_owner(db_schema, run):
    """The fence row is locked for the whole write: a takeover cannot slip in between check and commit (C5, C25)."""
    from adapters.postgres.fencing import fenced_write
    from contracts.step_execution import FencedOut
    run(_seed(db_schema, "fw-race"))

    async def scenario():
        inside, release = asyncio.Event(), asyncio.Event()

        async def slow_write(connection):
            inside.set()
            await release.wait()
            await _mark("fw-race")(connection)

        writer = asyncio.create_task(fenced_write(db_schema.database(), _holder("fw-race"), slow_write))
        await asyncio.wait_for(inside.wait(), 5)
        blocked = False
        try:
            await db_schema.execute("SET LOCAL lock_timeout = '300ms'; UPDATE execution_ownership SET fencing_token = 9,"
                                    " runtime_instance_id = 'runtime-B' WHERE execution_id = 'fw-race'", tenant=T)
        except asyncpg.LockNotAvailableError:
            blocked = True
        finally:
            release.set()
            await asyncio.wait_for(writer, 5)
        assert blocked, "a takeover committed while a fenced write for the old owner was open"
        await db_schema.execute("UPDATE execution_ownership SET fencing_token = 9, runtime_instance_id = 'runtime-B'"
                                " WHERE execution_id = 'fw-race'", tenant=T)
        with pytest.raises(FencedOut):
            await fenced_write(db_schema.database(), _holder("fw-race"), _mark("fw-race"))
        assert await _spent(db_schema, "fw-race") == 1

    run(scenario())


# --- Transition log (C24) and I5 -------------------------------------------------------------------------------

def test_log_transition_writes_one_complete_row(db_schema, run):
    from adapters.postgres.fencing import fenced_write
    from adapters.postgres.transition_log import log_transition
    run(_seed(db_schema, "log-1"))

    async def write(connection):
        await log_transition(connection, tenant_id=T, machine="run", entity_id="log-1", from_state=None,
                             to_state="pending", reason="created", runtime_instance_id=RUNTIME, fence_token=7,
                             execution_id="log-1")
        await log_transition(connection, tenant_id=T, machine="run", entity_id="log-1", from_state="pending",
                             to_state="running", reason="admitted", runtime_instance_id=RUNTIME, fence_token=7,
                             execution_id="log-1")

    run(fenced_write(db_schema.database(), _holder("log-1"), write))
    rows = run(db_schema.fetch("SELECT * FROM state_transitions WHERE entity_id = 'log-1' ORDER BY transition_id",
                               tenant=T))
    assert len(rows) == 2
    got = [(r["tenant_id"], r["from_state"], r["to_state"], r["reason"], r["runtime_instance_id"], r["fence_token"])
           for r in rows]
    assert got == [(T, None, "pending", "created", RUNTIME, 7), (T, "pending", "running", "admitted", RUNTIME, 7)]
    run(assert_system_invariants(db_schema))


def test_invariant_checker_rejects_illegal_rows():
    """Self-test of the I5 checker (fixture), so a broken checker cannot pass silently."""
    rows = [{"machine": "step", "entity_id": "s", "from_state": "timeout", "to_state": "dead_letter", "reason": "x"},
            {"machine": "run", "entity_id": "r", "from_state": "pending", "to_state": "running", "reason": "started"},
            {"machine": "step", "entity_id": "s", "from_state": None, "to_state": "running", "reason": "created"},
            {"machine": "step", "entity_id": "s", "from_state": "pending", "to_state": "cancelled", "reason": "no_worker"},
            {"machine": "episode", "entity_id": "e", "from_state": "none", "to_state": "pending_probe", "reason": "opened"}]
    assert len(transition_problems(rows)) == 3


# --- Settings (S1, C37) ----------------------------------------------------------------------------------------

VALID = {"S12_ADAPTER_CLIENT_TIMEOUT_S": "10", "S12_STEP_TIMEOUT_S": "30", "S12_PROBE_TIMEOUT_S": "5",
         "S12_LEASE_TTL_S": "30", "S12_LEASE_RENEWAL_INTERVAL_S": "10"}


def test_settings_from_environment():
    from engine.stages.s12_execute.settings import ExecutionSettings
    s = ExecutionSettings.from_env(VALID)
    assert (s.adapter_client_timeout_s, s.step_timeout_s, s.probe_timeout_s, s.lease_ttl_s,
            s.lease_renewal_interval_s) == (10, 30, 5, 30, 10)


@pytest.mark.parametrize("override", [
    {"S12_ADAPTER_CLIENT_TIMEOUT_S": "30"},          # adapter_client_timeout must be < step_timeout
    {"S12_PROBE_TIMEOUT_S": "31"},                   # probe_timeout must be < step_timeout
    {"S12_LEASE_RENEWAL_INTERVAL_S": "11"},          # lease_ttl must be >= 3 x renewal interval
])
def test_settings_reject_inverted_timeouts(override):
    from engine.stages.s12_execute.settings import ExecutionSettings
    with pytest.raises(ValueError):
        ExecutionSettings.from_env({**VALID, **override})


def test_settings_boundary_is_allowed():
    from engine.stages.s12_execute.settings import ExecutionSettings
    ExecutionSettings.from_env({**VALID, "S12_LEASE_TTL_S": "30", "S12_LEASE_RENEWAL_INTERVAL_S": "10"})


# --- Architecture ----------------------------------------------------------------------------------------------

def test_fencing_modules_exist_as_s12_code():
    names = {p.relative_to(ROOT).as_posix() for p in s12_files()}
    assert {"src/adapters/postgres/fencing.py", "src/adapters/postgres/transition_log.py",
            "src/engine/stages/s12_execute/settings.py"} <= names


def test_every_s12_query_filters_on_tenant_id():
    """C34: every repository statement on an S12 table names tenant_id (RLS is the second line, not the only one)."""
    missing = [f"{p.name}:{line}" for p in s12_files() for line, sql in sql_statements(p) if "tenant_id" not in sql]
    assert missing == []


def test_s0_s11_code_unchanged_since_the_tag():
    assert frozen_changes() == []
