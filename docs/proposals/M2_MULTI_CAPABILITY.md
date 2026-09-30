# Proposal — M2: plans that combine more than one capability

**Status: §6 ruled for M2a in `M2_RULINGS.md` (R-AB…R-AL); rulings 6–8 deferred to M2b. No code yet.**
Not a pinned document. Ruling ids below are placeholders (`R-AB…`; R-AA is the S0.1 check).

## 1. Where things stand

| | Today (this branch) |
|---|---|
| One plan = one capability, repeated per item (`parameters.items`, ≤ 5 steps, a chain) | done |
| Two different operations ("create contact X, then email X the invoice") | S3 finds >1 distinct capability → S7 CLARIFY `multi_capability_not_supported` (ruling R-U: one binding per plan) |
| Step data flow (step 2 uses step 1's output) | not supported by design: gate **C36** — params fully bound at S9 and covered by `plan_hash`; `depends_on` is ordering only; S12 entry denies any step-output reference (`data_flow_unsupported`); register **P0-B** open |

Contracts that are already multi-ready (DATA_CONTRACTS §7): `TaskProfile.capabilities`, `.mutations`
and `.providers` are lists, `risk` is the max over steps, `cost` the total. `Step` has per-step
`kernel_op_id`, `mutation`, `risk`, `cost`, `inverse`. What is single-valued today is the
**FrozenBindingIdentity** (one per run), the S2 answer (one intent), S3's output (one match) and
S8's checks (one capability/provider/mutation).

## 2. The key idea: stage it, so the first stage needs no data flow

Many useful requests need **ordering but not data flow**: "create contact Ana (ana@x.com), then email
ana@x.com the invoice" — every parameter is known from the request. Only "…then email *the new
contact's id*" needs a runtime value.

| Stage | Adds | Conflicts with C36? | Needs |
|---|---|---|---|
| **M2a** heterogeneous linear chain (≤ 5 steps, different capabilities, params fully bound at S9) | per-step bindings, multi-intent S2, chain graph, per-step S8/S10/S11 | **No** — no step references another's output; S12 entry unchanged | rulings 1–5, 9–11 |
| **M2b** step data flow (`StepOutputReference` / `StepParameterBinding`) | references in params, the six validation rules of PIPELINE_STAGES §11, typed/secret-flagged output schemas | **Yes** — replaces C36's interim rule; S12 entry must accept references | rulings 6–8, a schema migration, gate change |
| **M2c** branching graphs (parallel steps, `join_mode` any/threshold) | DAG with fan-out/fan-in | Yes (S12 scheduling) | later |

Recommendation: implement **M2a only** first. It removes the biggest usability gap without touching
the S12 gate, and it makes M2b a smaller step.

## 3. What changes, stage by stage (M2a; M2b noted)

Guiding invariants that do **not** change: risk, mutation, cost, provider, kernel op and versions
come **only** from the registry per step (A4); the model may choose *which* registered intents and in
what order, never their properties; every refusal is fail-closed with a status; a single-capability
plan is the degenerate one-step case (all current behaviour and golden tests keep passing).

| Stage | Change | Size |
|---|---|---|
| **S2** | model answers with an ordered list `steps: [{intent, parameters}]` (schema in the prompt; JSON mode has no schema constraint, so S2 validates). Each intent must be registry-offered (or `unknown`/`prohibited`); ≤ 5 steps after item expansion; a single intent stays valid (compat: `{"intent":…}` = one step). `IntentResult` gains `steps` (implementation contract, not R-O-listed) | M |
| **S3** | returns `CapabilityMatch` **per step**, keyed by step index: for step *i* the registry's capability for its intent. "More than one candidate for one intent" stays ambiguous (CLARIFY); "different intents for different steps" is now the normal case | M |
| **S4** | graph over steps: `simple` (1), `chain` (linear 2–5), `complex` (any branching, or > 5) — M2a builds linear chains from list order; `execution_steps` carry each step's own capability ref and params | M |
| **S5** | resolves and freezes **one binding per step**. New `PipelineState.frozen_bindings: tuple[FrozenBindingIdentity, ...]` (one per step, order = plan order); `frozen_binding_identity` (single) is retained for 1-step plans or replaced by `frozen_bindings[0]` — ruling 1. Policy versions unchanged (one set per run) | L |
| **S6** | `TaskProfile` from all bindings: `capabilities`/`mutations`/`providers` per step, `risk = max`, `cost = Σ cost_i`, `requires_confirmation` = any D/IRREVERSIBLE step ∨ Σcost > 20 ∨ max risk > 0.7 ∨ **≥ 3 distinct providers** (DATA_CONTRACTS §7's cross-provider row becomes reachable) | S |
| **S7** | row 4 (`multi_capability_not_supported`) is replaced: heterogeneous chain of 2–5 steps with confidence ≥ threshold → WORKFLOW; risk deny uses `max` risk over steps | S |
| **S8** | run the 8 checks **for every binding** (grant per capability, breaker per provider, mutation policy per (mutation, risk)); budget check on Σcost; first failure denies with the same R-L reasons (reason vocabulary unchanged) | M |
| **S9** | one `Step` per plan step with **its own** `kernel_op_id`/`mutation`/`risk`/`cost`/`params` from its binding; `depends_on` = previous step (chain); `budget_reserved = Σ`; `plan_hash` covers all of it (already includes steps) | M |
| **S10** | `Confirmation.operations` lists **every distinct operation** with mutation and (M2b) the bound parameters, so the user sees exactly the chain; one confirmation per plan (bound to `plan_hash`) | S |
| **S11** | R-S checks become per step: each `Step.kernel_op_id/risk/mutation` equals **its own** binding (`binding_mismatch`), plus DAG/plan_hash/budget/confirmation as today; unknown or duplicate binding for a step → `binding_mismatch` | S |
| **Manifest** | unchanged in shape: versions come from the registry (global), not per binding; add nothing until S12 needs per-step binding ids (gate C32 reads bindings **once** from state) | S |
| **S12 entry (C36)** | M2a: no change (no references). M2b: must accept references whose structure is covered by `plan_hash` | gate |

M2b additions: S9 emits `StepParameterBinding`s; validation (all six rules of PIPELINE_STAGES §11):
(1) referenced step exists and precedes, (2) output field exists in the referenced capability's
**output schema**, (3) `source.field_type == parameter.type`, (4) tenant/workspace identical across
steps, (5) **secret data never flows** (output fields flagged `secret` in the schema cannot be
referenced), (6) acyclic. Prerequisite: `kernel_ops.input_schema` / `output_schema` (typed fields with
a `secret` flag) in the registry — the database has none today (`CapabilityMetadata.output_schema` is
`{}`), plus a migration and registry loader.

## 4. Test plan (golden and ordinary)

Fixture API: `make_scenario(steps=[("W", 0.2, 3), ("W", 0.3, 1)], ...)` → registry with one capability
per step. Golden additions (owner-pinned): risk = max and cost = Σ (S6); route table rows for
heterogeneous chains (S7); per-step S8 denial (a grant missing for step 2 denies, reason names the
check); per-step binding equality and swapped/reordered bindings → `binding_mismatch` (S11); plan
hash changes if steps are reordered or a step's binding changes (S9); confirmation lists every
operation (S10); single-capability plans unchanged. Sabotage-verify each. Live test:
"create contact Ana (ana@example.com) then email her the invoice" through the real model.
M2b adds: each of the six data-flow rules with a failing case, and "a secret field can never be
referenced".

## 5. Order of work (each a separate, reviewable commit; certifier green at every step)

1. Rulings + contract additions (`frozen_bindings`, `IntentResult.steps`) with the old single path intact.
2. S2 multi-step answer + validation → S3 per-step matches → S4 chain graph.
3. S5 per-step freeze → S6 aggregation → S7 rows.
4. S8 per-binding checks → S9 per-step plan → S10 operation list → S11 per-step validation.
5. Golden tests, runbook Part 7 update, pins, required-test ids, live test.

## 6. Rulings the owner must make (nothing below is decided by the specs)

1. **Replace R-U** (one binding per plan) with per-step bindings; keep or retire the single
   `frozen_binding_identity` field for 1-step plans.
2. **Max steps** for a heterogeneous chain: 5 (matches "Chain 2–5 → WORKFLOW") or 10 (the agentic
   planning limit in PIPELINE_STAGES §11)?
3. **Confidence floor** for multi-step plans (today: ≥ 0.7 workflow, ≥ 0.9 fast). A wrong 3-step plan
   costs more than a wrong 1-step plan.
4. **Where parameters come from**: LLM-extracted values are untrusted; they are bound at S9, hashed
   and shown at S10, but nothing validates them against the capability's `input_schema` (also absent
   from the DB). Require input schemas before M2a, or accept unvalidated params for now?
5. **Partial failure / compensation**: if step 2 fails after step 1 succeeded, is `Step.inverse`
   required for W/D steps at S9 (deny plans without one)? This is S13's policy but S9 must record it.
6. **Plan hash and data flow (M2b)**: hash the *reference structure* (which step/field feeds which
   param) — recommended — so a runtime-resolved value never sits outside `plan_hash` (C36's concern).
7. **C36 replacement text** and the S12 entry rule for references (owner + S12 gate owner).
8. **Secret classification source** for output schemas (registry column `secret` per output field).
9. **Graph type naming**: linear chain = `chain`; any branching = `complex` (→ CLARIFY until M2c).
10. **Repeated items × several capabilities** ("create 3 contacts then email each"): expand to
    N + N steps within the step cap (recommended), or group by capability?
11. **Cross-provider confirmation** (≥ 3 providers) activates with M2a: confirm as specified.

## 7. Risks

- Largest: silent property drift — a step executing with another step's risk/mutation. Mitigated by
  S11's per-step binding equality, the runner's independent checks, and golden sabotage tests.
- LLM ordering errors ("email before create"): mitigated by confirmation showing the chain, and by
  rejecting plans that would send before create only if the registry declares such dependencies
  (needs M2b schemas; otherwise the user's confirmation is the guard for D/W chains).
- Cost: N steps → N-fold provider calls at S12 (budget check on Σ at S8 is only a precheck).
