# M6: S12 entry checks and durable admission (gate commit D, part 2) ⚙ (built)

| | |
|---|---|
| Status | Built in `6091a87` (DEF-001 fixed); quota and pause safety net added in M8a `24e2296`. Golden 23/23, sabotage 3/3 |
| Gate | §7.1 (items 1–7, 1a, 5a, 5b), §7.2, D1 (verifiers built at entry, deterministic), D3 (`join_mode = all`), C32 (each distinct binding row read once, never re-resolved), C33 (NOT NULL context values), C36 (no step data flow); invariants I5, I9, I10 |
| Rulings | CONF-008 (registry versions moved → fail closed; deferred register), CONF-011 (the prototype `admission.py`, `s12_entry/*` are S12 code) |
| Golden | `tests_golden/s12/M06_entry.py`: 23 cases, 12 functions |
| Sabotage (3) | `M06_first_binding_for_every_step`, `M06_skip_plan_integrity`, `M06_write_before_checks` |

## Files (as built)

| File | Interface |
|---|---|
| `src/engine/stages/s12_entry/checks.py` | `check_entry(state, *, bindings, activation, metadata=None, confirmations=None) -> EntryDecision(allowed, reason, verifiers)` (:103); `references_another_step(value)` (:66) |
| `src/engine/stages/s12_entry/verifiers.py` | `build_verifier(step, *, execution_id, binding_id, metadata)` (:34), `build_verifiers(state, reader) -> VerifierBuild` (:74) |
| `src/engine/stages/s12_entry/admission.py` | `admit_run(state, *, bindings, activation, metadata, admitter, runtime_instance_id, confirmations=None) -> AdmissionOutcome` (:20) |
| `src/adapters/postgres/admission.py` | `PostgresExecutionAdmission(database, *, settings=None).admit(state, verifiers, runtime_instance_id)` (:68): the §7.2 transaction |

## Logic and conditions

**`check_entry`: the order is fixed and the first failure wins. Nothing is written by any check.**

| # | Check | Deny reason |
|---|---|---|
| 1 | S11 succeeded and issued the manifest (`validation_result.is_valid`, manifest and plan present) | `plan_not_validated` |
| 1a | every NOT NULL value of `execution_runs` is in the context (C33) | `context_incomplete` |
| 2 | S8 authorised it: `ctx.auth_passed`, `auth_result_id`, and the manifest's `auth_result_id` matches. **Never re-authorise** | `authorization_missing` |
| 3 | the frozen binding(s) are present | `binding_missing` |
| 4 | `plan.join_mode == "all"` (D3) | `join_mode_unsupported` |
| 5 | `canonical_plan_digest(plan)` equals **both** `manifest.plan_hash` and `plan_result.plan_hash` (undecodable → same reason) | `plan_integrity` |
| 5a | no step parameter references another step's output (C36) | `data_flow_unsupported` |
| 5b | each **distinct** binding row read **once**: its version equals `manifest.binding_version` (C32). No reader, or the reader raises → fail closed | `binding_version_mismatch` / `binding_unavailable` |
| 6 | verifiers built (D1) from the step and the registry metadata at the manifest's versions; a mutation without observation metadata is denied | `verifier_metadata_unavailable` (or the builder's reason) |
| 7 | pause safety net (C39): the S0.1 activation check again, at the database's time | `tenant_paused`, `workspace_paused`, `not_yet_active`; `activation_unavailable` if unreadable |
| C20 | the confirmation check (M5), last | `confirmation_mismatch` / `confirmation_unavailable` |

**`PostgresExecutionAdmission.admit`: one transaction (§7.2), then the outcome:**

1. **Duplicate check.** `(tenant_id, request_id)` already admitted → `DUPLICATE` with the existing execution;
   nothing created and **no quota consumed**. A concurrent duplicate is settled by the unique index (only one
   admits).
2. **Quota** (M8a): see M08a.
3. **Insert** the run (`pending`), the manifest (byte-identical to S11's, `created_at` included), the plan (canonical
   form, `plan_hash`), every step with **its own** binding (`resolved_binding_id`, `effective_risk`,
   `effective_mutation`; I10), and the ownership row (`runtime_instance_id`).
4. **Log** creation `None → pending (created)` for run and steps, then run `pending → running (admitted)`. Every
   row goes through `transitions.validate` and `log_transition`, in insertion order (I5; DEF-001 fixed this).
5. A database failure denies and writes nothing.

**Invariants:** I5 (every log row legal), I9 (every persisted plan's digest equals its `plan_hash`), I10 (each step's
binding columns equal its binding's).

## Sabotage

| Patch | Breaks | Invariant |
|---|---|---|
| `M06_write_before_checks` | the run is written before the checks decide; a denied run leaves rows | zero-rows cases |
| `M06_skip_plan_integrity` | the digest is not recomputed; a plan changed after S11 is admitted | I9 |
| `M06_first_binding_for_every_step` | every step copies the first step's binding (G3) | I10 |

## Traps

- **Re-resolving the binding** or computing risk at S12 (M21's architecture suite also traps any S5 call after
  S11).
- Creating the run row before all checks pass.
- Reading the same binding row more than once (`test_each_distinct_binding_is_read_once`).
- A plan check that compares only one of the two stored hashes.

## Regression checklist

- [ ] 23/23; 3 patches caught; I5, I9, I10 after every admission.
- [ ] M12 re-checks the digest on every **load** too (CONF-034). The entry check stays as it is.
