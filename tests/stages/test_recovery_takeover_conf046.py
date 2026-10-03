"""CONF-046 at the recovery takeover (regression for the M20 two-sweeper race).

A sweeper may act on a candidate list fetched earlier. Its takeover (``PostgresLeaseManager.acquire(...,
skip_locked=True)``) must therefore re-apply CONF-046 under the ownership lock: a run whose latest lease was released
less than one lease TTL ago belongs to a live owner between two steps, so it is not orphaned and nothing is written.
Needs real PostgreSQL (TEST_DATABASE_URL); reuses the golden M19 helpers and fixtures read-only.
"""
from __future__ import annotations

import os

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("needs TEST_DATABASE_URL (real PostgreSQL)", allow_module_level=True)

from tests_golden.conftest import db_schema, run  # noqa: E402,F401 - fixtures
from tests_golden.s12.M19_recovery import (  # noqa: E402
    RECOVERING, CrashAt, _admit, _crash, _full, _mocked, _run_status, _state)


def _count(schema, run, table, execution):
    return run(schema.fetchval(f"SELECT count(*) FROM {table} WHERE execution_id = $1", execution))


def test_a_takeover_between_two_steps_of_a_live_owner_is_refused_until_a_ttl_has_passed(db_schema, run):
    from adapters.postgres.leases import Lease, PostgresLeaseManager
    from engine.stages.s12_execute.loop import recover_execution
    state = _state("unit-conf046-takeover", "conf046takeover")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_commit_before_checkpoint")), tenant, execution)
    row = run(db_schema.fetch("SELECT * FROM worker_leases WHERE execution_id = $1 AND status = 'active'",
                              execution))[0]
    lease = Lease(lease_id=row["lease_id"], tenant_id=tenant, worker_id=row["worker_id"], execution_id=execution,
                  fence_token=row["fence_token"])
    assert run(PostgresLeaseManager(db_schema.database()).release(lease, reason="work_complete")) is True
    leases, moves = _count(db_schema, run, "worker_leases", execution), _count(db_schema, run, "state_transitions",
                                                                               execution)

    result = run(recover_execution(_full(db_schema, mock, runtime=RECOVERING), tenant, execution))
    assert result.reason == "not_orphaned"                                    # live owner between steps
    assert _count(db_schema, run, "worker_leases", execution) == leases       # no lease written
    assert _count(db_schema, run, "state_transitions", execution) == moves    # nothing logged

    run(db_schema.execute("UPDATE worker_leases SET released_at = now() - interval '31 seconds' WHERE lease_id = $1",
                          row["lease_id"]))                                   # _dl_deps: lease_ttl_s = 30
    run(recover_execution(_full(db_schema, mock, runtime=RECOVERING), tenant, execution))
    assert _run_status(db_schema, run, execution) == "completed"              # silent for a TTL: taken over
