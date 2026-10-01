# B2 agent guide: M5–M9 incl. M8a (confirmation check, S12 entry, leases, admission and selection, worker management, budget)

Read `../README.md` first: precedence, the ten rules, the S12→S15 module map and the names the tests patch. Read
`../B1_M01-M04/AGENT_GUIDE.md` for the foundation B2 stands on. This file covers what is specific to B2. Each
milestone has its own file in `milestones/`.

## 1. Status: built; owner rows open

**B2 is implemented on `s12-work`.** The agent must not rebuild it. B3 calls straight into it: the loop admits steps
(M8), selects and leases workers (M8/M8a/M7) and reserves budget (M9) for every step.

Verified on 2026-10-01 against plain `s12-work` (`f4a8d5f`), PostgreSQL 16, Python 3.11:

| Check | Result |
|---|---|
| Golden M05 / M06 / M07 / M08 / M08a / M09 | 30 / 23 / 15 / 40 / 49 / 17 passed (174) |
| Sabotage M05–M09 | 21 / 21 caught, none as an error |
| C-M5, C-M7, C-M8a, C-M9 (5 consecutive runs) | PASS |
| `tests` / `tests_agent` / `tests_postgres` | 836 / 93 / 330 passed |
| S0–S11 certifier (`PYTHONPATH=src`) | 19/19 |
| S12-FRZ, S12-DOC | PASS |
| **S12-PIN** | **FAIL: owner row.** No B2 golden file, sabotage patch or helper is pinned yet |
| **S12-REC** | **FAIL: owner row.** STOP-001 `ruled`; STOP-002 `open` |

Milestone commits: M5 `77c26e2`, M6 `6091a87`, M7 `62f8ebb`, M8 `6e49b7a`, M8a `24e2296`, M9 `32fa999`; then
DEF-005 `2cd2f9d` and CONF-032 `150a668` (both in `admission_control.py`).

## 2. Owner actions that close B2 (not agent work)

| # | Action | Why | Unblocks |
|---|---|---|---|
| O1 | Pin the reviewed golden set (`owner_certify_s12.py --pin`) | 6 golden files, 21 patches and the helpers `_lease_base.py`, `_budget_base.py` are "not pinned (new file in a pinned area)" | S12-PIN |
| O2 | Close STOP-002 (`applied` or `withdrawn`) | It was opened because M5 had no golden file; `M05_confirmation_store.py` now exists and passes | S12-REC M5–M9 |
| O3 | STOP-001 `applied` (see B1) | same row blocks every milestone | S12-REC |
| O4 | **M8a ★ review** (plan §4) | The autopilot stopped there ("★ STOP for owner review"). STOP-003 is `applied` (CONF-019/020 ruled) | M8a → `green` |
| O5 | **DEF-003 decision** | Frozen `adapters/postgres/confirmations.py:32-50`: the consume/expire/reject UPDATEs have no `tenant_id` predicate. Reproduced as superuser; forced RLS blocks it under the app role. Either S0–S11 change control (§19.3) or accept RLS as the guard and record the deviation | the S0–S11 defect register |
| O6 | Put CONF-008 into the deferred register | Fail closed when registry versions move (accepted "for this phase") | M21 deferred register |
| O7 | `tools/owner_verify_s12.ps1 M5` … `M9` | only the owner moves statuses | M5–M9 → `green` |

STOP-004 and STOP-005 (M10) are B3's: STOP-004 is resolved by the B3 golden files existing, and STOP-005 by
CONF-021–023 being ruled. Both still need the owner's `applied` before M10 certifies.

## 3. Files B2 owns (as built)

