# REFAUDIT — State Machine Cross-Reference Verification

**Date**: 2026-09-26
**Status**: COMPLETE — 8 bugs found, all repaired

---

## Bugs Found and Fixed

### BUG-1 (CRITICAL): STATE_TRANSITIONS.md §4 had OLD worker states contradicting WLVA

**Before**:
- STATE_TRANSITIONS.md §4: `initializing`, `idle`, `busy`, `leasing`, `reconciling`, `shutting_down`, `dead`
- WLVA §1: `REGISTERED`, `ACTIVE`, `DRAINING`, `DRAINED`, `TERMINATED`
- WLVA line 305: "See STATE_TRANSITIONS.md §4 for the complete state machine" — circular reference to contradictory content

**After**:
- STATE_TRANSITIONS.md §4 replaced with WorkerIdentity state machine from WLVA §1
- STATE_TRANSITIONS.md §4 has an Owner pointer back to WLVA §1
- WLVA §3 cross-reference removed (STATE_TRANSITIONS.md §4 IS the authoritative definition now)

### BUG-2 (HIGH): Budget state names differed across 3 documents

**Before**:
- STATE_TRANSITIONS.md §3: lowercase `pending`, `reserved`, `locked`, `committed`, `released`
- DATA_CONTRACTS §16.3: UPPERCASE `RESERVED`, `LOCKED`, `COMMITTED`, `RELEASED` (no PENDING)
- DATABASE.md budget_reservations: UPPERCASE `PENDING`, `RESERVED`, `LOCKED`, `COMMITTED`, `RELEASED`

**After**:
- STATE_TRANSITIONS.md §3: UPPERCASE enum names with DB value column, includes PENDING
- DATA_CONTRACTS §16.3 ReservationState: already had all 5 values (PENDING, RESERVED, LOCKED, COMMITTED, RELEASED) — confirmed canonical
- STATE_TRANSITIONS.md §3 now has Owner pointer to DATA_CONTRACTS §16.3

### BUG-3 (HIGH): STATE_TRANSITIONS.md §2 Step States had duplicate definitions with different casing

