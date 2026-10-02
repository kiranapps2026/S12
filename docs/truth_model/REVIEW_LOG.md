# Review log: truth model documents

Append-only. Each pass lists what was wrong in this folder's documents, the evidence, and where it was fixed.

## Pass 2 (2026-10-01, on the owner's request "many critical issues are missed")

Pass 1 (`c505af0`) corrected the brief. Pass 2 re-read every document in this folder against the gate, the golden
drafts M11–M19, the B4/B5 reviews, `batch_bundles/IMPROVEMENT_GUIDE_B3-B5.md`, the ruling pack and the source. Gate
means `docs/implementation/S12_S15_EXECUTION_GATE.md`. Issues are listed most severe first.

### Missed issues: the model itself was incomplete

| # | Issue | Evidence | Fixed in |
|---|---|---|---|
| P2-1 | **Execution events were not evidence.** Every event (`step_attempt`, `ProviderCalled`, `ProviderReturned`, `idempotency_hit`, `verification_layer`, `episode_closed`, `dead_letter_alert`, `authorization_revoked`) is its own fenced transaction. A `ProviderReturned` with status `ok` can therefore be durable while the ledger row is not. §13 never reads events, so recovery probes; with the default probe (INCONCLUSIVE) the step dead-letters with its budget LOCKED, although the database records that the provider answered. Phase 4 had called the two fault points around the call "indistinguishable by design"; that holds only if the events are written after the ledger row, which nothing pins. | Golden M12 `M12_loop.py:19-21` (`record` = one `fenced_write`); M11 docstring (events after the call, before the ledger store); §13 `:1748-1784` | Phase 2 (new D9, C-9), phase 4 (fault table), 5a (view) |
| P2-2 | **A recorded verification FAIL can be overturned after a crash.** At `after_verification_before_step_commit` with a FAIL recorded, §13 sees "ledger record exists, verification not recorded as PASS" and opens a VERIFICATION episode, and C19 re-runs "only the layers not yet PASS", which includes the failed one. §8 step 9 says a FAIL is not retryable. No golden case covers it: M19 tests that crash point only with every layer PASS. | §8 `:1634`; §13 `:1757-1760`; C19 `:615-616`; `M19_recovery.py:152-163` (`crash_c_all_passed` only) | Phase 2 (C-10), phase 4 |
| P2-3 | **Dead letters have no production path.** `retry_dead_letter` takes injected callables, and no golden pins an operator entry point (resolution exists only as an adapter method). A LOCKED reservation therefore stays LOCKED indefinitely. I1 counts LOCKED against `budget_pool` exactly like COMMITTED, so the tenant is charged for every unresolved uncertainty and never refunded for one that did not happen. With C32's default `observe()`, every mutation on an adapter without observation support ends this way, even on success (C-16). | IMP-M17-2 (`IMPROVEMENT_GUIDE_B3-B5.md:339`); B4 review "known gaps"; I1 `:2078`; D4; C32 `:1046-1050` | Phase 2 (C-11, C-16), 5b, 7 |
| P2-4 | **Run-level outcomes were not modelled.** §10's table is overridden in three places: CONF-034 (steps `cancelled (run_dead_lettered)` make the run DEAD_LETTER even with no DEAD_LETTER step and no dead-letter record, so an operator has nothing to resolve), C16 (DEAD_LETTER wins over CANCELLED) and M14 (DEAD_LETTER wins over a revocation). C15 sends budget exhaustion to CANCELLED. | §10 `:1682`; CONF-034; C16 `:517`; C15 `:497`; `M19_recovery.py:311-334` | Phase 2 (run-outcome rules), 3 (disposal), 5b |
| P2-5 | **Revocation and cancellation are not pure overrides.** Phase 2 said a revocation "changes what follows, not the step verdict". But a step found NOT_EXECUTED under a revocation or a cancellation request ends `cancelled` with that reason: it is neither retried nor `not_executed_no_retry`. Cancellation requests (C16) were not a run-context dimension at all. Revocation precedence is unpinned, and a failing credential check may give either reason. | M14 docstring; `M19_recovery.py:546` (`REVOKED_IN_RECOVERY`); C16 `:511-517`; IMP-M14-1, IMP-M14-2 | Phase 2 (R2, new R5) |
| P2-6 | **The tampered-plan dead letter reintroduces the hazard it avoids.** CONF-043 option A gives the in-flight step a PROBE-mode dead letter. A D5 PROBE retry must rebuild the probe call, and the parameters come from the plan that cannot be trusted. The option also does not say whether an episode is opened, and it uses the reason `probe_exhausted` where no probe ran. | CONF-043; `M19_recovery.py:512-548`; D5 `:1421-1436`; ruling pack `:128-137` | Phase 2 (C-12), phase 6 |
| P2-7 | **Leases are per step, not per run.** R1 called it "ownership lease". §8 acquires a lease at step 3 and releases it at step 11, so between steps a live run has none. The orphan rule judges the execution's latest lease (CONF-046), and the ownership row decides who may drive the run (CONF-033). | §8 `:1589`, `:1639`; CONF-033; CONF-046 | Phase 2 (R1) |
| P2-8 | **Attempt numbering on a retry.** EX-1 said "retried as the next attempt". After a crash with no marker, the undispatched attempt's number is reused (C35 counts dispatched attempts). After a probe found NOT_EXECUTED, the retry is attempt n + 1. The live path uses the step reason `execution_uncertain`, the cold path `recovery`. | `S12_B5_REVIEW.md` ("Two first-draft expectations"); `M19_recovery.py:201-203` (`att-0-2`); M14 docstring | Phase 3 (EX-1) |
| P2-9 | **The ledger dimension missed a value.** A row for the step's key with another `kernel_op_id` raises `IdempotencyConflict` (a stop condition); on the probe path no golden case covers it. The ledger key is globally unique, but `request_id` is unique only per tenant in the schema. It is a server-generated UUID on every entry path today, so cross-tenant collisions are an assumption, not a defect. | §8 `:1612-1616`; IMP-M13-1; `009:32`; `s0_entry/handler.py:46`; `control_plane/api.py:148` | Phase 2 (D4), 5a, 7 |
| P2-10 | **The evidence ladder ranked answers to different questions against each other.** "Was it dispatched?", "did the provider act?", "is the effect verified?" and "is money settled?" have separate evidence. A layer verdict cannot outrank a marker, because they answer different questions. | Phase 2 | Phase 2 (ladder by question) |

