# S12–S15 schema reference (as built on `s12-work`, migrations 001–015)

Generated on 2026-10-01 from a live PostgreSQL 16 database built by applying `src/adapters/postgres/migrations/001…015` to an
empty database (`s12-work` `45ea2bd`). Nothing here is hand-written except the summary sections: the tables, constraints, indexes,
triggers and RLS flags come from the catalog, and the usage map comes from scanning the code. If this file and the database disagree,
the database wins: regenerate it, don't edit it.

## How this schema relates to every milestone

| Check | Result |
|---|---|
| Migrations 001–015 in the B3, B4 and B5 reference layers | **byte-identical** to `s12-work` |
| Schema added after B1 | only `016_execution_events.sql` (M12: `execution_events`, append-only by triggers `execution_events_no_update` / `_no_delete`, forced RLS) and `017_recovery_candidates.sql` (M19: the one `SECURITY DEFINER` function `s12_recovery_candidates`) |
| Columns M10–M21 need that are missing here | **none**: the reference passes every M10–M21 golden case on this schema plus 016/017 |
| Columns M10–M21 rely on that already exist (and when they are first written) | `execution_steps.dispatched_attempt`, `attempt` (M11 marker); `execution_steps.undo_token` (M12); `step_reconciliations.*` (M13, M15, M19); `execution_runs.cancel_requested_at` (M14); `execution_runs.consolidation`, `terminal_reason` (M16); `dead_letters.*` (M17); `idempotency_ledger.*` (M11); `bindings.required_runtime_types` (M8a read, M12 carries) |

## Where the database enforces a rule, and where only code does

| Rule | Database | Code only (a bypassing writer would break it silently) |
|---|---|---|
| state and reason vocabularies (C28) | CHECK from the enums on every listed column | — |
| `cancelled` / `skipped` step needs a reason; reason written once | `chk_step_terminal_reason_required`, trigger `execution_steps_terminal_reason` (`keep_terminal_reason()`) | — |
| one open episode per step | `uq_step_reconciliations_open` (partial unique) | — |
| at most one live reservation per step (I12) | `uq_budget_reservation_open_step` (partial unique, `status <> 'released'`) | — |
| one run per `(tenant_id, request_id)` | `uq_execution_runs_request` | — |
| manifest and plan never change after admission (I9) | triggers `execution_manifests_immutable`, `execution_plans_immutable` (`reject_update()`) | — |
| dead letter: resolved/abandoned needs an outcome; `resolved` flag consistent; rollback ⇒ `retry_mode = NONE` | `chk_dead_letters_outcome`, `chk_dead_letters_resolved`, `chk_dead_letters_rollback` | — |
| quota: no worker-level rows; usage never above the limit; one row per scope and period | `chk_operation_quotas_no_worker`, `operation_quotas_check1`, `uq_operation_quotas_scope` | — |
| worker load within capacity | `workers_check` (`current_load <= capacity`) | — |
| tenant isolation (C34) | forced RLS + `tenant_isolation` (`USING` and `WITH CHECK`) on every tenant table | — |
| **every transition carries a reason (C24)** | `state_transitions.reason` is **nullable** | `transitions.validate` + `log_transition`; I5 checks the log |
| **one owner per execution at a time (C25)** | no unique index on active leases per execution | `PostgresLeaseManager.acquire` under the ownership row lock (`FOR UPDATE`) |
| **token order** | `fence_token_seq` | compare-and-set in `acquire`/`renew`; I8 checks the log |
| **fenced writes** | — | `fenced_write` / `check_fence`; M21 scans for writes outside them |
| **budget never above the pool (I1)** | — | `reserve` under the tenant row lock |
| **a reservation commits only from LOCKED** | — | `transitions.validate` in the reserver |

Any new writer (a script, a migration, an admin tool) must go through the code paths in the right-hand column, or these rules fail
silently. The invariant checker (`tests_golden/fixtures/invariants.py`) is what notices.

## Known gaps (as built; none blocks a golden case)

| Gap | Effect | Owner / where |
|---|---|---|
| 14 columns no code reads or writes: `workers.worker_class`, `runtime_version`, `heartbeat_at`, `last_assignment_at`, `drain_state`; `dead_letters.is_idempotent`, `next_retry_at`; `checkpoints.checkpoint_id`, `pending_steps`, `current_step` (no checkpoint writer at all); `execution_ownership.checkpoint_sequence`; `worker_leases.acquired_at`, `step_reconciliations.opened_at`, `state_transitions.transition_id` (defaults / ordering only) | Spec columns carried for later phases. `dead_letters.is_idempotent` stays `false` on every record M17 writes, so do not read it as information. `workers.worker_class` is NOT NULL without a default: whatever registers workers (not S12 code; fixtures in tests) must supply it | worker lifecycle (deferred, gate §14); checkpoints: CONF-044 (open); `is_idempotent`: M17 may set it from the kernel op's `retry_safety`, not pinned |
| no worker liveness | `heartbeat_at` is never written; the lease TTL is the only liveness signal (C26) | fleet phase |
| `bindings` has no RLS | global registry, by design (S0–S11) | — |
| `pending_confirmations` has no FK to runs | by design (C20) | — |
| frozen confirmation store UPDATEs lack a `tenant_id` predicate | forced RLS is the only guard | **DEF-003, owner** |

## Tables (exact, from the catalog)

S12 tables (`tests_golden/fixtures/code_scan.S12_TABLES`), then `tenants`, `workspaces`, `bindings` (the C39 / M8a columns).

