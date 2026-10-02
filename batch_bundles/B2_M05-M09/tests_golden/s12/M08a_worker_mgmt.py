"""M8a golden — worker management: entry safety net, eligibility filters, operation quota (gate commit E part 3). ★
Owner-pinned.

Gate v10: C39 (revised in audit round 2), §7.1 item 7, §7.2 (quota in the admission transaction), §8 step 2 (filters
before scoring), suite 20; invariants I17, I18; WORKER_LIFECYCLE §13 (filters), §16; rulings CONF-004, CONF-007,
CONF-016.

Interface this file fixes (``engine.stages.s12_execute.eligibility``; M08 already uses ``WorkerCandidate``):
  * ``WorkerCandidate`` (frozen): ``worker_id``, ``workspace_id``, ``capacity``, ``current_load``, ``paused_until``,
    ``scheduled_activation_at`` (database epoch seconds or None), ``assigned_user_id``, ``capability_profile``
    (frozenset of capability ids), ``settings`` (mapping; ``restricted_capabilities`` list,
    ``execution_policy.max_mutation``), ``runtime_type``.
  * ``SelectionContext`` (frozen): ``workspace_id``, ``capability_id``, ``effective_mutation``,
    ``required_runtime_types`` (tuple; empty = any), ``original_principal_id``, ``principal_is_human``, ``event_driven``,
    ``admin`` (live owner/admin membership of the original principal in the run's workspace), ``now`` (database epoch).
  * ``filter_workers(candidates, ctx) -> FilterResult(eligible, removed, bypassed)``: ``eligible`` keeps input order;
    ``removed`` maps worker_id → the first failing reason in the order 4b ``workspace_mismatch``, 12b ``worker_paused``,
    13b ``worker_not_yet_active``, 14 ``not_assigned``, 17a–c ``capability_mismatch``, 17d ``mutation_ceiling``;
    ``bypassed`` lists ``(worker_id, reason)`` for every 12b/13b/14 failure the admin bypass let through. Pure.
  * ``adapters.postgres.selection.PostgresSelectionReader(database)``: ``async candidates(tenant_id) ->
    tuple[WorkerCandidate]`` (ACTIVE workers of the tenant, times as database epoch) and ``async is_workspace_admin(
    tenant_id, workspace_id, user_id) -> bool`` (active membership with role owner or admin, read live).
Entry quota and the pause safety net use ``engine.stages.s12_entry.admission.admit_run`` (M6 interface).
"""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from contracts.admission import ADMITTED, DENIED, DUPLICATE
from tests_golden.fixtures.certified import certified_state, entry_readers, fresh, seed_identity
from tests_golden.fixtures.code_scan import ROOT, s12_files, string_literals
from tests_golden.fixtures.invariants import assert_system_invariants

T = "golden-tenant"
NOW = 1_800_000_000.0


def _w(worker_id, **changes):
    from engine.stages.s12_execute.eligibility import WorkerCandidate
    base = dict(worker_id=worker_id, workspace_id="ws", capacity=2, current_load=0, paused_until=None,
                scheduled_activation_at=None, assigned_user_id=None, capability_profile=frozenset({"cap.x"}),
                settings={}, runtime_type="llm")
    return WorkerCandidate(**{**base, **changes})


def _ctx(**changes):
    from engine.stages.s12_execute.eligibility import SelectionContext
    base = dict(workspace_id="ws", capability_id="cap.x", effective_mutation="W", required_runtime_types=(),
                original_principal_id="user-1", principal_is_human=True, event_driven=False, admin=False, now=NOW)
    return SelectionContext(**{**base, **changes})


def _filter(candidates, **ctx):
    from engine.stages.s12_execute.eligibility import filter_workers
    return filter_workers(candidates, _ctx(**ctx))


