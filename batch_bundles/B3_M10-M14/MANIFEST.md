# B3 dependency folder — M10–M14: adapter interface and guard, idempotency and retry, the S12 loop, probe path, live revalidation and cancellation

> **Agents: start here.** Read [`../README.md`](../README.md) (rules for every batch, the S12→S15 module map, the
> names the tests patch), then [`AGENT_GUIDE.md`](AGENT_GUIDE.md) (entry conditions, order, files you may change,
> targets), then one milestone file at a time: [`M10`](milestones/M10_guard.md) · [`M11`](milestones/M11_idempotency_retry.md) · [`M12`](milestones/M12_loop.md) · [`M13`](milestones/M13_probe.md) · [`M14`](milestones/M14_revocation_cancel.md).
> This MANIFEST only lists the files the golden tests load and how to run the reference layer in a scratch checkout.

Every file the B3 golden tests depend on, found by tracing what the tests import when they run (a pytest plugin that
records every loaded module under the checkout), plus the migrations the test database applies, the B3 sabotage
patches and their helper, and the B3 review. Snapshot of 2026-10-01, `s12-work` at `402dd6b`.

**Status: the golden tests are owner-pinned; the source under "Reference implementation" is the drafter's scratch
reference, UNREVIEWED, and is not the milestone implementation.** It exists to prove the tests are passable; the real
implementation is built milestone by milestone under the autopilot.

**The reference is one merged snapshot.** It is the same `src/` as the B4 and B5 folders (the reference built through
M21), so the loop already carries the M15–M21 seams and imports some later modules (marked below). A B3 milestone
builds only what its card asks; later modules arrive in their own milestones.

## How to use it

The folder mirrors the repository layout. It is a layer on top of `s12-work`, not a standalone project: the
architecture scans read git history (tag `s0-s11-certified`), so run it in a checkout.

```
git worktree add ../s12-b3 s12-work          # a clean, separate checkout
cp -r batch_bundles/B3_M10-M14/src/. ../s12-b3/src/
cd ../s12-b3
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/suprpg_test PYTHONPATH=$PWD/src \
  python -m pytest -q -p no:cacheprovider tests_golden/s12/M10_guard.py tests_golden/s12/M11_idempotency_retry.py tests_golden/s12/M12_loop.py tests_golden/s12/M13_probe.py tests_golden/s12/M14_revocation_cancel.py
```

A sabotage patch runs the same way with `GOLDEN_SABOTAGE=$PWD/tests_golden/sabotage/<patch>`. Never copy this layer
over your working `s12-work` tree: it would put unreviewed code into `src/`.

