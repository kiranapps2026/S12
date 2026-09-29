# Roadmap: what is left before the S0–S11 tag and the S12–S15 gate, in phases

Status of 2026-09-29, branch `s0-s11-repair` (35 commits, 960 tests, certifier 19/19). This file is a plan,
not a pinned document. It answers: "is this sufficient to pass the S12 gate?"

## 1. Verdict

**No.** Three separate things are being called "the gate":

| Gate | What it needs | Where we are |
|---|---|---|
| **S0–S11 certification** (`owner_verify.ps1`, then `git tag s0-s11-certified`) | certifier N/N, self-test, clean tree, the certifier's hash equal to the one inside `owner_verify.ps1` | Certifier passes 19/19 here, **but `owner_verify.ps1` line 6 still holds the old certifier hash (`E5D5AB0D…`)**. The certifier changed on the owner's instructions (now `6B9D1C30…`), so the owner's script will report "certifier was modified. Certification void" until its `$expected` is updated (an owner-integrity edit; I have not made it). Not yet run on the owner's machine. |
| **S12–S15 preconditions** (plan §1) | tag exists; v9/v10 docs pinned after the tag; D1–D6 and C24–C38 confirmed; R-Z and R-P in code | R-Z and R-P are in code. Tag does not exist. D/C confirmations and the doc re-pin are the owner's. |
| **S12–S15 certification** (`owner_certify_s12.py`, tag `s12-s15-certified`) | milestones M0–M21 each passing owner-drafted *red-first* golden tests, sabotage patches, invariants I1–I18, 8 journeys, S0–S11 code unchanged since the tag | Not started as a certified process. What exists is pre-gate prototype code (§4). |

Two process facts matter more than any single missing feature:
1. The S0–S11 runbook ends with "tag `s0-s11-certified` **and stop. Do not begin S12.**" S12 work was started ahead of that
   on the owner's instruction; it is prototype material, not certified S12.
2. The S12–S15 plan's exit rule for every milestone is "S0–S11 code unchanged since the tag". Any S0–S11 change made
   after the tag (multi-step data flow, for instance) fails the gate. **All S0–S11 work must therefore be finished, or
   consciously deferred to after S15, before the tag.**

## 2. Phases

Order matters: A → B → (C, D in parallel) → tag → E → F. Blocking items are marked **[B]**.

### Phase A — Owner rulings and integrity (blocks the tag)
| # | Item | Who |
|---|---|---|
| A1 **[B]** | Update `$expected` in `tools/owner_verify.ps1` to the current certifier hash, re-run `owner_pin.ps1` for pinned files | owner |
| A2 **[B]** | Rule R-AA (S0.1 pause check), the S1 reference-resolution choices | owner |
| A3 **[B]** | Rule E1–E5 (webhook credential columns, `event_log` payload, synchronous run, no RLS on credentials, webhook-only sources) | owner |
| A4 **[B]** | Ratify or overrule the working M2 rulings R-AB…R-AL (`M2_RULINGS.md`) | owner |
| A5 | Accept or amend the gate amendments G1–G8 (`S12_MULTI_STEP.md`) and the schema deviations of migrations 006, 008, 009, 010 | gate owner |
| A6 **[B]** | Decide item 1a: the gate denies every run without a `conversation_id`, the API does not require one. Either S0 supplies one or the gate drops it | owner |
| A7 | Decide whether S12 prototype code stays in this tree before the tag (see §4) or moves to a separate branch | owner |

