# B4 golden review (M15–M18)

2026-09-30, drafted on the owner's instruction "B4 review for M15 onwards". **Self-review**: the drafter will also
implement B4, so this does not replace an independent review. It records how every file was validated and what needs
a ruling before pinning. B4 follows B3's second-pass method: for each case, ask which wrong implementation would still
pass.

## Validation (every file)

Each file was run three ways:
- **Red on `s12-work`**: it must fail for the right reason (missing modules, not test errors).
- **Green on a scratch reference implementation**: a detached worktree in the session scratchpad; nothing of it is in `src/`.
- **Under every sabotage patch**: each must turn an assertion red, never a setup error.

Results on the reference:
- All 19 golden files M01–M18 pass together, 794 cases: 489 for M01–M09, 184 for M10–M14, 121 for B4. With `tests_agent` the total is 888.
- The frozen `tests/` suite passes (836).
- The four B4 files passed 10 consecutive runs.

M01–M09 stay green on `s12-work` with the new invariants (583 with `tests_agent`).

| File | Cases | Red on `s12-work` | Reference | Sabotage caught |
|---|---|---|---|---|
| `s12/M15_verification.py` | 47 | 46 fail, 1 passes (invariants of an unfinished schema) | 47 / 47 | 3 / 3 |
| `s12/M16_consolidation.py` | 28 | 27 fail, 1 passes (same) | 28 / 28 | 3 / 3 |
| `s12/M17_dead_letter.py` | 32 | 31 fail, 1 passes (same) | 32 / 32 | 3 / 3 |
| `s12/M18_response.py` | 14 | 14 fail | 14 / 14 | 3 / 3 |

Two cases were also mutation-checked by hand on the reference:
- M18 redaction: making the guard log the exception text fails the M18 redaction case and M10's leak case.
- Ledger bodies: a ledger that stores error bodies is caught by `M18_ledger_keeps_bodies`.

Fixture changes with B4:
- `invariants.py` gains I3, I13 (M16), I11, and the dead-letter parts of I12 (M17). I13's "never rewritten" part applies to rows that have a transition log; fixture shortcuts write some rows without one.
- M12's "not RUNNING" case now uses a `pending` run. Its earlier `cancelled` run with pending steps is exactly what I3 forbids, and the shared module schema made later invariant checks fail.

## What each file pins

| File | Main cases |
|---|---|
| M15 | Layer selection by mutation and risk, including the 0.69 / 0.7 boundary. The semantic answer is parsed into the strict enum (10 malformed forms are UNKNOWN). Every layer passes for a correct write without a new adapter call. A deterministic FAIL is never overridden by a semantic PASS: the model is not even asked. An observed mismatch FAILs whatever the model says. Text injected into a provider response never reaches the model and never passes. A semantic layer that is malformed, raises or is absent is UNKNOWN. A failed observation is UNKNOWN, never FAIL, bounded at 3 × 1 s, and a later observation can still pass. Schema and deterministic layers never answer UNKNOWN. The human layer is UNKNOWN at once, never retried. `layers=` subsets; a probe-confirmed step has no result layers. In the loop: every layer result is persisted before the commit; a mismatch fails the step and skips its dependents. UNKNOWN opens a VERIFICATION episode that re-runs only the open layers and never probes. Persistent UNKNOWN gives DEAD_LETTER with the budget LOCKED (3 attempts). A re-attempt FAIL fails the step. The human layer gives DEAD_LETTER at once. A probe-confirmed step with UNKNOWN verification gets an EXECUTION and a VERIFICATION episode. An injected non-verdict fails closed. A VERIFICATION episode can never end NOT_EXECUTED. The code lives in the S13 package. |
| M16 | Every row of the §10 table (11 cases). A CANCELLED step never gives COMPLETED. Consolidation needs every step terminal. The loop with the real consolidator: outcome and events; VERIFICATION_STARTED / COMPLETED with the layer results, in the run's transaction; FAILED / PARTIAL / DEAD_LETTER with LOCKED only under D4. An admission reject after a completed step gives PARTIAL. A tampered plan gives DEAD_LETTER (CONF-034). No RESERVED reservation survives. Consolidation is refused on live steps and never runs twice. The quota refund applies to a cancel with no completed step, at tenant and workspace level, in the same transaction; a user cancel refunds once; there is no refund after a completed step or for a FAILED run. |
| M17 | Creation rules:<br>• retries exhausted: transient / NONE with evidence and the last attempt id<br>• 401 / 422: no record<br>• verification FAIL: data / NONE, and the run follows its step states<br>• EXECUTION exhausted: PROBE with its episode, LOCKED budget, alert event and ERROR log<br>• VERIFICATION exhausted: VERIFY<br>• human layer: NONE<br>• refused: empty, None or list evidence, an empty error, unknown enum values<br>The A.6 lifecycle and its illegal moves. The budget per resolution (4 cases) never changes the run or the step. A failed step's record moves no budget. Retries: PROBE calls only the probe; NOT_EXECUTED releases the budget; VERIFY calls only the verifier (adapter and probe: 0 calls); NONE never retries and writes nothing; inconclusive ×3 gives abandoned UNDETERMINED, committed. Rollback:<br>• confirms, then compensates in reverse order through the guard with the `:inverse` key; never twice<br>• unconfirmed: no inverse<br>• a failed inverse becomes a `rollback` dead letter and changes nothing else<br>• IRREVERSIBLE is never compensated; a live run is refused<br>• `InverseBudget` admits only inverses without a reservation<br>• nothing calls rollback automatically |
| M18 | The mapping for ok, partial, cancelled (3 reasons), no_worker wording, dead_letter, and non-terminal. Summaries follow the plan. The envelope holds no execution, request, tenant, user, workspace, runtime, step or reservation id, and another tenant cannot read a summary. Redaction: the credential, a stack trace and a provider error body are absent from the envelope, every log record and every persisted row of 9 tables, for an adapter defect, a 401 with a body, and retries exhausted with a body (with a dead letter). |