INELIGIBLE = [
    ("other workspace", {"workspace_id": "ws-other"}, "workspace_mismatch"),
    ("legacy NULL workspace", {"workspace_id": None}, "workspace_mismatch"),
    ("paused", {"paused_until": NOW + 60}, "worker_paused"),
    ("not yet active", {"scheduled_activation_at": NOW + 60}, "worker_not_yet_active"),
    ("assigned to another user", {"assigned_user_id": "user-2"}, "not_assigned"),
    ("capability not in profile", {"capability_profile": frozenset({"cap.y"})}, "capability_mismatch"),
    ("capability restricted", {"settings": {"restricted_capabilities": ["cap.x"]}}, "capability_mismatch"),
    ("mutation ceiling below the step", {"settings": {"execution_policy": {"max_mutation": "R"}}}, "mutation_ceiling"),
]


# --- filters (C39, I18) ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,changes,reason", INELIGIBLE, ids=[c[0] for c in INELIGIBLE])
def test_each_filter_removes_exactly_the_ineligible_worker(name, changes, reason):
    good, bad = _w("w-good"), _w("w-bad", **changes)
    result = _filter([bad, good])
    assert [w.worker_id for w in result.eligible] == ["w-good"]
    assert dict(result.removed) == {"w-bad": reason} and tuple(result.bypassed) == ()


def test_runtime_not_in_the_binding_list_is_a_capability_mismatch():
    result = _filter([_w("w-llm"), _w("w-rules", runtime_type="rules")], required_runtime_types=("rules",))
    assert [w.worker_id for w in result.eligible] == ["w-rules"] and dict(result.removed) == {"w-llm": "capability_mismatch"}


def test_empty_required_runtime_types_accepts_any_runtime():
    workers = [_w(f"w-{r}", runtime_type=r) for r in ("llm", "rules", "code", "human")]
    assert len(_filter(workers, required_runtime_types=()).eligible) == 4


@pytest.mark.parametrize("ceiling,step,allowed", [
    ("R", "R", True), ("W", "W", True), ("W", "D", False), ("D", "IRREVERSIBLE", False), ("IRREVERSIBLE", "D", True)])
def test_mutation_ceiling_order(ceiling, step, allowed):
    result = _filter([_w("w", settings={"execution_policy": {"max_mutation": ceiling}})], effective_mutation=step)
    assert bool(result.eligible) is allowed


def test_elapsed_pause_and_activation_are_eligible():
    result = _filter([_w("w", paused_until=NOW - 1, scheduled_activation_at=NOW - 1)])
    assert len(result.eligible) == 1


def test_every_filter_reason_is_reported_when_nothing_is_left():
    bad = [_w(f"w-{i}", **changes) for i, (_, changes, _) in enumerate(INELIGIBLE)]
    result = _filter(bad)
    assert result.eligible == () or list(result.eligible) == []
    assert sorted(result.removed.values()) == sorted(reason for _, _, reason in INELIGIBLE)


@pytest.mark.parametrize("changes,reason", [({"paused_until": NOW + 60}, "worker_paused"),
                                            ({"scheduled_activation_at": NOW + 60}, "worker_not_yet_active"),
                                            ({"assigned_user_id": "user-2"}, "not_assigned")])
def test_admin_bypass_applies_to_12b_13b_14_and_is_recorded(changes, reason):
    result = _filter([_w("w", **changes)], admin=True)
    assert [w.worker_id for w in result.eligible] == ["w"] and list(result.bypassed) == [("w", reason)]


@pytest.mark.parametrize("name,changes,reason", [c for c in INELIGIBLE if c[2] in ("workspace_mismatch",
                                                                                   "capability_mismatch",
                                                                                   "mutation_ceiling")],
                         ids=lambda v: v if isinstance(v, str) else "")
def test_admin_bypass_never_applies_to_4b_or_17(name, changes, reason):
    result = _filter([_w("w", **changes)], admin=True)
    assert result.eligible == () or list(result.eligible) == []
    assert dict(result.removed) == {"w": reason}


@pytest.mark.parametrize("ctx,eligible", [
    ({"event_driven": True}, True),                                            # event-driven run: 14 skipped
    ({"principal_is_human": False, "original_principal_id": None}, True),      # system run: 14 skipped
    ({"principal_is_human": True, "original_principal_id": "user-2"}, True),   # worker-delegated for user-2: kept, matches
    ({"principal_is_human": True, "original_principal_id": "user-1"}, False),  # human user-1: not assigned
])
def test_assignment_rule_by_activation(ctx, eligible):
    result = _filter([_w("w", assigned_user_id="user-2")], **ctx)
    assert bool(result.eligible) is eligible


