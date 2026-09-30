"""M6 golden — S12 entry checks and durable admission (gate commit D part 2). Owner-pinned.

Gate v10: §7.1 (items 1–7, 1a, 5a, 5b), §7.2, D1 (verifiers built at entry, deterministic), D3 (join_mode all), C32
(each distinct binding row read once, never re-resolved), C33 (NOT NULL context values), C36 (step data flow denied);
invariants I5, I9, I10. The prototype (adapters/postgres/admission.py, s12_entry/) is S12 code under CONF-011.

Interface this file fixes (the prototype's, kept):
  * ``engine.stages.s12_entry.admission.admit_run(state, *, bindings, activation, metadata, admitter,
    runtime_instance_id, confirmations=None) -> contracts.admission.AdmissionOutcome``;
  * ``adapters.postgres.admission.PostgresExecutionAdmission(database)`` is the admitter;
  * ``engine.stages.s12_entry.checks.check_entry(state, *, bindings, activation, metadata, confirmations=None)``
    returns ``EntryDecision(allowed, reason, verifiers)``.
A denied entry writes **zero rows** in every S12 table. An admitted run is RUNNING; its manifest equals S11's field by
field; its plan, steps, ownership and transition log satisfy I5, I9 and I10.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from contracts.activation import ActivationState
from contracts.admission import ADMITTED, DENIED, DUPLICATE
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import StepOutputReference, ValidationResult
from tests_golden.fixtures.certified import (AllMetadata, ManifestBindings, NoPause, certified_state, entry_readers,
                                             fresh, seed_identity)
from tests_golden.fixtures.invariants import assert_system_invariants

T = "golden-tenant"
RUNTIME = "runtime-A"
TABLES = ("execution_runs", "execution_steps", "execution_manifests", "execution_plans", "execution_ownership",
          "state_transitions", "budget_reservations", "worker_leases")


def _state(suffix: str, chain: bool = False):
    return fresh(certified_state(tenant_id=T, chain=chain), suffix)


def _rehash(state, plan):
    """Replace the plan and recompute both hashes, so only the check under test can deny it."""
    digest = canonical_plan_digest(plan)
    return dataclasses.replace(state, plan=dataclasses.replace(state.plan, plan=plan, plan_hash=digest),
                               execution_manifest=dataclasses.replace(state.execution_manifest, plan_hash=digest))


async def _counts(schema) -> dict:
    return {t: await schema.fetchval(f"SELECT count(*) FROM {t}") for t in TABLES}


def _admit(schema, run, state, **overrides):
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    run(seed_identity(schema, state))
    kwargs = {**entry_readers(), "admitter": PostgresExecutionAdmission(schema.database()),
              "runtime_instance_id": RUNTIME, **overrides}
    return run(admit_run(state, **kwargs))


class Paused:
    def __init__(self, **fields):
        self.fields = fields

    async def read(self, tenant_id, workspace_id):
        now = time.time()
        base = {"tenant_paused_until": None, "tenant_activation_at": None, "workspace_paused_until": None,
                "workspace_activation_at": None}
        return ActivationState(now, **{**base, **{k: now + v for k, v in self.fields.items()}})


class Raising:
    async def binding_version(self, binding_id):
        raise ConnectionError("registry down")


class NoObservation:
    async def read(self, kernel_op_ids, *, capability_version, binding_version):
        return {}


def _deny_cases():
    base = certified_state(tenant_id=T)
    ctx, plan = base.execution_context, base.plan.plan
    yield "plan_not_validated", {"validation_result": ValidationResult(is_valid=False, errors=("x",))}, {}
    yield "context_incomplete", {"execution_context": dataclasses.replace(ctx, task_id="")}, {}
    yield "authorization_missing", {"execution_context": dataclasses.replace(ctx, auth_passed=False)}, {}
    yield "binding_missing", {"frozen_binding_identity": None}, {}
    yield "join_mode_unsupported", {"plan": dataclasses.replace(base.plan, plan=dataclasses.replace(plan,
                                                                                                    join_mode="any"))}, {}
    tampered = dataclasses.replace(plan.steps[0], params={**plan.steps[0].params, "tampered": True})
    yield "plan_integrity", {"plan": dataclasses.replace(base.plan, plan=dataclasses.replace(plan, steps=(tampered,)))}, {}
    yield "binding_version_mismatch", {}, {"bindings": ManifestBindings("bind-other")}
    yield "binding_unavailable", {}, {"bindings": Raising()}
    yield "tenant_paused", {}, {"activation": Paused(tenant_paused_until=3600)}
    yield "workspace_paused", {}, {"activation": Paused(workspace_paused_until=3600)}
    yield "not_yet_active", {}, {"activation": Paused(tenant_activation_at=3600)}


@pytest.mark.parametrize("reason,state_changes,reader_changes", list(_deny_cases()), ids=lambda v: v if isinstance(v, str) else "")
def test_entry_denial_has_its_reason_and_writes_nothing(db_schema, run, reason, state_changes, reader_changes):
    state = dataclasses.replace(_state(f"deny-{reason}"), **state_changes)
    run(seed_identity(db_schema, state))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state, **reader_changes)
    assert (outcome.status, outcome.reason) == (DENIED, reason)
    assert run(_counts(db_schema)) == before


def test_mutation_without_observation_metadata_is_denied(db_schema, run):
    """D1: a W step whose operation has no observation method gets no verifier, so the run is not admitted."""
    state = _state("deny-verifier", chain=True)
    assert all(step.mutation == "W" for step in state.plan.plan.steps)
    run(seed_identity(db_schema, state))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state, metadata=NoObservation())
    assert (outcome.status, outcome.reason) == (DENIED, "verifier_metadata_unavailable")
    assert run(_counts(db_schema)) == before


def test_step_output_reference_is_denied(db_schema, run):
    """C36: a parameter that consumes another step's output (hashes recomputed, so only 5a can deny)."""
    base = _state("deny-dataflow")
    step = base.plan.plan.steps[0]
    step = dataclasses.replace(step, params={**step.params, "id": StepOutputReference("step-0", "id", "str")})
    state = _rehash(base, dataclasses.replace(base.plan.plan, steps=(step,)))
    run(seed_identity(db_schema, state))
    before = run(_counts(db_schema))
    outcome = _admit(db_schema, run, state)
    assert (outcome.status, outcome.reason) == (DENIED, "data_flow_unsupported")
    assert run(_counts(db_schema)) == before