### `execution_runs`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `execution_id` | text | NOT NULL |  |
| `request_id` | text | NOT NULL |  |
| `trace_id` | text | NOT NULL |  |
| `task_id` | text | NOT NULL |  |
| `user_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `workspace_id` | text | NOT NULL |  |
| `conversation_id` | text | NOT NULL |  |
| `plan_id` | text |  |  |
| `status` | text | NOT NULL |  |
| `actor_type` | text | NOT NULL | `'user'::text` |
| `actor_id` | text | NOT NULL |  |
| `consolidation` | text |  |  |
| `budget_spent` | integer | NOT NULL | `0` |
| `duration_ms` | integer |  |  |
| `started_at` | timestamptz |  |  |
| `completed_at` | timestamptz |  |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `cancel_requested_at` | timestamptz |  |  |
| `connection_id` | text |  |  |
| `terminal_reason` | text |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `execution_runs_actor_type_check` | CHECK | `CHECK ((actor_type = ANY (ARRAY['user'::text, 'worker'::text, 'system'::text])))` |
| `execution_runs_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'reconciling'::text, 'completed'::text, 'partial'::text, 'failed'::text, 'cancelled'::text, 'dead_letter'::text])))` |
| `execution_runs_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `execution_runs_user_id_fkey` | FK | `FOREIGN KEY (user_id) REFERENCES users(user_id)` |
| `execution_runs_workspace_id_fkey` | FK | `FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)` |
| `execution_runs_pkey` | PK | `PRIMARY KEY (execution_id)` |

| Index | Definition |
|---|---|
| `idx_execution_runs_status` | `btree (tenant_id, status)` |
| `idx_execution_runs_trace` | `btree (trace_id)` |
| `uq_execution_runs_request` | UNIQUE `btree (tenant_id, request_id)` |

### `execution_steps`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `step_id` | text | NOT NULL |  |
| `plan_step_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `plan_id` | text |  |  |
| `kernel_op_id` | text | NOT NULL |  |
| `resolved_binding_id` | text | NOT NULL |  |
| `effective_risk` | double precision | NOT NULL |  |
| `effective_mutation` | text | NOT NULL |  |
| `request_fingerprint` | text | NOT NULL |  |
| `reservation_id` | text |  |  |
| `status` | text | NOT NULL |  |
| `data` | text |  |  |
| `error` | text |  |  |
| `attempt` | integer | NOT NULL | `1` |
| `undo_token` | text |  |  |
| `duration_ms` | integer |  |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `terminal_reason` | text |  |  |
| `dispatched_attempt` | integer |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `chk_step_terminal_reason` | CHECK | `CHECK (((terminal_reason IS NULL) OR (terminal_reason = ANY (ARRAY['user_cancelled'::text, 'admission_rejected'::text, 'admission_exhausted'::text, 'no_worker'::text, 'lease_unavailable'::text, 'budget_exhausted'::text, 'preflight_failed'::text, 'not_executed_no_retry'::text, 'dependency_failed'::text, 'run_dead_lettered'::text, 'authorization_revoked'::text, 'kill_switch_engaged'::text, 'binding_invalid'::text, 'credential_invalid'::text]))))` |
| `chk_step_terminal_reason_required` | CHECK | `CHECK (((status <> ALL (ARRAY['cancelled'::text, 'skipped'::text])) OR (terminal_reason IS NOT NULL)))` |
| `execution_steps_effective_mutation_check` | CHECK | `CHECK ((effective_mutation = ANY (ARRAY['R'::text, 'W'::text, 'D'::text, 'IRREVERSIBLE'::text])))` |
| `execution_steps_effective_risk_check` | CHECK | `CHECK (((effective_risk >= (0)::double precision) AND (effective_risk <= (1)::double precision)))` |
| `execution_steps_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'partial'::text, 'failed'::text, 'cancelled'::text, 'skipped'::text, 'timeout'::text, 'unknown'::text, 'pending_probe'::text, 'dead_letter'::text])))` |
| `execution_steps_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `execution_steps_reservation_id_fkey` | FK | `FOREIGN KEY (reservation_id) REFERENCES budget_reservations(reservation_id)` |
| `execution_steps_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `execution_steps_pkey` | PK | `PRIMARY KEY (step_id)` |
| `execution_steps_execution_id_plan_step_id_key` | UNIQUE | `UNIQUE (execution_id, plan_step_id)` |

| Index | Definition |
|---|---|
| `idx_execution_steps_execution` | `btree (execution_id)` |

| Trigger | Definition |
|---|---|
| `execution_steps_terminal_reason` | `BEFORE UPDATE ON public.execution_steps FOR EACH ROW EXECUTE FUNCTION keep_terminal_reason()` |

### `execution_manifests`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `execution_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `trace_id` | text | NOT NULL |  |
| `plan_hash` | text | NOT NULL |  |
| `capability_version` | text | NOT NULL |  |
| `binding_version` | text | NOT NULL |  |
| `policy_version` | text | NOT NULL |  |
| `risk_policy_version` | text | NOT NULL |  |
| `authorization_version` | text | NOT NULL |  |
| `auth_result_id` | text |  |  |
| `worker_runtime_version` | text | NOT NULL |  |
| `model_version` | text | NOT NULL |  |
| `created_at` | timestamptz | NOT NULL |  |

| Constraint | Kind | Definition |
|---|---|---|
| `execution_manifests_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `execution_manifests_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `execution_manifests_pkey` | PK | `PRIMARY KEY (execution_id)` |

| Trigger | Definition |
|---|---|
| `execution_manifests_immutable` | `BEFORE UPDATE ON public.execution_manifests FOR EACH ROW EXECUTE FUNCTION reject_update()` |

### `execution_plans`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `execution_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `plan_hash` | text | NOT NULL |  |
| `canonical_plan` | jsonb | NOT NULL |  |
| `frozen_bindings` | jsonb | NOT NULL |  |
| `step_binding_index` | jsonb | NOT NULL |  |
| `verifiers` | jsonb | NOT NULL |  |
| `created_at` | timestamptz | NOT NULL | `now()` |

