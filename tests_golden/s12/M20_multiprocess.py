"""M20 golden — real Worker Runtime processes, two runtimes on one database, tenant isolation (gate commit L part 2).
Owner-pinned.

Gate v10: §15.2 (at least three tests kill a real Worker Runtime subprocess with ``Popen.kill()`` mid-execution and
recover in a new process), suite 14, suite 17 (two Worker Runtime processes on one database: one owner per execution
at a time; after a kill the other's sweeper takes over; no step executes twice; invariants hold), suite 18 (a runtime
working for tenant A cannot read or modify tenant B's executions, reservations, leases or dead letters; RLS enforces it
at the database; every row carries its tenant, C34), §21 S4 (``FOR UPDATE SKIP LOCKED``: sweepers never claim the same
execution), S9 (portable: ``subprocess`` + ``Popen.kill()``, ``pathlib``, no POSIX-only process APIs in the engine).
Rulings: CONF-033, CONF-042 (M19).

Interface this file relies on (all fixed by M19 and earlier): ``RecoverySweeper``, ``recover_execution``,
``run_execution``, M17's dependencies, ``PostgresLeaseManager.acquire(..., skip_locked=True)``. The process itself is
the owner fixture ``tests_golden/fixtures/runtime_process.py`` (a ``FileProvider`` whose side effects are an
append-only file shared by every process).
"""
from __future__ import annotations

import dataclasses
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _order, _state, _steps

LEASE_TTL_S = 1.0


# --- real processes (§15.2, S9) --------------------------------------------------------------------------------------

class Runtime:
    """One Worker Runtime process; its stdout lines are read on a thread (portable: no select on pipes)."""
    def __init__(self, schema, runtime_id, effects, *args):
        from tests_golden.fixtures.code_scan import ROOT
        from tests_golden.fixtures.db import golden_database_url
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
        self.lines: queue.Queue = queue.Queue()
        self.seen: list[str] = []
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tests_golden.fixtures.runtime_process", "--url", golden_database_url(),
             "--schema", schema.name, "--runtime", runtime_id, "--effects", str(effects), "--ttl", str(LEASE_TTL_S),
             *args], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))

    def wait_for(self, prefix, timeout=30.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                if self.proc.poll() is not None and self.lines.empty():
                    break
                continue
            self.seen.append(line)
            if line.startswith(prefix):
                return line
        raise AssertionError(f"no {prefix!r} from {self.proc.args[-1]}; output: {self.seen[-20:]}")

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()                                          # portable: TerminateProcess / SIGKILL
        self.proc.wait(timeout=10)


def _executions(effects):
    from tests_golden.fixtures.runtime_process import executions
    return executions(Path(effects))


def _until(check, timeout=30.0, message="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {message}")


def _status(schema, run, execution):
    return run(schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution))


def _no_usable_lease(schema, run, execution):
    return run(schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1 AND status = 'active'"
                               " AND expires_at > now()", execution)) == 0


def _max_concurrent_leases(schema, run, execution):
    """From the lease log in commit order: how many leases of the execution were active at once, at most."""
    rows = run(schema.fetch(
        "SELECT t.to_state, t.from_state FROM state_transitions t JOIN worker_leases l ON l.lease_id = t.entity_id"
        " WHERE t.entity_type = 'lease' AND l.execution_id = $1 ORDER BY t.transition_id", execution))
    active = peak = 0
    for r in rows:
        if r["from_state"] is None and r["to_state"] == "active":
            active += 1
        elif r["from_state"] == "active" and r["to_state"] in ("released", "expired"):
            active -= 1
        peak = max(peak, active)
    return peak


def _episodes(schema, run, step_id):
    return [(r["kind"], r["outcome"]) for r in run(schema.fetch(
        "SELECT kind, outcome FROM step_reconciliations WHERE step_id = $1 ORDER BY opened_at", step_id))]