def test_database_failure_denies_and_writes_nothing(db_schema, run):
    from engine.stages.s12_entry.admission import admit_run

    class Broken:
        async def admit(self, state, verifiers, runtime_instance_id):
            raise ConnectionError("database gone")

    state = _state("deny-db")
    run(seed_identity(db_schema, state))
    before = run(_counts(db_schema))
    outcome = run(admit_run(state, **entry_readers(), admitter=Broken(), runtime_instance_id=RUNTIME))
    assert (outcome.status, outcome.reason) == (DENIED, "admission_unavailable")
    assert run(_counts(db_schema)) == before


# --- admitted ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chain", [False, True], ids=["one-step", "two-step-chain"])
def test_admitted_run_is_durable_and_consistent(db_schema, run, chain):
    state = _state(f"ok-{chain}", chain=chain)
    outcome = _admit(db_schema, run, state)
    assert (outcome.status, outcome.execution_id, outcome.run_status) == (ADMITTED, state.plan.execution_id, "running")
    eid = state.plan.execution_id
    runs = run(db_schema.fetch("SELECT * FROM execution_runs WHERE execution_id = $1", eid))
    assert len(runs) == 1 and runs[0]["status"] == "running" and runs[0]["tenant_id"] == T
    assert runs[0]["request_id"] == state.execution_context.request_id
    steps = run(db_schema.fetch("SELECT * FROM execution_steps WHERE execution_id = $1 ORDER BY plan_step_id", eid))
    assert sorted(s["plan_step_id"] for s in steps) == sorted(s.id for s in state.plan.plan.steps)
    assert all(s["status"] == "pending" and s["step_id"] == f"{eid}:{s['plan_step_id']}" for s in steps)
    # G3: each step row carries THAT step's frozen binding from the certified state (not only a consistent index)
    from engine.stages.plan_steps import plan_step_bindings
    expected = ({s.id: state.frozen_binding_identity for s in state.plan.plan.steps} if not chain else
                {step.id: item.binding for step, item in zip(state.plan.plan.steps, plan_step_bindings(state))})
    for row in steps:
        b = expected[row["plan_step_id"]]
        assert (row["resolved_binding_id"], row["effective_risk"], row["effective_mutation"]) == \
            (b.binding_id, b.effective_risk, b.effective_mutation), row["plan_step_id"]
    if chain:
        assert len({row["resolved_binding_id"] for row in steps}) == 2
    owner = run(db_schema.fetch("SELECT runtime_instance_id FROM execution_ownership WHERE execution_id = $1", eid))
    assert [o["runtime_instance_id"] for o in owner] == [RUNTIME]
    run(assert_system_invariants(db_schema))