Verified that way on a clean checkout (2026-10-01, PostgreSQL 16, Python 3.11):
- B3: **184 / 184 passed**; sabotage **39 / 39 caught** (none as an error).
- Same layer: M01–M09 490 passed; M15–M18 135 passed; M19–M21 68 passed (with B5's `recovery.py` added);
  the frozen `tests/` suite 836 passed.

## Contents (193 files, plus this MANIFEST and `CHANGES_vs_s12-work.patch`)

### B3 golden tests (5)
- `tests_golden/s12/M10_guard.py`
- `tests_golden/s12/M11_idempotency_retry.py`
- `tests_golden/s12/M12_loop.py`
- `tests_golden/s12/M13_probe.py`
- `tests_golden/s12/M14_revocation_cancel.py`

### Earlier golden files whose helpers they import (1)
- `tests_golden/s12/__init__.py`

### Sabotage patches (39) and their helper (1)
`_guard_base.py` is loaded by five M10 patches by file path, not by import, so a trace cannot see it; it is not a
patch (the certifier runs only files named `Mxx_*`).

- `tests_golden/sabotage/M10_breaker_before_bulkhead.py`
- `tests_golden/sabotage/M10_budget_unchecked.py`
- `tests_golden/sabotage/M10_call_unchecked.py`
- `tests_golden/sabotage/M10_client_error_counts.py`
- `tests_golden/sabotage/M10_mock_no_dedup.py`
- `tests_golden/sabotage/M10_probe_through_breaker.py`
- `tests_golden/sabotage/M10_timeout_from_text.py`
- `tests_golden/sabotage/M10_trial_held_on_cancel.py`
- `tests_golden/sabotage/M10_trial_leak.py`
- `tests_golden/sabotage/M10_unsafe_default_probe.py`
- `tests_golden/sabotage/M11_conflict_ignored.py`
- `tests_golden/sabotage/M11_expired_counts.py`
- `tests_golden/sabotage/M11_fenced_result_kept.py`
- `tests_golden/sabotage/M11_foreign_hit_accepted.py`
- `tests_golden/sabotage/M11_hit_ignored.py`
- `tests_golden/sabotage/M11_irreversible_retried.py`
- `tests_golden/sabotage/M11_key_per_attempt.py`
- `tests_golden/sabotage/M11_marker_not_checked.py`
- `tests_golden/sabotage/M11_no_dispatch_marker.py`
- `tests_golden/sabotage/M11_timeout_retried.py`
- `tests_golden/sabotage/M12_acquire_steals.py`
- `tests_golden/sabotage/M12_consolidate_again.py`
- `tests_golden/sabotage/M12_dependents_cancelled.sql`
- `tests_golden/sabotage/M12_lease_kept_when_fenced.py`
- `tests_golden/sabotage/M12_ledger_mutable.sql`
- `tests_golden/sabotage/M12_lock_in_own_transaction.py`
- `tests_golden/sabotage/M12_log_without_ids.py`
- `tests_golden/sabotage/M12_topology_ignored.py`
- `tests_golden/sabotage/M13_inconclusive_guessed.py`
- `tests_golden/sabotage/M13_ledger_not_consulted.py`
- `tests_golden/sabotage/M13_retry_beyond_ceiling.py`
- `tests_golden/sabotage/M13_uncertain_as_failure.py`
- `tests_golden/sabotage/M14_anyone_can_cancel.py`
- `tests_golden/sabotage/M14_cancel_time_moves.py`
- `tests_golden/sabotage/M14_kill_switch_as_revoked.py`
- `tests_golden/sabotage/M14_live_check_allows_all.py`
- `tests_golden/sabotage/M14_live_check_writes.py`
- `tests_golden/sabotage/M14_no_check_before_call.py`
- `tests_golden/sabotage/M14_validity_ignored.py`
- `tests_golden/sabotage/_guard_base.py`

### Test fixtures (14)
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

### Reference implementation: new files, not on `s12-work` (19)
- `src/adapters/postgres/cancellation.py`
- `src/adapters/postgres/execution_events.py`
- `src/adapters/postgres/idempotency.py`
- `src/adapters/postgres/kernel_policy.py`
- `src/adapters/postgres/migrations/016_execution_events.sql`
- `src/adapters/postgres/migrations/017_recovery_candidates.sql` — owned by M19; present because the test database applies every migration in the folder
- `src/adapters/postgres/reconciliation.py`
- `src/adapters/postgres/step_attempts.py`
- `src/adapters/runtime/mock_adapter.py`
- `src/adapters/runtime/reliability.py`
- `src/contracts/adapter_interface.py`
- `src/contracts/idempotency.py`
- `src/contracts/metrics.py` — owned by M21; loaded only because the merged reference loop imports it
- `src/contracts/verification.py` — owned by M15; loaded only because the merged reference loop imports it
- `src/engine/stages/s12_execute/attempts.py`
- `src/engine/stages/s12_execute/fault_injection.py` — owned by M19; loaded only because the merged reference loop imports it
- `src/engine/stages/s12_execute/reliability.py`
- `src/engine/stages/s12_execute/retry_policy.py`
- `src/engine/stages/s13_reconciliation/probe.py`

### Reference implementation: changed versions of `s12-work` files (9)
The differences are in `CHANGES_vs_s12-work.patch`.

- `src/adapters/postgres/budget_reserver.py`
- `src/adapters/postgres/execution.py`
- `src/adapters/postgres/leases.py`
- `src/adapters/runtime/circuit_breaker.py`
- `src/contracts/execution_states.py`
- `src/engine/stages/s12_execute/admission_control.py`
- `src/engine/stages/s12_execute/eligibility.py`
- `src/engine/stages/s12_execute/loop.py`
- `src/engine/stages/s12_execute/settings.py`

### Reference implementation: written while assembling this folder (2)
The B4/B5 snapshot did not hold these two files (their golden tests never load them), so the reference failed 14 B3
cases without them. They were written on 2026-10-01 against the M12 and M14 golden docstrings and verified as above
(including the `M14_live_check_allows_all`, `M14_validity_ignored` and `M14_live_check_writes` patches). Same
status as the rest: UNREVIEWED. `live_authorization.py` reworks a prototype file (CONF-011 list), so its diff is also
in `CHANGES_vs_s12-work.patch`.

- `src/engine/stages/s12_execute/dispatch.py` — new: `InProcessDispatcher(run).dispatch(tenant_id, execution_id)`
- `src/adapters/postgres/live_authorization.py` — reworked: `PostgresLiveAuthorization(scopes, *, database,
  credentials)`; adds capability retired, `binding_invalid`, `credential_invalid`; read-only; fails closed

### Unchanged `s12-work` source they also import (102)
Identical to `s12-work`; included so the folder lists every dependency (mostly S0–S11 frozen code and migrations).

- `src/adapters/__init__.py`
- `src/adapters/postgres/__init__.py`
- `src/adapters/postgres/admin.py`
- `src/adapters/postgres/admission.py`
- `src/adapters/postgres/api_keys.py`
- `src/adapters/postgres/budget.py`
- `src/adapters/postgres/database.py`
- `src/adapters/postgres/event_schemas.py`
- `src/adapters/postgres/fencing.py`
- `src/adapters/postgres/identity.py`
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
- `src/adapters/postgres/migrations/015_s12_schema.sql`
- `src/adapters/postgres/migrations/__init__.py`
- `src/adapters/postgres/schedules.py`
- `src/adapters/postgres/scope.py`
- `src/adapters/postgres/selection.py`
- `src/adapters/postgres/transition_log.py`
- `src/adapters/postgres/webhook_credentials.py`
- `src/adapters/runtime/__init__.py`
- `src/constants.py`
- `src/contracts/__init__.py`
- `src/contracts/activation.py`
- `src/contracts/admission.py`
- `src/contracts/authorization_state_provider.py`
- `src/contracts/binding_reader.py`
- `src/contracts/capability.py`
- `src/contracts/codec.py`
- `src/contracts/confirmation_record.py`
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
- `src/contracts/step_admission.py`
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
- `src/engine/stages/s12_entry/__init__.py`
- `src/engine/stages/s12_entry/admission.py`
- `src/engine/stages/s12_entry/checks.py`
- `src/engine/stages/s12_entry/confirmation.py`
- `src/engine/stages/s12_entry/verifiers.py`
- `src/engine/stages/s12_execute/__init__.py`
- `src/engine/stages/s12_execute/selection.py`
- `src/engine/stages/s12_execute/transitions.py`
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

### Review
- `docs/gates/S12_B3_REVIEW.md`
