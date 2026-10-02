"""M1 golden — S12–S15 schema (gate commit C part 1). Owner-pinned: Fable never edits this file.

Gate v10: §7.3 (+ v9/v10 additions), C16, C18, C20, C21, C22, C26, C27, C28, C33, C34, C35, C39; ruling CONF-007
(`operation_quotas.worker_id`, S12_RECORDS.md). Sources: DATABASE.md "S12–S15 Additive Tables", table notes for
checkpoints, dead_letters, idempotency_ledger, workers, worker_leases.

Interface this file fixes (plan §3: the golden files define interfaces, Fable implements them):
  * module ``contracts.execution_states`` with the StrEnums below; every CHECK constraint on the listed column
    must have exactly the enum's value set (C28: one source, CHECKs generated from the enums);
  * new tables are created by new migration files (015+); 001–014 are inside the ``s0-s11-certified`` tag;
  * timestamp columns of tables created in this phase are ``TIMESTAMPTZ`` (C33);
  * a row inserted with only the columns used in the ``_insert_*`` helpers below must be valid (every other column
    is nullable or defaulted).
"""
from __future__ import annotations

import re

import asyncpg
import pytest

from adapters.postgres.migrate import migration_files

ENUMS = "contracts.execution_states"

# (table, column) -> (enum class in contracts.execution_states, values the CHECK must exclude)
CHECKED = {
    ("execution_runs", "status"): ("ExecutionStatus", ()),
    ("execution_steps", "status"): ("StepState", ()),
    ("execution_steps", "terminal_reason"): ("StepTerminalReason", ()),
    ("budget_reservations", "status"): ("ReservationState", ()),
    ("step_reconciliations", "status"): ("ReconciliationStatus", ("none",)),   # none is never stored (C18, A.7)
    ("step_reconciliations", "kind"): ("ReconciliationKind", ()),
    ("step_reconciliations", "outcome"): ("ReconciliationOutcome", ()),
    ("worker_leases", "status"): ("LeaseStatus", ()),
    ("dead_letters", "status"): ("DeadLetterStatus", ()),
    ("dead_letters", "error_type"): ("DeadLetterErrorType", ()),
    ("dead_letters", "retry_mode"): ("RetryMode", ()),
    ("dead_letters", "resolution_outcome"): ("ResolutionOutcome", ()),
    ("dead_letters", "origin"): ("DeadLetterOrigin", ()),
    ("pending_confirmations", "status"): ("ConfirmationStatus", ()),
    ("workers", "runtime_type"): ("RuntimeType", ()),
}

# The values the gate text states for each enum (C18, C21, C26, C27, C28, DATA_CONTRACTS §19, §22, §50, StepTerminalReason).
EXPECTED_ENUM_VALUES = {
    "ExecutionStatus": {"pending", "running", "reconciling", "completed", "partial", "failed", "cancelled", "dead_letter"},
    "StepState": {"pending", "running", "completed", "partial", "failed", "cancelled", "skipped", "timeout", "unknown",
                  "pending_probe", "dead_letter"},
    "StepTerminalReason": {"user_cancelled", "admission_rejected", "admission_exhausted", "no_worker", "lease_unavailable",
                           "budget_exhausted", "preflight_failed", "not_executed_no_retry", "dependency_failed",
                           "run_dead_lettered", "authorization_revoked", "kill_switch_engaged", "binding_invalid",
                           "credential_invalid"},
    "ReservationState": {"reserved", "locked", "committed", "released"},
    "ReconciliationStatus": {"none", "pending_probe", "reconciling", "confirmed_success", "confirmed_failure"},
    "ReconciliationKind": {"EXECUTION", "VERIFICATION"},
    "ReconciliationOutcome": {"EXECUTED_SUCCESS", "EXECUTED_FAILURE", "NOT_EXECUTED", "LEDGER_HIT", "VERIFIED_PASS",
                              "VERIFIED_FAIL", "EXHAUSTED"},
    "LeaseStatus": {"pending", "active", "expired", "released"},
    "DeadLetterStatus": {"pending", "retrying", "resolved", "abandoned"},
    "DeadLetterErrorType": {"transient", "permanent", "data", "unknown_unresolved"},
    "RetryMode": {"PROBE", "VERIFY", "NONE"},
    "ResolutionOutcome": {"EXECUTED", "NOT_EXECUTED", "UNDETERMINED"},
    "DeadLetterOrigin": {"execution", "rollback"},
    "ConfirmationStatus": {"pending", "consumed", "rejected", "expired"},
    "RuntimeType": {"llm", "rules", "vision", "browser", "rpa", "data", "rag", "code", "human"},
}

