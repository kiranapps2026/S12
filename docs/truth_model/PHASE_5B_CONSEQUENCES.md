# Phase 5b: Consequences

Part of the [S12 truth model](README.md). Input: the validated rows (phase 4). It produces §13 (terminal reason →
operator action → budget → customer message), §14 (cost and latency per path) and the cost column of §9. It runs
beside phase 5a and needs no database.

Revised in review pass 2 (`REVIEW_LOG.md` P2-3, P2-4, P2-17): no production path to release LOCKED money, the
default `observe()`, run-level endings, and four missing symptoms.

## Purpose

Every row of the matrix ends in something a customer sees and an operator has to handle. This phase writes, for every
customer-visible ending: what the customer is told, what the operator does, what happens to the money, and how long it
takes in the worst case. Several endings are correct behaviour that will still be reported as faults. They need
wording and a resolution time, not a fix.

## Entry conditions

- Phase 4 exit criteria met: rows validated, findings routed.
- The owner signs off this phase's output (the wording is product policy, not engineering).

## Inputs

| Input | Location |
|---|---|
| Step terminal reasons (14) | `010_step_loop.sql:10-14` (`chk_step_terminal_reason`) |
| Step failure and dead-letter reasons | Appendix A.2 (`non_retryable_error`, `retries_exhausted`, `verification_failed`, `ledger_hit_failure`, `probe_executed_failure`; `probe_exhausted`, `verification_exhausted`, `human_verification_pending`) |
| Run endings and consolidation outcome | §10 `:1675`; A.1 |
| Envelope mapping, redaction | §12 `:1722`; golden `M18_response.py` docstring; CONF-039 |
| Dead-letter settlement | D4 `:1404-1419`; D5 `:1421-1436`; C21; A.3 |
| Timing parameters | table below |

## Timing parameters (for §14)

| Parameter | Value | Source |
|---|---|---|
| Probe attempts, backoff | 3, backoff ≥ 1.0 s, never shrinking, none after the last | §9 `:1666`; M13 draft (`probe_max_attempts`, `probe_backoff_s`) |
| Verification episode attempts, backoff | 3, 1.0 s | C19 `:618-619`; M15 draft |
| Verifier limits per episode attempt | 3 observations, 1 s apart, 5 s timeout each | C19 `:618` (WORKER_LIFECYCLE §7) |
| Step timeout, adapter timeout, probe timeout | From the environment, **no default in code**; adapter and probe timeouts must be below the step timeout | `src/engine/stages/s12_execute/settings.py:3-6`, `:51-54` |
| Lease TTL, renewal interval | From the environment, no default; TTL ≥ 3 × renewal | `settings.py:6`, `:55-56`; CONF-045 (renewal during a step) |
| Recovery sweep interval | Default 10 s, must be under 30 s | §13; M19 draft (`S12_RECOVERY_SWEEP_INTERVAL_S`) |
| Orphan grace for a never-leased run | One lease TTL | CONF-046 (open) |
| Dead-letter retries | `max_retries` 3, then abandoned UNDETERMINED (budget COMMITTED) — **but no production entry point triggers a retry or a resolution** | `015` (`dead_letters.max_retries`); M17 draft; D4; IMP-M17-2 |
| Admission DELAY loop | Gates 8, 9 and 11 DELAY with `retry_after_ms`, bounded by `admission_max_attempts`, then `admission_exhausted` | §8 step 1; CONF-017, CONF-032; M12 `LoopSettings` |
| Lease acquisition retries | `lease_max_attempts`, then `lease_unavailable` | §8 step 3; M12 `LoopSettings` |

Because several values have no default, §14 states the values it assumes and gives every figure as a formula of the
parameters as well as a number.

## Procedure

1. **Enumerate the endings.** Each customer-visible ending is a (run status, step terminal reason or dead-letter
   reason, envelope `error.type`) triple reached by at least one row. Rows that end in the same triple share a table
   row and list their TM IDs.
2. **For each ending, write:**

   | Column | Content |
   |---|---|
   | ending | Run status, reason, envelope type (`ok`, `partial`, `error`; `recoverable`) |
   | rows | TM IDs |
   | frequency | expected / rare / should never happen, with the reason |
   | budget | Settled, released or held LOCKED, and until when |
   | operator action | What to check (the phase 5a reverse-index query) and what to do |
   | customer message | Plain words, within the M18 redaction rules (no provider bodies, internal IDs other than `trace_id`, or exception text) |
   | support view | What support may see beyond the customer (dead-letter evidence, probe results) and where |
   | resolution time | Who resolves it, and the time limit the owner commits to |

3. **Compute worst-case latency per path (§14)**, at minimum:
   - live timeout → probe exhausted → dead letter;
   - live result → verification exhausted → dead letter;
   - probe confirms execution → verification → completed or dead letter;
   - crash at each of the ten fault points → detection (sweep interval plus orphan grace) → resolution.

   Give each as a formula, then a number under the stated assumptions.