### Phase B — S0–S11 production readiness and proof
| # | Item | Status |
|---|---|---|
| B1 **[B]** | Re-run the live DeepSeek test on the latest commits, including an answer with `steps` (only the owner's key can) | open |
| B2 | Observe real empty / truncated / content-filtered provider replies (unit-tested only) | open |
| B3 | CI: a workflow that runs `pytest tests`, `tests_postgres` (PostgreSQL service) and `owner_certify.py`; the repo has none | open |
| B4 | Admin API or CLI to issue/revoke API keys and to issue/rotate webhook secrets (`issue`/`rotate` exist, no route) | open |
| B5 | KEK rotation tool (re-wrap `wrapped_dek`), `event_log` retention, rate limiting on `/execute`, `/confirmations`, webhooks | open |
| B6 | LLM usage billing (`llm.token`) not ported | open |
| B7 | Writers for `conversation_results` and `files` (nothing populates them, so no real `$ref`/`$file` resolves) | open |
| B8 | Revoke the DeepSeek test key committed on `exciting-brahmagupta` and `peaceful-brown` when testing ends | owner |

### Phase C — Event gateway completion (S0 event mode)
| # | Item |
|---|---|
| C1 | Schedule, MCP and API event sources and their authentication (only signed webhooks exist) |
| C2 | Per-event-type payload schema registry and validation |
| C3 | EventRouter and subscription matching (bridge from `event_log` to a run; currently the run is synchronous) |
| C4 | Event replay after a pause (`event_log` keeps the payload; nothing replays) |

C3 and C4 belong to S12/S13 in the gate's own text; only C1–C2 must precede the tag.

### Phase D — Multi-step (exclusive phase)
Everything about plans that combine capabilities, in one place.

| # | Item | Blocks the tag? |
|---|---|---|
| **D1 — M2a finish** | | |
| D1a | Live proof: a real model answering with `steps`; prompt tuning; ordering errors ("email before create") | **yes** |
| D1b | Ratified M2 rulings and R-AF inverse behaviour confirmed with real registry data (`kernel_ops.inverse` is empty in seed data) | **yes** |
| D1c | S12 per-step contract accepted: G1–G8; S12 entry, admission and loop already work per step (prototype) | **yes** (decision) |
| D1d | Observation metadata for real operations (migration 008 columns are empty, so every W/D/IRREVERSIBLE plan is denied at S12 entry) | **yes** for any mutating chain |
| D1e | Pre-flight parameter validation against a kernel input schema (none exists; R-AE accepted unvalidated parameters for M2a) | no (M2b prerequisite) |
| D1f | Compensation policy for a failed step after earlier ones succeeded (S13 rollback, D2/M17) | no (S13) |
| **D2 — M2b step-to-step data flow** | | |
| D2a | `input_schema`/`output_schema` columns with a `secret` flag, registry loader, migration | after tag |
| D2b | `StepOutputReference` / `StepParameterBinding` in plans, the six validation rules (PIPELINE_STAGES §11) | after tag |
| D2c | `plan_hash` over the reference structure (R-AG); C36 replacement text (R-AH); secret classification (R-AI) | after tag |
| D2d | S12 resolves references at run time; S12 entry check 5a changes; S10 shows the references | after tag |
| **D3 — M2c branching graphs** | | |
| D3a | DAG / fan-out / fan-in, `join_mode` any/threshold (gate D3 executes `all` only), parallel step execution (gate: out of scope), S7 routing for `complex` | after S15 |

Rationale: the gate itself defers data flow (C36 target phase "LLM layer / planning"), so D2 and D3 must **not** be
done before the tag (they change S0–S11 code) and must not be required for it. D1 must be finished before the tag.

### Phase T — Tag
Owner runs `owner_verify.ps1` (after A1), then `git tag s0-s11-certified`. From here S0–S11 code is frozen.

### Phase E — S12–S15, by the gate's milestones (M0–M21)
Existing prototype code and what it covers. "Rework" means it must be re-run under the owner's red-first golden tests.

| Milestone | Gate item | State |
|---|---|---|
| M0 | preflight report (17 items, no code) | not done |
| M1 | schema: `fence_token_seq`, `execution_plans`, `step_reconciliations`, `state_transitions`, enum-generated CHECKs, idempotency ledger `tenant_id`, worker tables | partial: migrations 009/010 (deviations listed); no `fence_token_seq`, `step_reconciliations`, dead-letter tables |
| M2 | `fenced_write()`, repositories, transition log | partial: ownership-row fence, transition log, no token sequence |
| M3 | run, step, budget state machines | built (`transitions.py`), rework |
| M4 | lease, worker, dead letter, episode, confirmation, breaker machines | not done |
| M5 | PostgreSQL confirmation store | built in S0–S11 |
| M6 | S12 entry and durable admission | built (items 1–7, verifiers, quota, one transaction), rework |
| M7 | leases, fencing, ownership | not done (no leases, no fence token) |
| M8 / M8a | admission controller, worker selection, worker-management eligibility, operation quota | quota built; controller, selection, eligibility not done |
| M9 | BudgetReserver | built, rework |
| M10 | adapter interface, mock adapter, reliability guard | guard built; `BaseAdapter` probe/observe and mock adapter not done |
| M11 | idempotency ledger and retry | not done (mutations are never retried) |
| M12 | loop, dependents, terminal reasons | built minus checkpoints, rework |
| M13 | probe and EXECUTION episodes | not done (timeouts dead-letter) |
| M14 | live revalidation, cancellation | live check built; `request_cancellation` API, re-entry revalidation not done |
| M15 | verification and VERIFICATION episodes | port only |
| M16 | consolidation | minimal only |
| M17 | dead letter and explicit rollback | not done |
| M18 | S15 response and redaction | not done |
| M19 | crash recovery, fault injection | not done |
| M20 | multi-process, two Worker Runtimes | not done |
| M21 | 8 journeys, architecture suite, `owner_certify_s12.py`, report | not done |

Roughly 6 of 22 milestones are substantially built as prototypes, 4 partly, 12 not started. None is certified: the
gate's golden tests do not exist yet, and no sabotage or invariant checker runs.

### Phase F — Release
Deployment configuration (secrets, CORS, KEK), runbook, monitoring, then the S12–S15 certification report and tag.

## 3. Recommended order of the next work

1. **Phase A** (owner): A1, A2, A3, A4, A6 unblock everything else.
2. **B1 + D1a/D1b/D1d** together: one live session proves S2 with real chains and needs real observation metadata.
3. **B3 (CI)**, then B4/B5, then C1–C2.
4. Stop adding S12 code until the tag exists; resume it as Phase E under the gate's own golden-test process.
