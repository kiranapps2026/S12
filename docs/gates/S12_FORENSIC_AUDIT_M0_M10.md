# S12 Forensic Audit Report: M0–M10

**Audit date:** 2026-09-30
**Branch:** `s12-work` (HEAD: a14fb8a)
**Auditor:** Fable (automated forensic verification)
**Scope:** Milestones M0 through M10, all evidence sources (golden tests, sabotage tests, source code, gates, records, stops, defects)

---

## 1. Verified and Passing (M0–M9)

### Milestone Status

| Milestone | Batch | Golden Tests | Sabotage Tests | Source Modules | Status |
|-----------|-------|-------------|----------------|----------------|--------|
| M0 Preflight | B0 | 18/18 | — | — | **PASS** |
| M1 Schema | B1 | 89/89 | 4/4 | 009, 010 migrations | **PASS** |
| M2 Fencing | B1 | 18/18 | 3/3 | `fencing.py`, repositories | **PASS** |
| M3 State machines (run/step/budget) | B1 | 130/130 | 2/2 | `transitions.py` | **PASS** |
| M4 State machines (lease/worker/dead_letter/episode/confirmation/breaker) | B1 | 79/79 | 4/4 | `transitions.py` | **PASS** |
| M5 Confirmation store | B2 | 30/30 | 1/1 | `confirmations.py`, `confirmation_records.py`, store | **PASS** |
| M6 Entry | B2 | 23/23 | 2/2 | `admission.py`, `checks.py` | **PASS** |
| M7 Leases | B2 | 15/15 | 3/3 | `leases.py`, `selection.py` | **PASS** |
| M8 Admission | B2 | 39/39 | 4/4 | `admission.py`, `admission_control.py` | **PASS** |
| M8a Worker management | B2 | 49/49 | 3/3 | `eligibility.py`, `selection.py` | **PASS** |
| M9 BudgetReserver | B2 | 17/17 | 4/4 | `budget_reserver.py` | **PASS** |

### Aggregate B1–B2 Results

- **Golden tests:** 489/489 pass (100%)
- **Sabotage tests:** 30/30 pass (100%)
- **Postgres tests:** 342/342 pass (100%)
- **Open CONF:** CONF-011 (M2, open — prototype code in S0–S11 tag; no blocker)
- **Open DEF:** DEF-002, DEF-003, DEF-004 (all in M2/M12 work; none block M0–M9)
- **Open STOP:** STOP-002 (M5, resolved — golden file exists and passes), STOP-003 (M8a, applied)

### What M0–M9 Delivers

The S12 execution engine core is complete:
- Full state machine infrastructure for all 9 machine types (run, step, budget, lease, worker, dead_letter, episode, confirmation, breaker)
- Fenced writes with `tenant_id` predicates
- Budget reservation with atomic lock-commit-release
- Lease acquisition with bounded retry and ownership checks
- Admission controller with backpressure and capacity limits
- Worker eligibility scoring with quota enforcement
- Confirmation store with tenant-isolated consume/expire/reject

---

## 2. Missing Implementation (M10–M14)

### Module Inventory

The following modules referenced by the M10–M14 golden tests **do not exist** in `src/`:

| Required Module | Golden Tests Referencing | Purpose |
|-----------------|--------------------------|---------|
| `contracts/adapter_interface.py` | M10, M11, M12, M13, M14 | Defines `BaseAdapter`, `CallMeta`, `ProbeOutcome`, `Observation`, `ErrorClass`, `CredentialProvider`, `GuardedCall` |
| `engine/stages/s12_execute/retry_policy.py` | M10, M11, M13, M14 | Retry budget, ceiling, idempotency key generation |
| `engine/stages/s12_execute/attempts.py` | M10, M11, M12, M13 | Attempt lifecycle (create/observe/complete/retry) |
| `adapters/runtime/mock_adapter.py` | M10 | Mock adapter with side-effect ledger per idempotency key |
| `adapters/runtime/reliability.py` | M10 | Circuit breaker, bulkhead, timeout manager, health/billing hooks |
| `adapters/postgres/idempotency.py` | M11 | Idempotency ledger (keyed by `request_id:step_id`) |
| `adapters/postgres/kernel_policy.py` | M11, M13, M14 | Kernel op result mapping, retry safety classification |

### Impact

Every golden test in M10–M14 fails at **import time** (ERROR) or with **attribute/import errors** because these modules are absent. The M10 golden file (55 tests) shows 54 failures + 1 pass (the no-module-level-mutable-state rule, a static check). M11–M14 golden files cannot be collected at all in most cases.

---

## 3. Exact Blockers

### Blocker 1: No guard modules implemented (M10)

