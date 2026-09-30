# M2 rulings (R-AB…R-AL) — scope: M2a, heterogeneous linear chain

**Status:** decided on the owner's instruction "complete m2 ruling first" (2026-09-29). The options and
reasons are in `M2_MULTI_CAPABILITY.md` §6; the choices below take the proposal's recommendation
unless marked. They are a working ruling for this branch, not a pinned document; the owner may
overrule any line before the code for that stage is written. Nothing here changes S12 or gate C36.

| # | Ruling id | Decision |
|---|---|---|
| 1 | R-AB | **Replaces R-U.** One `FrozenBindingIdentity` per plan step: `PipelineState.frozen_bindings` (tuple, plan order). The single `frozen_binding_identity` stays as a read-only property = `frozen_bindings[0]` **only when the plan has exactly one step**; for 2+ steps it is `None`, so no code can silently use "the" binding of a multi-step plan. |
| 2 | R-AC | **Maximum 5 steps** for any plan, counting item expansion (matches "Chain 2–5 → WORKFLOW"). More → CLARIFY `too_many_steps`. The agentic limit of 10 is not used. |
| 3 | R-AD | **Confidence floor for plans of 2+ steps: 0.85** (single-step rules unchanged: ≥ 0.7 workflow, ≥ 0.9 fast). Below it → CLARIFY. The floor is a constant in one place, changeable only by a new ruling. |
| 4 | R-AE | **Accept unvalidated parameters for M2a**, because the database has no `input_schema`. Safeguards stay: parameters are bound at S9, covered by `plan_hash`, and shown in full at S10. Adding `kernel_ops.input_schema` and validating against it is a prerequisite of M2b, not of M2a. |
| 5 | R-AF | **S9 records, does not require, an inverse.** `Step.inverse` is filled from the registry when it declares one; a W/D step without one is allowed but marks `requires_confirmation` (already true for D) and the S10 text says "cannot be undone automatically". Compensation policy itself is S13's. |
| 6 | R-AG | **Deferred to M2b** (hash the reference structure). |
| 7 | R-AH | **Deferred to M2b** (C36 replacement text; needs the S12 gate owner). M2a keeps C36 unchanged: no step references another step's output. |
| 8 | R-AI | **Deferred to M2b** (secret classification source for output schemas). |
| 9 | R-AJ | **Graph naming:** a linear chain of 2–5 steps is `chain`; any branching or more than 5 steps is `complex` and ends in CLARIFY until M2c. |
| 10 | R-AK | **Repeated items × several capabilities expand to N + N steps** in list order within the 5-step cap ("create 3 contacts then email each" = 6 steps → too many → CLARIFY). No grouping by capability. |
| 11 | R-AL | **Cross-provider confirmation confirmed:** a plan touching 3 or more distinct providers requires confirmation (DATA_CONTRACTS §7 row becomes reachable with M2a). |

## Consequences to build in (M2_MULTI_CAPABILITY §5, unchanged order)

1. Contract additions: `frozen_bindings`, `IntentResult.steps`; the single path keeps working.
2. S2 ordered `steps` answer (a lone `intent` stays valid) → S3 per-step matches → S4 chain graph.
3. S5 per-step freeze → S6 (risk = max, cost = Σ, R-AL) → S7 (floor per R-AD, cap per R-AC).
4. S8 per binding → S9 per step (R-AF) → S10 lists every operation → S11 per-step binding equality.
5. Golden tests, runbook Part 7, pins, certifier ids, live test — each an owner-authorised integrity change.

## Not decided here

Rulings 6–8 (M2b), S13 compensation, and any change to S12. The M2b prerequisites are the
`input_schema`/`output_schema` columns, a registry loader and a gate change.

## Implementation status (M2a, built)

Built and tested: R-AB (per-step matches and bindings; the singular fields stay for one-step plans and
are None for 2-5 steps), R-AC (5 steps, items included), R-AD (0.85 floor at S7), R-AE (bounded step
parameters, bound at S9, in `plan_hash`, shown at S10), R-AJ, R-AK, R-AL. A step's binding is looked up
through one mapping (`engine/stages/plan_steps.py`) used by S6, S9 and S11, and S11 re-checks every step
against its own binding (operation, mutation, risk, cost, dependencies, id).

**R-AF is only partly built.** `Step.inverse` stays `None`: the registry does hold `kernel_ops.inverse`,
but carrying it to S9 needs a new field on `FrozenBindingIdentity`, whose field list is pinned by
`tools/owner_certify.py` (OWN-17, R-O approved extensions). Adding it is an owner-authorised change to
the certifier's `CONTRACTS` table (and its hash). Until then S10 does not claim a step is or is not
undoable.

Not covered by tests here: a live DeepSeek answer with `steps` (the prompt asks for it; only a run with
the key can show how the real model behaves), and S12, which still reads the singular
`frozen_binding_identity` and must be made per-step before a multi-step plan can execute.
