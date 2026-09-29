# S0–S11 CERTIFICATION RUNBOOK (BUILD → VERIFY → REPAIR → TEST → CERTIFY)

Repository: `C:\Users\Administrator\Documents\1SuperAgents`
This file replaces `S0_S11_COMPLETION_PROMPT.md`. Save it as
`docs\gates\S0_S11_RUNBOOK.md`. It is the only instruction set for finishing S0–S11.
Revision: v8 — spec documents pinned (Part 0 item 5, OWN-20). v7 — FrozenBindingIdentity extensions updated; ExecutionContext and
module-level-state rulings added (R-X, R-Y). v6 — the owner certifier `tools/owner_certify.py` is the only
certification authority; `raw_input` leaves ExecutionContext. v5 — R-Q rewritten (reachable high-risk path, deny threshold), R-U (single
binding scope), R-V (S6 formula), R-W (scenario and tamper fixtures), Part 6 exact
test code for S6, S7, S9. v4 — adds R-O to R-S (contract conformance, canonical vocabularies, S7
routing, S10 outcome, S11 checks, write order, scenario fixtures), Step 2A, CHK-16 to
CHK-18. v3.1 — R-B argument sources aligned with DATA_CONTRACTS (capability from
frozen binding, `task_profile.cost`, canonical mutation values). v3 — v2 plus R-L (reason vocabulary), R-M (S8 sets auth_passed on
ExecutionContext), R-N (S7 routing and downstream safety preconditions), and
Step 2B (S7–S11 cross-stage safety).

---

## PART 0 — CERTIFICATION AUTHORITY (READ FIRST)

1. The only certification authority is **`tools/owner_certify.py`**, supplied by the
   owner. Its SHA-256 is stored in `docs/gates/owner_certify.sha256`. You must never
   create, edit, move, rename or delete that file, the `.sha256` file, or this
   runbook. You must never edit the required-test list or any threshold. Doing so
   voids the phase.
2. `tools/certify_s0_s11.py` (your own checker) is advisory only. Its PASS results
   mean nothing for certification.
3. When an owner check fails, the fix is always in `src/` or `tests/`, never in a
   checker. If you believe an owner check is wrong, STOP (condition S3) and quote the
   check, the file and the line; the owner decides.
4. Before every report, run:
   `python tools/owner_certify.py --selftest` (must print OK on every row), then
   `python tools/owner_certify.py`. Paste both outputs in full. "Certified" means the
   second command printed `N/N PASS` and exited 0 at the reported commit.
5. **Spec documents are owner-controlled.** Everything in `docs/implementation/`
   is pinned by SHA-256 in `docs/gates/spec_pins.sha256` and checked by OWN-20. You
   must never edit a spec document or the pin file. If a ruling in this runbook
   requires a spec change, list the exact text change in your report; the owner
   applies it and re-pins. Changing the spec to make a check pass voids the phase.
6. `docs/gates/S0_S11_COMPLETION_PROMPT.md` is obsolete and must be deleted. Its step
   letters (A–J, "Section 5") are not used anymore. Steps are numbered as in Part 3
   of this runbook (0, 0B, 1, 2, 2A, 2B, 3 … 11).

---

## PART 1 — HOW TO WORK

### 1.1 Operating rules

1. Re-read this file at the start of every session and after any context
   summarization. This file overrides your memory of earlier instructions. If your
   memory of an instruction differs from this file, this file is right.
2. Work through the steps in Part 3 in order, **without waiting for the owner between
   steps**. Stop only at: the checkpoint after Step 5, a STOP condition (1.3), or the
   end.
3. Every step has the same four parts: **Build** (exact changes), **Verify** (exact
   commands and expected output), **Repair** (what to do if verification fails),
   **Commit**. A step is finished only when its Verify section passes exactly.
4. Never ask the owner a question that this file answers. Rulings for all known
   decisions are in Part 2.
5. Do not read `.env`. Tests use the environment variable `TEST_DATABASE_URL`
   (not needed in S0–S11; everything here is in-memory).
6. Do not touch `C:\Users\Administrator\Documents\AiagentsOS\rebuild`.

### 1.2 Forbidden actions (any one fails the step)

- Changing a test's expected value to match current behavior, unless the step says so
  and cites the spec.
- Building a stage's output by hand in an integration or journey test.
- Any code path that supplies a default, fallback or "test value" for a safety input
  (policy, kill switch, provider state) inside `src/`.
- Any "skip if already set", "tolerate existing value" or overwrite logic around
  PipelineState writes.
- Module-level mutable state or setter functions (`set_*()`, `global`) in `src/`.
- `pytest.skip`, `xfail`, `@pytest.mark.skip` anywhere in `tests/`.
- Deleting a test without replacing its coverage (report name, reason, replacement).
- `json.dumps(..., default=str)` anywhere in `src/`.

### 1.3 STOP conditions (only these)

Stop, report, and wait only if:
- S1. A step requires changing a spec document not named in this file.
- S2. Two spec documents contradict each other on something this file does not rule on.
- S3. The checker (Step 0) reports a FAIL you cannot repair within 3 attempts using
  the Repair section and Part 4.
- S4. The test count would drop below the previous step's count and you cannot
  restore the coverage.

For each STOP: quote the conflicting text or the failing output, list what you tried,
and propose one fix.

### 1.4 Report format (after every step, nothing else)

```text
STEP <n> — <name>: DONE | STOPPED (<condition>)
Changed files: <list>
Tests added: <names>   Tests removed: <names + replacement>
Expected values changed: <list with spec citation> | none
Checker: <paste the full checker table>
pytest: <raw summary line, copied>
Commit: <hash>
```

---

## PART 2 — RULINGS (DECIDED; DO NOT RE-ASK)

R-A. **Kill switch.** Source is `KernelPolicy.kill_switch_engaged`, a required field
with no default. S8 receives the policy through its dependencies (R-C). If the policy
object is missing, the field is missing, or reading raises → `SafetyResult(allowed=False,
reason="kill_switch_state_unavailable", failed_check="kill_switch")`. Engaged →
`reason="kill_switch", failed_check="kill_switch"`. The kill switch is evaluated first;
when it denies, no other check is evaluated.

R-B. **Checks evaluate status, not ID presence.** Missing ID → DENY (precondition).
Present ID → the provider is asked for status. Table:

| # | check name (exact) | Precondition | Status rule (via provider) |
|---|---|---|---|
| 1 | `user_active` | `context.user_id` present | `auth_state.user_status(user_id) == "active"` |
| 2 | `tenant_active` | `context.tenant_id` present | `auth_state.tenant_status(tenant_id) == "active"` |
| 3 | `connection_active` | `context.connection_id` present | status `== "active"` and (expires_at is None or expires_at > now) via `auth_state.connection_status(connection_id)` returning `(status, expires_at)` |
| 4 | `capability_granted` | `frozen_binding.capability_id` present | `auth_state.has_grant(tenant_id, user_id, frozen_binding.capability_id) is True` |
| 5 | `resource_scope` | `context.workspace_id` present | `auth_state.in_scope(tenant_id, user_id, workspace_id) is True` |
| 6 | `circuit_breaker` | `frozen_binding.provider` present | `circuit_breaker.state(provider_id)` is `"CLOSED"` or `"HALF_OPEN"`; `"OPEN"` → DENY |
| 7 | `budget_available` | `task_profile.cost` present (DATA_CONTRACTS TaskProfile field name) | `auth_state.budget_available(tenant_id, task_profile.cost) is True` |
| 8 | `mutation_safety` | `effective_mutation` from the frozen binding | `mutation_policy.permits(effective_mutation, effective_risk) is True` |

Mutation values are exactly the DATA_CONTRACTS vocabulary `"R"`, `"W"`, `"D"`,
`"IRREVERSIBLE"`. Any other mutation string in `src/` (for example `"READ"`,
`"IDEMPOTENT_WRITE"`) is a defect: replace it with the canonical value. If the
implementation's TaskProfile names the cost field differently from `cost`, rename it
to `cost`.

For every check: the provider returns `None`, returns a value of the wrong type or an
unknown value, or raises → DENY with `failed_check` = that check's exact name and
`reason` = `"<check>_unavailable"` for None/exception or `"<check>_invalid"` for wrong
type/unknown value. Rule values (`"active"`, `True`, `"CLOSED"`) must match exactly;
anything else is a denial.

R-C. **Dependency injection.** Create in `src/engine/stages/s8_safety_gate/`:

```python
class AuthorizationStateProvider(Protocol):
    def user_status(self, user_id: str) -> str: ...
    def tenant_status(self, tenant_id: str) -> str: ...
    def connection_status(self, connection_id: str) -> tuple[str, float | None]: ...
    def has_grant(self, tenant_id: str, user_id: str, capability_id: str) -> bool: ...
    def in_scope(self, tenant_id: str, user_id: str, workspace_id: str) -> bool: ...
    def budget_available(self, tenant_id: str, amount: float) -> bool: ...

class CircuitBreaker(Protocol):
    def state(self, provider_id: str) -> str: ...   # "CLOSED" | "OPEN" | "HALF_OPEN"

class MutationPolicy(Protocol):
    def permits(self, mutation: str, risk: float) -> bool: ...

@dataclass(frozen=True)
class S8Dependencies:
    policy: KernelPolicy | None
    auth_state: AuthorizationStateProvider | None
    circuit_breaker: CircuitBreaker | None
    mutation_policy: MutationPolicy | None
```

S8's handler receives `S8Dependencies` from the pipeline runner. The runner receives
all stage dependencies from one composition root (`build_pipeline(deps)`), never from
module globals. A `None` dependency → DENY for every check that needs it (reason
`"<check>_unavailable"`; for policy: R-A). In-memory implementations
(`InMemoryAuthorizationStateProvider`, `InMemoryCircuitBreaker`, `AllowAllMutationPolicy`
for tests only) live in `tests/fixtures/`, **not** in `src/`.

R-D. **Shared check library.** The 8 check functions live in
`src/engine/stages/s8_safety_gate/checks.py` as pure functions
`check_<name>(context, task_profile, frozen_binding, deps) -> CheckResult` where
`CheckResult(name: str, passed: bool, reason: str | None)`. S8 calls them in table
order after the kill switch. They never write anything. (S12 will reuse them.)

R-E. **ExecutionContext.** Remove fields `provider`, `binding_id`, `capability_id`,
`kernel_op_id`. S5's permitted ExecutionContext changes are exactly
`tenant_policy_version_id`, `workspace_policy_version_id`, `policy_version_id`. Anything
that read the removed fields reads `state.frozen_binding_identity` instead.

R-F. **PipelineState writes.** `with_stage_output(stage_id, **fields)` is the only
write path. For each field: stage must own it, field must be `None`, value must be an
instance of the field's declared type (`isinstance`; `None` not allowed as a value
except S11's `execution_manifest=None` on denial). Violation → `ContractViolationError`
naming stage, field, expected type, actual type.

R-G. **Remove legacy.** `StageResult` (including the alias in
`src/contracts/stage_result.py`), `_StageHandlerAdapter`,
`stage_result_to_pipeline_update`, `_replace_fields` must have zero references in
`src/` and `tests/`. Delete `stage_result.py` if nothing else is in it.

R-H. **Journeys use real handlers.** Tests build state through a helper
`tests/fixtures/pipeline.py::run_through(stage_id, request, deps)` that runs the real
handlers S0…stage_id in order. No journey test calls `with_stage_output()` directly.

R-I. **Stage sequence scope.** The repository contains pre-existing S12–S15
handlers. They are not part of this certification and are not deleted. Define
`PRE_EXECUTION_SEQUENCE = ("S0", …, "S11")` in the runner. The S0–S11 pipeline, all
journeys and CHK-05 use only this sequence. S12–S15 handlers are not called by it.
Add a header comment to each S12–S15 handler file: "Pre-existing. Not certified.
Superseded by the S12–S15 execution gate." Do not modify their logic.

R-J. **Scope of source scans.** CHK-07, CHK-08, CHK-09 and CHK-10 scan `src/` except
the S12–S15 handler packages (`s12_*`, `s13_*`, `s14_*`, `s15_*`). Findings inside
those packages are written to `docs\gates\s12_s15_findings.md` (file, line,
pattern) for the S12 gate, and are not fixed now. Everything else in `src/`,
including `src/contracts/`, is in scope and must be fixed.

R-K. **Checker errors.** A check that crashes or reports "checker error" is not a
FAIL result; it is a broken checker. Fix the checker before continuing. A step
cannot be DONE while any row shows a checker error.

R-L. **S8 reason vocabulary (exact).** Every S8 denial reason is one of:
`<check>_missing_id` (precondition ID absent), `<check>_unavailable` (dependency or
provider missing, returned None, or raised), `<check>_invalid` (value of wrong type
or not in the known vocabulary, e.g. `"UNKNOWN"`, `42`, a bare string where a tuple is
expected), or the rule-not-met reason from this table:

| check | rule-not-met reason |
|---|---|
| user_active, tenant_active, connection_active | `<check>_inactive` (known non-active status) |
| connection_active | `connection_active_expired` (active but expires_at ≤ now) |
| capability_granted, resource_scope, budget_available, mutation_safety | `<check>_denied` (provider returned exactly `False`) |
| circuit_breaker | `circuit_breaker_open` |

Plus `kill_switch`, `kill_switch_state_unavailable`, `missing_task_profile`,
`missing_frozen_binding`, `missing_identity`. No other reason strings. Boolean
providers pass only on `is True`, deny on `is False`, and anything else is
`_invalid`. `connection_status` must return a 2-tuple `(str, float | None)`;
anything else is `_invalid`.

R-M. **S8 records authorization on ExecutionContext.** DATA_CONTRACTS assigns
`auth_passed` and `auth_result_id` to S8. On ALLOW, S8 produces a replacement
ExecutionContext with `auth_passed=True` and a new `auth_result_id` (UUID), through
the single controlled context-replacement path (the B4 `validate_replace`
mechanism, whitelist for S8 = exactly these two fields). On DENY, ExecutionContext
is unchanged (`auth_passed` stays False). S2 (`task_id`), S5 (policy version
fields) and S8 use the same mechanism; no other stage may replace the context.

R-N. **Cross-stage safety.**
- S7: every combination not matched by the PIPELINE_STAGES S7 decision matrix
  (including confidence 0.5–0.7 with any graph type, and missing values) →
  CLARIFY. S7 reads risk from the frozen binding's `effective_risk`. Every
  executable path (FAST, WORKFLOW) passes through S8; no path skips it.
- S9, S10 and S11 each check, as their first action, that
  `state.safety_result is not None and state.safety_result.allowed is True and
  state.execution_context.auth_passed is True`; otherwise DENY with reason
  `safety_not_passed`. This is defense in depth: a runner bug must not be able to
  plan, confirm or manifest an unauthorized request.
- The ExecutionManifest records `auth_result_id` from ExecutionContext.

R-O. **Contract conformance.** For every class below that DATA_CONTRACTS.md defines,
the implementation's field **names** must equal the spec's field names, except the
extensions listed in the table. Allowed type deviations: `tuple` instead of `list`,
a frozen mapping instead of `dict` (R8).

| Contract | Definition in DATA_CONTRACTS.md | Approved extensions (only these) |
|---|---|---|
| ExecutionContext | `class ExecutionContext` | none |
| Plan, Step | `class Plan`, `class Step` | none |
| FrozenBindingIdentity | `class FrozenBindingIdentity` | `capability_version`, `binding_version`, `risk_policy_version`, `authorization_version` (versions frozen at resolution time; the manifest and S12 D1 read them from here) |
| TaskProfile | `class TaskProfile` | none |
| SafetyResult | `class SafetyResult` | none |
| ValidationResult | `class ValidationResult` | none (`errors` holds reason codes, e.g. `("budget_invalid",)`) |
| Confirmation | `class Confirmation` | none (status lives in the confirmation store, not on the contract) |
| ExecutionManifest | `class ExecutionManifest` | `auth_result_id` (R-N) |
| StageStatus, PathDecision | `class StageStatus`, `class PathDecision` | none (these are enums) |

Consequences to implement:
- FrozenBindingIdentity: `mutation_type` → `effective_mutation`; add
  `engine_module`, `resolved_at_stage` (always `"S5"`); remove `tenant_id`,
  `provider_health_score`, `policy_version` and `metadata`. `policy_version` lives on
  ExecutionContext as `policy_version_id` (S5 whitelist); the manifest's
  `policy_version` is taken from there. `risk_policy_version` and
  `authorization_version` stay on the frozen binding (approved extensions).