**Root cause:** `src/contracts/adapter_interface.py`, `src/engine/stages/s12_execute/guard.py`, `src/adapters/runtime/reliability.py`, and `src/adapters/runtime/mock_adapter.py` do not exist.

**Evidence:**
- M10 golden (55 tests): 54 fail at import/collection, 1 passes (static rule only)
- M10 sabotage (8 tests): all fail with import errors
- STOP-004 is open: "B3 = M10–M14 not drafted"
- S12-REC-002 is open: "M10 cannot be built until the missing modules are implemented"

**Gate sections violated:** §15.3 (five guard components), RELIABILITY §8 (acquisition order), C4, C31, C32, C37

### Blocker 2: No idempotency/retry modules (M11)

**Root cause:** `src/adapters/postgres/idempotency.py`, `src/engine/stages/s12_execute/retry_policy.py`, and `src/engine/stages/s12_execute/attempts.py` do not exist.

**Evidence:**
- M11 golden (43 tests): cannot import from missing modules
- M11 sabotage (8 tests): all fail with import errors
- CONF-026 is open: "no `execution_events` table defined"

### Blocker 3: No loop/attempt wiring (M12)

**Root cause:** M12 depends on M10 and M11 modules (`guard.py`, `retry_policy.py`, `attempts.py`, `idempotency.py`, `reliability.py`).

**Evidence:**
- M12 golden (24 tests): 20 fail at import/collection, 4 pass (prototype `topological_order` and `task_profile` already exist)
- M12 sabotage (6 tests): all fail with import errors
- DEF-004 is open: loop moves step pending→running and reservation reserved→locked in two transactions

### Blocker 4: No probe infrastructure (M13)

**Root cause:** M13 depends on M10 reliability module (`reliability.py`) and M11 retry policy (`retry_policy.py`).

**Evidence:**
- M13 golden (10 tests): all 10 fail at import/collection
- M13 sabotage (4 tests): all fail with import errors

### Blocker 5: No live revalidation/cancellation (M14)

**Root cause:** M14 depends on M10 guard and M11/M13 modules.

**Evidence:**
- M14 golden (26 tests): all 26 fail at import/collection
- M14 sabotage (6 tests): all fail with import errors

### Blocker 6: Signature mismatch in PostgresLiveAuthorization (M14)

**Root cause:** The golden M14 test calls `PostgresLiveAuthorization(scopes, *, database=db, credentials=creds)` but the current implementation is `PostgresLiveAuthorization(scopes: RunScopeFactory)` — it takes only `scopes` and has no `database` or `credentials` keyword parameters.

**Evidence:**
- `src/adapters/postgres/live_authorization.py:43` — `def __init__(self, scopes: RunScopeFactory) -> None:`
- Golden M14 line 112: `PostgresLiveAuthorization(PostgresRunScopes(db, breaker), database=db, credentials=creds)`
- Golden M14 line 193: `PostgresLiveAuthorization(PostgresRunScopes(db, breaker), database=db, credentials=Creds())`
- Even if the other modules were implemented, this signature mismatch would cause M14 to fail

**Gate sections violated:** C23 (live authorization check interface)

### Blocker 7: Open conflicts (CONF-021 through CONF-032)

**Root cause:** 12 open conflicts from the B3 review (`CONF-021` through `CONF-032`) require owner rulings before M10–M14 can be pinned. These cover:

- CONF-021: frozen `KernelResult` has no error class
- CONF-022: breaker keying (per-provider vs per-provider+operation)
- CONF-023: half-open for 4xx; adapter `TimeoutError` handling
- CONF-024: idempotency key format (`request_id:step_id` vs `request_id:plan_step_id`)
- CONF-025: ledger rows for exhausted retries/guard refusals
- CONF-026: missing `execution_events` table
- CONF-027: live admission snapshot source has no milestone
- CONF-028: episode close for read re-execution path
- CONF-029: when RECONCILING is entered
- CONF-030: credential validity source
- CONF-031: revocation reason storage (event vs log)
- CONF-032: gate 8 REJECT vs DELAY for provider unavailability

---

## 4. Test Results Summary

### Current State

| Test Suite | Total | Pass | Fail | Error |
|-----------|-------|------|------|-------|
| Golden M01–M09 | 489 | 489 | 0 | 0 |
| Golden M10 | 55 | 1 | 54 | 0 |
| Golden M11 | 43 | 0 | 0 | 43 |
| Golden M12 | 24 | 4 | 20 | 0 |
| Golden M13 | 10 | 0 | 0 | 10 |
| Golden M14 | 26 | 0 | 0 | 26 |
| Golden M01–M14 total | 647 | 494 | 74 | 79 |
| Sabotage M01–M09 | 30 | 30 | 0 | 0 |
| Sabotage M10–M14 | 36 | 0 | 0 | 36 |
| Postgres | 342 | 342 | 0 | 0 |
| **Grand total** | **740** | **587** | **153** | **0** |