# Tables this phase creates (C33: their timestamps are TIMESTAMPTZ).
NEW_TABLES = ("step_reconciliations", "dead_letters", "idempotency_ledger", "checkpoints", "workers", "worker_leases")

# Columns §7.3 / DATABASE require, with the type where the gate fixes it (None = any type).
REQUIRED_COLUMNS = {
    "execution_plans": {"execution_id": "text", "tenant_id": "text", "plan_hash": "text", "canonical_plan": "jsonb",
                        "frozen_bindings": "jsonb", "step_binding_index": "jsonb", "verifiers": "jsonb",
                        "created_at": "timestamp with time zone"},
    "step_reconciliations": {"episode_id": "text", "tenant_id": "text", "execution_id": "text", "step_id": "text",
                             "kind": "text", "status": "text", "outcome": "text", "evidence": "jsonb",
                             "attempts": "integer", "opened_at": "timestamp with time zone",
                             "closed_at": "timestamp with time zone"},
    "execution_steps": {"plan_step_id": "text", "dispatched_attempt": "integer", "terminal_reason": "text",
                        "tenant_id": "text", "reservation_id": "text"},
    "execution_runs": {"cancel_requested_at": "timestamp with time zone"},
    "dead_letters": {"dead_letter_id": "text", "tenant_id": "text", "execution_id": "text", "step_id": "text",
                     "kernel_op_id": "text", "reservation_id": "text", "error": "text", "error_type": "text",
                     "status": "text", "resolved": "boolean", "retry_mode": "text", "episode_id": "text",
                     "resolution_outcome": "text", "origin": "text", "attempt_id": "text"},
    "idempotency_ledger": {"idempotency_key": "text", "tenant_id": "text", "kernel_op_id": "text",
                           "expires_at": "timestamp with time zone"},
    "checkpoints": {"checkpoint_id": "text", "tenant_id": "text", "execution_id": "text"},
    "workers": {"worker_id": "text", "tenant_id": "text", "capability_profile": "jsonb", "state": None,
                "capacity": "integer", "current_load": "integer", "lease_epoch": "bigint", "workspace_id": "text",
                "settings": "jsonb", "assigned_user_id": "text", "paused_until": "timestamp with time zone",
                "scheduled_activation_at": "timestamp with time zone", "runtime_type": "text"},
    "worker_leases": {"lease_id": "text", "worker_id": "text", "tenant_id": "text", "fence_token": "bigint",
                      "status": "text", "execution_id": "text", "expires_at": "timestamp with time zone"},
    "bindings": {"required_runtime_types": "jsonb"},
    "execution_ownership": {"tenant_id": "text", "fencing_token": "bigint", "runtime_instance_id": "text"},
    "state_transitions": {"tenant_id": "text", "from_state": "text", "to_state": "text", "reason": "text",
                          "runtime_instance_id": "text", "fence_token": "bigint"},
    "operation_quotas": {"worker_id": "text", "tenant_id": "text"},
    "budget_reservations": {"created_at": "timestamp with time zone"},
}

# C34: every table this phase creates or writes carries tenant_id NOT NULL, under the forced RLS policy.
TENANT_TABLES = ("execution_runs", "execution_steps", "execution_manifests", "execution_plans", "execution_ownership",
                 "step_reconciliations", "checkpoints", "dead_letters", "worker_leases", "idempotency_ledger",
                 "budget_reservations", "pending_confirmations", "state_transitions", "operation_quotas")

DEFERRED_TABLES = ("worker_spawn_audit", "worker_groups", "worker_group_members", "execution_batches",
                   "worker_config_versions", "step_decisions")