| Constraint | Kind | Definition |
|---|---|---|
| `execution_plans_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `execution_plans_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `execution_plans_pkey` | PK | `PRIMARY KEY (execution_id)` |

| Trigger | Definition |
|---|---|
| `execution_plans_immutable` | `BEFORE UPDATE ON public.execution_plans FOR EACH ROW EXECUTE FUNCTION reject_update()` |

### `execution_ownership`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `execution_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `worker_id` | text |  |  |
| `runtime_instance_id` | text | NOT NULL |  |
| `lease_id` | text |  |  |
| `fencing_token` | bigint | NOT NULL | `0` |
| `checkpoint_sequence` | integer | NOT NULL | `0` |
| `updated_at` | timestamptz | NOT NULL | `now()` |

| Constraint | Kind | Definition |
|---|---|---|
| `execution_ownership_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `execution_ownership_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `execution_ownership_pkey` | PK | `PRIMARY KEY (execution_id)` |

### `state_transitions`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `transition_id` | bigint | NOT NULL | `nextval('state_transitions_transition_id_seq'::regclass)` |
| `tenant_id` | text | NOT NULL |  |
| `entity_type` | text | NOT NULL |  |
| `entity_id` | text | NOT NULL |  |
| `from_state` | text |  |  |
| `to_state` | text | NOT NULL |  |
| `reason` | text |  |  |
| `runtime_instance_id` | text |  |  |
| `fence_token` | bigint |  |  |
| `occurred_at` | timestamptz | NOT NULL | `now()` |
| `execution_id` | text |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `chk_state_transitions_machine` | CHECK | `CHECK ((entity_type = ANY (ARRAY['run'::text, 'step'::text, 'reservation'::text, 'lease'::text, 'dead_letter'::text, 'episode'::text, 'confirmation'::text])))` |
| `state_transitions_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `state_transitions_pkey` | PK | `PRIMARY KEY (transition_id)` |

| Index | Definition |
|---|---|
| `idx_state_transitions_entity` | `btree (entity_type, entity_id)` |
| `idx_state_transitions_execution` | `btree (tenant_id, execution_id, transition_id)` |
| `idx_state_transitions_machine` | `btree (tenant_id, entity_type, entity_id, transition_id)` |

### `budget_reservations`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `reservation_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `user_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `step_id` | text | NOT NULL |  |
| `cost` | integer | NOT NULL |  |
| `status` | text | NOT NULL | `'reserved'::text` |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `locked_at` | timestamptz |  |  |
| `committed_at` | timestamptz |  |  |
| `released_at` | timestamptz |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `budget_reservations_cost_check` | CHECK | `CHECK ((cost >= 0))` |
| `budget_reservations_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['reserved'::text, 'locked'::text, 'committed'::text, 'released'::text])))` |
| `budget_reservations_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `budget_reservations_pkey` | PK | `PRIMARY KEY (reservation_id)` |

| Index | Definition |
|---|---|
| `idx_reservations_tenant_period` | `btree (tenant_id, created_at) WHERE (status <> 'released'::text)` |
| `uq_budget_reservation_open_step` | UNIQUE `btree (step_id) WHERE (status <> 'released'::text)` |

### `worker_leases`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `lease_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `worker_id` | text | NOT NULL |  |
| `execution_id` | text |  |  |
| `task_id` | text |  |  |
| `fence_token` | bigint | NOT NULL |  |
| `status` | text | NOT NULL | `'active'::text` |
| `expires_at` | timestamptz | NOT NULL |  |
| `acquired_at` | timestamptz | NOT NULL | `now()` |
| `released_at` | timestamptz |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `worker_leases_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'expired'::text, 'released'::text])))` |
| `worker_leases_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `worker_leases_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `worker_leases_worker_id_fkey` | FK | `FOREIGN KEY (worker_id) REFERENCES workers(worker_id)` |
| `worker_leases_pkey` | PK | `PRIMARY KEY (lease_id)` |

| Index | Definition |
|---|---|
| `idx_worker_leases_active` | `btree (worker_id) WHERE (status = 'active'::text)` |
| `idx_worker_leases_execution` | `btree (tenant_id, execution_id)` |

### `step_reconciliations`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `episode_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `step_id` | text | NOT NULL |  |
| `kind` | text | NOT NULL |  |
| `status` | text | NOT NULL |  |
| `outcome` | text |  |  |
| `evidence` | jsonb | NOT NULL | `'{}'::jsonb` |
| `attempts` | integer | NOT NULL | `0` |
| `opened_at` | timestamptz | NOT NULL | `now()` |
| `closed_at` | timestamptz |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `step_reconciliations_attempts_check` | CHECK | `CHECK ((attempts >= 0))` |
| `step_reconciliations_kind_check` | CHECK | `CHECK ((kind = ANY (ARRAY['EXECUTION'::text, 'VERIFICATION'::text])))` |
| `step_reconciliations_outcome_check` | CHECK | `CHECK ((outcome = ANY (ARRAY['EXECUTED_SUCCESS'::text, 'EXECUTED_FAILURE'::text, 'NOT_EXECUTED'::text, 'LEDGER_HIT'::text, 'VERIFIED_PASS'::text, 'VERIFIED_FAIL'::text, 'EXHAUSTED'::text])))` |
| `step_reconciliations_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending_probe'::text, 'reconciling'::text, 'confirmed_success'::text, 'confirmed_failure'::text])))` |
| `step_reconciliations_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `step_reconciliations_step_id_fkey` | FK | `FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)` |
| `step_reconciliations_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `step_reconciliations_pkey` | PK | `PRIMARY KEY (episode_id)` |

| Index | Definition |
|---|---|
| `idx_step_reconciliations_execution` | `btree (tenant_id, execution_id)` |
| `uq_step_reconciliations_open` | UNIQUE `btree (step_id) WHERE (closed_at IS NULL)` |