def test_manifest_is_persisted_identical_to_s11(db_schema, run):
    state = _state("manifest")
    _admit(db_schema, run, state)
    row = run(db_schema.fetch("SELECT * FROM execution_manifests WHERE execution_id = $1", state.plan.execution_id))[0]
    m = state.execution_manifest
    for field in ("execution_id", "trace_id", "plan_hash", "capability_version", "binding_version", "policy_version",
                  "risk_policy_version", "authorization_version", "auth_result_id", "worker_runtime_version",
                  "model_version"):
        assert row[field] == getattr(m, field), field


def test_run_creation_and_admission_are_logged_as_appendix_a_transitions(db_schema, run):
    state = _state("log")
    _admit(db_schema, run, state)
    eid = state.plan.execution_id
    rows = run(db_schema.fetch("SELECT entity_type, entity_id, from_state, to_state, reason FROM state_transitions"
                               " WHERE entity_id = $1 OR entity_id LIKE $2 ORDER BY transition_id", eid, f"{eid}:%"))
    run_rows = [(r["from_state"], r["to_state"], r["reason"]) for r in rows if r["entity_type"] == "run"]
    assert run_rows == [(None, "pending", "created"), ("pending", "running", "admitted")]
    step_rows = [(r["from_state"], r["to_state"], r["reason"]) for r in rows if r["entity_type"] == "step"]
    assert step_rows == [(None, "pending", "created")] * len(state.plan.plan.steps)
    run(assert_system_invariants(db_schema))


def test_duplicate_request_returns_the_existing_execution_and_creates_nothing(db_schema, run):
    state = _state("dup")
    first = _admit(db_schema, run, state)
    before = run(_counts(db_schema))
    again = dataclasses.replace(state, plan=dataclasses.replace(state.plan, execution_id="golden-exec-dup-2"),
                                execution_manifest=dataclasses.replace(state.execution_manifest,
                                                                       execution_id="golden-exec-dup-2"))
    second = _admit(db_schema, run, again)
    assert (second.status, second.execution_id) == (DUPLICATE, first.execution_id)
    assert run(_counts(db_schema)) == before


def test_concurrent_duplicates_admit_once(db_schema, run):
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    state = _state("dup-race")
    run(seed_identity(db_schema, state))
    admitter = PostgresExecutionAdmission(db_schema.database())

    async def one(i):
        s = dataclasses.replace(state, plan=dataclasses.replace(state.plan, execution_id=f"golden-exec-race-{i}"),
                                execution_manifest=dataclasses.replace(state.execution_manifest,
                                                                       execution_id=f"golden-exec-race-{i}"))
        return await admit_run(s, **entry_readers(), admitter=admitter, runtime_instance_id=RUNTIME)

    async def race():
        return await asyncio.gather(*(one(i) for i in range(8)))

    outcomes = run(race())
    assert [o.status for o in outcomes].count(ADMITTED) == 1
    assert {o.execution_id for o in outcomes} == {next(o.execution_id for o in outcomes if o.status == ADMITTED)}
    assert run(db_schema.fetchval("SELECT count(*) FROM execution_runs WHERE request_id = $1",
                                  state.execution_context.request_id)) == 1


# --- D1 and C32 --------------------------------------------------------------------------------------------------

def test_verifier_factory_is_deterministic():
    from engine.stages.s12_entry.checks import check_entry
    state = certified_state(tenant_id=T, chain=True)
    first = asyncio.run(check_entry(state, **entry_readers()))
    second = asyncio.run(check_entry(state, **entry_readers()))
    assert first.allowed and first.verifiers == second.verifiers and len(first.verifiers) == 2


def test_each_distinct_binding_is_read_once():
    from engine.stages.s12_entry.checks import check_entry
    state = certified_state(tenant_id=T, chain=True)
    bindings = ManifestBindings()
    decision = asyncio.run(check_entry(state, bindings=bindings, activation=NoPause(), metadata=AllMetadata()))
    distinct = {b.binding_id for b in state.frozen_bindings}
    assert decision.allowed and sorted(bindings.calls) == sorted(distinct)


def test_entry_never_resolves_bindings_again():
    """C32 / §7.1 traps: S12 entry code imports no resolver (S5) and computes no risk (S6)."""
    from tests_golden.fixtures.code_scan import ROOT, imports
    entry = [ROOT / "src/engine/stages/s12_entry" / n for n in ("checks.py", "admission.py", "verifiers.py")]
    entry.append(ROOT / "src/adapters/postgres/admission.py")
    for path in entry:
        mods = imports(path)
        assert not any("s5_provider_resolution" in m or "s6_task_profile" in m for m in mods), path.name
