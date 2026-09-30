"""Agent tests for M8a (never count for certification): filter edges and fail-closed data, the C39 ledger events, the
selection reader's live reads (tenant isolation, database time, the binding's runtime list) and the soft-quota retry
taken from the settings object."""
import asyncio
import dataclasses
import time

import pytest
from tests_golden.fixtures.certified import entry_readers, seed_identity
from tests_golden.fixtures.db import GoldenSchema, golden_database_url, new_schema_name
from tests_golden.s12.M08a_worker_mgmt import NOW, _ctx, _quota, _tenant_state, _w

from contracts.admission import DENIED
from engine.stages.s12_execute.eligibility import filter_workers, record_filtering
from engine.stages.s12_execute.settings import ExecutionSettings


def _filter(candidates, **ctx):
    return filter_workers(candidates, _ctx(**ctx))


class Ledger:
    def __init__(self):
        self.events = []

    async def record(self, kind, payload):
        self.events.append((kind, dict(payload)))


# --- filters ---------------------------------------------------------------------------------------------------------

def test_a_bypassed_worker_that_fails_a_later_filter_is_removed_and_no_bypass_is_recorded():
    result = _filter([_w("w", paused_until=NOW + 60, capability_profile=frozenset({"cap.y"}))], admin=True)
    assert dict(result.removed) == {"w": "capability_mismatch"} and result.bypassed == ()


def test_every_bypassed_reason_of_an_eligible_worker_is_recorded():
    result = _filter([_w("w", paused_until=NOW + 60, assigned_user_id="user-2")], admin=True)
    assert [w.worker_id for w in result.eligible] == ["w"]
    assert result.bypassed == (("w", "worker_paused"), ("w", "not_assigned"))


def test_without_bypass_the_first_reason_in_filter_order_decides():
    result = _filter([_w("w", paused_until=NOW + 60, capability_profile=frozenset())])
    assert dict(result.removed) == {"w": "worker_paused"}


def test_a_human_principal_without_an_id_never_matches_an_assignment():
    result = _filter([_w("w", assigned_user_id="user-2")], original_principal_id=None)
    assert dict(result.removed) == {"w": "not_assigned"}


def test_pause_ending_exactly_now_is_eligible():
    assert len(_filter([_w("w", paused_until=NOW, scheduled_activation_at=NOW)]).eligible) == 1


@pytest.mark.parametrize("settings,reason", [
    (["not", "a", "mapping"], "capability_mismatch"),
    ({"restricted_capabilities": "cap.x"}, "capability_mismatch"),        # a string, not a list: never substring-match
    ({"restricted_capabilities": [1, 2]}, "capability_mismatch"),
    ({"execution_policy": "W"}, "mutation_ceiling"),
    ({"execution_policy": {"max_mutation": "X"}}, "mutation_ceiling"),
    ({"execution_policy": {"max_mutation": ["W"]}}, "mutation_ceiling"),
])
def test_malformed_worker_settings_fail_closed(settings, reason):
    assert dict(_filter([_w("w", settings=settings)]).removed) == {"w": reason}


def test_an_unknown_step_mutation_under_a_ceiling_fails_closed_and_without_a_ceiling_passes():
    assert dict(_filter([_w("w", settings={"execution_policy": {"max_mutation": "IRREVERSIBLE"}})],
                        effective_mutation="?").removed) == {"w": "mutation_ceiling"}
    assert len(_filter([_w("w")], effective_mutation="IRREVERSIBLE").eligible) == 1


def test_an_empty_restriction_list_restricts_nothing():
    assert len(_filter([_w("w", settings={"restricted_capabilities": []})]).eligible) == 1


# --- ledger events ---------------------------------------------------------------------------------------------------

def test_bypasses_are_ledger_events_and_a_survivor_means_no_no_worker_event():
    ledger = Ledger()
    result = _filter([_w("w-a", paused_until=NOW + 60), _w("w-b", workspace_id="other")], admin=True)
    asyncio.run(record_filtering(ledger, result))
    assert ledger.events == [("eligibility_bypass", {"worker_id": "w-a", "reason": "worker_paused"})]