4. **Compute how long money stays LOCKED** for each path ending in a dead letter. Under D4/D5, a dead letter with
   `retry_mode = NONE` leaves `pending` only by human resolution. No production entry point calls
   `retry_dead_letter` or `resolve` at all (IMP-M17-2: the retry takes injected callables, and no golden pins an
   operator path). Today LOCKED time is therefore unbounded, and the resolution-time column carries the commitment.
   State the cost plainly: a LOCKED reservation counts against `budget_pool` like a committed one (I1), so the tenant
   pays for the action whether or not it happened (C-11).
5. **Compute the frequency of the dead-letter endings under the default adapter.** By design, an adapter without
   `observe()` makes provider_state verification UNKNOWN, so every W, D and IRREVERSIBLE step on it ends DEAD_LETTER
   even when the call succeeded (C32 `:1046-1050`; C-16). Until real adapters (roadmap 2c), "budget held, nothing
   reported as done" is the normal ending of a mutation, not an edge case. Every frequency in step 2 states which
   adapter regime it assumes.
6. **Run-level endings.** Write the run's ending from the phase 2 `RO` rules, including the one that surprises
   everyone: a tampered plan with no step in flight ends DEAD_LETTER with every remaining step
   `cancelled (run_dead_lettered)` and no dead letter to resolve (CONF-034). The customer gets `error`, not
   recoverable, and the operator has nothing to act on except the `plan_integrity` alert.
7. **Flag product gaps** separately from wording: no HITL channel (`human_verification_pending` can only be resolved
   by an operator), no post-execution human-approval run state (D4 open question), no operator entry point for dead
   letters (IMP-M17-2), and dead-letter records that may show the wrong operation class (C-15).

## Symptoms to cover first

Ranked by how often they will occur and how badly they read. The first three are correct behaviour.

| Symptom the customer reports | Matrix origin | Severity | What this phase must supply |
|---|---|---|---|
| Budget held, nothing happened | Both exhaustion paths leave the reservation LOCKED (D4) | High, frequent | Resolution time, who releases it, and the message that explains the hold |
| It said it failed but it went through | INCONCLUSIVE three times on a real side effect | High | Wording that tells "unknown" apart from "failed"; the probe evidence to show on request |
| It took far too long | Three probes with backoff, then up to three verification attempts | Medium, frequent | Worst-case latency per path, computed |
| The same action happened twice | A retry of an operation whose `retry_safety` is wrong in the registry | Critical, rare | The registry audit this implies, and the rows that depend on `retry_safety` being right (C-8) |
| Nothing came back at all | A run left non-terminal | Critical | Every row that can leave a run non-terminal, with its detection query from 5a |
| Waiting on a human, forever | `human_verification_pending` with no HITL channel | High | Product gap, plus an interim operator procedure |
| Support cannot explain it | Redaction removes provider bodies from the envelope, logs and persisted rows (M18) | Medium | What support may see, and where |
| Everything broke at once | A registry version bump denies every earlier plan (CONF-008, ruled fail-closed for this phase) | Critical, correlated | Call it out separately: one of two failures that hit every tenant at once (the other is the default `observe()`, C-16) |
| Every change I make gets stuck | Default `observe()`: every mutation dead-letters even on success (C-16) | Critical, frequent until real adapters | Whether to ship mutations at all before 2c; the message; the operator procedure |
| I cancelled, but it still happened | C16 never interrupts an in-flight call; the step completes and the run is CANCELLED with that step listed | Medium | The wording for "completed before cancellation" (§12 lists those steps) |
| Access was revoked, but it still happened | A step whose call preceded the revocation completes (`M19_recovery.py:546`, the `after_adapter_call_before_ledger` case) | High | Same: the envelope lists completed steps; support must be able to show when the call happened versus when access was revoked |
| It failed, and nobody can fix it | DEAD_LETTER run with no dead letter (CONF-034, tampered plan) | Medium, rare | Who investigates a `plan_integrity` alert, and what the customer is told |
| I keep paying for things that did not happen | LOCKED reservations never released (C-11) | High, cumulative | The refund policy until an operator path exists |

State two framings plainly, because they change how the product is sold. The system is built to hold money and stop
rather than guess. And it says when it does not know. Both are the right engineering choice, and both look like
faults to a customer who was not told.

## Outputs (`docs/truth_model/work/`)

| File | Content |
|---|---|
| `P5B_ENDINGS.md` | §13: one row per ending, columns as in step 2 |
| `P5B_LATENCY.md` | §14: formulas, stated assumptions, numbers |
| `P5B_LOCKED_TIME.md` | LOCKED duration per dead-letter path, and who releases it |
| `P5B_PRODUCT_GAPS.md` | Gaps found, kept separate from wording |

## Exit criteria

- Every customer-visible ending reached by any row has an operator action and a customer message.
- Every latency and LOCKED-time figure is a formula with stated assumptions, not an estimate.
- The owner has signed off the customer messages and resolution times (record the date in the decision log).

## Can it split?

Yes, beside 5a. The endings table and the latency figures can also be written by different people, because both read
only the frozen matrix.