## Defects caught while drafting

| Where | Finding | Fix |
|---|---|---|
| reference ledger (B3) | a non-retryable failure was stored with its provider body, so a token in an error body reached a persisted row | a failure row stores its class only (M18, `M18_ledger_keeps_bodies`) |
| reference mock (M10) | a success result had no identifier, so no deterministic check could ever pass on a mock write | success data carries `id`; stated in M15 |
| reference loop (B3) | any non-PASS verdict was treated as FAIL; UNKNOWN had no path; the probe path verified with no result | VERIFICATION episodes (C19); CONF-040 |
| reference (drafting) | `ruff --fix` over a directory rewrote two frozen S0–S11 files (`admission.py`, `usage.py`) | caught by M02's frozen-source check, restored; fixes now run only on files named one by one |
| reference (drafting) | a module-level dict in the mock; consolidation outcome and rollback/response string values equal to state names | caught by M10's §21 S3 rule and M04's bare-literal scan; `ConsolidationOutcome` moved to `contracts.execution_states`, keys renamed |
| M12 golden (B3) | the "not RUNNING" case left a `cancelled` run with pending steps in the shared schema | uses `pending` (see fixtures above) |
| M16 draft | the quota helper seeded the tenant before the budget pool was applied | the pool is passed through |
| M15 draft | the NOT_EXECUTED case opened an episode for a PENDING step (an I6 violation of its own) | probed inside a real episode attempt |
| M17 draft | illegal A.6 moves were expected as `ValueError` | the pinned `IllegalStateTransition` (M03/M04) |

## Rulings needed (recorded in S12_RECORDS.md)

| ID | Question | Proposal |
|---|---|---|
| CONF-005 (open since M0) | no AutonomyLevel source (D6 says STOP) | layer selection by mutation and risk only in this phase (see CONF-041) |
| CONF-036 | no storage for per-step layer results | `verification_layer` events in `execution_events` |
| CONF-037 | which quota rows the refund decrements | the run's tenant/workspace `executions` rows whose period contains its creation |
| CONF-038 | the guard's budget layer vs an inverse (no reservation) | `InverseBudget` layer for rollback |
| CONF-039 | no envelope error type for cancellations, revocations | the mapping in the ruling text |
| CONF-040 | verification after a probe has no adapter result | skip schema / deterministic |
| CONF-041 | §43 table vs its own function (human for D? semantic "AGENTIC path") | follow the function |

## Known gaps, left as they are (reasons)

| Gap | Why it stays |
|---|---|
| The production wiring of a dead-letter retry (building the probe call and the verifier from the record) | the retry takes injected `probe` / `reverify` callables; an operator entry point is M21 |
| Dead letters for permanent errors that §11 does not list (`adapter_defect`, a guard refusal) | §11's creation list is exhaustive; D5 mentions "permanent errors" only for the retry mode. Not pinned |
| The IRREVERSIBLE and human-layer paths in the loop use a scripted verification | the certified fixture cannot produce an IRREVERSIBLE step (S10 confirmation); the layer rules are pinned on the verifier itself |
| Semantic verification in the loop | certified risks are below 0.7; pinned on the verifier |
| S12 entry denials (DENY) and the envelope | they keep the S0–S11 `ExecuteResponse` mapping (§12 first bullet); unchanged |
| Consolidation of a RECONCILING run | the in-line loop never enters RECONCILING (CONF-029); M19 recovery |

## Sabotage patches added

- M15: `M15_lenient_semantic_parse`, `M15_provider_state_skipped`, `M15_verification_as_execution`.
- M16: `M16_cancelled_counts_as_completed`, `M16_live_step_consolidated`, `M16_refund_always`.
- M17: `M17_evidence_optional`, `M17_resolution_moves_step`, `M17_verify_retry_probes`.
- M18: `M18_ledger_keeps_bodies`, `M18_cancelled_hides_completed`, `M18_internal_ids_leak`.

## Interfaces B4 adds to B3 modules

- `MockAdapter`: success `data["id"]`; `observe="inconclusive"`, `observe_unknown=k`, `observations`; `body=` for error results.
- `LoopDeps`: `verification`, `dead_letters`, `cancel_run`.
- `LoopSettings`: `verification_max_attempts`, `verification_backoff_s`.
- The loop reads the persisted verifiers.
- `PostgresEpisodes.close` refuses NOT_EXECUTED for VERIFICATION.
- The idempotency ledger stores a failure without its body.

All are additive. M10–M14 pass unchanged on the reference except the M12 fixture fix above.
