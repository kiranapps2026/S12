# B4 dependency folder — M15–M18: verification, consolidation, dead letters, S15 response

Every file the B4 golden tests depend on, found by tracing what the tests import when they run (plus the migrations,
which the test database applies, and the B4 sabotage patches). Snapshot of 2026-09-30, `s12-work` at
`49d1538`.

**Status: the golden tests are drafts (unpinned); the source under "Reference implementation" is the drafter's
scratch reference, UNREVIEWED, and is not the milestone implementation.** It exists to prove the tests are passable;
the real implementation is built milestone by milestone under the autopilot.

## How to use it

The folder mirrors the repository layout. It is a layer on top of `s12-work`, not a standalone project: the
architecture scans read git history (tag `s0-s11-certified`), so run it in a checkout.

```
git worktree add ../s12-b4 s12-work          # a clean, separate checkout
cp -r batch_bundles/B4_M15-M18/src/. ../s12-b4/src/
cd ../s12-b4
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/suprpg_test PYTHONPATH=$PWD/src \
  python -m pytest -q -p no:cacheprovider tests_golden/s12/M15_verification.py tests_golden/s12/M16_consolidation.py tests_golden/s12/M17_dead_letter.py tests_golden/s12/M18_response.py
```

A sabotage patch runs the same way with `GOLDEN_SABOTAGE=$PWD/tests_golden/sabotage/<patch>`. Never copy this layer
over your working `s12-work` tree: it would put unreviewed code into `src/`.

Verified that way on a clean checkout: 135 / 135 passed; sabotage 12 / 12 caught (none as an error); M01–M09 and
`tests_agent` still 583 green.

## Contents (172 files)

### B4 golden tests (4)
- `tests_golden/s12/M15_verification.py`
- `tests_golden/s12/M16_consolidation.py`
- `tests_golden/s12/M17_dead_letter.py`
- `tests_golden/s12/M18_response.py`

### Earlier golden files whose helpers they import (3)
- `tests_golden/s12/M10_guard.py`
- `tests_golden/s12/M12_loop.py`
- `tests_golden/s12/__init__.py`

### Sabotage patches (12)
- `tests_golden/sabotage/M15_lenient_semantic_parse.py`
- `tests_golden/sabotage/M15_provider_state_skipped.py`
- `tests_golden/sabotage/M15_verification_as_execution.py`
- `tests_golden/sabotage/M16_cancelled_counts_as_completed.py`
- `tests_golden/sabotage/M16_live_step_consolidated.py`
- `tests_golden/sabotage/M16_refund_always.py`
- `tests_golden/sabotage/M17_evidence_optional.py`
- `tests_golden/sabotage/M17_resolution_moves_step.py`
- `tests_golden/sabotage/M17_verify_retry_probes.py`
- `tests_golden/sabotage/M18_cancelled_hides_completed.py`
- `tests_golden/sabotage/M18_internal_ids_leak.py`
- `tests_golden/sabotage/M18_ledger_keeps_bodies.py`

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

### Reference implementation: new files, not on `s12-work` (29)
- `src/adapters/postgres/cancellation.py`
- `src/adapters/postgres/consolidation.py`
- `src/adapters/postgres/dead_letters.py`
- `src/adapters/postgres/execution_events.py`
- `src/adapters/postgres/idempotency.py`
- `src/adapters/postgres/kernel_policy.py`
- `src/adapters/postgres/migrations/016_execution_events.sql`
- `src/adapters/postgres/migrations/017_recovery_candidates.sql`
- `src/adapters/postgres/reconciliation.py`
- `src/adapters/postgres/run_summary.py`
- `src/adapters/postgres/step_attempts.py`
- `src/adapters/runtime/mock_adapter.py`
- `src/adapters/runtime/reliability.py`
- `src/contracts/adapter_interface.py`
- `src/contracts/envelope.py`
- `src/contracts/idempotency.py`
- `src/contracts/metrics.py`
- `src/contracts/verification.py`
- `src/engine/stages/s12_execute/attempts.py`
- `src/engine/stages/s12_execute/fault_injection.py`
- `src/engine/stages/s12_execute/reliability.py`
- `src/engine/stages/s12_execute/retry_policy.py`
- `src/engine/stages/s13_reconciliation/consolidation.py`
- `src/engine/stages/s13_reconciliation/probe.py`
- `src/engine/stages/s13_reconciliation/verification.py`
- `src/engine/stages/s14_dead_letter/__init__.py`
- `src/engine/stages/s14_dead_letter/retry.py`
- `src/engine/stages/s14_dead_letter/rollback.py`
- `src/engine/stages/s15_final_state/response.py`

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

### Unchanged `s12-work` source they also import (100)
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
- `docs/gates/S12_B4_REVIEW.md`