TRANSITION_MACHINES = {"run", "step", "reservation", "lease", "dead_letter", "episode", "confirmation"}


def _enum_values(name: str) -> set[str]:
    module = __import__(ENUMS, fromlist=[name])
    return {member.value for member in getattr(module, name)}


async def _columns(schema, table: str) -> dict[str, tuple[str, bool, str | None]]:
    rows = await schema.fetch(
        "SELECT column_name, data_type, is_nullable = 'NO' AS not_null, column_default FROM information_schema.columns"
        " WHERE table_schema = $1 AND table_name = $2", schema.name, table)
    return {r["column_name"]: (r["data_type"], r["not_null"], r["column_default"]) for r in rows}


async def _single_column_checks(schema, table: str, column: str) -> list[str]:
    rows = await schema.fetch(
        "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c"
        "  JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace"
        "  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = c.conkey[1]"
        " WHERE n.nspname = $1 AND t.relname = $2 AND c.contype = 'c' AND array_length(c.conkey, 1) = 1"
        "   AND a.attname = $3", schema.name, table, column)
    return [r["def"] for r in rows]


def _literals(definition: str) -> set[str]:
    return set(re.findall(r"'((?:[^']|'')*)'", definition))


# --- Seed rows (as the connecting role; forced RLS needs app.current_tenant) -----------------------------------

T = "golden-tenant"


async def _seed_run(schema, execution_id: str) -> str:
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
        " VALUES ($1, $1, 'tr', 'task', 'golden-user', $2, 'golden-ws', 'conv', 'running', 'user', 'golden-user', 0)",
        execution_id, T, tenant=T)
    step_id = f"{execution_id}:s1"
    await schema.execute(
        "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id, resolved_binding_id,"
        " effective_risk, effective_mutation, request_fingerprint, status, attempt)"
        " VALUES ($1, 's1', $2, $3, 'op', 'b1', 0.1, 'W', 'fp', 'pending', 0)", step_id, execution_id, T, tenant=T)
    return step_id


async def _insert_episode(schema, episode_id: str, execution_id: str, step_id: str, closed: bool):
    await schema.execute(
        "INSERT INTO step_reconciliations (episode_id, tenant_id, execution_id, step_id, kind, status, closed_at)"
        " VALUES ($1, $2, $3, $4, 'EXECUTION', 'pending_probe', CASE WHEN $5 THEN now() END)",
        episode_id, T, execution_id, step_id, closed, tenant=T)


async def _insert_worker(schema, worker_id: str):
    await schema.execute(
        "INSERT INTO workers (worker_id, tenant_id, worker_class, capability_profile, workspace_id)"
        " VALUES ($1, $2, 'golden', '{}'::jsonb, 'golden-ws')", worker_id, T, tenant=T)


async def _insert_quota(schema, quota_id: str, workspace_id: str | None, used: int = 0, worker_id: str | None = None):
    await schema.execute(
        "INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, worker_id, period_start, period_end,"
        " limit_value, used_count) VALUES ($1, $2, $3, $4, '2026-10-01', '2026-11-01', 5, $5)",
        quota_id, T, workspace_id, worker_id, used, tenant=T)


# --- Migrations ------------------------------------------------------------------------------------------------

def test_migrations_apply_to_an_empty_schema(db_schema):
    assert db_schema.applied_first == [name for name, _ in migration_files()]


def test_migrations_are_idempotent(db_schema, run):
    assert run(db_schema.migrate()) == []


def test_new_migrations_are_new_files():
    names = [name for name, _ in migration_files()]
    assert names[:14] == ["001_s0_s11_schema.sql", "002_api_keys.sql", "003_suspended_runs.sql",
                          "004_pipeline_events.sql", "005_references.sql", "006_budget_reservations.sql",
                          "007_event_gateway.sql", "008_verifier_metadata.sql", "009_execution_admission.sql",
                          "010_step_loop.sql", "011_event_sources.sql", "012_admin_api.sql",
                          "013_access_management.sql", "014_onboarding_usage_limits.sql"]
    assert len(names) > 14, "the S12–S15 schema must arrive in new migration files (015+)"


