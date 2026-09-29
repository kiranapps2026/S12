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

## Built ahead of the gate (owner instruction: "start the S12 entry checks")

`engine/stages/s12_entry/checks.py::check_entry` implements gate §7.1 items 1, 1a, 2, 3, 4, 5, 5a, 5b
and 7 in the gate's order, as a pure decision (writes nothing, re-authorises nothing), for single-step
plans and, following G1/G2/G7 above, multi-step plans. It is not wired into the runner: S12 does not
exist yet. `PostgresBindingVersionReader` reads a binding's
version once by `binding_id` (active rows only).

Points the gate owner should know:
- **1a will deny every run without a conversation.** The API accepts requests without
  `conversation_id`, and `context_incomplete` is what the gate specifies for that (C33). Either S0
  must supply one, or the gate must drop it from the required list.
- **5a has no reference form to match**: S9 has none, so the check is deliberately broad (the
  reference dataclasses, a `{step_id, output_field}` mapping, `${steps.N.x}`, `{{steps.N.x}}`,
  `step-N.output`, anything nested too deep to inspect). A user parameter that merely looks like one is
  denied; that is the fail-closed side.
- Reason names not fixed by the gate: `plan_not_validated` (item 1), `binding_missing` (item 3),
  `binding_unavailable` (registry unreadable, 5b).
- **Item 6 (verifiers, D1) is built** (`s12_entry/verifiers.py`, contract `contracts/verifier.py`):
  one `Verifier` per W/D/IRREVERSIBLE step in plan order (reads get none), built by a pure
  `build_verifier(step, ...)`. The verifier id is a UUIDv5 of (execution, step, operation, binding)
  instead of the "UUID v4" of DATA_CONTRACTS §34, because D1 requires the factory to be
  deterministic and recovery must rebuild the same ids. `expected_state` is derived from the step
  (`{"exists": true, "properties": <step params>}`, or `{"exists": false}` for an operation registered as
  expecting absence), because `Step` has no `expected_state` field. The resource identifier is read from
  the adapter result at run time (`observation_params.identifier_from_result`), the one thing taken from it.
- **New schema (migration 008, needs a ruling):** `kernel_ops.observation_method`,
  `observation_expects_absent`, `observation_identifier_field`. The specs call for an observation-method
  registry but no table holds one. A mutating operation with no method is refused at entry
  (`verifier_metadata_unavailable`), as is metadata for versions the registry no longer serves.
  Until real operations have these columns filled, every W/D/IRREVERSIBLE plan is denied at S12 entry
  (fail closed).
- **Durable admission (§7.2) is built** (`s12_entry/admission.py::admit_run`, `adapters/postgres/admission.py`,
  migration 009): the §7.1 checks, then ONE transaction: duplicate check by `(tenant, request_id)` (returns the
  existing run, writes nothing), one quota use at tenant then workspace level (hard exhausted → DENY
  `quota_exhausted`; soft → 3 attempts, then DENY with `retry_after_ms`), the run `pending`, the manifest
  (as S11 froze it), the frozen plan with its bindings, step→binding index and verifiers, one `pending`
  step row per plan step (binding, risk and mutation copied from that step's binding), the ownership
  record (no worker or lease yet), transition rows, then `pending → running`. Any failure rolls
  everything back (`admission_unavailable`); two concurrent admissions of one request create one run and
  use the quota once; the manifest and plan tables reject updates; all tables have forced RLS.
- **Schema deviations for the gate owner (migration 009):** times are `TIMESTAMPTZ` (DATABASE.md has `REAL`
  for the run tables); `execution_plans.frozen_bindings` is an array with `step_binding_index` (G4); no foreign
  keys to `workers`, `worker_leases` or `worker_versions` (they do not exist yet) and none from
  `budget_reservations` to runs/steps (S12's reserve step adds them); `operation_quotas` has no `worker_id`
  column (the spec's own CHECK made it always NULL); a minimal `state_transitions` table (C24).
- **Not built:** the S12 step loop (lease, reserve, execute), quota refunds, `fenced_write`, worker selection.
  Nothing calls `admit_run` yet: S12 is not in the runner.

## S12 step loop (built: gate §8 slice, milestones M9, M10-lite, M12, M14-lite)

`engine/stages/s12_execute/loop.py::run_execution` runs an ADMITTED run one step at a time in topological
order (ties by plan position, C11), loading the frozen plan, bindings and verifiers from the database
(so it is recovery-shaped): cancellation check (C16); live authorization at step start and before EVERY
adapter call (C23, S8's own check functions, fail closed, kill switch first); per-step budget
reserve → lock → commit/release through `PostgresBudgetReserver` (C3: tenant row locked, availability by
period, idempotent per step); pending → running; dispatch marker before the call (C35); the
`ReliabilityGuard` (reservation must be LOCKED, breaker, timeout, adapter exceptions → `adapter_defect`);
independent verification; `undo_token` for W/D steps with an inverse; dependents SKIPPED
(`dependency_failed`); collateral cancellation with the trigger's reason (C22); a minimal consolidation.
Every write goes through `PostgresExecutionRepository`: fenced by the ownership row (`FencedOut` stops all
work), checked against the canonical state machines (`transitions.py`), logged in `state_transitions`.
`terminal_reason` is a closed set with CHECKs and an immutability trigger (migration 010).

Fail-closed choices where a later milestone is missing (documented in the module docstring):
- a mutation is NEVER retried (no idempotency ledger, M11); READ steps retry retryable errors, 3 attempts;
- a timeout, or a verification that is not a clear PASS/FAIL, goes running → (timeout →) pending_probe →
  DEAD_LETTER with the budget left LOCKED (D4), the run DEAD_LETTER, remaining steps `run_dead_lettered`
  (no probe, M13; no dead-letter record or rollback, M17);
- a mutating step with no verifier or no verification runner is unverifiable, hence dead-lettered;
- budget exhausted → run CANCELLED `budget_exhausted` and earlier commits stay (C15).

Not built: worker selection, leases and the admission controller (M7/M8: one runtime, ownership row only),
pre-flight schema validation (no kernel input schema exists), checkpoints, the real verification engine
and its layers (M15), full consolidation and S13/S15 (M16/M18), quota refunds, `LiveAuthorizationCheck`'s
"capability not retired" check (C30), no real provider adapter (a scripted adapter is used in tests).
Nothing calls `run_execution` from the API yet.

Deviations for the gate owner (migration 010): `execution_runs.connection_id` and `terminal_reason`
(the live check needs the connection; a cancelled run needs its reason); `budget_reservations` still has no
foreign keys to runs and steps (existing S8 budget tests use free-form ids).