def test_filters_are_pure():
    candidates, ctx = [_w("w-a"), _w("w-b", paused_until=NOW + 5)], _ctx()
    from engine.stages.s12_execute.eligibility import filter_workers
    assert filter_workers(candidates, ctx) == filter_workers(list(candidates), dataclasses.replace(ctx))


# --- live reads ------------------------------------------------------------------------------------------------------

async def _seed_workers(schema):
    await schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id)"
        " VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1') ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('ws-live', $1, 'w')"
                         " ON CONFLICT DO NOTHING", T, tenant=T)
    for user, role in (("u-owner", "owner"), ("u-admin", "admin"), ("u-member", "member"), ("u-revoked", "admin")):
        await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ($1, $2, 'active')"
                             " ON CONFLICT DO NOTHING", user, T, tenant=T)
        await schema.execute(
            "INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, is_active)"
            " VALUES ($1, $2, $3, 'ws-live', $4, $5) ON CONFLICT DO NOTHING", f"m-{user}", T, user, role,
            user != "u-revoked", tenant=T)
    await schema.execute(
        "INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile, state, capacity,"
        " paused_until, runtime_type, settings) VALUES"
        " ('w-live-1', $1, 'ws-live', 'g', '[\"cap.x\"]'::jsonb, 'ACTIVE', 3, now() + interval '1 hour', 'rules',"
        "  '{\"restricted_capabilities\": [\"cap.z\"]}'::jsonb),"
        " ('w-live-2', $1, 'ws-live', 'g', '[\"cap.x\", \"cap.y\"]'::jsonb, 'ACTIVE', 1, NULL, 'llm', '{}'::jsonb),"
        " ('w-live-3', $1, 'ws-live', 'g', '[\"cap.x\"]'::jsonb, 'DRAINING', 1, NULL, 'llm', '{}'::jsonb)"
        " ON CONFLICT DO NOTHING", T, tenant=T)


def test_candidates_are_the_tenants_active_workers_as_database_state(db_schema, run):
    from adapters.postgres.selection import PostgresSelectionReader
    run(_seed_workers(db_schema))
    found = {w.worker_id: w for w in run(PostgresSelectionReader(db_schema.database()).candidates(T))}
    assert set(found) == {"w-live-1", "w-live-2"}
    w1 = found["w-live-1"]
    assert w1.capability_profile == frozenset({"cap.x"}) and w1.runtime_type == "rules" and w1.capacity == 3
    assert w1.paused_until is not None and w1.paused_until > time.time() + 3000
    assert w1.settings.get("restricted_capabilities") == ["cap.z"] and found["w-live-2"].paused_until is None


@pytest.mark.parametrize("user,expected", [("u-owner", True), ("u-admin", True), ("u-member", False),
                                           ("u-revoked", False), ("u-nobody", False)])
def test_admin_is_read_live_from_memberships(db_schema, run, user, expected):
    from adapters.postgres.selection import PostgresSelectionReader
    run(_seed_workers(db_schema))
    assert run(PostgresSelectionReader(db_schema.database()).is_workspace_admin(T, "ws-live", user)) is expected


# --- I18 end to end: live candidates -> filters -> selection -> lease ------------------------------------------------

async def _seed_i18(schema, execution):
    await _seed_workers(schema)
    await schema.execute(
        "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
        " conversation_id, status, actor_type, actor_id, budget_spent) VALUES ($1, $1, 'tr', 'task', 'u-member', $2,"
        " 'ws-live', 'conv', 'running', 'user', 'u-member', 0) ON CONFLICT DO NOTHING", execution, T, tenant=T)
    await schema.execute(
        "INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token,"
        " checkpoint_sequence, updated_at) VALUES ($1, $2, 'admission', 0, 0, now()) ON CONFLICT DO NOTHING",
        execution, T, tenant=T)