| File | Class | Milestone | Interface (line at `f4a8d5f`) |
|---|---|---|---|
| `src/contracts/confirmation_record.py` | new | M5 | `ConsumedConfirmation` (:13), `ConsumedConfirmationReader.read(confirmation_id, *, tenant_id)` (:20) |
| `src/adapters/postgres/confirmation_records.py` | new | M5 | `PostgresConsumedConfirmationReader(database).read(...)` (:9) |
| `src/engine/stages/s12_entry/confirmation.py` | new | M5 | `confirmation_denial(state, reader) -> str \| None` (:22) |
| `src/engine/stages/s12_entry/checks.py` | prototype | M5/M6 | `check_entry(state, *, bindings, activation, metadata=None, confirmations=None) -> EntryDecision` (:103) |
| `src/engine/stages/s12_entry/admission.py` | prototype | M5/M6 | `admit_run(state, *, bindings, activation, metadata, admitter, runtime_instance_id, confirmations=None)` (:20) |
| `src/engine/stages/s12_entry/verifiers.py` | prototype | M6 | `build_verifier` (:34), `build_verifiers(state, reader)` (:74) |
| `src/adapters/postgres/admission.py` | prototype | M6, M8a | `PostgresExecutionAdmission(database, *, settings=None).admit(state, verifiers, runtime_instance_id)` (:68) |
| `src/adapters/postgres/leases.py` | new | M7 | `Lease` (:63), `LeaseLost` (:72), `PostgresLeaseManager.acquire / renew / release` (:82) |
| `src/contracts/step_admission.py` | new | M8 | `AdmissionStatus` (:15), `AdmissionDecision` (:27), `DecisionLedger.record(kind, payload)` (:36) |
| `src/engine/stages/s12_execute/admission_control.py` | new | M8 (+DEF-005, CONF-032) | `AdmissionSnapshot` (:36), `evaluate` (:83), `admit_step` (:93), `reject_outcome` (:114) |
| `src/engine/stages/s12_execute/selection.py` | new | M8 | `score` (:23), `select_worker` (:29), `lease_for_step` (:37) |
| `src/engine/stages/s12_execute/eligibility.py` | new | M8, M8a | `WorkerCandidate` (:35), `SelectionContext` (:49), `FilterResult` (:63), `filter_workers` (:69), `record_filtering` (:81) |
| `src/adapters/postgres/selection.py` | new | M8a | `PostgresSelectionReader(database)`: `candidates`, `database_now`, `is_workspace_admin`, `required_runtime_types` (:44) |
| `src/engine/stages/s12_execute/settings.py` | new | M8a, M9 | quota retry fields (B1 file, extended) |
| `src/adapters/postgres/budget_reserver.py` | prototype | M9 | `Reservation` (:62); `PostgresBudgetReserver.reserve / lock / commit / release / status` (:68) |
| `src/adapters/postgres/fencing.py` | new | M9 | `check_fence` split out so `lock/commit/release(connection=)` can join the caller's transaction |

Agent tests written alongside (never counted; they mutation-checked the builds): `tests_agent/test_m5_confirmation_entry.py`,
`test_m7_leases.py`, `test_m8_admission_selection.py`, `test_m8a_worker_mgmt.py`, `test_m9_budget.py`.
Prototype tests updated under CONF-011/CONF-035: `tests/stages/test_s12_entry_checks.py`,
`tests_postgres/test_admission.py`, `tests_postgres/test_step_loop.py`.

## 4. Rules for touching B2 code from a later batch

These later changes are **expected and additive**. The B3–B5 reference makes exactly these:

| B2 file | Later change (owner milestone) | Keep |
|---|---|---|
| `leases.py` | `acquire(..., holder=None)` → `FencedOut` when ownership moved (M12, CONF-033); `acquire(..., skip_locked=False)` and `expire_lapsed(tenant_id, execution_id)` (M19) | Defaults keep M07 behaviour; the token comes from `fence_token_seq`; one owner at a time |
| `budget_reserver.py` | `reservation(tenant_id, reservation_id)` read (M10, the guard's `BudgetTracker`); `settle_dead_letter_reservation(conn, …)` (M17) | One fenced write per move; the reserver stays the **only** budget writer (C31) |
| `eligibility.py` | `binding_requirements(reader, binding_ids)`, `step_context(...)` (M12) so the loop never names a runtime type | The filter order and reasons; `filter_workers` stays pure |
| `admission_control.py` | none expected | **`s12-work`'s text is current**: gates 8, 9, 11 are DELAY (CONF-017, CONF-032) and exhausted admission keeps `admission_exhausted` (DEF-005). The B3–B5 reference copies carry older docstrings; do not copy them back |
| `settings.py` | `recovery_sweep_interval_s` (M19) | C37 checks; defaults for every optional field |
| `admission.py`, `s12_entry/*` | none expected | A denied entry writes zero rows; the binding is never re-resolved |

After any change to a B2 file, re-run M05–M09 (including the x5 concurrency rows) and their 21 patches.

## 5. Conflict avoidance (B2-specific)

| Risk | Rule |
|---|---|
| Re-resolving or recomputing after S11 | S12 entry reads each distinct binding row **once** for its version (C32). It never calls S5, never computes risk or mutation (M21 scans it later) |
| Writing before deciding | Every entry check runs before the first write; a denial writes **zero rows** in every S12 table (sabotage `M06_write_before_checks`) |
| Two owners of one execution | `acquire` refuses while the execution has a usable lease (sabotage `M07_steal_live_execution`); tokens only from `fence_token_seq` (sabotage `M07_per_worker_token`) |
| Admission that writes | `evaluate` is pure and `admit_step` writes nothing except ledger events through the injected `DecisionLedger` |
| Capacity cancelling a run | Gate 7 is a QUEUE, never a REJECT (C30); gates 8/9/11 are DELAY. Only a bounded number of retries, then `admission_exhausted` |
| Quota checked per step | Quota is consumed **once**, in the durable-admission transaction (§7.2). An admitted run's later steps are never rejected by quota. Pause is checked at entry (safety net), not per step |
| A worker-level quota | `operation_quotas.worker_id` is always NULL (CONF-007) |
| Frozen contracts | S12 uses `contracts.step_admission.AdmissionDecision` (CONF-015), not the frozen `contracts.worker.AdmissionDecision`. The frozen `AdmissionOutcome` has no `detail`: soft-quota upgrade text is S15's job (CONF-020) |
| Budget outside the reserver | Only `PostgresBudgetReserver` writes `budget_reservations`; no `tenant_budget` table; per **step**, never per execution |

## 6. Commands

```bash
export TEST_DATABASE_URL=postgresql://…/suprpg_test PYTHONPATH=$PWD/src
python tools/owner_certify_s12.py --milestone M9 --fast     # G-M1..G-M9
python tools/owner_certify_s12.py --milestone M9            # + C rows (x5) + X-M9
for f in M05_confirmation_store M06_entry M07_leases M08_admission M08a_worker_mgmt M09_budget; do
  python -m pytest -q tests_golden/s12/$f.py; done
python -m pytest -q tests_agent && python -m pytest -q tests_postgres    # 93 and 330 must hold
```

## 7. Milestone files

| Milestone | Cases | Sabotage | x5 | File |
|---|---|---|---|---|
| M5 confirmation check | 30 | 3 | yes | [milestones/M05_confirmation_store.md](milestones/M05_confirmation_store.md) |
| M6 S12 entry | 23 | 3 | | [milestones/M06_entry.md](milestones/M06_entry.md) |
| M7 leases | 15 | 4 | yes | [milestones/M07_leases.md](milestones/M07_leases.md) |
| M8 admission and selection | 40 | 4 | | [milestones/M08_admission.md](milestones/M08_admission.md) |
| M8a worker management ★ | 49 | 3 | yes | [milestones/M08a_worker_mgmt.md](milestones/M08a_worker_mgmt.md) |
| M9 budget | 17 | 4 | yes | [milestones/M09_budget.md](milestones/M09_budget.md) |

Batch target (met): **174/174, 21/21**, plus the standing exit rules (S0–S11 19/19, frozen code unchanged,
invariants I1, I2, I5, I7–I10, I12 (non-dead-letter parts), I17, I18 after every integration case).