def test_no_worker_event_lists_every_filter_reason():
    ledger = Ledger()
    result = _filter([_w("w-a", workspace_id=None), _w("w-b", runtime_type="rules")], required_runtime_types=("llm",))
    asyncio.run(record_filtering(ledger, result))
    assert ledger.events == [("no_worker", {"reasons": {"w-a": "workspace_mismatch", "w-b": "capability_mismatch"}})]


# --- settings --------------------------------------------------------------------------------------------------------

BASE_ENV = {"S12_ADAPTER_CLIENT_TIMEOUT_S": "10", "S12_STEP_TIMEOUT_S": "30", "S12_PROBE_TIMEOUT_S": "5",
            "S12_LEASE_TTL_S": "30", "S12_LEASE_RENEWAL_INTERVAL_S": "10"}


def test_quota_limits_have_defaults_and_can_come_from_the_environment():
    assert ExecutionSettings.from_env(BASE_ENV).quota_retry_max == 3
    s = ExecutionSettings.from_env({**BASE_ENV, "S12_QUOTA_RETRY_MAX": "5", "S12_QUOTA_BACKOFF_S": "0.2",
                                    "S12_QUOTA_RETRY_AFTER_MS": "250"})
    assert (s.quota_retry_max, s.quota_backoff_s, s.quota_retry_after_ms) == (5, 0.2, 250)


@pytest.mark.parametrize("override", [{"S12_QUOTA_RETRY_MAX": "0"}, {"S12_QUOTA_RETRY_MAX": "2.5"},
                                      {"S12_QUOTA_RETRY_AFTER_MS": "-1"}, {"S12_QUOTA_BACKOFF_S": "x"}])
def test_invalid_quota_limits_are_refused(override):
    with pytest.raises(ValueError):
        ExecutionSettings.from_env({**BASE_ENV, **override})


# --- database --------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_schema(request):
    schema = GoldenSchema(golden_database_url(), new_schema_name(request.module.__name__))
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(schema.create())
        loop.run_until_complete(schema.migrate())
        schema.loop = loop
        yield schema
    finally:
        loop.run_until_complete(schema.drop())
        loop.close()


@pytest.fixture
def run(db_schema):
    return db_schema.loop.run_until_complete


def _reader(schema):
    from adapters.postgres.selection import PostgresSelectionReader
    return PostgresSelectionReader(schema.database())


async def _tenant(schema, tenant, workspace):
    await schema.execute("INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation,"
                         " policy_version_id) VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1')"
                         " ON CONFLICT DO NOTHING", tenant)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'w')"
                         " ON CONFLICT DO NOTHING", workspace, tenant)


async def _worker(schema, worker_id, tenant, workspace, *, profile="[]", state="ACTIVE"):
    await schema.execute("INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile,"
                         " state, capacity) VALUES ($1, $2, $3, 'g', $4::jsonb, $5, 1)",
                         worker_id, tenant, workspace, profile, state)


def test_candidates_never_include_another_tenants_workers(db_schema, run):
    run(_tenant(db_schema, "t-iso-a", "ws-iso-a"))
    run(_tenant(db_schema, "t-iso-b", "ws-iso-b"))
    run(_worker(db_schema, "w-iso-a", "t-iso-a", "ws-iso-a"))
    run(_worker(db_schema, "w-iso-b", "t-iso-b", "ws-iso-b"))
    assert [w.worker_id for w in run(_reader(db_schema).candidates("t-iso-a"))] == ["w-iso-a"]


def test_a_profile_that_is_not_an_array_matches_no_capability(db_schema, run):
    run(_tenant(db_schema, "t-prof", "ws-prof"))
    run(_worker(db_schema, "w-prof", "t-prof", "ws-prof", profile='{"cap.x": true}'))
    (worker,) = run(_reader(db_schema).candidates("t-prof"))
    assert worker.capability_profile == frozenset() and worker.settings == {}


def test_database_now_is_database_time(db_schema, run):
    assert abs(run(_reader(db_schema).database_now()) - time.time()) < 5


async def _member(schema, tenant, workspace, user, *, role="admin", user_status="active", revoked=False):
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ($1, $2, $3)", user, tenant, user_status)
    await schema.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, is_active,"
                         " revoked_at) VALUES ($1, $2, $3, $4, $5, true, CASE WHEN $6 THEN now() END)",
                         f"m-{user}", tenant, user, workspace, role, revoked)


