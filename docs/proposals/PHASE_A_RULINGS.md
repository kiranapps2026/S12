# Phase A rulings (R-AA, R-AM…R-BA)

**Status:** decided on the owner's instruction "Phase A: your rulings on R-AA, E1–E5 and the S1 choices, and the
G1–G8 gate amendments" (2026-09-30). Options and reasons are in the proposals named in each section. These are working
rulings for this branch: the owner may overrule any line. **Not applied to the pinned or owner documents**
(`docs/gates/S0_S11_RUNBOOK.md` Part 2, `S12_S15_EXECUTION_GATE.md`, `DATABASE.md`): the exact text to apply is given
below and each needs the owner (and, for the implementation documents, a re-pin).

## 1. R-AA — S0.1 activation (pause) check (`S0_1_PAUSE_CHECK.md`)
**Adopted as proposed**, id kept as `R-AA`. Text to insert in the runbook, Part 2 after R-Z, is in `S0_1_PAUSE_CHECK.md`.
Reason: it is the S0–S11 half of gate ruling R-P, already implemented, tested (`test_s0_activation.py`, golden) and
required by S12 entry item 7.

## 2. S1 reference resolution (`S1_REFERENCE_RESOLUTION.md`, rulings needed 1–7)
| Ruling | # | Decision |
|---|---|---|
| R-AM | 1 | `$ref:N` (N = 1–20) and bare `$N` (single digit 1–9) **only when that result exists**; otherwise `$5` is literal text. |
| R-AN | 2 | Files resolve to **metadata only** (`[file:name#id]`). Reading file content is a separate, gated capability that does not exist and must not be added to S1. |
| R-AO | 3 | Templates are **variable names only**. System variables: `today`, `yesterday`, `tomorrow` (database clock). Stored variables are set only by a tenant or workspace administrator through an admin path (not built); users cannot define variables. Workspace overrides tenant. |
| R-AP | 4 | A "result" belongs to a **user within a conversation** (a user never resolves another user's results, even in a shared conversation). |
| R-AQ | 5 | Result text is the `summary` (≤ 4000 characters). It is written by S15, **and nothing may write `conversation_results` until S15's redaction (M18) exists**, so secrets cannot be stored there. |
| R-AR | 6 | Injection detection runs on the NFKC-normalised, invisible-character-stripped copy; the model still receives the user's own NFC text. Detection may only DENY, never rewrite the text. Accepted. |
| R-AS | 7 | Entity extraction stays English-only and advisory. Entities are **not** passed to S2 as hints (they would add derived, user-influenced text to the one LLM call). Revisit only with a test showing benefit. |

## 3. S0 event-driven mode (`S0_EVENT_DRIVEN_MODE.md`, E1–E5)
| Ruling | Item | Decision |
|---|---|---|
| R-AT | E1 | **Accepted.** `webhook_credentials` carries `endpoint_id` and the identity events run as (workspace, user, membership, connection, resource scope). Nothing else in the spec can identify a credential before the tenant is known. The identity must be a dedicated service user/connection created for the integration, never a person's own. |
| R-AU | E2 | **Accepted.** `event_log.payload` (BYTEA, ≤ 64 KiB) and `TIMESTAMPTZ`. |
| R-AV | E3 | **Interim.** The run is synchronous and answers `200` with the outcome. When the EventRouter exists (S12/S13), the endpoint changes to `202 Accepted` after storing the event, as the gateway spec says; that change is part of Phase C3. |
| R-AW | E4 | **Accepted with a condition.** No RLS on `webhook_credentials` (pre-tenant lookup, holds only ciphertext and the fixed identity). The application database role may only `SELECT`/`INSERT`/`UPDATE` it; before production, credential reads move to the spec's `system_worker_role` with SELECT on active and retiring rows only. |
| R-AX | E5 | **Accepted.** Only signed webhooks in this phase; schedule, MCP and API event sources are Phase C1. |

## 4. S12 gate amendments G1–G8 (`S12_MULTI_STEP.md`)
| Ruling | Decision |
|---|---|
| R-AY | **G1–G8 accepted as written** in `S12_MULTI_STEP.md`: (G1) one frozen binding per plan step is present, exactly one of the singular field and the per-step tuple; (G2) each distinct binding row is read once and its version must equal the manifest's, one version per kind (S11 refuses mixed versions); (G3) step rows take binding, risk and mutation from that step's binding through the S4 step→binding index; (G4) `execution_plans` stores the bindings array and the index; (G5) live authorization and the circuit breaker use each step's own binding and provider; (G6) C36 unchanged for M2a; (G7) plan-digest check unchanged; (G8) compensation stays S13's policy, `Step.inverse` is available. The gate document itself is **not edited** here: the owner applies the text and re-pins `S12_S15_EXECUTION_GATE.md`. |

## 5. Schema deviations and small decisions
| Ruling | Decision |
|---|---|
| R-AZ | **Accepted:** migration 006 (`tenants.budget_period`, `budget_reservations` without foreign keys until S12 adds them); 008 (observation columns on `kernel_ops`; a mutating operation without an observation method is refused at S12 entry); 009 (`TIMESTAMPTZ`, plan bindings array and index, no worker/lease foreign keys, no `worker_id` on quotas, minimal `state_transitions`); 010 (`execution_runs.connection_id` and `terminal_reason`). The implementation documents (`DATABASE.md`) are not edited here; the owner records these as the additive deviations and re-pins. |
| R-BA | **Gate item 1a (conversation id): S0 supplies it.** When the authenticated entry has no conversation id, S0 generates one (UUID v4); a supplied id is kept. A generated id resolves no `$ref` (correct: there is no earlier conversation). Implemented and tested; the gate's "context_incomplete" for a missing conversation id therefore only fires on a genuinely broken context. Also accepted: the reason names not fixed by the gate, `plan_not_validated`, `binding_missing`, `binding_unavailable`. |

## What is still the owner's, after these rulings
1. Apply the runbook text for R-AA and R-AM…R-BA (Part 2) and re-pin, if the runbook is pinned in your scripts.
2. Apply G1–G8 to the gate and the schema deviations to `DATABASE.md`, and re-pin those documents.
3. Overrule any line above; the code needs no change for a ruling that stands.
