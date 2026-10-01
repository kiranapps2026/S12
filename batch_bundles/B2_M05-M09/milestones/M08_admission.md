# M8: per-step admission controller and worker selection (gate commit E, part 2) ⚙ (built)

| | |
|---|---|
| Status | Built in `6e49b7a`; DEF-005 fixed in `2cd2f9d`; CONF-032 applied in `150a668`. Golden 40/40, sabotage 4/4 |
| Gate | §8 steps 1–3, C5 (a worker at capacity is not selectable), C30 (REJECT mapped by `gate_failed`; gate 7 is a QUEUE, never a REJECT; every decision is a ledger event); WORKER_LIFECYCLE §10 (gates 1–11 in order, first reject wins, stateless), §11 (`AdmissionDecision`), §13 (locality scoring, deterministic and advisory) |
| Rulings | CONF-015 (use the WORKER_LIFECYCLE §11 contract `contracts.step_admission.AdmissionDecision`, not the frozen one), CONF-017 (gates 9 and 11 are DELAY), CONF-032 (gate 8 is a DELAY), DEF-005 (exhausted admission keeps `admission_exhausted`) |
| Golden | `tests_golden/s12/M08_admission.py`: 40 cases, 20 functions |
| Sabotage (4) | `M08_backpressure_rejects`, `M08_capacity_rejects`, `M08_last_gate_wins`, `M08_owner_ignored` |

## Files (as built)

| File | Interface |
|---|---|
| `src/contracts/step_admission.py` | `AdmissionStatus` (ACCEPT, QUEUE, DELAY, REJECT, DEGRADE); `AdmissionDecision(status, reason=None, detail=None, retry_after_ms=None, degraded_features=None, gate_failed=None)`; protocol `DecisionLedger.record(kind, payload)` |
| `src/engine/stages/s12_execute/admission_control.py` | `AdmissionSnapshot` (frozen, bools only; a non-bool raises `TypeError`); `evaluate(snapshot)` (pure); `admit_step(snapshot_source, *, ledger, max_attempts, sleep)`; `reject_outcome(decision)` |
| `src/engine/stages/s12_execute/selection.py` | `score(candidate, *, current_owner)`, `select_worker(candidates, *, current_owner)`, `lease_for_step(*, candidates, acquire, current_owner, max_attempts)` |
| `src/engine/stages/s12_execute/eligibility.py` | `WorkerCandidate` (M8a extends it) |

## Logic and conditions

**`evaluate(snapshot)`: gates in order; the first failing gate decides:**

| Gate | Snapshot field fails when | Reason | Decision |
|---|---|---|---|
| 1 | `kill_switch_engaged` is True | `system_halted` | REJECT |
| 2 | `tenant_quota_exceeded` is True | `tenant_quota_exceeded` | REJECT |
| 3 | `tenant_active` is False | `tenant_inactive` | REJECT |
| 4 | `workspace_active` is False | `workspace_inactive` | REJECT |
| 5 | `mode_allowed` is False | `mode_not_allowed` | REJECT |
| 6 | `provider_allowed` is False | `provider_blocked` | REJECT |
| 7 | `worker_capacity_available` is False | `worker_at_capacity` | **QUEUE** + `retry_after_ms` |
| 8 | `circuit_open` is True | `provider_circuit_open` | **DELAY** + `retry_after_ms` (CONF-032) |
| 9 | `db_pool_pressure` is True | `db_pool_pressure` | **DELAY** (CONF-017) |
| 10 | `budget_available` is False | `budget_exhausted` | REJECT |
| 11 | `system_overloaded` is True | `system_overloaded` | **DELAY** (CONF-017) |
| — | all pass | | ACCEPT, or DEGRADE when `degrade` |

Every decision carries `gate_failed` ("1".."11") and `detail` naming the gate. `retry_after_ms` is
`QUEUE_RETRY_AFTER_MS = 1000` for QUEUE and `DELAY_RETRY_AFTER_MS = 500` for DELAY. DEGRADE carries
`degraded_features = ("analytics", "notifications", "post_processing")` (WORKER_LIFECYCLE §11). `evaluate` touches no database
(`test_admission_module_touches_no_database`).

**`admit_step`:**

- Evaluate a fresh snapshot up to `max_attempts` times. Every decision, including the final one, is recorded as
  `ledger.record("admission_decision", {"status", "gate_failed", "reason"})`.
- QUEUE/DELAY → `await sleep(retry_after_ms / 1000)`, then try again; there is no sleep after the last attempt.
- Still QUEUE/DELAY at the end → `REJECT` with reason `admission_exhausted`.
- `max_attempts < 1` → `ValueError`.

**`reject_outcome(decision)` → (step terminal reason, path):**

| Decision | Result |
|---|---|
| reason `admission_exhausted` | (`admission_exhausted`, consolidate), DEF-005 |
| gate "1" | (`kill_switch_engaged`, revocation) |
| gate "3" | (`authorization_revoked`, revocation) |
| gate "10" | (`budget_exhausted`, budget) |
| any other REJECT | (`admission_rejected`, consolidate) |
| not a REJECT | `ValueError` |

**Selection:**

- `score = 0.30 × locality (1.0 for the current owner, else 0) + 0.20 × (1 − current_load / capacity)`.
- A worker with `current_load >= capacity` is never chosen.
- The highest score wins; ties go to the smallest `worker_id` (deterministic).
- `lease_for_step`: select, then `await acquire(worker_id)`. A `None` from acquire re-reads `await candidates()` and
  selects again, at most `max_attempts` acquisitions, then `"lease_unavailable"`. No candidate at all →
  `"no_worker"`.

## Sabotage

| Patch | Breaks |
|---|---|
| `M08_backpressure_rejects` | gates 9/11 reject instead of delaying |
| `M08_capacity_rejects` | gate 7 rejects instead of queueing |
| `M08_last_gate_wins` | gates evaluated in reverse |
| `M08_owner_ignored` | no locality preference for the current owner |

## Traps

- A momentary outage or load cancelling an admitted run. Gates 7, 8, 9 and 11 never REJECT directly.
- State in the admission module (it is stateless).
- Choosing an adapter from `runtime_type` (M8a forbids it).
- Using the frozen `contracts.worker.AdmissionDecision`.
- Retry delays hard-coded in the loop. The M8 log notes that M12 moves them to settings (§21 S1).

## Regression checklist

- [ ] 40/40; 4 patches caught.
- [ ] Keep `s12-work`'s module docstring (CONF-032, DEF-005). The B3–B5 reference copy is older.