@pytest.mark.parametrize("user,kwargs,expected", [
    ("u-adm-ok", {}, True), ("u-adm-suspended", {"user_status": "suspended"}, False),
    ("u-adm-revoked", {"revoked": True}, False), ("u-viewer", {"role": "viewer"}, False)])
def test_the_admin_bypass_needs_a_live_unrevoked_membership_of_an_active_user(db_schema, run, user, kwargs, expected):
    run(_tenant(db_schema, "t-adm", "ws-adm"))
    run(_member(db_schema, "t-adm", "ws-adm", user, **kwargs))
    assert run(_reader(db_schema).is_workspace_admin("t-adm", "ws-adm", user)) is expected


def test_the_admin_bypass_is_per_tenant_and_workspace_and_needs_a_principal(db_schema, run):
    run(_tenant(db_schema, "t-adm2", "ws-adm2"))
    run(_tenant(db_schema, "t-adm2", "ws-adm2-other"))
    run(_member(db_schema, "t-adm2", "ws-adm2", "u-adm2"))
    reader = _reader(db_schema)
    assert run(reader.is_workspace_admin("t-adm2", "ws-adm2-other", "u-adm2")) is False
    assert run(reader.is_workspace_admin("t-other", "ws-adm2", "u-adm2")) is False
    assert run(reader.is_workspace_admin("t-adm2", "ws-adm2", None)) is False


async def _binding(schema, binding_id, runtime_types, *, active=True):
    await schema.execute("INSERT INTO capabilities (capability_id, name, intent, mutation, risk_floor, risk_rule,"
                         " risk_implied, truth_state) VALUES ('cap-rt', 'c', 'i', 'R', 0, 0, 0, 'PRODUCTION_ENABLED')"
                         " ON CONFLICT DO NOTHING")
    await schema.execute("INSERT INTO kernel_ops (kernel_op_id, mutation, risk_floor, cost, timeout_seconds,"
                         " retry_safety, truth_state) VALUES ('op-rt', 'R', 0, 1, 1, 'safe', 'PRODUCTION_ENABLED')"
                         " ON CONFLICT DO NOTHING")
    await schema.execute("INSERT INTO bindings (binding_id, capability_id, kernel_op_id, provider, engine_module,"
                         " adapter_class, is_active, required_runtime_types) VALUES ($1, 'cap-rt', 'op-rt', 'p', 'm',"
                         " 'a', $2, $3::jsonb)", binding_id, active, runtime_types)


def test_the_bindings_runtime_list_is_read_and_empty_means_any(db_schema, run):
    run(_binding(db_schema, "b-rt-list", '["rules", "code"]'))
    run(_binding(db_schema, "b-rt-any", "[]"))
    reader = _reader(db_schema)
    assert run(reader.required_runtime_types("b-rt-list")) == ("rules", "code")
    assert run(reader.required_runtime_types("b-rt-any")) == ()


@pytest.mark.parametrize("binding_id,value,active,error", [
    ("b-rt-missing", None, True, LookupError), ("b-rt-inactive", "[]", False, LookupError),
    ("b-rt-object", '{"rules": true}', True, ValueError), ("b-rt-numbers", "[1]", True, ValueError)])
def test_a_missing_or_malformed_runtime_list_is_never_read_as_any(db_schema, run, binding_id, value, active, error):
    if value is not None:
        run(_binding(db_schema, binding_id, value, active=active))
    with pytest.raises(error):
        run(_reader(db_schema).required_runtime_types(binding_id))


def test_the_soft_quota_retry_follows_the_settings_object(db_schema, run):
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    state = _tenant_state("agent-quota-settings", "settings")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-agent-soft", limit=1, used=1, hard=False))
    settings = dataclasses.replace(ExecutionSettings.from_env(BASE_ENV), quota_retry_max=1, quota_retry_after_ms=7)
    admitter = PostgresExecutionAdmission(db_schema.database(), settings=settings)
    outcome = run(admit_run(state, **entry_readers(), admitter=admitter, runtime_instance_id="runtime-A"))
    assert (outcome.status, outcome.reason, outcome.retry_after_ms) == (DENIED, "quota_exhausted", 7)


def test_integer_quota_limits_are_checked_at_construction_too():
    base = ExecutionSettings.from_env(BASE_ENV)
    with pytest.raises(ValueError):
        dataclasses.replace(base, quota_retry_max=2.5)