- TaskProfile becomes exactly: `intent`, `capabilities`, `graph_type`,
  `steps_estimated`, `mutations`, `risk`, `cost`, `requires_confirmation`,
  `resource_scope`, `providers`. The binding copies (`binding_id`, `capability_id`,
  `kernel_op_id`, `provider`, `adapter_class`, `effective_risk`, `mutation_type`)
  are removed: every reader uses `state.frozen_binding_identity`. `risk` and
  `mutations` are copied by S6 from the frozen binding, never recomputed.
  `estimated_duration_ms` and `timeout_seconds` are removed (timeouts are per Step).
- ExecutionContext has no `raw_input`. The raw request moves to a new PipelineState
  field `entry_request: EntryRequest`, owned by S0 (S0 owns exactly two fields:
  `execution_context` and `entry_request`). S1 reads `state.entry_request`.
  Untrusted user text never lives in the security context.
- `IntentResult` (S2 output) is not the spec's IntentSpecification; it stays as an
  implementation contract and is documented in DATA_CONTRACTS as such. Record
  "IntentSpecification adoption" as an open question; do not implement it now.
- A test-side allowlist is not allowed: extensions are only those in this table.

R-P. **Canonical vocabularies.** Only these literal values are valid in `src/`:
mutation `"R" | "W" | "D" | "IRREVERSIBLE"`; graph_type
`"simple" | "chain" | "complex"`; join_mode `"all" | "any" | "threshold"` (S9 emits
`"all"`); PathDecision enum values `fast | workflow | agentic | clarify | deny`;
confirmation store statuses `pending | consumed | rejected | expired`. Known
non-canonical literals to eliminate: `"READ"`, `"WRITE"`, `"DELETE"`,
`"IDEMPOTENT_WRITE"`, `"STANDARD"`, `"SINGLE_STEP"`, `"WORKFLOW"` (as a graph type),
`"sequential"`, `"approved"`.

R-Q. **S7 routing.** The code's `PathDecision` dataclass is renamed
`PathRoutingResult(decision: PathDecision, reason: str | None)`, where `PathDecision`
is the spec enum. Spec conflict resolved here (record it in the register): the
PIPELINE_STAGES S7 table limits WORKFLOW to risk ≤ 0.5, but DATA_CONTRACTS requires
confirmation for risk > 0.7, which would make that confirmation unreachable. Ruling:
risk decides FAST eligibility and the DENY threshold; high-risk requests go WORKFLOW
and get confirmation at S10. Evaluate in this order; first match wins:

| # | Condition | Decision | reason |
|---|---|---|---|
| 1 | `KernelPolicy.risk_deny_threshold` missing/unreadable | deny | `risk_threshold_unavailable` |
| 2 | frozen `effective_risk` > `risk_deny_threshold` | deny | `risk_above_threshold` |
| 3 | no capability matched | clarify | `no_capability` |
| 4 | more than one distinct capability required (R-U) | clarify | `multi_capability_not_supported` |
| 5 | confidence missing or < 0.5 | clarify | `low_confidence` |
| 6 | graph_type `complex` or steps ≥ 6 | clarify | `complex_not_supported` |
| 7 | graph `simple`, steps == 1, confidence ≥ 0.9, risk ≤ 0.3 | fast | None |
| 8 | graph `simple` or `chain`, 1 ≤ steps ≤ 5, confidence ≥ 0.7 | workflow | None |
| 9 | anything else | clarify | `unmatched_route` |

`risk_deny_threshold` is a required `KernelPolicy` field with no default (test
fixtures use 0.95). Confidence comes from the S2 output; risk from the frozen binding;
graph type and step count from the S4 output. `agentic` is never emitted. `clarify`
and `deny` end the pipeline with StageStatus CLARIFY / DENY.

R-R. **S10 outcome.** S10 always writes exactly one output
`ConfirmationOutcome(required: bool, confirmation: Confirmation | None)`.
`requires_confirmation` False → `required=False, confirmation=None`. True → a
`Confirmation` per spec (`plan_id` = plan.id, `plan_hash` from S9, `user_id` and
`conversation_id` from ExecutionContext, `expires_at` = now + 300 s) is stored in the
confirmation store with status `pending`, and the pipeline returns CLARIFY-style
"confirm" to the user (status per the S0–S11 envelope mapping). On the confirmed
re-entry, the store's conditional consume (C20 pattern) must succeed before S11 runs;
expired → DENY `confirmation_expired`; wrong user or hash → DENY
`confirmation_mismatch`. No `approved` status exists.

R-S. **S11 checks.** In order, after the R-N safety precondition: every
`Step.kernel_op_id == frozen_binding.kernel_op_id` (else `binding_mismatch`); every
`Step.risk == frozen_binding.effective_risk` and `Step.mutation ==
frozen_binding.effective_mutation` (else `binding_mismatch`); plan digest equals S9
`plan_hash` (else `plan_hash_mismatch`); when `ConfirmationOutcome.required`, the
confirmation was consumed and its `plan_hash` matches (else `confirmation_mismatch`);
`budget_reserved >= 0` (else `budget_invalid`); DAG acyclic (else `dag_invalid`);
at least one step (else `plan_empty`). Denial → `ValidationResult(is_valid=False,
errors=(<code>,))`, `execution_manifest=None`, StageStatus DENY with that code as
reason.

R-U. **Single-binding scope for this phase.** S5 produces one FrozenBindingIdentity.
Therefore every plan in this phase uses one capability: all steps have the frozen
binding's `kernel_op_id`, `effective_risk` and `effective_mutation` (a chain is the
same operation applied N times). Requests needing several distinct capabilities are
routed to clarify by S7 row 4. Record "per-step bindings for multi-capability
workflows" as an open architecture question for the S12/M2 gate.

R-V. **S6 exact formula.** Inputs: the frozen binding, the S3 output's
CapabilityMetadata for `frozen_binding.capability_id` (field `cost`), the S4 output's
step count. Missing metadata → StageStatus DENY `capability_metadata_missing`.
- `risk = frozen_binding.effective_risk`
- `mutations = (frozen_binding.effective_mutation,) * steps_estimated` (tuple)
- `cost = capability.cost * steps_estimated`
- `requires_confirmation = ("IRREVERSIBLE" in mutations) or ("D" in mutations) or
  (cost > 20) or (risk > 0.7)`