@pytest.mark.parametrize("hang,expected", [
    ("call", ("EXECUTION", "NOT_EXECUTED")),                 # killed before the side effect: probe, then a retry
    ("after_call", ("EXECUTION", "EXECUTED_SUCCESS")),       # killed after it: the probe finds it, no second call
    ("observe", ("VERIFICATION", "VERIFIED_PASS")),          # killed while verifying: the ledger answers, no probe
])
def test_a_killed_worker_runtime_process_is_recovered_by_a_new_one(db_schema, run, tmp_path, hang, expected):
    state = _state(f"golden-proc-kill-{hang}", f"prockill{hang.replace('_', '')}")
    tenant, execution = _admit(db_schema, run, state)
    effects = tmp_path / "effects.jsonl"
    first = Runtime(db_schema, "runtime-A", effects, "--run", tenant, execution, "--hang", hang)   # the owner
    try:
        first.wait_for("HANG")
    finally:
        first.kill()
    _until(lambda: _no_usable_lease(db_schema, run, execution), 10, "the killed runtime's lease to lapse")
    second = Runtime(db_schema, "runtime-P2", effects, "--sweep", "30")
    try:
        _until(lambda: _status(db_schema, run, execution) == "completed", 40, "the recovered run to complete")
    finally:
        second.kill()
    keys = _executions(effects)
    for sid in _order(state):
        assert keys.count(f"{state.execution_context.request_id}:{sid}") == 1, sid            # never twice
    step_id = _steps(db_schema, run, execution)[_order(state)[0]]["step_id"]
    assert expected in _episodes(db_schema, run, step_id)
    assert run(db_schema.fetchval("SELECT runtime_instance_id FROM execution_ownership WHERE execution_id = $1",
                                  execution)) == "runtime-P2"
    run(assert_system_invariants(db_schema))


def test_two_worker_runtimes_share_the_work_and_one_takes_over_after_the_other_is_killed(db_schema, run, tmp_path):
    states = [_state(f"golden-proc-pair-{i}", f"procpair{i}") for i in range(4)]
    admitted = [_admit(db_schema, run, s) for s in states]            # orphaned: owned by the admitting runtime
    effects = tmp_path / "effects.jsonl"
    first = Runtime(db_schema, "runtime-P1", effects, "--sweep", "40", "--hang", "call")
    second = None
    try:
        hung = first.wait_for("HANG")
        second = Runtime(db_schema, "runtime-P2", effects, "--sweep", "40")
        second.wait_for("STARTED")
        time.sleep(0.5)
        first.kill()                                                  # P1 dies holding one run
        _until(lambda: all(_status(db_schema, run, e) == "completed" for _, e in admitted), 60,
               "every run to complete")
    finally:
        first.kill()
        if second is not None:
            second.kill()
    keys = _executions(effects)
    for state in states:
        for sid in _order(state):
            assert keys.count(f"{state.execution_context.request_id}:{sid}") == 1, (state.plan.execution_id, sid)
    hung_key = hung.split()[-1]
    hung_execution = next(e for s, (_, e) in zip(states, admitted, strict=True)
                          if hung_key.startswith(s.execution_context.request_id + ":"))
    assert run(db_schema.fetchval("SELECT runtime_instance_id FROM execution_ownership WHERE execution_id = $1",
                                  hung_execution)) == "runtime-P2"                     # taken over after the kill
    for _, execution in admitted:
        assert _max_concurrent_leases(db_schema, run, execution) <= 1, execution    # one owner at a time
    run(assert_system_invariants(db_schema))


def test_two_sweeping_processes_claim_every_orphaned_run_exactly_once(db_schema, run, tmp_path):
    states = [_state(f"golden-proc-race-{i}", f"procrace{i}") for i in range(6)]
    admitted = [_admit(db_schema, run, s) for s in states]
    effects = tmp_path / "effects.jsonl"
    pair = [Runtime(db_schema, f"runtime-R{i}", effects, "--sweep", "40") for i in (1, 2)]
    try:
        _until(lambda: all(_status(db_schema, run, e) == "completed" for _, e in admitted), 60,
               "every run to complete")
    finally:
        for p in pair:
            p.kill()
    keys = _executions(effects)
    assert len(keys) == len(set(keys)) == sum(len(s.plan.plan.steps) for s in states)
    for _, execution in admitted:
        takers = {r["runtime_instance_id"] for r in run(db_schema.fetch(
            "SELECT runtime_instance_id FROM state_transitions WHERE execution_id = $1 AND entity_type = 'step'"
            " AND runtime_instance_id LIKE 'runtime-R%'", execution))}
        assert len(takers) == 1, (execution, takers)                   # claimed by exactly one sweeper
        assert _max_concurrent_leases(db_schema, run, execution) <= 1
    run(assert_system_invariants(db_schema))


# --- SKIP LOCKED, in process (§21 S4) --------------------------------------------------------------------------------

