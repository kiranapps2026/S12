# M8a: worker management (entry safety net, eligibility filters, operation quota) (gate commit E, part 3) ★ (built)

| | |
|---|---|
| Status | Built in `24e2296`. Golden 49/49, x5 (C-M8a PASS), sabotage 3/3. **★ owner review pending** (the autopilot stopped here). STOP-003 `applied` (CONF-019, CONF-020 ruled) |
| Gate | C39 (revised in audit round 2), §7.1 item 7, §7.2 (quota in the admission transaction), §7.3, §8 step 2 (filters **before** scoring), suite 20; invariants I17, I18; WORKER_LIFECYCLE §13 (filters), §16 |
| Rulings | CONF-004 (the S0.1 check lives in `pipeline_state_runner.py`), CONF-007 (`operation_quotas.worker_id` always NULL), CONF-016 (filter 14 is a pure function of `SelectionContext`), CONF-019 (`PostgresSelectionReader.required_runtime_types` reads the binding row once at entry), CONF-020 (soft-quota upgrade text goes in S15, not the frozen `AdmissionOutcome`) |
| Golden | `tests_golden/s12/M08a_worker_mgmt.py`: 49 cases, 23 functions; 5 consecutive runs |
| Sabotage (3) | `M08a_assignment_for_event_runs`, `M08a_bypass_everything`, `M08a_null_workspace_matches` |
| Moved out (audit A6) | "a pause set mid-run cancels nothing" → M14; "refund only for CANCELLED runs with no COMPLETED step" → M16 |

## Files (as built)

| File | Interface |
|---|---|
| `src/engine/stages/s12_execute/eligibility.py` | `WorkerCandidate`, `SelectionContext`, `FilterResult(eligible, removed, bypassed)`, `filter_workers(candidates, ctx)` (pure), `record_filtering(ledger, result)` |
| `src/adapters/postgres/selection.py` | `PostgresSelectionReader(database)`: `candidates(tenant_id)` (ACTIVE workers of the tenant, times as database epoch), `database_now()`, `is_workspace_admin(tenant_id, workspace_id, user_id)` (live owner/admin membership), `required_runtime_types(binding_id)` |
| `src/adapters/postgres/admission.py` | quota consumption and the soft-quota retry inside `admit` |
| `src/engine/stages/s12_execute/settings.py` | `quota_retry_max` (3), `quota_backoff_s` (0.05), `quota_retry_after_ms` (1000), from `S12_QUOTA_*` |

**`WorkerCandidate`** (frozen): `worker_id`, `workspace_id`, `capacity`, `current_load`, `paused_until`,
`scheduled_activation_at` (database epoch or None), `assigned_user_id`, `capability_profile` (frozenset of
capability ids), `settings` (mapping: `restricted_capabilities` list, `execution_policy.max_mutation`),
`runtime_type`.

**`SelectionContext`** (frozen): `workspace_id`, `capability_id`, `effective_mutation`, `required_runtime_types`
(tuple; empty = any), `original_principal_id`, `principal_is_human`, `event_driven`, `admin` (live owner/admin of
the original principal in the run's workspace), `now` (database epoch).

## Logic and conditions

**`filter_workers`: the first failing filter, in this order, removes the worker:**

| Filter | Fails when | Reason | Admin bypass? |
|---|---|---|---|
| 4b | `workspace_id` is NULL or differs from the run's | `workspace_mismatch` | **never** |
| 12b | `paused_until > now` | `worker_paused` | yes, recorded |
| 13b | `scheduled_activation_at > now` | `worker_not_yet_active` | yes, recorded |
| 14 | a **human** principal, **not** event-driven, worker has `assigned_user_id` ≠ original principal | `not_assigned` | yes, recorded |
| 17a | `capability_id` not in `capability_profile` | `capability_mismatch` | never |
| 17b | `capability_id` in `settings.restricted_capabilities` (malformed settings → fail closed) | `capability_mismatch` | never |
| 17c | `required_runtime_types` non-empty and `runtime_type` not in it | `capability_mismatch` | never |
| 17d | `settings.execution_policy.max_mutation` is set and the step's mutation ranks above it (R 0 < W 1 < D 2 < IRREVERSIBLE 3); an unknown ceiling or mutation, or malformed settings, fails closed; no ceiling = any | `mutation_ceiling` | never |

- Elapsed pause and elapsed activation are eligible.
- Filter 14 is skipped for event-driven and system runs, and kept for worker-delegated runs (the human's id is the
  original principal).
- `eligible` keeps input order. `removed` maps each worker to its first failing reason. `bypassed` lists every
  12b/13b/14 failure the admin bypass let through.
- With nothing left, `record_filtering` writes a `no_worker` ledger event with **every** reason, and no lease is
  taken.
- Filters run **before** locality scoring. Only an eligible worker is ever leased (I18, checked through a real
  `PostgresLeaseManager`).

**Operation quota, inside the §7.2 admission transaction (once per run):**

1. Tenant-level `executions` rows, then workspace-level rows, for the current period, locked `FOR UPDATE`.
2. `UPDATE … SET used_count = used_count + 1 WHERE … AND used_count < limit_value`.
3. A hard quota exhausted → `DENIED quota_exhausted`, nothing written.
4. A soft quota exhausted → retry the whole transaction up to `quota_retry_max` times, waiting
   `quota_backoff_s × attempt`, then `DENIED quota_exhausted` with `retry_after_ms`, nothing written. The upgrade text
   comes from S15 (CONF-020).

- A duplicate request consumes nothing.
- **20 concurrent entries against `limit_value = 5` → exactly 5 admitted** (5 runs, I17).
- `limit_value` cannot be lowered below `used_count`. `worker_id` must be NULL.
- **No quota check after entry:** an admitted run's later steps are never rejected by quota.

**Entry pause safety net (§7.1 item 7):** a paused or not-yet-active tenant or workspace is denied at entry, writes
zero rows and consumes no quota. Pause is **not** checked per step.

**`runtime_type` never chooses an adapter** (`test_runtime_type_never_chooses_an_adapter`). It is only a filter.

## Sabotage

| Patch | Breaks |
|---|---|
| `M08a_null_workspace_matches` | a legacy NULL-workspace (or other-workspace) worker matches 4b |
| `M08a_bypass_everything` | the admin bypass also lets through 4b, 17a–d |
| `M08a_assignment_for_event_runs` | filter 14 applied to event-driven and system runs |

The card also names "re-check quota before every step", "filter after locality scoring" and "compare assignment
with `user_id`". The cases `test_no_quota_check_exists_after_entry`, `test_only_an_eligible_worker_is_ever_leased` and
`test_assignment_rule_by_activation` pin those.

## Traps

- Choosing an adapter from `runtime_type`; checking pause per step; a worker-level quota.
- Reading `settings` in S0–S11 code (frozen).
- Implementing worker groups or any other deferred table.

## Regression checklist

- [ ] 49/49, 5 runs in a row; 3 patches caught; I17, I18.
- [ ] M12 builds `SelectionContext` through `eligibility` (`step_context`, `binding_requirements`) and never names a
      runtime type in the loop (RD-9).