Every D and IRREVERSIBLE plan is confirmed, whatever its cost or risk (amended: PIPELINE_STAGES
§12 "never execute D/IRREVERSIBLE unconfirmed" wins over the older DATA_CONTRACTS §7 "D only
above cost 5"). Cross-provider (3+) cannot occur: one binding, one provider (R-U).
Comparisons are strict (`>`). The cost rule is S6's job; "enforced at S12" is wrong.

R-T. **Write order and scenario fixtures.**
- Every S0–S11 stage writes its owned output exactly once when it finishes,
  including when it denies (S10 via R-R). `with_stage_output(stage_k, ...)` raises
  `ContractViolationError` unless the owned field of stage k−1 in
  `PRE_EXECUTION_SEQUENCE` is already set. This makes out-of-order or partial
  hand-built states impossible.
- Scenario API (implement exactly): `make_scenario(mutation="R", risk=0.1,
  risk_floor=None, risk_rule=None, risk_implied=None, cost=1, steps=1,
  graph="simple", confidence=0.95, capabilities=1) -> Scenario`. It configures the
  fixture capability registry (CapabilityMetadata with `mutation`, `cost` and
  risk components; when only `risk` is given, all three components equal `risk`),
  the binding rows, and the mock LLM response (intent, confidence, step count).
  `tamper(state, **fields) -> PipelineState` (in `tests/fixtures/states.py`) wraps
  `dataclasses.replace` for negative tests only; tests that use it must have
  `tampered` in their name.
- Stage unit tests build their input with
  `tests/fixtures/states.py::state_ready_for(stage_id, scenario="read_low_risk")`,
  which runs the real handlers up to the previous stage. Scenarios are defined once
  in `tests/fixtures/scenarios.py` by configuring the fixture registry, bindings and
  mock LLM, never by writing stage outputs: at least `read_low_risk` (R, risk 0.1,
  simple), `write_chain` (W, 3 steps, chain), `delete_high_risk` (D, risk 0.9, cost 6),
  `irreversible` (IRREVERSIBLE), `low_confidence` (confidence 0.4), `complex`
  (7 steps). Only tests of PipelineState itself may call `with_stage_output`
  directly.

R-X. **ExecutionContext conformance.** Field names exactly as DATA_CONTRACTS. Remove
and relocate:
- `raw_input`, `trace`, `created_at`, `updated_at` → `PipelineState.entry_request`
  (S0-owned, R-O) or logging; not the security context.
- `sanitized_input` → S1 output; `intent` → S2 output. LLM-derived or untrusted
  content must never be in ExecutionContext.
- `confirmation_status` → S10 `ConfirmationOutcome`; `execution_mode` → S7
  `PathRoutingResult`; `retry_policy` → `Step.retry_policy`.
Add the missing spec fields: `membership_id`, `actor_type`, `actor_id`,
`idempotency_key`, `resource_scope`, `tags` (S0, from the entry request; if the
entry request lacks a required value, S0 returns DENY `missing_<field>`), `task_id`
(S2), `auth_passed`, `auth_result_id` (S8, R-M). Types and nullability as in
DATA_CONTRACTS; collections immutable (tuple / frozen mapping).

R-Y. **Module-level state (OWN-08).** Module-level constants must be immutable:
lists → tuples, dicts → `types.MappingProxyType({...})`, sets → `frozenset`. This
applies to `STAGE_OUTPUT_FIELD`, `OUTCOME_TO_STATUS`, `STAGE_REGISTRY`,
`INJECTION_PATTERNS`, `_FIELD_TYPE_MODULES`, `_FIELD_TYPE_NAMES` and any other
reported name. SQLAlchemy models: replace `Base = declarative_base()` with the
SQLAlchemy 2.0 form `class Base(DeclarativeBase): pass` in each file (one class per
file, same as now, so table metadata is unchanged). `KernelPolicy.metadata` is
removed; if a caller needs extra settings, add named fields instead.

---

## PART 3 — STEPS

### STEP 0 — Build the certification checker (do this first)

**Build.** Create `tools/certify_s0_s11.py`. It runs every check below, prints a table
`ID | check | PASS/FAIL | detail`, and exits 0 only if all pass. It uses Python only
(`ast`, `dataclasses`, `importlib`, `subprocess`, `re`), so it works on Windows.

| ID | Check | How | PASS when |
|---|---|---|---|
| CHK-01 | Legacy symbols gone | regex over `src/` and `tests/` for `StageResult\b`, `_StageHandlerAdapter`, `stage_result_to_pipeline_update`, `_replace_fields` | 0 matches |
| CHK-02 | ExecutionContext fields | import `ExecutionContext`, `dataclasses.fields()` | none of `provider`, `binding_id`, `capability_id`, `kernel_op_id`, `metadata` |
| CHK-03 | PipelineState typing | import `PipelineState`, inspect field annotations | no `dict`, `Dict`, `Any`, `Mapping` in any field annotation |
| CHK-04 | Runtime type guard | call `with_stage_output` with a wrong-typed value and with a non-owner stage | both raise `ContractViolationError` |
| CHK-05 | Stage list | import the runner's stage sequence | exactly `S0`…`S11`, one handler each; no module path containing `lock_acquisition` or `kill_switch` |
| CHK-06 | Kill switch required | `dataclasses.fields(KernelPolicy)` | `kill_switch_engaged` has no default and no default_factory |
| CHK-07 | No safety fallbacks | regex over `src/` | 0 matches for `kill_switch_engaged\s*=\s*False`, `enable_kill_switch` |
| CHK-08 | No hidden globals | AST over `src/` | no `global` statements; no module-level functions named `set_*`; no module-level assignment of a mutable instance (list/dict/set or class instance) other than constants in UPPER_CASE holding tuples/frozensets/str/int |
| CHK-09 | Test fixtures not in src | regex over `src/` | 0 matches for `InMemoryAuthorizationStateProvider`, `AllowAllMutationPolicy` |
| CHK-10 | No `default=str` | regex over `src/` | 0 matches |
| CHK-11 | No skips | regex over `tests/` | 0 matches for `pytest.skip`, `xfail`, `mark.skip` |
| CHK-12 | Required tests exist | `pytest --collect-only -q` | every test ID in Part 5 is present; `test_s8_matrix` has ≥ 40 parametrized cases |
| CHK-13 | Suite green | `pytest -q` | summary contains `passed`, and no `failed`, `error`, `skipped`, `xfailed` |
| CHK-14 | Count | parse collection count | ≥ 185 (baseline commit `d972516`) |
| CHK-15 | Manifests | files exist | `docs/gates/test_manifest_baseline.txt` and `docs/gates/test_manifest_final.txt` |
| CHK-16 | Import paths | regex over `src/` and `tests/` | 0 matches for `from src.` or `import src.` |
| CHK-17 | Contract conformance | parse the ```python blocks in `docs/implementation/DATA_CONTRACTS.md`, extract field names for each class in the R-O table; import the implementation class; compare | field-name sets equal, apart from the R-O approved extensions |
| CHK-18 | Canonical vocabularies | regex over `src/` (excluding S12–S15 packages per R-J) for the non-canonical literals listed in R-P, as quoted strings | 0 matches |
| CHK-19 | Hand-built states | regex over `tests/` excluding `tests/contracts/test_pipeline_state.py` and `tests/fixtures/` | 0 matches for `with_stage_output(` |

**Verify.** Run `python tools/certify_s0_s11.py`. It must run to completion and print
all rows (most will FAIL now; that is expected). Save the output as
`docs/gates/checker_before.txt`.

**Repair.** If the script crashes: fix the script, not the code under test. If an
import path differs from the one assumed, locate the real module with a search and use
it; record the path in a comment.

**Commit** `tools/certify_s0_s11.py` and `checker_before.txt`.

From now on, every step's Verify runs this checker. Each step lists which CHK IDs must
become PASS; rows already PASS must stay PASS.

---

### STEP 0B — Prove the checker can fail (self-test)

A checker that passes broken code is worse than none. Before Step 1, prove every
check detects what it is meant to detect.

**Build.** Add `python tools/certify_s0_s11.py --selftest`. It creates a temporary
directory containing a minimal fake `src/` and `tests/` tree with **one planted
violation per check** (for example a file containing `class StageResult:`, an
`ExecutionContext` dataclass with a `provider` field, a `PipelineState` field typed
`dict`, a `KernelPolicy` with `kill_switch_engaged: bool = False`, a line
`kill_switch_engaged=False`, a module-level `set_breaker()` function and a `global`
statement, a class named `InMemoryAuthorizationStateProvider` in `src/`,
`json.dumps(x, default=str)`, a test with `pytest.skip`). It runs checks CHK-01 to
CHK-11 against that tree and asserts **every one of them reports FAIL**. CHK-12 to
CHK-15 are checked against a planted pytest collection output and a missing manifest.
Then it runs the same checks against a planted **clean** tree and asserts they PASS.

**Verify.** `python tools/certify_s0_s11.py --selftest` exits 0 and prints, for each
CHK ID, "detects violation: yes" and "passes clean tree: yes".

**Then re-validate the real results.** The Step 0 run reported PASS for CHK-01,
CHK-02, CHK-03, CHK-04, CHK-07 and CHK-11, but earlier reports said these were NOT
DONE (a `StageResult` alias in `src/contracts/stage_result.py`, binding fields on
ExecutionContext, no `isinstance` guard, a `kill_switch_engaged=False` fallback in the
S8 handler, a skipped test). For each of those six, paste the evidence that it is
really clean now (file content or search output), or fix the checker so it reports
FAIL. Record the answer per CHK ID.

Also list the 5 tests currently failing (name + first line of the error), and state
whether each was failing before Step 0 (check with `git stash` or at commit
`ef8bb34`). They must all pass by Step 11.

**Repair.** A check that does not detect its planted violation: fix the check
(wrong path, wrong regex, wrong AST node type) and re-run the self-test. The CHK-08
crash (`'Attribute' object has no attribute 'id'`) comes from an assignment target
like `obj.attr = ...`; handle `ast.Attribute` and `ast.Subscript` targets by skipping
them.

**Commit.** From now on, every checker run is preceded by `--selftest`; if the
self-test fails, the checker is fixed before anything else.

---

### STEP 1 — S8 dependencies and kill switch (R-A, R-C)

**Build.** Start from the last commit. If files become inconsistent during this step,
restore them with `git checkout -- <file>` or `git restore <file>` to the last commit
and redo the change. Never delete or rewrite existing S8 tests to "reset" the
package; the test count must not drop.
1. Add the Protocols and `S8Dependencies` (R-C).
2. S8 handler signature: `handle(state: PipelineState, deps: S8Dependencies) -> PipelineState`.
3. Kill-switch block: delete the `if policy is None: policy = KernelPolicy(...)`
   fallback. New logic: `deps.policy is None` → DENY unavailable; read
   `deps.policy.kill_switch_engaged` inside `try`; exception → DENY unavailable;
   `True` → DENY `kill_switch`; `False` → continue; any other value → DENY unavailable.
4. Delete `set_circuit_breaker()` and any module-level breaker instance.
5. Pipeline runner: `build_pipeline(deps: PipelineDependencies)` passes
   `deps.s8` to S8.
6. Create `tests/fixtures/deps.py` with `make_s8_deps(**overrides)` returning
   all-permissive in-memory dependencies, and the in-memory classes.
7. Update every test that calls S8 to pass `make_s8_deps(...)`.

**Verify.** Checker: CHK-06, CHK-07, CHK-08, CHK-09 PASS. `pytest tests/stages -q`
green. These tests exist and pass: `test_kill_switch_engaged_denies`,
`test_kill_switch_policy_missing_denies`, `test_kill_switch_policy_raises_denies`,
`test_kill_switch_evaluated_first` (engaged kill switch plus a failing user check →
reason is `kill_switch`, and the auth provider records zero calls).

**Repair.**
- CHK-08 FAIL on a constant → make it UPPER_CASE and immutable (tuple/frozenset).
- Tests fail with `TypeError: handle() missing deps` → pass `make_s8_deps()`.
- CHK-09 FAIL → move in-memory classes to `tests/fixtures/deps.py`.

**Commit.**

---

### STEP 2 — S8 status checks (R-B, R-D)

**Build.** Rewrite `checks.py` per R-D; implement the 8 rules exactly as in the R-B
table. S8 runs kill switch, then checks 1–8 in order, returns the first DENY, else
`SafetyResult(allowed=True, reason=None, failed_check=None)`. One write per call.

**Verify.** Tests exist and pass:
- `test_status_denials` parametrized over exactly these 6 cases, all IDs present:
  `suspended_tenant`, `deactivated_user`, `revoked_connection`, `expired_connection`,
  `withdrawn_grant`, `out_of_scope_workspace` → DENY with the matching `failed_check`.
- `test_all_checks_pass_allows`.
- `test_s8_write_once_guard` (S8 on a state that already has `safety_result` raises
  the write-once error).
`pytest tests/stages -q` green.

**Repair.**
- An existing test now denies with `<check>_unavailable` → its fixture lacks that
  dependency; use `make_s8_deps()`. Do not change the expected value of a test that
  was asserting ALLOW with valid inputs.
- A test expected ALLOW for a missing ID → that expectation contradicts R-B;
  change it to DENY and cite "Runbook R-B / PIPELINE_STAGES S8 check table" in the report.

**Commit.**

---

### STEP 2A — Contract conformance and fixtures (R-O, R-P, R-Q, R-R, R-S, R-T)

**Build.** In this order, committing after each sub-step:
1. Scenario fixtures and `state_ready_for` (R-T). Convert every stage test outside
   `tests/contracts/test_pipeline_state.py` to use them.
2. Write-order guard in `with_stage_output` (R-T).
3. FrozenBindingIdentity and TaskProfile conformance (R-O). Update S5, S6 and every
   reader.
4. Vocabulary cleanup (R-P).
5. S7 per R-Q; S10 per R-R; S11 per R-S; ValidationResult with `errors`.
6. Add the conformance and vocabulary checks CHK-16 to CHK-19 to the checker, with
   planted violations in `--selftest`.

**Verify.** CHK-16, CHK-17, CHK-18, CHK-19 PASS; all previously passing CHK rows still
PASS; the full suite is green. Tests exist and pass:
- `test_write_order_enforced` (writing S6 before S5 raises).
- `test_s7_routing_table` parametrized over every R-Q row including the
  unmatched case; `test_s7_never_emits_agentic`.
- `test_s10_not_required_writes_outcome`, `test_s10_required_creates_pending_confirmation`
  (asserts plan_id, plan_hash, user_id, conversation_id, expires_at = now + 300 ± 5),
  `test_s10_expired_denies`, `test_s10_wrong_user_denies`,
  `test_s10_wrong_hash_denies`.
- `test_s11_kernel_op_mismatch_denies`, `test_s11_risk_mismatch_denies`,
  `test_s11_empty_plan_denies`, `test_s11_negative_budget_denies`
  (`errors == ("budget_invalid",)`), `test_s11_cycle_denies`,
  `test_s11_unconsumed_confirmation_denies`.
- `test_s6_copies_risk_and_mutations_from_frozen_binding`.

**Repair.**
- Many tests break after the TaskProfile change → they built TaskProfile by hand;
  convert them to `state_ready_for(...)` with a scenario. Do not re-add removed
  fields.
- A scenario cannot be produced (for example no fixture capability with risk 0.9)
  → add it to the fixture registry in `tests/fixtures/`, not to `src/`.
- CHK-17 fails on a field the code needs that the spec lacks → STOP S1 with the
  field, its purpose and the proposed DATA_CONTRACTS addition. Do not add it to
  the allowlist yourself.

**Commit.**

---

### STEP 2B — S7–S11 cross-stage safety (R-M, R-N)

**Build.** Implement R-M in S8 and in the context-replacement mechanism. Implement
R-N in S7, S9, S10, S11. Extend the test fixtures in `tests/fixtures/deps.py` so each
fake records its call arguments: `ConfigurableAuthState.calls` holds
`(method, args)` tuples; `ConfigurableCircuitBreaker.calls` and
`ConfigurableMutationPolicy.calls` likewise.

**Verify.** These tests exist and pass:
- `test_providers_receive_frozen_values`: after an ALLOW, the breaker was called with
  the frozen binding's provider id; `permits` with
  `(frozen_binding.effective_mutation, frozen_binding.effective_risk)`; `has_grant`
  with `frozen_binding.capability_id`; `budget_available` with
  `task_profile.cost`.
- `test_s8_allow_sets_auth_passed` (context replaced; only `auth_passed` and
  `auth_result_id` differ from before S8) and `test_s8_deny_leaves_context_unchanged`.
- `test_s8_writes_only_safety_result_and_context`: every other PipelineState field
  is identical before and after S8.
- `test_s7_unmatched_combination_clarifies` (parametrized over at least:
  confidence 0.6 simple risk 0.2; confidence 0.95 chain risk 0.2; missing confidence)
  and `test_every_executable_path_runs_s8` (FAST and WORKFLOW journeys both produce a
  `safety_result`).
- `test_s9_requires_safety_passed`, `test_s10_requires_safety_passed`,
  `test_s11_requires_safety_passed`: each stage called on a state where S8 denied
  (built by running real S0–S8 with a denying fixture) → DENY `safety_not_passed`,
  and it writes no output of its own.
- `test_manifest_records_auth_result_id`.

**Repair.** If S8 cannot replace the context because `with_stage_output` treats
`execution_context` as write-once for S0 only: add the controlled replacement method
described in B4 (whitelist per stage, S2/S5/S8 only), with its own tests. Do not
loosen write-once for any other field.

**Commit.**

---

### STEP 3 — Stage list and status contract (verification, items 0 and 6)

**Build.** Only if needed: make the runner's stage sequence exactly S0…S11; ensure
every refusal returns `StageStatus.DENY` or `CLARIFY` with a reason and the runner maps
uncaught exceptions to `StageStatus.ERROR` and stops.

**Verify.** CHK-05 PASS. Tests exist and pass: `test_stage_sequence_is_s0_to_s11`,
`test_uncaught_exception_becomes_error_and_stops` (a handler raising `RuntimeError`
→ final status ERROR, no later stage runs), `test_s8_missing_task_profile_denies`.

**Repair.** If CHK-05 fails on a leftover module reference, remove it from the
sequence only; keep the file with a header comment "belongs to S12, not called".

**Commit.**

---

### STEP 4 — ExecutionContext cleanup (R-E, item 3)

**Build.** Remove the 4 fields. Update S5 to write resolution only to
`FrozenBindingIdentity`. Update every reader to use `state.frozen_binding_identity`.
Replace the skipped B5 test with a real one.

**Verify.** CHK-02 PASS, CHK-11 PASS. Tests exist and pass:
`test_no_binding_fields_on_context`, `test_s5_writes_only_policy_version_fields`
(runtime diff of ExecutionContext before/after S5: only the 3 permitted fields may
differ).

**Repair.** `AttributeError: 'ExecutionContext' object has no attribute 'provider'`
→ that code must read `state.frozen_binding_identity.<field>`; change the reader, not
the contract.

**Commit.**

---

### STEP 5 — PipelineState typing (R-F, items 4 and 12) — CHECKPOINT AFTER

**Build.** Implement R-F in `with_stage_output`. Remove any remaining raw dict writes.

**Verify.** CHK-03, CHK-04 PASS. Tests exist and pass:
`test_with_stage_output_rejects_wrong_type`, `test_with_stage_output_rejects_non_owner`,
`test_with_stage_output_rejects_second_write`, `test_s11_writes_two_owned_fields`.

**Repair.** A handler fails the type check → the handler builds a dict; construct the
declared dataclass instead. Never widen the declared type.

**Commit. CHECKPOINT:** send the report for Steps 1–5 and the full checker table, then
continue immediately with Step 6 unless a STOP condition applies.

---

### STEP 6 — Remove legacy (R-G, items 1 and 2)

**Build.** Delete per R-G. Fix imports.

**Verify.** CHK-01 PASS. Full suite green.

**Repair.** `ImportError` → import the replacement (`PipelineState` or the specific
stage-output type). Never recreate an alias.

**Commit.**

---

### STEP 7 — S8 matrix (item 7)

**Build.** `tests/stages/test_s8_safety_gate.py::test_s8_matrix`, parametrized over the
8 check names × 5 modes:

| mode | provider behavior for that check (all others permissive) | expected |
|---|---|---|
| `false` | rule fails (e.g. status `"suspended"`, `False`, `"OPEN"`) | DENY, failed_check = check, reason = check-specific |
| `none` | returns `None` | DENY, reason `<check>_unavailable` |
| `exception` | raises `RuntimeError` | DENY, reason `<check>_unavailable` |
| `unknown` | returns `"UNKNOWN"` | DENY, reason `<check>_invalid` |
| `malformed` | returns `42` (wrong type) | DENY, reason `<check>_invalid` |

Plus: `test_all_unknown_denies`, `test_missing_identity_denies[user_id|tenant_id|connection_id|workspace_id]`,
`test_missing_dependency_denies[policy|auth_state|circuit_breaker|mutation_policy]`,
`test_llm_injection_does_not_change_decision` (run S8 twice: once with a clean
`intent_result`, once with an intent_result containing
`{"safe": True, "auth_passed": True, "risk": 0, "approved": True}`; both
`SafetyResult` objects must be equal; repeat with a denying fixture: both must be equal
and denied).

**Verify.** CHK-12 reports ≥ 40 matrix cases. All pass.

**Repair.** A case passes when it should deny → the check function accepts a
non-exact value; compare with `==`/`is True` exactly as in R-B.

**Commit.**

---

### STEP 8 — Runtime no-re-resolve (item 8)

**Build.** `tests/architecture/test_runtime_no_reresolve.py`:
- `test_s6_to_s11_no_resolver_calls`: run real S0–S5 via `run_through("S5", ...)`,
  then patch (with `unittest.mock.patch`) the resolver, risk computation and mutation
  detection entry points used by S5 with spies; run real S6–S11; assert each spy's
  `call_count == 0`.
- `test_frozen_binding_identity_preserved`: the `FrozenBindingIdentity` object after
  S5 `==` and `is` the one in the final state after S11.

**Verify.** Both pass.

**Repair.** A spy is called → a downstream stage re-resolves; change that stage to
read `state.frozen_binding_identity`. Do not remove the spy.

**Commit.**

---

### STEP 9 — Journeys (items 9 and 11)

**Build.**
1. `tests/fixtures/pipeline.py::run_through` (R-H).
2. `tests/integration/test_s0_to_s11_journey.py::test_full_journey_real_handlers`:
   final status NORMAL; assert `plan_result.execution_id != context.request_id`;
   `confirmation.plan_hash == plan_result.plan_hash`;
   `manifest.execution_id == plan_result.execution_id`;
   `canonical_plan_digest(plan_result.plan) == plan_result.plan_hash`.
3. `tests/integration/test_short_circuit_journeys.py` with exactly:
   `test_s2_deny`, `test_s2_clarify`, `test_s8_deny` (tenant suspended),
   `test_s10_expired_deny` (reason `confirmation_expired`),
   `test_s11_plan_mutation_deny` (mutate the plan after S10 using
   `dataclasses.replace` on a step; S11 → DENY, `execution_manifest is None`).
   Each asserts: final StageStatus, reason, and that no stage after the denying stage
   produced output.

**Verify.** All pass. A grep for `with_stage_output(` in `tests/integration/` returns 0.

**Repair.** S2 cannot produce DENY/CLARIFY with the mock LLM → configure the mock
LLM's canned response for that test; do not bypass S2.

**Commit.**

---

### STEP 10 — Count reconciliation (item 10)

**Build.**
1. `git worktree add ..\baseline_d972516 d972516`; in it run
   `pytest --collect-only -q > ..\1SuperAgents\docs\gates\test_manifest_baseline.txt`;
   then `git worktree remove ..\baseline_d972516`.
2. `pytest --collect-only -q > docs\gates\test_manifest_final.txt`.
3. Write `docs\gates\test_reconciliation.md`: baseline count, final count, list of
   removed test IDs each with reason and replacement, count of added tests.
4. Rename `CERTIFICATION_REPORT.md` (the void one) to `CERTIFICATION_REPORT_VOID.md`
   if it still exists.

**Verify.** CHK-14, CHK-15 PASS. `baseline + added − removed = final` holds.

**Commit.**

---

### STEP 11 — Certify

**Build.** Run `python tools/owner_certify.py --selftest` then
`python tools/owner_certify.py > docs\gates\owner_certify_final.txt`.

**Verify.** Self-test OK on every row; the certifier exits 0 with every OWN row PASS;
`git diff --stat` shows no change to `tools/owner_certify.py` since the owner
committed it.

**Repair.** Any FAIL → go back to the step that owns that CHK ID, apply its Repair,
re-run. Three failed attempts → STOP S3.

**Commit, then write** `docs\gates\S0_S11_CERTIFICATION_REPORT.md`:

```text
S0–S11 CERTIFICATION
Owner certifier: N/N PASS (docs/gates/owner_certify_final.txt), self-test OK
pytest: <raw summary line>
Count: baseline 185 + added N − removed M = final F (docs/gates/test_reconciliation.md)
Rejection-list items 0–14: each DONE, with the step and test that proves it
Open questions recorded: <list from register>
Commit: <hash>
Final: S0–S11 CERTIFIED
```

Then `git tag s0-s11-certified` and stop. Do not begin S12.

---

## PART 4 — TROUBLESHOOTING (symptom → cause → exact fix)

| Symptom | Cause | Fix |
|---|---|---|
| `ContractViolationError: write-once` in a test | The test pre-fills a field the stage under test writes | Build the state with `run_through(<previous stage>)`; never pre-fill |
| `ContractViolationError: write-once` in a handler | Handler writes the same field twice | Return immediately after the first write |
| `ContractViolationError: expected <Type>, got dict` | Handler builds a dict | Construct the declared dataclass |
| S8 returns `<check>_unavailable` in a test expecting ALLOW | Missing dependency in the fixture | Use `make_s8_deps()` |
| `AttributeError` on a removed ExecutionContext field | Reader not migrated | Read `state.frozen_binding_identity` |
| Test order changes results | Shared state between tests | Build dependencies per test; CHK-08 finds the global |
| Hash mismatch between test and handler | Test computes its own hash | Call `canonical_plan_digest()` |
| `TypeError` from `canonical_plan_digest` | Unsupported type in Plan | Convert at construction in S9 to a supported type; never add `default=str` |
| pytest summary shows `skipped` | A skip or conditional skip exists | Remove it and make the test pass |
| Count drops | A test was deleted or merged | Restore coverage; name it in the report |

---

## PART 5 — REQUIRED TEST IDS (checked by CHK-12)

```text
tests/stages/test_s8_safety_gate.py::test_kill_switch_engaged_denies
tests/stages/test_s8_safety_gate.py::test_kill_switch_policy_missing_denies
tests/stages/test_s8_safety_gate.py::test_kill_switch_policy_raises_denies
tests/stages/test_s8_safety_gate.py::test_kill_switch_evaluated_first
tests/stages/test_s8_safety_gate.py::test_status_denials            (6 cases)
tests/stages/test_s8_safety_gate.py::test_all_checks_pass_allows
tests/stages/test_s8_safety_gate.py::test_s8_write_once_guard
tests/stages/test_s8_safety_gate.py::test_s8_matrix                 (≥ 40 cases)
tests/stages/test_s8_safety_gate.py::test_all_unknown_denies
tests/stages/test_s8_safety_gate.py::test_missing_identity_denies   (4 cases)
tests/stages/test_s8_safety_gate.py::test_missing_dependency_denies (4 cases)
tests/stages/test_s8_safety_gate.py::test_llm_injection_does_not_change_decision
tests/stages/test_s8_safety_gate.py::test_s8_missing_task_profile_denies
tests/stages/test_s8_safety_gate.py::test_providers_receive_frozen_values
tests/stages/test_s8_safety_gate.py::test_s8_allow_sets_auth_passed
tests/stages/test_s8_safety_gate.py::test_s8_deny_leaves_context_unchanged
tests/stages/test_s8_safety_gate.py::test_s8_writes_only_safety_result_and_context
tests/stages/test_s8_safety_gate.py::test_connection_expired_denies
tests/stages/test_s8_safety_gate.py::test_kill_switch_invalid_value_denies     (values: None, "yes", 1)
tests/stages/test_s8_safety_gate.py::test_first_failure_stops_evaluation
tests/stages/test_s7_path_routing.py::test_s7_unmatched_combination_clarifies
tests/integration/test_s0_to_s11_journey.py::test_every_executable_path_runs_s8
tests/stages/test_s7_to_s11.py::test_s9_requires_safety_passed
tests/stages/test_s7_to_s11.py::test_s10_requires_safety_passed
tests/stages/test_s7_to_s11.py::test_s11_requires_safety_passed
tests/stages/test_s7_to_s11.py::test_manifest_records_auth_result_id
tests/contracts/test_pipeline_state.py::test_write_order_enforced
tests/stages/test_s7_path_routing.py::test_s7_routing_table
tests/stages/test_s7_path_routing.py::test_s7_never_emits_agentic
tests/stages/test_s6_task_profile.py::test_s6_copies_risk_and_mutations_from_frozen_binding
tests/stages/test_s6_task_profile.py::test_s6_confirmation_table      (10 cases)
tests/stages/test_s7_path_routing.py::test_s7_threshold_unavailable_denies
tests/stages/test_s9_plan_creation.py::test_s9_plan_shape
tests/stages/test_s9_plan_creation.py::test_s9_uses_frozen_risk_when_task_profile_tampered
tests/stages/test_s9_plan_creation.py::test_s9_plan_hash_changes_with_execution_inputs
tests/stages/test_s10_confirmation.py::test_s10_not_required_writes_outcome
tests/stages/test_s10_confirmation.py::test_s10_required_creates_pending_confirmation
tests/stages/test_s10_confirmation.py::test_s10_expired_denies
tests/stages/test_s10_confirmation.py::test_s10_wrong_user_denies
tests/stages/test_s10_confirmation.py::test_s10_wrong_hash_denies
tests/stages/test_s11_plan_validation.py::test_s11_kernel_op_mismatch_denies
tests/stages/test_s11_plan_validation.py::test_s11_risk_mismatch_denies
tests/stages/test_s11_plan_validation.py::test_s11_empty_plan_denies
tests/stages/test_s11_plan_validation.py::test_s11_negative_budget_denies
tests/stages/test_s11_plan_validation.py::test_s11_cycle_denies
tests/stages/test_s11_plan_validation.py::test_s11_unconsumed_confirmation_denies
tests/architecture/test_pipeline_runner.py::test_stage_sequence_is_s0_to_s11
tests/architecture/test_pipeline_runner.py::test_uncaught_exception_becomes_error_and_stops
tests/contracts/test_execution_context_protection.py::test_no_binding_fields_on_context
tests/contracts/test_execution_context_protection.py::test_s5_writes_only_policy_version_fields
tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_wrong_type
tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_non_owner
tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_second_write
tests/contracts/test_pipeline_state.py::test_s11_writes_two_owned_fields
tests/architecture/test_runtime_no_reresolve.py::test_s6_to_s11_no_resolver_calls
tests/architecture/test_runtime_no_reresolve.py::test_frozen_binding_identity_preserved
tests/integration/test_s0_to_s11_journey.py::test_full_journey_real_handlers
tests/integration/test_short_circuit_journeys.py::test_s2_deny
tests/integration/test_short_circuit_journeys.py::test_s2_clarify
tests/integration/test_short_circuit_journeys.py::test_s8_deny
tests/integration/test_short_circuit_journeys.py::test_s10_expired_deny
tests/integration/test_short_circuit_journeys.py::test_s11_plan_mutation_deny
```

Existing tests with other names that cover the same behavior may be renamed to these
IDs. Existing plan-hash, confirmation and S6 confirmation-table tests remain and must
stay green.


---

## PART 6 — EXACT TEST CODE (copy; do not reinterpret)

Use normal imports at the top of each file (`from engine.stages.s6_task_profile_assembly
import handler as s6`); never `__import__(...)` inside tests. Delete the existing tests
these replace; record them in the report as replaced.

### 6.1 `tests/stages/test_s6_task_profile.py`

```python
import asyncio
import pytest
from engine.stages.s6_task_profile_assembly import handler as s6
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import state_ready_for

CASES = [  # id, mutation, risk, cost_per_step, steps, expected
    ("irreversible",            "IRREVERSIBLE", 0.1, 1, 1, True),
    ("delete_cost_6",           "D",            0.3, 6, 1, True),
    ("delete_cost_5_confirmed", "D",            0.3, 5, 1, True),    # R-V amended: D is always confirmed
    ("delete_cost_1_low_risk", "D",            0.1, 1, 1, True),
    ("write_cost_6_not_delete", "W",            0.3, 6, 1, False),
    ("total_cost_21",           "W",            0.3, 7, 3, True),
    ("total_cost_20_boundary",  "W",            0.3, 5, 4, False),
    ("risk_0_8",                "R",            0.8, 1, 1, True),
    ("risk_0_7_boundary",       "R",            0.7, 1, 1, False),
    ("nothing_triggers",        "R",            0.3, 1, 1, False),
]

@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_s6_confirmation_table(case):
    _, mutation, risk, cost, steps, expected = case
    sc = make_scenario(mutation=mutation, risk=risk, cost=cost, steps=steps,
                       graph="simple" if steps == 1 else "chain")
    state = state_ready_for("S6", sc)
    tp = asyncio.run(s6.handle(state)).task_profile
    fb = state.frozen_binding_identity
    assert tp.requires_confirmation is expected
    assert tp.cost == cost * steps
    assert tp.risk == fb.effective_risk
    assert tuple(tp.mutations) == (fb.effective_mutation,) * steps

def test_s6_copies_risk_and_mutations_from_frozen_binding():
    sc = make_scenario(mutation="D", risk_floor=0.2, risk_rule=0.9, risk_implied=0.1)
    state = state_ready_for("S6", sc)
    fb = state.frozen_binding_identity
    assert fb.effective_risk == 0.9          # proves the scenario is effective
    tp = asyncio.run(s6.handle(state)).task_profile
    assert (tp.risk, tuple(tp.mutations)) == (0.9, ("D",))
```

### 6.2 `tests/stages/test_s7_path_routing.py`

```python
import asyncio
import pytest
from contracts.safety import PathDecision   # spec enum (adjust module if different)
from engine.stages.s7_path_routing import handler as s7
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import state_ready_for

ROUTES = [  # id, scenario kwargs, expected decision, expected reason
    ("fast",            dict(risk=0.2, steps=1, graph="simple", confidence=0.95), PathDecision.FAST, None),
    ("simple_risky",    dict(risk=0.6, steps=1, graph="simple", confidence=0.95), PathDecision.WORKFLOW, None),
    ("chain",           dict(risk=0.2, steps=3, graph="chain",  confidence=0.8),  PathDecision.WORKFLOW, None),
    ("chain_high_risk", dict(risk=0.9, steps=2, graph="chain",  confidence=0.8),  PathDecision.WORKFLOW, None),
    ("above_threshold", dict(risk=0.97, steps=1, graph="simple", confidence=0.95), PathDecision.DENY, "risk_above_threshold"),
    ("low_confidence",  dict(risk=0.2, steps=1, graph="simple", confidence=0.4),  PathDecision.CLARIFY, "low_confidence"),
    ("mid_confidence",  dict(risk=0.2, steps=1, graph="simple", confidence=0.6),  PathDecision.CLARIFY, "unmatched_route"),
    ("complex",         dict(risk=0.2, steps=7, graph="complex", confidence=0.95), PathDecision.CLARIFY, "complex_not_supported"),
    ("six_steps_chain", dict(risk=0.2, steps=6, graph="chain",  confidence=0.95), PathDecision.CLARIFY, "complex_not_supported"),
    ("multi_capability",dict(risk=0.2, steps=2, graph="chain",  confidence=0.95, capabilities=2), PathDecision.CLARIFY, "multi_capability_not_supported"),
]

@pytest.mark.parametrize("case", ROUTES, ids=[c[0] for c in ROUTES])
def test_s7_routing_table(case):
    _, kwargs, decision, reason = case
    state = state_ready_for("S7", make_scenario(**kwargs))
    out = asyncio.run(s7.handle(state)).path_decision
    assert (out.decision, out.reason) == (decision, reason)

def test_s7_never_emits_agentic():
    for _, kwargs, _, _ in ROUTES:
        out = asyncio.run(s7.handle(state_ready_for("S7", make_scenario(**kwargs)))).path_decision
        assert out.decision != PathDecision.AGENTIC
```

Add `test_s7_threshold_unavailable_denies` (policy without `risk_deny_threshold`
→ deny `risk_threshold_unavailable`). If S7 receives the policy through dependencies,
use the same injection pattern as S8.

### 6.3 `tests/stages/test_s9_plan_creation.py`

```python
import asyncio
import dataclasses
import uuid
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import PlanCreationResult
from engine.stages.s9_plan_creation import handler as s9
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import state_ready_for, tamper

def test_s9_plan_shape():
    state = state_ready_for("S9", make_scenario(mutation="W", risk=0.2, steps=3,
                                                graph="chain", confidence=0.8))
    out = asyncio.run(s9.handle(state)).get_stage_output("S9")
    fb, ctx = state.frozen_binding_identity, state.execution_context
    assert isinstance(out, PlanCreationResult)
    uuid.UUID(out.execution_id); uuid.UUID(out.plan.id)
    assert out.execution_id != ctx.request_id
    assert out.plan.join_mode == "all"
    assert len(out.plan.steps) == 3
    for i, step in enumerate(out.plan.steps):
        assert (step.kernel_op_id, step.risk, step.mutation) == (
            fb.kernel_op_id, fb.effective_risk, fb.effective_mutation)
        assert tuple(step.depends_on) == (() if i == 0 else (out.plan.steps[i - 1].id,))
    assert out.plan_hash == canonical_plan_digest(out.plan)

def test_s9_uses_frozen_risk_when_task_profile_tampered():
    state = state_ready_for("S9", make_scenario(mutation="D", risk_floor=0.2,
                                                risk_rule=0.9, confidence=0.95))
    assert state.frozen_binding_identity.effective_risk == 0.9
    state = tamper(state, task_profile=dataclasses.replace(state.task_profile, risk=0.1))
    out = asyncio.run(s9.handle(state)).get_stage_output("S9")
    assert all(step.risk == 0.9 for step in out.plan.steps)

def test_s9_plan_hash_changes_with_execution_inputs():
    a = asyncio.run(s9.handle(state_ready_for("S9", make_scenario(steps=1)))).get_stage_output("S9")
    b = asyncio.run(s9.handle(state_ready_for("S9", make_scenario(steps=2, graph="chain",
                                                                    confidence=0.8)))).get_stage_output("S9")
    assert a.plan_hash != b.plan_hash
```

A scenario with risk 0.9 reaches S8/S9 only because of R-Q row 8 and the fixture
`risk_deny_threshold` of 0.95. If `state_ready_for("S9", ...)` stops early, print the
final StageStatus and reason of the partial run; that tells you which stage refused.

### 6.4 S10 and S11

Use `state_ready_for("S10", make_scenario(mutation="D", risk=0.9, steps=2,
graph="chain", confidence=0.8))` for required-confirmation tests and
`make_scenario()` (defaults) for not-required. S11 negative cases use `tamper` on the
S9 output (`plan_result=dataclasses.replace(...)`) and are named `*_tampered` where
applicable; each asserts `(validation_result.is_valid, validation_result.errors,
execution_manifest)` equals `(False, ("<code>",), None)` with the R-S code.

---

## PART 7 — GOLDEN TEST AMENDMENTS (owner instruction; the test files are authoritative)

The golden tests were rewritten to match the amended rulings and the production behaviour
(R-V amended, S0.1, suspended runs and the confirmation reply, registry-sourced binding data).
Each golden file's header records its amendments. The pins in `docs/gates/spec_pins.sha256`
for these six files must be regenerated by the owner after any amendment.

| file | added / changed |
|---|---|
| `test_s6_task_profile.py` | `delete_cost_5_boundary` → `delete_cost_5_confirmed` (True); `delete_cost_1_low_risk`; D/IRREVERSIBLE confirmed at any cost and risk; missing or mismatched capability metadata → DENY `capability_metadata_missing`, nothing written; NORMAL status |
| `test_s7_path_routing.py` | strict `>` at the threshold (`just_above_threshold` deny, `at_threshold_is_not_denied` workflow); stage status follows the decision; threshold read from policy only |
| `test_s9_plan_creation.py` | step costs = task cost / steps and add up to `budget_reserved`; single-step cost; NORMAL status, no confirmations on the plan |
| `test_s10_confirmation.py` | status NORMAL / CLARIFY `confirmation_required`; tenant-bound consume; reject only by its user then unusable; resume uses the replying user, once; resume after expiry → `confirmation_expired` |
| `test_s11_plan_validation.py` | manifest versions from the frozen binding and `policy_version_id`; DENY status/reason; unknown dependency and duplicate step ids → `dag_invalid`; consumed confirmation for this plan allows the manifest, for another plan → `confirmation_mismatch` |
| `test_s7_to_s11.py` | `auth_result_id` is a UUID set only on allow; no stage after a refused gate writes anything |

| `test_s0_activation.py` (new golden) | R-AA S0.1: reason table (tenant/workspace pause, scheduled activation, first match wins, `paused_until == now` is not paused), nothing after S0, denied before the run scope is read, fail closed (unreadable state, missing reader), a pause also blocks the reply to a waiting confirmation |
| `test_s2_intent_validation.py` (new golden) | S2 validation: valid answer + `task_id`; invalid answers retried once with feedback then CLARIFY `intent_unparseable`; an intent the registry never offered is rejected; `unknown` → CLARIFY, `prohibited` → DENY; model failure → ERROR `llm_unavailable`; no text → CLARIFY without calling the model; the model cannot change risk, mutation or capabilities |
| `test_stage_event_log.py` (new golden, `tests/architecture/`) | one event per stage in order with trace/request/tenant ids; no user text in the log; denials recorded with reason; S0.1 recorded as `S0.1`; an unrecordable stage stops the run (ERROR `ledger_unavailable`) before the next stage; a refusal stays a refusal when the ledger is down; confirmation pause and reply steps recorded |
| `test_m2a_chain.py` (new golden) | M2a heterogeneous chains (R-AB…R-AL, `docs/proposals/M2_RULINGS.md`): per-step bindings with the singular fields None; each step carries its own operation, mutation, risk, cost, parameters and inverse; profile risk = max, cost = sum; 5-step cap counting item expansion; items expand N + N; 0.85 confidence floor; ambiguous candidates → CLARIFY `ambiguous_capability`; 3+ providers, any D/IRREVERSIBLE step or cost > 20 → confirmation listing every operation with its parameters and `undoable`; S8 checks every step's grant, breaker and mutation policy and the plan's total budget; S11 refuses a step that differs from its own binding even when `plan_hash` was recomputed, swapped, missing or extra steps; the suspended chain holds no intent parameters and resumes after a confirmed reply |

Spec text amended with R-V: the "Confirmation Requirements" row "Any D mutation with cost > 5" now
reads "Any D mutation (always, whatever the cost; amended — R-V)" in DATA_CONTRACTS §7,
FINAL_ARCHITECTURE, MUTATION_SAFETY and PIPELINE_STAGES §7; `docs/implementation/README.md` marks
the conflict resolved. These five pinned specs, and the three new golden files, need pin lines.

R-O extension (owner-authorised for M2a): `FrozenBindingIdentity.inverse_kernel_op_id` (the kernel op that undoes this one, from the registry; R-AF) is added to the certifier's `CONTRACTS` approved-extension list for `FrozenBindingIdentity`. `test_m2a_chain.py` and its fixture `tests/fixtures/multi.py` are pinned.

Source fixes found while amending: S6 no longer assumes cost 1 without metadata (R-V); S9 step
costs were a constant 1 while the reserved budget was the task total.