### `dead_letters`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `dead_letter_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `step_id` | text | NOT NULL |  |
| `kernel_op_id` | text | NOT NULL |  |
| `reservation_id` | text |  |  |
| `attempt_id` | text |  |  |
| `episode_id` | text |  |  |
| `error` | text | NOT NULL |  |
| `error_type` | text | NOT NULL |  |
| `mutation_type` | text | NOT NULL | `'R'::text` |
| `is_idempotent` | boolean | NOT NULL | `false` |
| `retry_count` | integer | NOT NULL | `0` |
| `max_retries` | integer | NOT NULL | `3` |
| `next_retry_at` | timestamptz |  |  |
| `context` | jsonb | NOT NULL | `'{}'::jsonb` |
| `status` | text | NOT NULL | `'pending'::text` |
| `resolved` | boolean | NOT NULL | `false` |
| `retry_mode` | text | NOT NULL |  |
| `resolution_outcome` | text |  |  |
| `origin` | text | NOT NULL | `'execution'::text` |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `updated_at` | timestamptz | NOT NULL | `now()` |

| Constraint | Kind | Definition |
|---|---|---|
| `chk_dead_letters_outcome` | CHECK | `CHECK (((status <> ALL (ARRAY['resolved'::text, 'abandoned'::text])) OR (resolution_outcome IS NOT NULL)))` |
| `chk_dead_letters_resolved` | CHECK | `CHECK ((resolved = (status = ANY (ARRAY['resolved'::text, 'abandoned'::text]))))` |
| `chk_dead_letters_rollback` | CHECK | `CHECK (((origin <> 'rollback'::text) OR (retry_mode = 'NONE'::text)))` |
| `dead_letters_error_type_check` | CHECK | `CHECK ((error_type = ANY (ARRAY['transient'::text, 'permanent'::text, 'data'::text, 'unknown_unresolved'::text])))` |
| `dead_letters_max_retries_check` | CHECK | `CHECK ((max_retries >= 0))` |
| `dead_letters_mutation_type_check` | CHECK | `CHECK ((mutation_type = ANY (ARRAY['R'::text, 'W'::text, 'D'::text, 'IRREVERSIBLE'::text])))` |
| `dead_letters_origin_check` | CHECK | `CHECK ((origin = ANY (ARRAY['execution'::text, 'rollback'::text])))` |
| `dead_letters_resolution_outcome_check` | CHECK | `CHECK ((resolution_outcome = ANY (ARRAY['EXECUTED'::text, 'NOT_EXECUTED'::text, 'UNDETERMINED'::text])))` |
| `dead_letters_retry_count_check` | CHECK | `CHECK ((retry_count >= 0))` |
| `dead_letters_retry_mode_check` | CHECK | `CHECK ((retry_mode = ANY (ARRAY['PROBE'::text, 'VERIFY'::text, 'NONE'::text])))` |
| `dead_letters_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending'::text, 'retrying'::text, 'resolved'::text, 'abandoned'::text])))` |
| `dead_letters_episode_id_fkey` | FK | `FOREIGN KEY (episode_id) REFERENCES step_reconciliations(episode_id)` |
| `dead_letters_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `dead_letters_reservation_id_fkey` | FK | `FOREIGN KEY (reservation_id) REFERENCES budget_reservations(reservation_id)` |
| `dead_letters_step_id_fkey` | FK | `FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)` |
| `dead_letters_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `dead_letters_pkey` | PK | `PRIMARY KEY (dead_letter_id)` |

| Index | Definition |
|---|---|
| `idx_dead_letters_execution` | `btree (tenant_id, execution_id)` |

### `idempotency_ledger`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `idempotency_key` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `kernel_op_id` | text | NOT NULL |  |
| `result` | jsonb | NOT NULL |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `expires_at` | timestamptz | NOT NULL |  |

| Constraint | Kind | Definition |
|---|---|---|
| `idempotency_ledger_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `idempotency_ledger_pkey` | PK | `PRIMARY KEY (idempotency_key)` |

| Index | Definition |
|---|---|
| `idx_idempotency_ledger_tenant_key` | `btree (tenant_id, idempotency_key)` |

### `checkpoints`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `checkpoint_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `sequence` | integer | NOT NULL |  |
| `completed_steps` | jsonb | NOT NULL | `'[]'::jsonb` |
| `failed_steps` | jsonb | NOT NULL | `'[]'::jsonb` |
| `pending_steps` | jsonb | NOT NULL | `'[]'::jsonb` |
| `current_step` | text |  |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `expires_at` | timestamptz |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `checkpoints_sequence_check` | CHECK | `CHECK ((sequence >= 0))` |
| `checkpoints_execution_id_fkey` | FK | `FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)` |
| `checkpoints_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `checkpoints_pkey` | PK | `PRIMARY KEY (checkpoint_id)` |
| `checkpoints_execution_id_sequence_key` | UNIQUE | `UNIQUE (execution_id, sequence)` |

| Index | Definition |
|---|---|
| `idx_checkpoints_execution` | `btree (tenant_id, execution_id)` |

### `operation_quotas`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `quota_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `workspace_id` | text |  |  |
| `resource_type` | text | NOT NULL | `'executions'::text` |
| `period_start` | timestamptz | NOT NULL |  |
| `period_end` | timestamptz | NOT NULL |  |
| `limit_value` | integer | NOT NULL |  |
| `used_count` | integer | NOT NULL | `0` |
| `is_hard` | boolean | NOT NULL | `true` |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `worker_id` | text |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `chk_operation_quotas_no_worker` | CHECK | `CHECK ((worker_id IS NULL))` |
| `operation_quotas_check` | CHECK | `CHECK (((used_count >= 0) AND (limit_value >= 0)))` |
| `operation_quotas_check1` | CHECK | `CHECK ((used_count <= limit_value))` |
| `operation_quotas_check2` | CHECK | `CHECK ((period_end > period_start))` |
| `operation_quotas_resource_type_check` | CHECK | `CHECK ((resource_type = 'executions'::text))` |
| `operation_quotas_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `operation_quotas_worker_id_fkey` | FK | `FOREIGN KEY (worker_id) REFERENCES workers(worker_id)` |
| `operation_quotas_workspace_id_fkey` | FK | `FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)` |
| `operation_quotas_pkey` | PK | `PRIMARY KEY (quota_id)` |
| `uq_operation_quotas_scope` | UNIQUE | `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)` |

| Index | Definition |
|---|---|
| `idx_quotas_lookup` | `btree (tenant_id, resource_type, period_start, period_end)` |

### `workers`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `worker_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `workspace_id` | text |  |  |
| `worker_class` | text | NOT NULL |  |
| `runtime_version` | text |  |  |
| `capability_profile` | jsonb | NOT NULL |  |
| `state` | text | NOT NULL | `'REGISTERED'::text` |
| `capacity` | integer | NOT NULL | `1` |
| `current_load` | integer | NOT NULL | `0` |
| `lease_epoch` | bigint | NOT NULL | `0` |
| `heartbeat_at` | timestamptz |  |  |
| `last_assignment_at` | timestamptz |  |  |
| `drain_state` | text |  |  |
| `settings` | jsonb | NOT NULL | `'{}'::jsonb` |
| `assigned_user_id` | text |  |  |
| `paused_until` | timestamptz |  |  |
| `scheduled_activation_at` | timestamptz |  |  |
| `runtime_type` | text | NOT NULL | `'llm'::text` |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `updated_at` | timestamptz | NOT NULL | `now()` |