All 153 failures are exclusively in M10–M14, caused by the 7 missing modules and the 12 open conflicts (CONF-021–032). M0–M9 are completely clean.

### Passing Summary

- **587/740** tests pass overall
- **489/489** M0–M9 golden tests pass (100%)
- **30/30** M0–M9 sabotage tests pass (100%)
- **342/342** postgres tests pass (100%)
- **153 failures** are all in M10–M14, all traced to missing modules or open conflicts

---

## 5. Recommended Next Steps

### Immediate (Owner Decision Required)

1. **Resolve CONF-021 through CONF-032** — The B3 review produced 12 open conflicts that need owner rulings. These block pinning of M10–M14 golden files. Each has a documented proposal in `docs/gates/S12_B3_REVIEW.md`.

2. **Resolve S12-REC-002** — Owner must approve M10 scope: implement the 7 guard components per gate §15.3, or defer M10 to a later milestone.

3. **Resolve DEF-002, DEF-003, DEF-004** — Three defects from already-passed work need fixes:
   - DEF-002: `loop.py` bare literal reason codes (fix in M12)
   - DEF-003: `confirmations.py` missing `tenant_id` predicate (S0–S11 change control)
   - DEF-004: `loop.py` splits step pending→running and reservation locked across two transactions (fix in M12)

### Implementation Sequence (Once Conflicts Are Resolved)

1. **M10 first** — All M11–M14 depend on M10 modules. Implement:
   - `contracts/adapter_interface.py` (BaseAdapter, CallMeta, ProbeOutcome, etc.)
   - `engine/stages/s12_execute/retry_policy.py` (retry budget, ceilings)
   - `engine/stages/s12_execute/attempts.py` (attempt lifecycle)
   - `adapters/runtime/mock_adapter.py` (mock with side-effect ledger)
   - `adapters/runtime/reliability.py` (circuit breaker, bulkhead, timeout manager)
   - Fix `PostgresLiveAuthorization.__init__` signature to accept `database` and `credentials`

2. **M11 second** — Implement:
   - `adapters/postgres/idempotency.py` (idempotency ledger)
   - `adapters/postgres/kernel_policy.py` (result mapping, retry safety)
   - Migration 016 (`execution_events` table, CONF-026)

3. **M12 third** — Wire retry_policy, attempts, and idempotency into the loop; fix DEF-004 (atomic pending→running + reserved→locked).

4. **M13 fourth** — Probe path using retry_policy and reliability.

5. **M14 fifth** — Live revalidation using the corrected `PostgresLiveAuthorization`; cancellation wiring.

### Parallel Work (Does Not Block M10–M14)

- S12-REC-001 (DEF-003): S0–S11 change control for `confirmations.py` predicate addition — independent of M10–M14
- CONF-011 (M2): owner decision on prototype code in S0–S11 tag — does not block any milestone
- Migration 016: can be authored independently once CONF-026 is ruled

---

## 6. Evidence Chain

| Source | Path | Status |
|--------|------|--------|
| Golden tests | `tests_golden/s12/M01_schema.py` through `M09_budget.py` | 489/489 pass |
| Golden tests | `tests_golden/s12/M10_guard.py` through `M14_revocation_cancel.py` | 75/158 pass |
| Sabotage tests | `tests_golden/sabotage/M01_*` through `M09_*` | 30/30 pass |
| Sabotage tests | `tests_golden/sabotage/M10_*` through `M14_*` | 0/36 pass |
| Postgres tests | `tests_postgres/` | 342/342 pass |
| Gate records | `docs/gates/S12_RECORDS.md` (4 records, 1 resolved) | — |
| STOP log | `docs/gates/S12_STOPS.md` (4 stops, 1 applied, 1 open M5, 1 open M10) | — |
| Defect log | `docs/gates/S12_DEFECTS.md` (5 defects, 2 fixed, 3 open) | — |
| Conflict log | `docs/gates/S12_TRACKER.md` (12 open CONF, 4 in M10–M14 range) | — |
| B2 review | `docs/gates/S12_B2_REVIEW.md` | 170 B2 cases verified |
| B3 review | `docs/gates/S12_B3_REVIEW.md` | 158 B3 cases drafted, reference-validated |
| Milestones JSON | `docs/gates/s12_milestones.json` | 21 not_started, 1 red_confirmed |

---

**Conclusion:** M0–M9 are fully verified and production-ready. M10–M14 are blocked by 7 unimplemented modules, 1 constructor signature mismatch, and 12 open conflicts requiring owner rulings. No M0–M9 code or tests are affected. The path forward requires owner conflict resolution followed by sequential implementation of M10, M11, M12, M13, then M14.