### Inconsistencies inside the documents

| # | Issue | Fixed in |
|---|---|---|
| P2-11 | Phase 1 counted "27 sabotage patches across those milestones" for eight milestones. That figure covered six. The eight have 42 patches, and M12 has 30 cases and M14 18. | Phase 1 |
| P2-12 | Seed rule i cited C16 (run cancellation). The source is C18 (an episode opens with the step's move to pending_probe) and §13 step 3. | Phase 2 |
| P2-13 | Seed rules l and u assumed a dead letter, an exhausted episode and the step's move to DEAD_LETTER share a transaction. The gate gives the meaning, not the atomicity; the co-occurrence part is basis `atomicity`. | Phase 2 |
| P2-14 | The README said M14 is cited only for live authorization. M14 also owns cancellation (C16), which is now dimension R5. | README |
| P2-15 | The view's "after a probe" test missed an EXECUTION episode closed VERIFIED_FAIL (a probe confirmed the call, then verification failed). In that case it required schema/deterministic layers that never run. The latest-episode pick also did not prefer the open episode. | `sql/step_evidence.sql`, smoke test |
| P2-16 | Phase 4's `after_budget_reserve` row said "check what releases or reuses the RESERVED row". It is settled: `reserve()` returns the existing live reservation (`budget_reserver.py:82-84`), pinned as `reuses_reservation`. | Phase 4 |
| P2-17 | Phase 5b's symptoms omitted four endings customers will report: cancelled but it happened (C16 never interrupts a call), revoked but it happened (M19 completes a step whose call preceded the revocation), a DEAD_LETTER run with nothing to resolve (P2-4), and a shrinking budget (P2-3). Latency omitted the admission DELAY loop and lease retries. | Phase 5b |
| P2-18 | Phase 6 stated only the pack's recommendations. For three rulings the recorded proposal in `S12_RECORDS.md` differs from the pack (CONF-042 amended by 046; CONF-044 A vs A+; CONF-045 C vs A), so "accept as proposed" means something different from "accept the pack". It also left out the STOP and DEF rows the certifier and tracker read, and STOP-001 (status `ruled` still blocks). | Phase 6 |

### Folded in from the circulated owner-approval analysis

A separate analysis of "open items requiring owner approval" was checked against the records at `c505af0`. Its
errors are listed in phase 6, "Corrections to the circulated analysis", so the owner does not act on them.

## Pass 3 (2026-10-01): recommendations added

Not a review: on the owner's request, phase 6 now carries this work's recommendations for C-16 (refuse unverifiable
mutations at enablement; production read-only until 2c), C-12 (CONF-043 option A′: `retry_mode = NONE` and a recorded
EXHAUSTED episode with 0 attempts) and their shared prerequisite C-11 (a proposed CONF-049 operator path for dead
letters, pinned in M21), with draft record text, proposals to the test-author session and the order in the overall
process. Nothing in `tests_golden/`, `src/` or the records was changed.