| Constraint | Kind | Definition |
|---|---|---|
| `workers_capacity_check` | CHECK | `CHECK ((capacity >= 1))` |
| `workers_check` | CHECK | `CHECK ((current_load <= capacity))` |
| `workers_current_load_check` | CHECK | `CHECK ((current_load >= 0))` |
| `workers_runtime_type_check` | CHECK | `CHECK ((runtime_type = ANY (ARRAY['llm'::text, 'rules'::text, 'vision'::text, 'browser'::text, 'rpa'::text, 'data'::text, 'rag'::text, 'code'::text, 'human'::text])))` |
| `workers_state_check` | CHECK | `CHECK ((state = ANY (ARRAY['REGISTERED'::text, 'ACTIVE'::text, 'DRAINING'::text, 'DRAINED'::text, 'TERMINATED'::text])))` |
| `workers_assigned_user_id_fkey` | FK | `FOREIGN KEY (assigned_user_id) REFERENCES users(user_id)` |
| `workers_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `workers_workspace_id_fkey` | FK | `FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)` |
| `workers_pkey` | PK | `PRIMARY KEY (worker_id)` |

| Index | Definition |
|---|---|
| `idx_workers_tenant` | `btree (tenant_id)` |
| `idx_workers_workspace` | `btree (workspace_id)` |

### `pending_confirmations`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `confirmation_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `execution_id` | text | NOT NULL |  |
| `user_id` | text | NOT NULL |  |
| `conversation_id` | text | NOT NULL |  |
| `plan_id` | text | NOT NULL |  |
| `plan_hash` | text | NOT NULL |  |
| `operations` | jsonb | NOT NULL |  |
| `status` | text | NOT NULL | `'pending'::text` |
| `expires_at` | timestamptz | NOT NULL |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `consumed_at` | timestamptz |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `pending_confirmations_execution_id_check` | CHECK | `CHECK ((execution_id <> ''::text))` |
| `pending_confirmations_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'rejected'::text, 'expired'::text])))` |
| `pending_confirmations_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `pending_confirmations_pkey` | PK | `PRIMARY KEY (confirmation_id)` |

| Index | Definition |
|---|---|
| `idx_confirmations_execution` | `btree (tenant_id, execution_id)` |

### `tenants`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `tenant_id` | text | NOT NULL |  |
| `name` | text | NOT NULL |  |
| `status` | text | NOT NULL | `'active'::text` |
| `budget_pool` | integer | NOT NULL | `10000` |
| `kill_switch_engaged` | boolean | NOT NULL | `false` |
| `max_mutation` | text | NOT NULL | `'W'::text` |
| `policy_version_id` | text | NOT NULL |  |
| `paused_until` | timestamptz |  |  |
| `scheduled_activation_at` | timestamptz |  |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `budget_period` | text | NOT NULL | `'monthly'::text` |

| Constraint | Kind | Definition |
|---|---|---|
| `tenants_budget_period_check` | CHECK | `CHECK ((budget_period = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text])))` |
| `tenants_budget_pool_check` | CHECK | `CHECK ((budget_pool >= 0))` |
| `tenants_max_mutation_check` | CHECK | `CHECK ((max_mutation = ANY (ARRAY['R'::text, 'W'::text, 'D'::text, 'IRREVERSIBLE'::text])))` |
| `tenants_status_check` | CHECK | `CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text, 'suspended'::text, 'deactivated'::text, 'revoked'::text, 'deleted'::text])))` |
| `tenants_pkey` | PK | `PRIMARY KEY (tenant_id)` |

### `workspaces`

RLS enabled, forced; policies: `tenant_isolation`

| Column | Type | Null | Default |
|---|---|---|---|
| `workspace_id` | text | NOT NULL |  |
| `tenant_id` | text | NOT NULL |  |
| `name` | text | NOT NULL |  |
| `policy_version_id` | text |  |  |
| `paused_until` | timestamptz |  |  |
| `scheduled_activation_at` | timestamptz |  |  |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `created_by` | text |  |  |

| Constraint | Kind | Definition |
|---|---|---|
| `workspaces_tenant_id_fkey` | FK | `FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)` |
| `workspaces_pkey` | PK | `PRIMARY KEY (workspace_id)` |

### `bindings`

RLS **OFF**, **not forced**; policies: none

| Column | Type | Null | Default |
|---|---|---|---|
| `binding_id` | text | NOT NULL |  |
| `capability_id` | text | NOT NULL |  |
| `kernel_op_id` | text | NOT NULL |  |
| `provider` | text | NOT NULL |  |
| `engine_module` | text | NOT NULL |  |
| `adapter_class` | text | NOT NULL |  |
| `priority` | integer | NOT NULL | `1` |
| `is_active` | boolean | NOT NULL | `true` |
| `created_at` | timestamptz | NOT NULL | `now()` |
| `required_runtime_types` | jsonb | NOT NULL | `'[]'::jsonb` |

| Constraint | Kind | Definition |
|---|---|---|
| `bindings_capability_id_fkey` | FK | `FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id)` |
| `bindings_kernel_op_id_fkey` | FK | `FOREIGN KEY (kernel_op_id) REFERENCES kernel_ops(kernel_op_id)` |
| `bindings_pkey` | PK | `PRIMARY KEY (binding_id)` |

| Index | Definition |
|---|---|
| `idx_bindings_capability` | `btree (capability_id)` |


## Column usage map

Word-boundary scan of `src/` (live) and the merged B3–B5 reference (later). Generic names are skipped, and a name that also means
something else (for example `completed_steps`, which is also an S15 envelope key) can show a false hit, so treat it as a lead, not proof.

### `execution_runs`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `request_id` | M6, prototype api.py, prototype checks.py, prototype events.py, prototype handler.py, prototype pipeline_state_runner.py, prototype usage.py, prototype webhook.py | M11, M12 loop, M13, M17, M2/M12 |
| `trace_id` | M6, prototype api.py, prototype checks.py, prototype events.py, prototype handler.py, prototype pipeline_state_runner.py | M12, M12 loop, M16, M17, M18, M2/M12 |
| `task_id` | M6, prototype checks.py, prototype handler.py | — |
| `user_id` | M12 loop, M14, M2/M12, M5, M6, M8a, M9, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype store.py, prototype tenant_setup.py, prototype usage.py, prototype webhook_credentials.py | M11, M17 |
| `workspace_id` | M12 loop, M14, M2/M12, M6, M8a, prototype activation.py, prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype event_log.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype scope.py, prototype tenant_setup.py, prototype webhook.py, prototype webhook_credentials.py | M11, M16, M17 |
| `conversation_id` | M6, S0–S11 (frozen), prototype admin_reference.py, prototype api.py, prototype checks.py, prototype handler.py, prototype references.py, prototype run.py | — |
| `plan_id` | M6, S0–S11 (frozen), prototype handler.py | — |
| `actor_type` | M6 | M12 loop, M2/M12 |
| `actor_id` | M6 | — |
| `consolidation` | M12 loop | M12, M16, prototype consolidation.py |
| `budget_spent` | M12 loop, M2/M12 | — |
| `duration_ms` | M12 loop, M2/M12, prototype events.py, prototype handler.py, prototype pipeline_state_runner.py | — |
| `started_at` | M6, prototype handler.py | — |
| `completed_at` | M2/M12, prototype handler.py | M16 |
| `cancel_requested_at` | M2/M12 | M14 |
| `connection_id` | M12 loop, M14, M2/M12, M6, prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_api.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype run.py, prototype schedules.py, prototype tenant_setup.py, prototype webhook.py, prototype webhook_credentials.py | M11, M17, prototype mock_adapter.py |
| `terminal_reason` | M12 loop, M2/M12 | M16, M18, prototype consolidation.py |

### `execution_steps`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `plan_step_id` | M2/M12, M6 | M11, M12 loop, M13, M16, M17, M18 |
| `plan_id` | M6, S0–S11 (frozen), prototype handler.py | — |
| `kernel_op_id` | M6, prototype catalog.py, prototype handler.py, prototype registry.py, prototype verifiers.py | M11, M12, M12 loop, M13, M15, M17, M18, M2/M12, prototype mock_adapter.py, prototype reliability.py |
| `resolved_binding_id` | M6 | — |
| `effective_risk` | M6, prototype checks.py, prototype handler.py, prototype registry.py | M12 loop, M15, M16 |
| `effective_mutation` | M6, M8a, prototype checks.py, prototype handler.py | M16, M17 |
| `request_fingerprint` | M6 | — |
| `reservation_id` | M12 loop, M2/M12, M9 | M11, M13, M16, M17, prototype reliability.py |
| `attempt` | M12 loop, M2/M12, M6, prototype admission_control.py, prototype handler.py, prototype settings.py | M11, M13, prototype reliability.py, prototype retry_policy.py |
| `undo_token` | M12 loop, M2/M12 | M17 |
| `duration_ms` | M12 loop, M2/M12, prototype events.py, prototype handler.py, prototype pipeline_state_runner.py | — |
| `terminal_reason` | M12 loop, M2/M12 | M16, M18, prototype consolidation.py |
| `dispatched_attempt` | M2/M12 | M11, M12 loop |

### `execution_manifests`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `trace_id` | M6, prototype api.py, prototype checks.py, prototype events.py, prototype handler.py, prototype pipeline_state_runner.py | M12, M12 loop, M16, M17, M18, M2/M12 |
| `plan_hash` | M12 loop, M2/M12, M5, M6, S0–S11 (frozen), prototype checks.py, prototype confirmation.py, prototype handler.py, prototype store.py | — |
| `capability_version` | M6, prototype catalog.py, prototype handler.py, prototype registry.py, prototype verifiers.py | — |
| `binding_version` | M6, prototype catalog.py, prototype checks.py, prototype handler.py, prototype registry.py, prototype verifiers.py | — |
| `policy_version` | M6, prototype handler.py, prototype registry.py | — |
| `risk_policy_version` | M6, prototype catalog.py, prototype handler.py, prototype registry.py | — |
| `authorization_version` | M6, prototype catalog.py, prototype handler.py, prototype registry.py | — |
| `auth_result_id` | M6, prototype checks.py, prototype handler.py | — |
| `worker_runtime_version` | M6, prototype catalog.py | — |
| `model_version` | M6, prototype catalog.py | — |

### `execution_plans`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `plan_hash` | M12 loop, M2/M12, M5, M6, S0–S11 (frozen), prototype checks.py, prototype confirmation.py, prototype handler.py, prototype store.py | — |
| `canonical_plan` | M2/M12, M6 | M17, M18 |
| `frozen_bindings` | M2/M12, M6, prototype checks.py, prototype handler.py | M17 |
| `step_binding_index` | M2/M12, M6 | M17 |
| `verifiers` | M12 loop, M2/M12, M6, prototype admission.py, prototype checks.py, prototype verifiers.py | — |

### `execution_ownership`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `worker_id` | M7, M8a, prototype handler.py, prototype selection.py | M12 loop |
| `runtime_instance_id` | M2, M2/M12, M6, M7, M9, prototype admission.py | M12, M12 loop, M13, M16, M17, M19 |
| `lease_id` | M7 | — |
| `fencing_token` | M2, M2/M12, M7 | — |
| `checkpoint_sequence` | **no code** | — |

### `state_transitions`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `transition_id` | **no code** | — |
| `entity_type` | M2 | — |
| `entity_id` | M2, M2/M12, M6, M7, M9 | M13, M16, M17 |
| `from_state` | M2, M2/M12, M6, M7, M9, prototype transitions.py | M13, M16, M17 |
| `to_state` | M2, M2/M12, M6, M7, M9, prototype transitions.py | M13, M16, M17 |
| `runtime_instance_id` | M2, M2/M12, M6, M7, M9, prototype admission.py | M12, M12 loop, M13, M16, M17, M19 |
| `fence_token` | M2, M2/M12, M6, M7, M9 | M12, M12 loop, M13, M16, M17 |
| `occurred_at` | prototype admin.py | — |

### `budget_reservations`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `reservation_id` | M12 loop, M2/M12, M9 | M11, M13, M16, M17, prototype reliability.py |
| `user_id` | M12 loop, M14, M2/M12, M5, M6, M8a, M9, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype store.py, prototype tenant_setup.py, prototype usage.py, prototype webhook_credentials.py | M11, M17 |
| `cost` | M12 loop, M9, S0–S11 (frozen), prototype catalog.py, prototype checks.py, prototype handler.py, prototype registry.py, prototype selection.py | — |
| `locked_at` | M9 | — |
| `committed_at` | M9 | — |
| `released_at` | M7, M9 | M16 |

### `worker_leases`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `lease_id` | M7 | — |
| `worker_id` | M7, M8a, prototype handler.py, prototype selection.py | M12 loop |
| `task_id` | M6, prototype checks.py, prototype handler.py | — |
| `fence_token` | M2, M2/M12, M6, M7, M9 | M12, M12 loop, M13, M16, M17 |
| `expires_at` | M7, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype store.py, prototype webhook_credentials.py | M11 |
| `acquired_at` | **no code** | — |
| `released_at` | M7, M9 | M16 |

### `step_reconciliations`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `episode_id` | — | M12 loop, M13, M17 |
| `kind` | prototype admin.py, prototype admin_api.py, prototype handler.py, prototype schedule.py, prototype schedules.py, prototype schema.py, prototype settings.py, prototype transitions.py | M11, M12, M12 loop, M13, M16, M17, M18, prototype mock_adapter.py |
| `outcome` | M9, prototype admission_control.py, prototype base.py, prototype confirmation.py, prototype event_log.py, prototype guard.py, prototype handler.py, prototype pipeline_state_runner.py, prototype scheduler.py | M12 loop, M13, M16, M17, prototype circuit_breaker.py, prototype consolidation.py, prototype reliability.py |
| `evidence` | — | M12 loop, M13, M15, M17 |
| `attempts` | prototype admission_control.py, prototype settings.py | M11, M12 loop, M13, M15, M17 |
| `opened_at` | **no code** | — |
| `closed_at` | prototype transitions.py | M13 |

### `dead_letters`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `dead_letter_id` | — | M17 |
| `kernel_op_id` | M6, prototype catalog.py, prototype handler.py, prototype registry.py, prototype verifiers.py | M11, M12, M12 loop, M13, M15, M17, M18, M2/M12, prototype mock_adapter.py, prototype reliability.py |
| `reservation_id` | M12 loop, M2/M12, M9 | M11, M13, M16, M17, prototype reliability.py |
| `attempt_id` | — | M11, M12, M12 loop, M13, M17, prototype reliability.py |
| `episode_id` | — | M12 loop, M13, M17 |
| `error_type` | — | M12 loop, M17, M19 |
| `mutation_type` | prototype base.py, prototype handler.py, prototype registry.py | M17 |
| `is_idempotent` | **no code** | — |
| `retry_count` | — | M17 |
| `max_retries` | — | M17, prototype reliability.py |
| `next_retry_at` | **no code** | — |
| `context` | M14, prototype base.py, prototype checks.py, prototype handler.py, prototype pipeline_state_runner.py, prototype usage.py | M11, M12 loop, M13, M15, M17, prototype mock_adapter.py, prototype reliability.py |
| `resolved` | prototype api.py, prototype checks.py, prototype handler.py, prototype pipeline_state_runner.py, prototype references.py | M12 loop, M17 |
| `retry_mode` | — | M12 loop, M17, prototype __init__.py |
| `resolution_outcome` | — | M17 |
| `origin` | — | M17 |

### `idempotency_ledger`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `idempotency_key` | prototype api.py, prototype event_log.py, prototype handler.py, prototype run.py, prototype webhook.py | M11, M12 loop, M15, prototype mock_adapter.py, prototype reliability.py |
| `kernel_op_id` | M6, prototype catalog.py, prototype handler.py, prototype registry.py, prototype verifiers.py | M11, M12, M12 loop, M13, M15, M17, M18, M2/M12, prototype mock_adapter.py, prototype reliability.py |
| `result` | M12 loop, M14, M8a, prototype admin_reference.py, prototype api.py, prototype catalog.py, prototype checks.py, prototype database.py, prototype deepseek_request.py, prototype guard.py, prototype handler.py, prototype onboarding_api.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype verifiers.py | M11, M13, M15, M17, M19, prototype mock_adapter.py, prototype reliability.py |
| `expires_at` | M7, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype store.py, prototype webhook_credentials.py | M11 |

### `checkpoints`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `checkpoint_id` | **no code** | — |
| `sequence` | M7, prototype pipeline_state_runner.py | — |
| `completed_steps` | — | M18 |
| `failed_steps` | — | M18 |
| `pending_steps` | **no code** | — |
| `current_step` | **no code** | — |
| `expires_at` | M7, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype store.py, prototype webhook_credentials.py | M11 |

### `operation_quotas`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `quota_id` | M6 | M16 |
| `workspace_id` | M12 loop, M14, M2/M12, M6, M8a, prototype activation.py, prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype event_log.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype scope.py, prototype tenant_setup.py, prototype webhook.py, prototype webhook_credentials.py | M11, M16, M17 |
| `resource_type` | M6 | M16 |
| `period_start` | M6 | M16 |
| `period_end` | M6 | M16 |
| `limit_value` | M6 | — |
| `used_count` | M6 | M16 |
| `is_hard` | M6 | — |
| `worker_id` | M7, M8a, prototype handler.py, prototype selection.py | M12 loop |

### `workers`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `worker_id` | M7, M8a, prototype handler.py, prototype selection.py | M12 loop |
| `workspace_id` | M12 loop, M14, M2/M12, M6, M8a, prototype activation.py, prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype event_log.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype scope.py, prototype tenant_setup.py, prototype webhook.py, prototype webhook_credentials.py | M11, M16, M17 |
| `worker_class` | **no code** | — |
| `runtime_version` | **no code** | — |
| `capability_profile` | M8a | — |
| `state` | M12 loop, M14, M2, M2/M12, M6, M7, M8a, M9, prototype __init__.py, prototype activation.py, prototype admin_api.py, prototype admission.py, prototype admission_control.py, prototype api.py, prototype base.py, prototype checks.py, prototype circuit_breaker.py, prototype confirmation.py, prototype dependencies.py, prototype guard.py, prototype handler.py, prototype identity.py, prototype onboarding_api.py, prototype pipeline_state_runner.py, prototype plan_steps.py, prototype preconditions.py, prototype selection.py, prototype suspended_runs.py, prototype transitions.py, prototype usage.py, prototype verifiers.py | M11, M15, M17, prototype consolidation.py |
| `capacity` | M7, M8a, prototype admission_control.py, prototype selection.py | — |
| `current_load` | M7, M8a, prototype selection.py | — |
| `lease_epoch` | M7 | — |
| `heartbeat_at` | **no code** | — |
| `last_assignment_at` | **no code** | — |
| `drain_state` | **no code** | — |
| `settings` | M6, M8a, prototype admission_control.py, prototype settings.py | M12 loop, M19 |
| `assigned_user_id` | M8a | — |
| `paused_until` | M8a, prototype activation.py, prototype admin_access.py | — |
| `scheduled_activation_at` | M8a, prototype activation.py, prototype admin_access.py | — |
| `runtime_type` | M8a | — |

### `pending_confirmations`

| Column | Live (`s12-work`) | Added by later milestones |
|---|---|---|
| `confirmation_id` | M5, S0–S11 (frozen), prototype api.py, prototype confirmation.py, prototype handler.py, prototype pipeline_state_runner.py, prototype store.py, prototype suspended_runs.py | — |
| `user_id` | M12 loop, M14, M2/M12, M5, M6, M8a, M9, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype admin_reference.py, prototype api.py, prototype api_keys.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype pipeline_state_runner.py, prototype references.py, prototype run.py, prototype schedules.py, prototype store.py, prototype tenant_setup.py, prototype usage.py, prototype webhook_credentials.py | M11, M17 |
| `conversation_id` | M6, S0–S11 (frozen), prototype admin_reference.py, prototype api.py, prototype checks.py, prototype handler.py, prototype references.py, prototype run.py | — |
| `plan_id` | M6, S0–S11 (frozen), prototype handler.py | — |
| `plan_hash` | M12 loop, M2/M12, M5, M6, S0–S11 (frozen), prototype checks.py, prototype confirmation.py, prototype handler.py, prototype store.py | — |
| `operations` | M7, S0–S11 (frozen), prototype base.py, prototype catalog.py, prototype deepseek_request.py, prototype handler.py | M12 |
| `expires_at` | M7, S0–S11 (frozen), prototype admin.py, prototype admin_access.py, prototype admin_access_api.py, prototype checks.py, prototype handler.py, prototype identity.py, prototype invitations.py, prototype onboarding_api.py, prototype store.py, prototype webhook_credentials.py | M11 |
| `consumed_at` | S0–S11 (frozen), prototype api.py, prototype handler.py, prototype pipeline_state_runner.py, prototype store.py | — |
