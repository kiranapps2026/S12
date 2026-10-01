# B2 dependency folder — M5–M9 (incl. M8a): confirmation check, S12 entry, leases, admission and selection, worker management, budget

> **Agents: start here.** Read [`../README.md`](../README.md) (rules for every batch, the S12→S15 module map, the
> names the tests patch), then [`AGENT_GUIDE.md`](AGENT_GUIDE.md) (status, owner actions, files, rules for touching
> this code later), then one milestone file at a time: [`M5`](milestones/M05_confirmation_store.md) · [`M6`](milestones/M06_entry.md) · [`M7`](milestones/M07_leases.md) · [`M8`](milestones/M08_admission.md) · [`M8a`](milestones/M08a_worker_mgmt.md) · [`M9`](milestones/M09_budget.md).

Every file the B2 golden tests depend on, found by tracing what the tests import when they run (a pytest plugin that
records every loaded module), plus the migrations, the B2 sabotage patches and their helpers, and the reviews.
Snapshot of 2026-10-01, `s12-work` at `f4a8d5f`.

## How this folder differs from B3–B5

**B2 is already implemented on `s12-work`.** The source it depends on is the live code in `src/` (verified, owner sign-off pending), so this
folder does **not** carry a copy of `src/`: a second copy would go stale, and an agent might edit the wrong one. The
tables below list every source file with its class (frozen S0–S11, prototype reworked under CONF-011, or new S12 code)
and the last commit that changed it. The golden tests, sabotage patches, fixtures and reviews **are** copied here,
byte-identical to the repository, so the batch can be read in one place.

## Verified state (2026-10-01, plain `s12-work`, PostgreSQL 16, Python 3.11)

- Golden: **174 / 174 (M05 30, M06 23, M07 15, M08 40, M08a 49, M09 17); sabotage 21 / 21 caught; C-M5, C-M7, C-M8a, C-M9 x5 PASS**.
- `pytest tests` 836 passed; `tests_agent` 93 passed; `tests_postgres` 330 passed; `tools/owner_certify.py` 19/19.
- `owner_certify_s12.py --milestone M9` (full): 18/21. The only failing rows are the owner rows **S12-PIN** (B2–B5
  golden files unpinned; three B1 fixtures changed since the pin) and **S12-REC** (STOP-001 `ruled`, STOP-002 `open`).
  See the owner actions in `AGENT_GUIDE.md`.
- Run the certifiers with `PYTHONPATH=src` (or after `pip install -e .`). Without it, `owner_certify.py` reports
  16/19 with 22 collection errors, which is an environment fault, not a regression.

## How to run

```
export TEST_DATABASE_URL=postgresql://postgres@localhost:5432/suprpg_test PYTHONPATH=$PWD/src   # name must end in _test
python -m pytest -q -p no:cacheprovider tests_golden/s12/M05_confirmation_store.py tests_golden/s12/M06_entry.py tests_golden/s12/M07_leases.py tests_golden/s12/M08_admission.py tests_golden/s12/M08a_worker_mgmt.py tests_golden/s12/M09_budget.py
GOLDEN_SABOTAGE=$PWD/tests_golden/sabotage/<patch> python -m pytest -q -p no:cacheprovider tests_golden/s12/<its file>
```

## Contents

### B2 golden tests (6)
- `tests_golden/s12/M05_confirmation_store.py`
- `tests_golden/s12/M06_entry.py`
- `tests_golden/s12/M07_leases.py`
- `tests_golden/s12/M08_admission.py`
- `tests_golden/s12/M08a_worker_mgmt.py`
- `tests_golden/s12/M09_budget.py`