def _lease_through_filters(schema, run, execution, **ctx):
    from adapters.postgres.leases import PostgresLeaseManager
    from adapters.postgres.selection import PostgresSelectionReader
    from engine.stages.s12_execute.eligibility import filter_workers
    from engine.stages.s12_execute.selection import lease_for_step
    reader, leases = PostgresSelectionReader(schema.database()), PostgresLeaseManager(schema.database())
    selection = _ctx(workspace_id="ws-live", now=time.time(), **ctx)

    async def candidates():
        return filter_workers(await reader.candidates(T), selection).eligible

    async def acquire(worker_id):
        return await leases.acquire(tenant_id=T, worker_id=worker_id, execution_id=execution,
                                    runtime_instance_id="runtime-A", ttl_s=30)

    return run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))


def test_only_an_eligible_worker_is_ever_leased(db_schema, run):
    """I18: w-live-1 is paused and w-live-3 is DRAINING; only w-live-2 may get the lease."""
    run(_seed_i18(db_schema, "e-i18-ok"))
    lease = _lease_through_filters(db_schema, run, "e-i18-ok")
    assert getattr(lease, "worker_id", None) == "w-live-2"
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id <> 'w-live-2'")) == 0


def test_no_eligible_worker_is_no_worker_and_nothing_is_leased(db_schema, run):
    run(_seed_i18(db_schema, "e-i18-none"))
    before = run(db_schema.fetchval("SELECT count(*) FROM worker_leases"))
    assert _lease_through_filters(db_schema, run, "e-i18-none", capability_id="cap.q") == "no_worker"
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases")) == before


# --- entry quota (§7.2, I17) and the pause safety net (§7.1 item 7) ---------------------------------------------------

TABLES = ("execution_runs", "execution_steps", "execution_manifests", "execution_plans", "execution_ownership",
          "state_transitions")


async def _counts(schema):
    out = {t: await schema.fetchval(f"SELECT count(*) FROM {t}") for t in TABLES}
    out["quota_used"] = await schema.fetchval("SELECT COALESCE(sum(used_count), 0) FROM operation_quotas")
    return out


async def _quota(schema, state, quota_id, *, limit, hard=True, workspace=False, used=0):
    ctx = state.execution_context
    await schema.execute(
        "INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, period_start, period_end, limit_value,"
        " used_count, is_hard) VALUES ($1, $2, $3, now() - interval '1 day', now() + interval '1 day', $4, $5, $6)",
        quota_id, ctx.tenant_id, ctx.workspace_id if workspace else None, limit, used, hard, tenant=ctx.tenant_id)


def _admit(schema, run, state, **readers):
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    return run(admit_run(state, **{**entry_readers(), **readers},
                         admitter=PostgresExecutionAdmission(schema.database()), runtime_instance_id="runtime-A"))


def _tenant_state(tenant, suffix):
    return fresh(certified_state(tenant_id=tenant), suffix)


def test_twenty_concurrent_entries_against_a_limit_of_five_admit_exactly_five(db_schema, run):
    """I17: the certifier repeats this file 5 times."""
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    tenant = "golden-quota-race"
    base = _tenant_state(tenant, "race-0")
    run(seed_identity(db_schema, base))
    run(_quota(db_schema, base, "q-race", limit=5))
    admitter = PostgresExecutionAdmission(db_schema.database())

    async def race():
        return await asyncio.gather(*(admit_run(_tenant_state(tenant, f"race-{i}"), **entry_readers(),
                                                admitter=admitter, runtime_instance_id="runtime-A") for i in range(20)))

    outcomes = run(race())
    assert [o.status for o in outcomes].count(ADMITTED) == 5
    assert {o.reason for o in outcomes if o.status == DENIED} == {"quota_exhausted"}
    assert run(db_schema.fetchval("SELECT used_count FROM operation_quotas WHERE quota_id = 'q-race'")) == 5
    assert run(db_schema.fetchval("SELECT count(*) FROM execution_runs WHERE tenant_id = $1", tenant)) == 5
    run(assert_system_invariants(db_schema))


def test_hard_quota_denies_and_writes_nothing(db_schema, run):
    state = _tenant_state("golden-quota-hard", "hard")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-hard", limit=1, used=1))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state)
    assert (outcome.status, outcome.reason, outcome.retry_after_ms) == (DENIED, "quota_exhausted", None)
    assert run(_counts(db_schema)) == before