# --- Enums and CHECK constraints (C28) -------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXPECTED_ENUM_VALUES))
def test_enum_has_the_gate_values(name):
    assert _enum_values(name) == EXPECTED_ENUM_VALUES[name]


@pytest.mark.parametrize("table,column", sorted(CHECKED))
def test_check_constraint_equals_its_enum(db_schema, run, table, column):
    enum_name, excluded = CHECKED[(table, column)]
    checks = run(_single_column_checks(db_schema, table, column))
    assert checks, f"{table}.{column} has no CHECK constraint"
    allowed = set().union(*(_literals(c) for c in checks))
    assert allowed == _enum_values(enum_name) - set(excluded)


def test_workers_state_default_is_a_canonical_worker_state(db_schema, run):
    from contracts.worker import WorkerStatus
    default = run(_columns(db_schema, "workers"))["state"][2] or ""
    assert _literals(default) and _literals(default) <= {s.value for s in WorkerStatus}, default


# --- Tables, columns, types ------------------------------------------------------------------------------------

@pytest.mark.parametrize("table", sorted(REQUIRED_COLUMNS))
def test_required_columns_and_types(db_schema, run, table):
    have = run(_columns(db_schema, table))
    assert have, f"table {table} does not exist"
    for column, kind in REQUIRED_COLUMNS[table].items():
        assert column in have, f"{table}.{column} missing"
        if kind is not None:
            assert have[column][0] == kind, f"{table}.{column} is {have[column][0]}, expected {kind}"


@pytest.mark.parametrize("table", NEW_TABLES)
def test_new_tables_use_timestamptz(db_schema, run, table):
    for column, (kind, not_null, default) in run(_columns(db_schema, table)).items():
        if kind.startswith("timestamp") or column.endswith("_at"):
            assert kind == "timestamp with time zone", f"{table}.{column} is {kind} (C33)"


def test_defaults_for_c39_json_columns(db_schema, run):
    workers, bindings = run(_columns(db_schema, "workers")), run(_columns(db_schema, "bindings"))
    assert workers["settings"][1] and "'{}'" in (workers["settings"][2] or "")
    assert workers["runtime_type"][1] and "'llm'" in (workers["runtime_type"][2] or "")
    assert bindings["required_runtime_types"][1] and "'[]'" in (bindings["required_runtime_types"][2] or "")


def test_fence_token_sequence_exists(db_schema, run):
    assert run(db_schema.fetchval(
        "SELECT count(*) FROM pg_sequences WHERE schemaname = $1 AND sequencename = 'fence_token_seq'", db_schema.name)) == 1


@pytest.mark.parametrize("table,columns,unique,predicate", [
    ("execution_runs", ["tenant_id", "request_id"], True, None),
    ("worker_leases", ["worker_id"], False, "status = 'active'"),
    ("idempotency_ledger", ["tenant_id", "idempotency_key"], False, None),
    ("step_reconciliations", ["step_id"], True, "closed_at IS NULL"),
    ("workers", ["workspace_id"], False, None),
])
def test_required_indexes(db_schema, run, table, columns, unique, predicate):
    rows = run(db_schema.fetch(
        "SELECT i.indisunique AS uniq, pg_get_expr(i.indpred, i.indrelid) AS pred,"
        "       array(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, n)"
        "             JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum ORDER BY k.n) AS cols"
        "  FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid JOIN pg_namespace ns ON ns.oid = t.relnamespace"
        " WHERE ns.nspname = $1 AND t.relname = $2", db_schema.name, table))
    def matches(r):
        pred = (r["pred"] or "").replace("(", "").replace(")", "").replace("::text", "")
        return (list(r["cols"]) == columns and (r["uniq"] or not unique)
                and (predicate is None or pred == predicate))
    assert any(matches(r) for r in rows), f"no index on {table}{tuple(columns)} unique={unique} where {predicate}"