def test_a_sweeper_skips_an_execution_another_sweeper_holds(db_schema, run):
    import asyncio
    from engine.stages.s12_execute.loop import recover_execution
    from tests_golden.s12.M17_dead_letter import _dl_deps
    from tests_golden.s12.M12_loop import _mock
    state = _state("golden-proc-skip", "procskip")
    tenant, execution = _admit(db_schema, run, state)
    deps = dataclasses.replace(_dl_deps(db_schema, _mock()), runtime_instance_id="runtime-S")

    async def while_held():
        async with db_schema.database().tenant_transaction(tenant) as c:
            await c.execute("SELECT 1 FROM execution_ownership WHERE execution_id = $1 FOR UPDATE", execution)
            return await asyncio.wait_for(recover_execution(deps, tenant, execution), 5)

    result = run(while_held())
    assert result.reason == "not_orphaned"
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1", execution)) == 0
    run(recover_execution(deps, tenant, execution))                               # released: now it is taken
    assert _status(db_schema, run, execution) == "completed"
    run(assert_system_invariants(db_schema))


# --- tenant isolation (suite 18, C34) --------------------------------------------------------------------------------

def test_a_runtime_for_one_tenant_can_neither_read_nor_change_another_tenants_rows(db_schema, run):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from adapters.postgres.fencing import FenceHolder, fenced_write
    from adapters.postgres.run_summary import PostgresRunSummaries
    from contracts.step_execution import FencedOut
    from tests_golden.s12.M12_loop import _mock
    from tests_golden.s12.M17_dead_letter import _dl_deps
    from engine.stages.s12_execute.loop import run_execution
    a_state, b_state = _state("golden-proc-tenant-a", "proctenanta"), _state("golden-proc-tenant-b", "proctenantb")
    a_tenant, _ = _admit(db_schema, run, a_state)
    b_tenant, b_execution = _admit(db_schema, run, b_state)
    b_first = _order(b_state)[0]
    run(run_execution(_dl_deps(db_schema, _mock(**{b_state.plan.plan.steps[0].kernel_op_id: {
        "call": "fail_500_then_success", "n": 9}})), b_tenant, b_execution))     # B now has a dead letter too
    db = db_schema.database()
    tables = ("execution_runs", "execution_steps", "budget_reservations", "worker_leases", "dead_letters",
              "execution_events", "step_reconciliations", "execution_ownership", "execution_plans")

    async def as_tenant_a():
        seen, changed = {}, {}
        async with db.tenant_transaction(a_tenant) as c:
            for table in tables:
                seen[table] = await c.fetchval(f"SELECT count(*) FROM {table} WHERE execution_id = $1", b_execution)
            for table, column in (("execution_runs", "status"), ("execution_steps", "status"),
                                  ("budget_reservations", "status"), ("worker_leases", "status"),
                                  ("dead_letters", "status")):
                changed[table] = await c.execute(f"UPDATE {table} SET {column} = {column} WHERE execution_id = $1",
                                                 b_execution)
        return seen, changed

    seen, changed = run(as_tenant_a())
    assert set(seen.values()) == {0}, seen
    assert set(changed.values()) == {"UPDATE 0"}, changed
    owner = run(db_schema.fetch("SELECT runtime_instance_id, fencing_token FROM execution_ownership"
                                " WHERE execution_id = $1", b_execution))[0]
    foreign = FenceHolder(tenant_id=a_tenant, execution_id=b_execution, runtime_instance_id=owner["runtime_instance_id"],
                          fence_token=owner["fencing_token"])

    async def noop(c):
        return None
    with pytest.raises(FencedOut):
        run(fenced_write(db, foreign, noop))
    (letter,) = [r["dead_letter_id"] for r in run(db_schema.fetch(
        "SELECT dead_letter_id FROM dead_letters WHERE execution_id = $1", b_execution))]
    assert run(PostgresDeadLetters(db).get(a_tenant, letter)) is None
    assert run(PostgresRunSummaries(db).load(a_tenant, b_execution)) is None
    assert _steps(db_schema, run, b_execution)[b_first]["status"] == "failed"
    run(assert_system_invariants(db_schema))                                       # includes I15