def test_soft_quota_retries_then_denies_with_retry_after_and_writes_nothing(db_schema, run):
    state = _tenant_state("golden-quota-soft", "soft")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-soft", limit=1, used=1, hard=False))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state)
    assert (outcome.status, outcome.reason) == (DENIED, "quota_exhausted") and outcome.retry_after_ms > 0
    assert run(_counts(db_schema)) == before


def test_workspace_level_quota_is_consumed_after_the_tenant_level(db_schema, run):
    state = _tenant_state("golden-quota-levels", "levels")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-t", limit=10))
    run(_quota(db_schema, state, "q-w", limit=0, workspace=True))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state)
    assert (outcome.status, outcome.reason) == (DENIED, "quota_exhausted")
    assert run(_counts(db_schema)) == before     # the tenant-level use rolled back with the workspace refusal


def test_duplicate_request_consumes_no_quota(db_schema, run):
    state = _tenant_state("golden-quota-dup", "dup")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-dup", limit=5))
    assert _admit(db_schema, run, state).status == ADMITTED
    again = dataclasses.replace(state, plan=dataclasses.replace(state.plan, execution_id="golden-exec-dup-again"),
                                execution_manifest=dataclasses.replace(state.execution_manifest,
                                                                       execution_id="golden-exec-dup-again"))
    assert _admit(db_schema, run, again).status == DUPLICATE
    assert run(db_schema.fetchval("SELECT used_count FROM operation_quotas WHERE quota_id = 'q-dup'")) == 1


@pytest.mark.parametrize("fields,reason", [({"tenant_paused_until": 3600}, "tenant_paused"),
                                           ({"workspace_paused_until": 3600}, "workspace_paused"),
                                           ({"workspace_activation_at": 3600}, "not_yet_active")])
def test_entry_safety_net_denies_a_paused_scope_and_consumes_nothing(db_schema, run, fields, reason):
    from contracts.activation import ActivationState
    state = _tenant_state("golden-quota-pause", f"pause-{reason}")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, f"q-pause-{reason}", limit=5))

    class Paused:
        async def read(self, tenant_id, workspace_id):
            now = time.time()
            base = {"tenant_paused_until": None, "tenant_activation_at": None, "workspace_paused_until": None,
                    "workspace_activation_at": None}
            return ActivationState(now, **{**base, **{k: now + v for k, v in fields.items()}})

    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state, activation=Paused())
    assert (outcome.status, outcome.reason) == (DENIED, reason) and run(_counts(db_schema)) == before


def test_quota_limit_cannot_be_lowered_below_usage(db_schema, run):
    import asyncpg
    state = _tenant_state("golden-quota-lower", "lower")
    run(seed_identity(db_schema, state))
    run(_quota(db_schema, state, "q-lower", limit=5, used=3))
    with pytest.raises(asyncpg.CheckViolationError):
        run(db_schema.execute("UPDATE operation_quotas SET limit_value = 2 WHERE quota_id = 'q-lower'",
                              tenant=state.execution_context.tenant_id))


# --- architecture (suite 20) -----------------------------------------------------------------------------------------

def test_no_quota_check_exists_after_entry():
    """A1: quota is consumed once at entry; no step code queries it or imports a quota module, so an admitted run is
    never rejected by quota."""
    from tests_golden.fixtures.code_scan import imports
    offenders = []
    for path in s12_files():
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith(("src/engine/stages/s12_execute/", "src/engine/stages/s13", "src/engine/stages/s14",
                               "src/engine/stages/s15")):
            continue
        if any("operation_quotas" in text for _, text in string_literals(path)) \
                or any("quota" in module for module in imports(path)):
            offenders.append(rel)
    assert offenders == []


def test_runtime_type_never_chooses_an_adapter():
    """RD-9: runtime_type is read only by the eligibility filter and the selection reader."""
    allowed = {"src/engine/stages/s12_execute/eligibility.py", "src/adapters/postgres/selection.py",
               "src/contracts/execution_states.py"}
    users = [p.relative_to(ROOT).as_posix() for p in s12_files() if "runtime_type" in p.read_text(encoding="utf-8")]
    assert sorted(set(users) - allowed) == []