### Sabotage patches (21) and helpers (2)
- `tests_golden/sabotage/M05_accept_pending.py`
- `tests_golden/sabotage/M05_consume_read_then_update.py`
- `tests_golden/sabotage/M05_ignore_execution_id.py`
- `tests_golden/sabotage/M06_first_binding_for_every_step.py`
- `tests_golden/sabotage/M06_skip_plan_integrity.py`
- `tests_golden/sabotage/M06_write_before_checks.py`
- `tests_golden/sabotage/M07_per_worker_token.py`
- `tests_golden/sabotage/M07_renew_after_expiry.py`
- `tests_golden/sabotage/M07_stale_leases_counted.py`
- `tests_golden/sabotage/M07_steal_live_execution.py`
- `tests_golden/sabotage/M08_backpressure_rejects.py`
- `tests_golden/sabotage/M08_capacity_rejects.py`
- `tests_golden/sabotage/M08_last_gate_wins.py`
- `tests_golden/sabotage/M08_owner_ignored.py`
- `tests_golden/sabotage/M08a_assignment_for_event_runs.py`
- `tests_golden/sabotage/M08a_bypass_everything.py`
- `tests_golden/sabotage/M08a_null_workspace_matches.py`
- `tests_golden/sabotage/M09_all_periods_count.py`
- `tests_golden/sabotage/M09_commit_from_reserved.py`
- `tests_golden/sabotage/M09_lock_in_own_transaction.py`
- `tests_golden/sabotage/M09_no_tenant_lock.py`

Helpers are loaded by file path from their patches (not imports), so no trace sees them:
- `tests_golden/sabotage/_budget_base.py`
- `tests_golden/sabotage/_lease_base.py`

### Test fixtures (copied)
- `tests/fixtures/__init__.py`
- `tests/fixtures/deps.py`
- `tests/fixtures/multi.py`
- `tests/fixtures/pipeline.py`
- `tests/fixtures/scenarios.py`
- `tests/fixtures/states.py`
- `tests_golden/__init__.py`
- `tests_golden/conftest.py`
- `tests_golden/fixtures/__init__.py`
- `tests_golden/fixtures/appendix_a.py`
- `tests_golden/fixtures/certified.py`
- `tests_golden/fixtures/code_scan.py`
- `tests_golden/fixtures/db.py`
- `tests_golden/fixtures/invariants.py`
- `tests_golden/s12/__init__.py`

### Reviews and conventions (copied)
- `docs/gates/S12_B2_REVIEW.md`
- `tests_golden/README.md`

### Source: new S12 code (live in `src/`, not copied)

| File | Last change |
|---|---|
| `src/adapters/postgres/confirmation_records.py` | `77c26e2` |
| `src/adapters/postgres/fencing.py` | `32fa999` |
| `src/adapters/postgres/leases.py` | `62f8ebb` |
| `src/adapters/postgres/migrations/015_s12_schema.sql` | `a8f8f58` |
| `src/adapters/postgres/selection.py` | `24e2296` |
| `src/adapters/postgres/transition_log.py` | `838ebcf` |
| `src/contracts/confirmation_record.py` | `77c26e2` |
| `src/contracts/execution_states.py` | `8f38edb` |
| `src/contracts/step_admission.py` | `6e49b7a` |
| `src/engine/stages/s12_entry/confirmation.py` | `77c26e2` |
| `src/engine/stages/s12_execute/admission_control.py` | `150a668` |
| `src/engine/stages/s12_execute/eligibility.py` | `24e2296` |
| `src/engine/stages/s12_execute/selection.py` | `6e49b7a` |
| `src/engine/stages/s12_execute/settings.py` | `32fa999` |

### Source: prototype files reworked under CONF-011 (live in `src/`, not copied)

| File | Last change |
|---|---|
| `src/adapters/postgres/admission.py` | `24e2296` |
| `src/adapters/postgres/budget_reserver.py` | `32fa999` |
| `src/engine/stages/s12_entry/__init__.py` | `ab8d82c` |
| `src/engine/stages/s12_entry/admission.py` | `77c26e2` |
| `src/engine/stages/s12_entry/checks.py` | `77c26e2` |
| `src/engine/stages/s12_entry/verifiers.py` | `ab8d82c` |
| `src/engine/stages/s12_execute/__init__.py` | `ab8d82c` |
| `src/engine/stages/s12_execute/transitions.py` | `8f38edb` |

