# M14: live revalidation and cancellation (gate commit H, part 3) ★

| | |
|---|---|
| Gate | C15, C16, C23, C30, C35 (validity), C39 (a pause while RUNNING), suites 16a, 16b; invariant I14 |
| Rulings | CONF-030 (`CredentialProvider.credential_valid`), CONF-031 (the event records the reason; the failing check's name is logged), CONF-032 (gate 8 is a DELAY: a persistent outage ends `admission_exhausted`, never a cancelled run) |
| Golden | `tests_golden/s12/M14_revocation_cancel.py`: 28 cases |
| Sabotage (7) | `M14_anyone_can_cancel`, `M14_cancel_time_moves`, `M14_kill_switch_as_revoked`, `M14_live_check_allows_all`, `M14_live_check_writes`, `M14_no_check_before_call`, `M14_validity_ignored` |
| Reference | `src/adapters/postgres/live_authorization.py` (written for this bundle, see the MANIFEST), `src/adapters/postgres/cancellation.py`, `execution.py` (`cancel_requested`), `loop.py`, `attempts.py` |
| Checkpoint | **★ owner review** before M15: the milestone summary and a sample of transition logs |

## Files

| File | Action |
|---|---|
| `src/contracts/adapter_interface.py` | `CredentialProvider` gains `async credential_valid(tenant_id, connection_id) -> bool` |
| `src/adapters/postgres/live_authorization.py` | **rework** of the prototype: `PostgresLiveAuthorization(scopes, *, database, credentials)`. It implements the frozen `LiveAuthorization` port and writes nothing |
| `src/adapters/postgres/cancellation.py` | **new**: `PostgresCancellation(database).request(tenant_id, execution_id, user_id) -> bool` |
| `src/adapters/postgres/execution.py` | the store reads `cancel_requested_at` (an ordinary method, never a method attached to the class at import) |
| `src/engine/stages/s12_execute/loop.py` | check cancellation and `live` before each step; resolve uncertainty first; the precedence rules below |
| `src/engine/stages/s12_execute/attempts.py` | `live.check(...)` before **every** call, retries included (sabotage `M14_no_check_before_call`) |

## Logic and conditions

**`PostgresLiveAuthorization.check(*, tenant_id, workspace_id, user_id, connection_id, binding) -> Revoked | None`.**
First match wins:

| # | Live state | Result |
|---|---|---|
| 1 | scope unreadable | `Revoked("authorization_revoked")` (fail closed) |
| 2 | system **or** tenant kill switch engaged (or unreadable) | `Revoked("kill_switch_engaged")`. Never mapped to `authorization_revoked` (sabotage `M14_kill_switch_as_revoked`) |
| 3 | the S8 checks `check_user_active`, `check_tenant_active`, `check_connection_active`, `check_capability_granted`, `check_resource_scope` fail or raise | `authorization_revoked` |
| 4 | `capabilities.truth_state = 'DEPRECATED'` (retired), missing, or unreadable | `authorization_revoked` |
| 5 | the frozen binding's row (`bindings.binding_id`) missing or `is_active = false` | `binding_invalid` |
| 6 | `await credentials.credential_valid(tenant_id, connection_id)` is not `True` | `credential_invalid` (an exception → `authorization_revoked`) |
| — | all pass | `None` |

- It reuses `engine.stages.s8_safety_gate.checks`, never the S8 handler.
- It **writes nothing**: the case compares row counts of every table (sabotage `M14_live_check_writes`).
- A provider outage (open breaker) is **not** a revocation (C35, CONF-032). A persistent outage at admission ends
  `admission_exhausted` through consolidation, never CANCELLED.
- The failing check's name goes to a log record attribute. `Revoked` carries only `reason` (it is frozen).

**The loop on REVOKED:**

| When | What happens |
|---|---|
| at a step's start | that step and every remaining PENDING step `cancelled (<reason>)`; the run CANCELLED with the reason; event `authorization_revoked`. At the first step: **no call, no reservation** |
| before an attempt (a retry) | no further call; step `running → pending_probe (execution_uncertain)`; EXECUTION episode opened and closed NOT_EXECUTED (evidence `no_dispatch_marker`); `pending_probe → pending (no_dispatch_marker)`, budget released; then `cancelled (<reason>)` |
| a step is uncertain (timeout) | the probe resolves it **first** (an executed step completes), then the rest is cancelled |

**Cancellation (C16):**

- `request` records `execution_runs.cancel_requested_at` only for the run's **own user and tenant**, while the run is
  not terminal. No lease is needed. A repeated request returns `True` and keeps the **first** time (sabotage
  `M14_cancel_time_moves`). It returns `False` for another user or tenant, no such run, or a finished run (sabotage
  `M14_anyone_can_cancel`).
- The loop checks the flag before each step and **never interrupts an in-flight call**: the in-flight step finishes
  (budget committed), then the rest is `cancelled (user_cancelled)` and the run CANCELLED.
- It applies only once no step is RUNNING or PENDING_PROBE: an uncertain step is probed first.
- **A DEAD_LETTER step wins** over both revocation and cancellation: the run is consolidated, not CANCELLED.

**A pause (C39, moved from M8a):** a tenant, workspace or worker pause set while a run is RUNNING cancels **no** step
and revokes **no** held lease.

**Budget exhaustion mid-plan** ends CANCELLED (`budget_exhausted`, C15). This case is pinned here as well.

## Traps

- A live check that allows everything, or ignores binding and credential validity (sabotages
  `M14_live_check_allows_all`, `M14_validity_ignored`).
- Revocation applied before the uncertain step is resolved. The probe comes first.
- Treating an open circuit as a revocation.
- The old prototype constructor `PostgresLiveAuthorization(scopes)`. The pinned one is `(scopes, *, database,
  credentials)`.
- Global fixture ids: the golden uses a separate user, workspace and connection per tenant. Never read another
  tenant's rows to answer a check.

## Done when (★)

- [ ] 28/28 in `M14_revocation_cancel.py`; M01–M13 green; I14 passes.
- [ ] `owner_certify_s12.py --milestone M14` (full): all PASS, sabotage 7/7.
- [ ] B3 complete: 184/184, 39/39. Send the milestone report and **STOP** for the owner's ★ review. B4 starts only
      after the owner says "continue per S12 AUTOPILOT".