**Before**:
- STATE_TRANSITIONS.md §2: lowercase `pending`, `running`, uppercase `UNKNOWN`, non-existent `PROBE`, `PENDING_PROBE`, lowercase `completed`, etc.
- Included `PROBE` as a persistent step state (doesn't exist in DATA_CONTRACTS)
- Had `PARTIAL` → `DEAD_LETTER` but no PARTIAL → (terminal)

**After**:
- STATE_TRANSITIONS.md §2 now has Owner pointer to DATA_CONTRACTS §19
- Removed duplicate state definitions — references canonical StepState enum
- Removed non-existent `PROBE` state from transition matrix
- Added `PENDING` → `CANCELLED` transition
- Added `RUNNING` → `PARTIAL` and `RUNNING` → `CANCELLED` transitions
- Added `PARTIAL` → `DEAD_LETTER` transition
- Added `PENDING_PROBE` → `PENDING` transition (probe confirmed not started — re-queue)
- Fixed NO SILENT SUCCESS rule to use UPPERCASE state names

### BUG-4 (MEDIUM): Reconciliation States mismatch between STATE_TRANSITIONS and DATA_CONTRACTS

**Before**:
- STATE_TRANSITIONS.md §10: `UNKNOWN`, `PENDING_PROBE`, `RECONCILING`, `CONFIRMED_SUCCESS`, `CONFIRMED_FAILURE`, `STILL_UNKNOWN`
- DATA_CONTRACTS §22 ReconciliationStatus: `NONE`, `PENDING_PROBE`, `CONFIRMED_SUCCESS`, `CONFIRMED_FAILURE`, `RECONCILING` (no STILL_UNKNOWN, has NONE)

**After**:
- STATE_TRANSITIONS.md §10 now has Owner pointer to DATA_CONTRACTS §22
- Removed `UNKNOWN` (it's a StepState, not ReconciliationStatus)
- Removed `STILL_UNKNOWN` (it's a transient condition, not a state)
- Added `NONE` as the initial state
- Fixed transition matrix to match canonical ReconciliationStatus
- Added note clarifying UNKNOWN vs ReconciliationStatus distinction

### BUG-5 (MEDIUM): execution_steps.status comment included `PROBE` but StepState has no PROBE

**Before**:
- DATABASE.md line 480: `status TEXT NOT NULL, -- pending, running, completed, failed, skipped, partial, UNKNOWN, PROBE`

**After**:
- DATABASE.md line 480: `status TEXT NOT NULL, -- pending, running, completed, failed, skipped, partial, UNKNOWN, PENDING_PROBE, DEAD_LETTER`

### BUG-6 (MEDIUM): execution_runs.status included `UNKNOWN` but ExecutionStatus didn't have it

**Before**:
- DATABASE.md line 445: `status TEXT NOT NULL, -- PENDING, RUNNING, RECONCILING, COMPLETED, FAILED, CANCELLED, DEAD_LETTER, UNKNOWN`
- DATA_CONTRACTS §9 ExecutionStatus: No UNKNOWN or RECONCILING

**After**:
- DATA_CONTRACTS §9 ExecutionStatus: Added `RECONCILING = "reconciling"` with note that UNKNOWN is a StepState, not ExecutionStatus
- DATABASE.md line 445: `status TEXT NOT NULL, -- PENDING, RUNNING, RECONCILING, COMPLETED, FAILED, CANCELLED, DEAD_LETTER`
- UNKNOWN removed from execution_runs comment (execution enters RECONCILING when steps are UNKNOWN)

### BUG-7 (LOW): Cross-State Invariant I-6 referenced `dead` state

**Before**:
- STATE_TRANSITIONS.md §12 I-6: "A worker can only transition to `dead` state"
- WLVA §1: Uses `TERMINATED`, not `dead`

**After**:
- STATE_TRANSITIONS.md §12 I-6: "A worker can only transition to `TERMINATED` state"

### BUG-8 (LOW): WLVA cross-reference to STATE_TRANSITIONS.md §4 was circular

**Before**:
- WLVA line 305: "See STATE_TRANSITIONS.md §4 for the complete state machine"
- STATE_TRANSITIONS.md §4 had different worker states

**After**:
- WLVA upstream contract: Removed STATE_TRANSITIONS.md from the list
- STATE_TRANSITIONS.md §4 is now the authoritative WorkerIdentity state machine (from WLVA)
- Cross-reference is one-directional: STATE_TRANSITIONS.md §4 → WLVA §1

---

## Additional Fixes (discovered during repair)

### PIPELINE_STAGES.md §14 (S12 Execute)
- Fixed UNKNOWN → PROBE cycle reference to UNKNOWN → PENDING_PROBE cycle
- Fixed STILL_UNKNOWN reference to PENDING_PROBE (inconclusive) → retry or DEAD_LETTER
- Fixed lowercase `completed`/`failed` to UPPERCASE `COMPLETED`/`FAILED`

### DATA_CONTRACTS §19.2 (StepState transitions text)
- Added `PENDING_PROBE → PENDING` transition (was missing)
- Added comments explaining each PENDING_PROBE outcome

### STATE_TRANSITIONS.md §12 Cross-State Invariants
- I-1: Removed `PROBE` from list of non-terminal states (PROBE doesn't exist as StepState)
- I-2: Removed `PROBE` from list of states that trigger RECONCILING

---

## Summary

| Bug | Severity | Files Fixed |
|-----|----------|-------------|
| BUG-1 | CRITICAL | STATE_TRANSITIONS.md, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md |
| BUG-2 | HIGH | STATE_TRANSITIONS.md, DATA_CONTRACTS.md |
| BUG-3 | HIGH | STATE_TRANSITIONS.md |
| BUG-4 | MEDIUM | STATE_TRANSITIONS.md |
| BUG-5 | MEDIUM | DATABASE.md |
| BUG-6 | MEDIUM | DATA_CONTRACTS.md, DATABASE.md |
| BUG-7 | LOW | STATE_TRANSITIONS.md |
| BUG-8 | LOW | WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md, STATE_TRANSITIONS.md |

All 8 bugs repaired. State machines are now consistent across all documents.