# --- Tenancy (C34) ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("table", TENANT_TABLES)
def test_tenant_id_not_null_and_forced_rls(db_schema, run, table):
    columns = run(_columns(db_schema, table))
    assert "tenant_id" in columns and columns["tenant_id"][1], f"{table}.tenant_id must be NOT NULL"
    row = run(db_schema.fetch(
        "SELECT c.relrowsecurity AS on, c.relforcerowsecurity AS forced,"
        "       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies"
        "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relname = $2",
        db_schema.name, table))[0]
    assert row["on"] and row["forced"] and row["policies"] >= 1, f"{table} must have forced RLS with a policy"


def test_no_on_delete_cascade(db_schema, run):
    rows = run(db_schema.fetch(
        "SELECT conrelid::regclass::text AS t, conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
        " WHERE n.nspname = $1 AND c.contype = 'f' AND c.confdeltype = 'c'", db_schema.name))
    assert [dict(r) for r in rows] == []


def test_every_foreign_key_matches_the_referenced_key_type(db_schema, run):
    rows = run(db_schema.fetch(
        "SELECT c.conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
        "  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)"
        "  JOIN pg_attribute r ON r.attrelid = c.confrelid"
        "   AND r.attnum = c.confkey[array_position(c.conkey, a.attnum)]"
        " WHERE n.nspname = $1 AND c.contype = 'f' AND a.atttypid <> r.atttypid", db_schema.name))
    assert [r["conname"] for r in rows] == []


def test_c39_foreign_keys_exist(db_schema, run):
    rows = run(db_schema.fetch(
        "SELECT conrelid::regclass::text || '.' || a.attname || '->' || confrelid::regclass::text AS fk"
        "  FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
        "  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]"
        " WHERE n.nspname = $1 AND c.contype = 'f'", db_schema.name))
    fks = {r["fk"].replace(f"{db_schema.name}.", "") for r in rows}
    for fk in ("workers.tenant_id->tenants", "workers.workspace_id->workspaces", "workers.assigned_user_id->users",
               "worker_leases.worker_id->workers", "operation_quotas.worker_id->workers"):
        assert fk in fks, fk


# --- Deferred features stay absent (C40, C41, §14) --------------------------------------------------------------

def test_no_deferred_table_or_column(db_schema, run):
    tables = run(db_schema.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = $1"
                                 " AND table_name = ANY ($2::text[])", db_schema.name, list(DEFERRED_TABLES)))
    columns = run(db_schema.fetch(
        "SELECT table_name || '.' || column_name AS c FROM information_schema.columns WHERE table_schema = $1"
        " AND column_name = ANY ($2::text[])", db_schema.name,
        ["parent_execution_id", "max_sub_agents", "parent_worker_id", "depth_level", "batch_id"]))
    assert [r["table_name"] for r in tables] == [] and [r["c"] for r in columns] == []


def test_transition_log_accepts_every_machine(db_schema, run):
    columns = run(_columns(db_schema, "state_transitions"))
    column = "machine" if "machine" in columns else "entity_type"
    checks = run(_single_column_checks(db_schema, "state_transitions", column))
    allowed = set().union(*(_literals(c) for c in checks)) if checks else None
    assert allowed is None or TRANSITION_MACHINES <= allowed, f"state_transitions.{column} allows {allowed}"


# --- Behaviour of the constraints (real inserts) ---------------------------------------------------------------

def test_cancelled_or_skipped_step_needs_a_reason(db_schema, run):
    step = run(_seed_run(db_schema, "golden-run-reason"))
    for status in ("cancelled", "skipped"):
        with pytest.raises(asyncpg.CheckViolationError):
            run(db_schema.execute("UPDATE execution_steps SET status = $2 WHERE step_id = $1", step, status, tenant=T))
    run(db_schema.execute("UPDATE execution_steps SET status = 'cancelled', terminal_reason = 'user_cancelled'"
                          " WHERE step_id = $1", step, tenant=T))