def test_a_runtime_for_one_tenant_can_neither_forge_rows_for_another_nor_claim_its_runs(db_schema, run):
    """Suite 18, writes: RLS checks the row written, not only the rows read (42501 on a forged tenant); the ledger,
    the transition log and the manifests are hidden as well; and a run is claimed only under its own tenant (the
    discovery function's ids are data, never a licence: recovery under the wrong tenant finds no run)."""
    import asyncpg
    from engine.stages.s12_execute.loop import recover_execution
    from tests_golden.s12.M12_loop import _mock
    from tests_golden.s12.M17_dead_letter import _dl_deps
    from engine.stages.s12_execute.loop import run_execution
    a_state, b_state = _state("golden-proc-forge-a", "procforgea"), _state("golden-proc-forge-b", "procforgeb")
    a_tenant, a_execution = _admit(db_schema, run, a_state)
    b_tenant, b_execution = _admit(db_schema, run, b_state)
    run(run_execution(_dl_deps(db_schema, _mock()), b_tenant, b_execution))
    db = db_schema.database()
    b_request = b_state.execution_context.request_id

    async def hidden():
        async with db.tenant_transaction(a_tenant) as c:
            return {
                "state_transitions": await c.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1",
                                                      b_execution),
                "execution_manifests": await c.fetchval(
                    "SELECT count(*) FROM execution_manifests WHERE execution_id = $1", b_execution),
                "checkpoints": await c.fetchval("SELECT count(*) FROM checkpoints WHERE execution_id = $1",
                                                b_execution),
                "idempotency_ledger": await c.fetchval(
                    "SELECT count(*) FROM idempotency_ledger WHERE idempotency_key LIKE $1", b_request + ":%"),
            }
    assert set(run(hidden()).values()) == {0}
    assert run(db_schema.fetchval("SELECT count(*) FROM idempotency_ledger WHERE idempotency_key LIKE $1",
                                  b_request + ":%")) > 0                          # they exist; A cannot see them

    async def forge(sql, *args):
        async with db.tenant_transaction(a_tenant) as c:
            await c.execute(sql, *args)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                    # moving a row into B's tenant
        run(forge("UPDATE execution_runs SET tenant_id = $1 WHERE execution_id = $2", b_tenant, a_execution))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                    # writing a row for B
        run(forge("INSERT INTO state_transitions (tenant_id, execution_id, entity_type, entity_id, from_state,"
                  " to_state, reason, runtime_instance_id) VALUES ($1, $2, 'run', $2, 'completed', 'running',"
                  " 'forged', 'runtime-X')", b_tenant, b_execution))
    before = run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1", b_execution))
    with pytest.raises(LookupError):
        run(recover_execution(dataclasses.replace(_dl_deps(db_schema, _mock()), runtime_instance_id="runtime-X"),
                              a_tenant, b_execution))
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1",
                                  b_execution)) == before
    assert run(db_schema.fetchval("SELECT tenant_id FROM execution_runs WHERE execution_id = $1",
                                  a_execution)) == a_tenant
    run(assert_system_invariants(db_schema))


def test_every_s12_table_forces_row_level_security_on_its_tenant(db_schema, run):
    from tests_golden.fixtures.code_scan import S12_TABLES
    rows = run(db_schema.fetch(
        "SELECT c.relname, c.relrowsecurity AND c.relforcerowsecurity AS forced,"
        " EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS policy,"
        " EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema = $1 AND k.table_name = c.relname"
        "  AND k.column_name = 'tenant_id' AND k.is_nullable = 'NO') AS tenant"
        " FROM pg_class c WHERE c.relnamespace = $1::regnamespace AND c.relkind = 'r'", db_schema.name))
    found = {r["relname"]: (r["forced"], r["policy"], r["tenant"]) for r in rows}
    expected = set(S12_TABLES) | {"execution_events", "idempotency_ledger"}
    assert {t: found.get(t) for t in expected if found.get(t) != (True, True, True)} == {}


# --- portability (§21 S9) --------------------------------------------------------------------------------------------

def test_the_engine_uses_no_posix_only_process_apis_or_fixed_paths():
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    banned = ("os.fork(", "signal.SIGTERM", "signal.SIGKILL", "signal.signal(", "os.kill(", "'/tmp", '"/tmp',
              "os.setsid", "preexec_fn")
    offenders = sorted({f"{p.relative_to(ROOT).as_posix()}:{b}" for p in s12_files()
                        for b in banned if b in p.read_text(encoding="utf-8")})
    assert offenders == []