### Source: frozen S0–S11 files they also load (85; never edit, S12-FRZ checks them byte for byte)
- `src/adapters/__init__.py`
- `src/adapters/postgres/__init__.py`
- `src/adapters/postgres/admin.py`
- `src/adapters/postgres/api_keys.py`
- `src/adapters/postgres/budget.py`
- `src/adapters/postgres/confirmations.py`
- `src/adapters/postgres/database.py`
- `src/adapters/postgres/event_schemas.py`
- `src/adapters/postgres/migrate.py`
- `src/adapters/postgres/migrations/001_s0_s11_schema.sql`
- `src/adapters/postgres/migrations/002_api_keys.sql`
- `src/adapters/postgres/migrations/003_suspended_runs.sql`
- `src/adapters/postgres/migrations/004_pipeline_events.sql`
- `src/adapters/postgres/migrations/005_references.sql`
- `src/adapters/postgres/migrations/006_budget_reservations.sql`
- `src/adapters/postgres/migrations/007_event_gateway.sql`
- `src/adapters/postgres/migrations/008_verifier_metadata.sql`
- `src/adapters/postgres/migrations/009_execution_admission.sql`
- `src/adapters/postgres/migrations/010_step_loop.sql`
- `src/adapters/postgres/migrations/011_event_sources.sql`
- `src/adapters/postgres/migrations/012_admin_api.sql`
- `src/adapters/postgres/migrations/013_access_management.sql`
- `src/adapters/postgres/migrations/014_onboarding_usage_limits.sql`
- `src/adapters/postgres/migrations/__init__.py`
- `src/adapters/postgres/schedules.py`
- `src/adapters/postgres/webhook_credentials.py`
- `src/constants.py`
- `src/contracts/__init__.py`
- `src/contracts/activation.py`
- `src/contracts/admission.py`
- `src/contracts/authorization_state_provider.py`
- `src/contracts/binding_reader.py`
- `src/contracts/capability.py`
- `src/contracts/codec.py`
- `src/contracts/data_sanitizer.py`
- `src/contracts/entry.py`
- `src/contracts/errors.py`
- `src/contracts/event_schema.py`
- `src/contracts/execution_context.py`
- `src/contracts/execution_manifest.py`
- `src/contracts/frozen_binding.py`
- `src/contracts/intent_model.py`
- `src/contracts/kernel_policy.py`
- `src/contracts/pipeline_state.py`
- `src/contracts/plan_hash.py`
- `src/contracts/principal.py`
- `src/contracts/reference_source.py`
- `src/contracts/safety.py`
- `src/contracts/schedule.py`
- `src/contracts/stage_events.py`
- `src/contracts/stage_outputs.py`
- `src/contracts/stage_registry.py`
- `src/contracts/step_execution.py`
- `src/contracts/suspended_runs.py`
- `src/contracts/verifier.py`
- `src/contracts/webhook_credentials.py`
- `src/contracts/worker.py`
- `src/engine/__init__.py`
- `src/engine/control_plane/__init__.py`
- `src/engine/control_plane/pipeline_state_runner.py`
- `src/engine/control_plane/scope.py`
- `src/engine/gateway/__init__.py`
- `src/engine/gateway/schedule.py`
- `src/engine/gateway/schema.py`
- `src/engine/stages/__init__.py`
- `src/engine/stages/plan_steps.py`
- `src/engine/stages/preconditions.py`
- `src/engine/stages/s0_entry/activation.py`
- `src/engine/stages/s0_entry/handler.py`
- `src/engine/stages/s10_confirmation/handler.py`
- `src/engine/stages/s10_confirmation/store.py`
- `src/engine/stages/s11_plan_validation/handler.py`
- `src/engine/stages/s1_normalize/entities.py`
- `src/engine/stages/s1_normalize/handler.py`
- `src/engine/stages/s1_normalize/references.py`
- `src/engine/stages/s2_intent_analysis/handler.py`
- `src/engine/stages/s3_capability_discovery/handler.py`
- `src/engine/stages/s4_graph_classification/handler.py`
- `src/engine/stages/s5_provider_resolution/handler.py`
- `src/engine/stages/s6_task_profile_assembly/handler.py`
- `src/engine/stages/s7_path_decision/handler.py`
- `src/engine/stages/s8_safety_gate/checks.py`
- `src/engine/stages/s8_safety_gate/dependencies.py`
- `src/engine/stages/s8_safety_gate/handler.py`
- `src/engine/stages/s9_plan_creation/handler.py`