def test_terminal_reason_is_written_once(db_schema, run):
    step = run(_seed_run(db_schema, "golden-run-once"))
    run(db_schema.execute("UPDATE execution_steps SET status = 'cancelled', terminal_reason = 'user_cancelled'"
                          " WHERE step_id = $1", step, tenant=T))
    for value in ("no_worker", None):
        with pytest.raises(asyncpg.RaiseError):
            run(db_schema.execute("UPDATE execution_steps SET terminal_reason = $2 WHERE step_id = $1",
                                  step, value, tenant=T))


def test_one_open_episode_per_step(db_schema, run):
    step = run(_seed_run(db_schema, "golden-run-episode"))
    run(_insert_episode(db_schema, "ep-closed", "golden-run-episode", step, closed=True))
    run(_insert_episode(db_schema, "ep-open-1", "golden-run-episode", step, closed=False))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(_insert_episode(db_schema, "ep-open-2", "golden-run-episode", step, closed=False))


def test_episode_rejects_status_none(db_schema, run):
    step = run(_seed_run(db_schema, "golden-run-none"))
    with pytest.raises(asyncpg.CheckViolationError):
        run(db_schema.execute(
            "INSERT INTO step_reconciliations (episode_id, tenant_id, execution_id, step_id, kind, status)"
            " VALUES ('ep-none', $1, 'golden-run-none', $2, 'EXECUTION', 'none')", T, step, tenant=T))


def test_dead_letter_minimal_row_and_origin_default(db_schema, run):
    step = run(_seed_run(db_schema, "golden-run-dl"))
    run(db_schema.execute(
        "INSERT INTO dead_letters (dead_letter_id, tenant_id, execution_id, step_id, kernel_op_id, error, error_type,"
        " retry_mode) VALUES ('dl1', $1, 'golden-run-dl', $2, 'op', 'e', 'unknown_unresolved', 'PROBE')",
        T, step, tenant=T))
    row = run(db_schema.fetch("SELECT status, origin FROM dead_letters WHERE dead_letter_id = 'dl1'", tenant=T))[0]
    assert (row["status"], row["origin"]) == ("pending", "execution")


def test_quota_rejects_duplicate_scope_and_period(db_schema, run):
    run(_seed_run(db_schema, "golden-run-quota"))
    run(_insert_quota(db_schema, "q-tenant", None))
    run(_insert_quota(db_schema, "q-ws", "golden-ws"))
    for quota_id, workspace in (("q-tenant-2", None), ("q-ws-2", "golden-ws")):
        with pytest.raises(asyncpg.UniqueViolationError):
            run(_insert_quota(db_schema, quota_id, workspace))


def test_quota_rejects_negative_count_and_worker_level_rows(db_schema, run):
    run(_seed_run(db_schema, "golden-run-quota2"))
    run(_insert_worker(db_schema, "golden-worker"))
    with pytest.raises(asyncpg.CheckViolationError):
        run(_insert_quota(db_schema, "q-neg", "golden-ws", used=-1))
    with pytest.raises(asyncpg.CheckViolationError):
        run(_insert_quota(db_schema, "q-worker", "golden-ws", worker_id="golden-worker"))


def test_quota_limit_cannot_drop_below_usage(db_schema, run):
    run(_seed_run(db_schema, "golden-run-quota3"))
    run(db_schema.execute(
        "INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, period_start, period_end, limit_value,"
        " used_count) VALUES ('q-used', $1, 'golden-ws', '2027-01-01', '2027-02-01', 5, 4)", T, tenant=T))
    with pytest.raises(asyncpg.CheckViolationError):
        run(db_schema.execute("UPDATE operation_quotas SET limit_value = 3 WHERE quota_id = 'q-used'", tenant=T))


def test_lease_status_defaults_to_active(db_schema, run):
    run(_seed_run(db_schema, "golden-run-lease"))
    run(_insert_worker(db_schema, "golden-worker-2"))
    run(db_schema.execute(
        "INSERT INTO worker_leases (lease_id, worker_id, tenant_id, fence_token, expires_at)"
        " VALUES ('l1', 'golden-worker-2', $1, nextval('fence_token_seq'), now() + interval '5 seconds')", T, tenant=T))
    assert run(db_schema.fetchval("SELECT status FROM worker_leases WHERE lease_id = 'l1'", tenant=T)) == "active"
