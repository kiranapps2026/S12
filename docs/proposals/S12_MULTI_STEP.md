# S12 and multi-step plans (M2a) — what is ready, what the gate must change

**Status: proposal for the S12–S15 gate owner. No S12 code is written or changed by it.**

## Why there is no S12 code to change

`src/engine/stages/s12_worker_execution/handler.py` is the pre-existing stub, marked *"Not certified.
Superseded by the S12–S15 execution gate"*. It is not in the runner, and it cannot run: it writes
`with_stage_output("S12", …)`, and S12 is not in `STAGE_OUTPUT_FIELD`. The real S12 is the gate's
M0–M17 programme (`S12_S15_IMPLEMENTATION_PLAN.md`), which starts only when its §1 preconditions
hold: the `s0-s11-certified` tag, the v10 documents installed and pinned, the D1–D6 confirmations and
the C24–C38 review. None of those has happened, and the gate is an owner document (pinned).
Building S12 around a single binding now would be built twice.

## What S0–S11 now guarantees to S12 for a multi-step plan (built, tested)

| Guarantee | Where |
|---|---|
| `state.frozen_bindings` holds one binding per intent step, `frozen_binding_identity` is `None` | S5, R-AB |
| `plan_step_bindings(state)` maps **every plan step to its binding** by index (S4 records it) | `engine/stages/plan_steps.py` |
| every `Step.kernel_op_id / mutation / risk / cost / inverse / depends_on` equals its own binding's | S9 builds, S11 re-checks |
| the manifest carries **one** version of each kind: a chain whose bindings disagree is refused (`binding_mismatch`), so the C32 comparison `binding row version == manifest.binding_version` stays well defined | S11 (this change) |
| `budget_reserved` = sum of the step costs; each step has its own cost for per-step reservation (C3) | S6/S9 |
| plan steps are a linear chain (`depends_on` = previous step), parameters are bound, no step references another's output | S4/S9, C36 unchanged |
| a suspended chain stores no request text or intent parameters | runner |

## Gate amendments needed before S12 can run a chain (owner decisions)

| # | Gate text (v10) | Change |
|---|---|---|
| G1 | §7.1 item 3: "`frozen_binding_identity` is present" | "one frozen binding per plan step is present" (`frozen_bindings`, or the singular field for a one-step plan; exactly one of the two) |
| G2 | §7.1 item 5b / C32: "read the binding row once by `FrozenBindingIdentity.binding_id`" | read each **distinct** `binding_id` once; every row's version must equal the manifest's; any mismatch → `binding_version_mismatch` |
| G3 | §7.2: `execution_steps.resolved_binding_id`, `effective_risk`, `effective_mutation` "copied from the FrozenBindingIdentity" | copied from **that step's** binding, found through the S4 step→binding index (never by position guess) |
| G4 | §7.3 / DATABASE.md `execution_plans.frozen_binding_identity JSONB NOT NULL` | store the array of bindings (or the single object for one step) plus the step→binding index, so recovery reloads the exact plan and re-verifies each binding |
| G5 | C35 `LiveAuthorizationCheck` "reads status by the same `binding_id`" | per step, for that step's binding and provider; circuit breaker per provider |
| G6 | C36 | unchanged for M2a (no step-output references). M2b replaces it |
| G7 | §7.1 item 5 plan digest | unchanged: `plan_hash` already covers every step |
| G8 | failure of step *n* after step *n-1* succeeded | S13's compensation policy; `Step.inverse` (R-AF) is now available per step when the registry declares one |

## What I will build once the gate is open

The S12 entry checks (§7.1) as a pure function over `PipelineState`, with tests for single and
multi-step plans first, then durable admission, one milestone at a time as the plan orders them.
