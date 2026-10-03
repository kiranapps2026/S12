# S0–S15 stage reference: logic, what works, limits, inconsistencies

One section per pipeline stage and per S12–S15 component, as the code stands at certification (`ee9c334`, M21 green
`3c2a515`). Every statement was checked in the code; the evidence column names the file or the tests. Gaps point to
`S12_DEFERRED_REGISTER.md` (`DR-nn`); report items point to `S12_CERTIFICATION_REPORT.md`.

**Legend.** **Works** = implemented and covered by tests that pass. **Limit** = a known limitation of this phase.
**Inconsistency** = two parts of the code or docs disagree, or a record says one thing and the code another.

## 0. The whole path in one view

```text
HTTP POST /execute (API key → principal)                        engine/control_plane/api.py
  S0 entry → S1 normalize → S2 intent (LLM) → S3 discovery → S4 graph → S5 binding (frozen)
  → S6 task profile → S7 path → S8 safety gate → S9 plan → S10 confirmation → S11 validation (manifest)
  └─ the API stops here and returns {trace_id, execution_id, status, final_stage, reason, confirmation_id}

NOT WIRED (DR-48): S11 manifest → S12 entry (admit_run) → durable run
S12 step loop (per step): live check → admission → eligibility/selection/lease → budget reserve → pre-flight
  → RUNNING + budget lock → attempts [live check → ledger → dispatch marker → guarded adapter call → retry]
  → probe on uncertainty (S13) → verification (S13) → commit / release → checkpoint → lease release
S13 consolidation → S14 dead letter (record, retry, operator, rollback) → S15 response (envelope)
NOT WIRED (DR-14, DR-49): a Worker Runtime that runs admitted runs; an endpoint that returns the S15 envelope
```

The certified kernel (S12–S15) is complete and exercised end to end by the goldens (M21 journeys), but in the
application it is reachable only from tests: the API runs S0–S11, and nothing admits, runs or reports a run (DR-14,
DR-48, DR-49).

## 1. Summary matrix

| Stage / component | Status | Tests | Main limits (register) |
|---|---|---|---|
| S0 entry | works | `tests/stages/test_s0*` 28 | — |
| S1 normalize | works | `test_s1*` 46 | regex-based injection detection only |
| S2 intent (LLM) | works | `test_s2*` 20, `llm/` 19 | one model, no fallback (DR-50); parameters free-form |
| S3 discovery | works | `test_s3*` 6 | lexical scoring |
| S4 graph | works with a defect | `test_s4*` 5, `m2a` 44 | **single-capability plans lose all parameters (DR-39)** |
| S5 binding | works | `test_s5*` 9 | — |
| S6 task profile | works | `test_s6*` 14 | risk 0.7 boundary differs from S13 (DR-51) |
| S7 path | works | `test_s7*` 36 | FAST vs WORKFLOW has no effect downstream (DR-52) |
| S8 safety gate | works | `test_s8*` 105 | a connection is required even for reads (DR-53) |
| S9 plan | works | `test_s9*` 6 | — |
| S10 confirmation | works | `test_s10*` 11, M5 30 | — |
| S11 validation | works | `test_s11*` 14 | no parameter / input-schema validation (DR-04) |
| API → S12 handoff | **missing** | — | DR-48 |
| S12 entry | works | M6 23 | not called by the application (DR-48) |
| S12 loop | works | M12 33, M7–M11, M13–M14 | sequential; event-driven flag hard-coded (DR-54) |
| Admission control | works with a defect | M8 40, M21 | 7 of 11 gates have no source (DR-26); budget gate defect (DR-55) |
| Eligibility / selection / leases | works | M8a 49, M7 15 | locality + free capacity only (DR-56) |
| Budget | works | M9 17 | — |
| Guard / adapters | works (mock) | M10 64 | one adapter per guard (DR-42); mock only (DR-38) |
| Idempotency / retry | works | M11 46 | global ledger key (DR-10) |
| Probe (S13) | works | M13 13 | — |
| Verification (S13) | works | M15 51 | no production semantic assessor (DR-21) |
| Consolidation (S13) | works | M16 31 | — |
| Dead letter / operator / rollback (S14) | works | M17 37, M21 | operator has no HTTP route (DR-57) |
| S15 response | works | M18 19 | no step data (DR-40); not served (DR-49) |
| Recovery / renewal / multi-runtime | works | M19 44, M20 12 | no runtime runs the sweeper (DR-14) |
| `tests_postgres` (S0–S11 integration) | **partly broken** | 294 pass | 2 files cannot import (CONF-035 not applied, DR-58); 1 stale audit (DR-59) |

## 2. Pre-execution pipeline (S0–S11, certified at `s0-s11-certified`, frozen in this phase)

### S0 entry (`engine/stages/s0_entry/handler.py`)
- **Logic.** The only place an `ExecutionContext` is created. `tenant_id`, `workspace_id` and `user_id` are required:
  any missing → DENY `missing_<field>`. It generates `trace_id`; `request_id` comes from the entry or a UUID;
  `conversation_id` is never empty (R-BA). The event id becomes `task_id` for event-driven runs. The context is
  frozen after S0 (only the policy-version fields may be added). The S0.1 activation check (tenant/workspace pause)
  lives in `activation.py`.
- **Works.** 28 stage tests; architecture tests forbid binding fields on the context.
- **Limits.** None found.

### S1 normalize (`s1_normalize/`)
- **Logic.** Limits first: 8,000 characters per string, 65,536 per payload, nesting depth 10 → DENY
  `input_too_large` / `invalid_characters`. Then control-character stripping, then reference resolution (CLARIFY
  `unresolved_reference`; ERROR `reference_source_unavailable`), then `DataSanitizer` last, over the resolved text
  (DENY `injection_detected` on a CRITICAL pattern; HIGH patterns are sanitised). A stop writes an empty
  `NormalizedInput`: nothing of the payload is kept.
- **Works.** 46 tests.
- **Limit.** Injection detection is pattern-based (regex plus evasion forms). It is a filter, not a guarantee; S2
  treats the model's answer as untrusted anyway.

### S2 intent analysis (`s2_intent_analysis/handler.py`, `adapters/llm/deepseek.py`)
- **Logic.** The only LLM call. The model sees the registry's known intents and answers JSON, which is untrusted:
  - the intent must be a known intent, `unknown` or `prohibited` (lowercase identifier);
  - the confidence must be a number in [0, 1];
  - `parameters` must be a JSON object.
  - An invalid answer is retried once with feedback (2 attempts) → CLARIFY `intent_unparseable`.
  - `unknown` → CLARIFY; `prohibited` → DENY.
  - Multi-step answers: at most 5 steps (items included); 2,000 characters of parameters per step.
  - The model can only narrow what happens, never add a capability or change risk or mutation.
- **Works.** 20 stage tests, 19 adapter tests; live tests in `tests_live` / `tests_postgres` need a key.
- **Limits.**
  - One provider (DeepSeek), no fallback model, no evaluation harness (DR-50).
  - `parameters` are free-form keys in the user's words, with no schema (DR-04). The adapters must map them
    (adapter package v2 does).

### S3 capability discovery (`s3_capability_discovery/handler.py`)
- **Logic.** Candidates come only from the registry; inactive capabilities never match. Scoring is lexical: intent
  and operations against capability tags/names, plus the parameter text. Ties break by capability id. No candidate
  → CLARIFY `no_capability`; registry failure → DENY. The LLM never adds or describes a capability.
- **Works.** 6 tests, plus M2a chain tests.
- **Limit.** Lexical scoring; `candidate_count > 1` for one intent sends S7 to CLARIFY (alternatives are not chosen
  among).

### S4 graph classification (`s4_graph_classification/handler.py`)
- **Logic.**
  - Multi-capability (more than one intent step): `_expand_steps` keeps each intent step's `parameters`. `items`
    become one step per item `{..., "item": item}`; `depends_on` is the previous step.
  - Single capability: `_build_execution_steps` builds 1 step (simple) or N linear steps from `items`.
  - Complexity: 1 step simple, 2–5 chain, 6 or more complex.
- **Works.** 5 tests; M2a 44.
- **Inconsistency / defect (DR-39).** On the single-capability path every step gets **`params: {}`**: S2's
  `parameters` (and each item's content) are dropped. Reproduced with the real S0–S9 stages (adapter package test
  `test_adapter_pipeline_fit`). Only multi-capability chains carry values. The kernel tests never noticed, because
  the mock adapter accepts empty params.

### S5 provider resolution (`s5_provider_resolution/handler.py`)
- **Logic.** The single source of `effective_risk` and `effective_mutation`. It reads the binding rows from the
  registry and freezes `FrozenBindingIdentity` (provider, adapter class, kernel op, versions, inverse). No active
  binding, an incomplete binding or a non-canonical mutation → DENY. Missing policy versions → DENY.
- **Works.** 9 tests; architecture tests forbid re-resolution after S5 (`test_runtime_no_reresolve`).

### S6 task profile (`s6_task_profile_assembly/handler.py`)
- **Logic.** Reads risk and mutation from the frozen binding (never recomputes).
  - Single capability: confirmation if D/IRREVERSIBLE, or `effective_risk > 0.7`, or total cost > 20.
  - Chain: confirmation also when it spans ≥ 3 providers.
  - Missing capability metadata → DENY `capability_metadata_missing` (an unknown cost is never cheap).
- **Works.** 14 tests.
- **Inconsistency (DR-51).** Confirmation needs risk **> 0.7**; S13 requires the semantic layer at risk **≥ 0.7**
  (`SEMANTIC_RISK`). A step at exactly 0.7 runs without confirmation yet needs a semantic assessor, which does not
  exist (DR-21), so it dead-letters.

### S7 path decision (`s7_path_decision/handler.py`)
- **Logic.** R-Q table, first match wins:
  1. no risk threshold → DENY;
  2. risk above the tenant threshold → DENY;
  3. no capability → CLARIFY;
  4. more than one candidate → CLARIFY (`ambiguous_capability` / `multi_capability_not_supported`);
  5. confidence < 0.5 → CLARIFY (multi-step below a higher floor);
  6. complex, or 6 or more steps → CLARIFY;
  7. FAST: simple, 1 step, confidence ≥ 0.9, risk ≤ 0.3;
  8. WORKFLOW: simple/chain, 1–5 steps, confidence ≥ 0.7;
  9. otherwise CLARIFY `unmatched_route`.
- **Works.** 36 tests.
- **Limit (DR-52).** FAST and WORKFLOW lead to the same S9–S12 behaviour (only AGENTIC changes S9's branch id), so
  the distinction is informational today.

### S8 safety gate (`s8_safety_gate/`)
- **Logic.** Kill switch first, then 8 checks in order: `user_active`, `tenant_active`, `connection_active`,
  `capability_granted`, `resource_scope`, `circuit_breaker`, `budget_available`, `mutation_safety`. Every check
  fails closed (`_missing_id` / `_unavailable` / `_invalid` / `_denied`). On ALLOW it sets `auth_passed` and
  `auth_result_id` on the context (R-M).
- **Works.** 105 tests; the same check functions are reused by M14's live re-check (logic exists once).
- **Limit (DR-53).** `connection_active` applies to every request, reads included: a user without an active
  connection cannot even read. Verified: a write with no connection is denied `connection_active_missing_id`.

### S9 plan creation (`s9_plan_creation/handler.py`)
- **Logic.** New `execution_id` and `plan_id` (distinct from `request_id`).
  - Chain: one step per binding, each with its own operation, mutation, risk, inverse, registry cost and S4
    params.
  - Single: steps from S4 (see DR-39).
  - `plan_hash` = SHA-256 of the canonical digest.
  - No budget reservation, no locks (S12's job).
- **Works.** 6 tests, plan-hash architecture tests (25).
- **Limit.** `Step.timeout` is never set (default 30 s), and the catalog's `timeout_seconds` is ignored (DR-16).

### S10 confirmation (`s10_confirmation/handler.py`)
- **Logic.** If confirmation is required, a pending confirmation (plan_id, plan_hash, user, conversation; expires in
  300 s) is saved with tenant and execution id, and the run stops CLARIFY `confirmation_required`. The confirmed
  re-entry (`resume_confirmation`) must conditionally consume it before S11: expired → DENY; wrong user or hash →
  DENY `confirmation_mismatch`. Chains show every step.
- **Works.** 11 tests; PostgreSQL store with exactly one concurrent winner (M5, 30 cases).
- **Limit.** The store's consume/expire/reject lack a `tenant_id` predicate (DEF-003, DR-09); RLS is the control.

### S11 plan validation (`s11_plan_validation/handler.py`)
- **Logic.** In order, first failure decides:
  1. every step equals its frozen binding → `binding_mismatch`;
  2. digest equals `plan_hash` → `plan_hash_mismatch`;
  3. a required confirmation was consumed with a matching hash → `confirmation_mismatch`;
  4. `budget_reserved ≥ 0` → `budget_invalid`;
  5. acyclic dependencies → `dag_invalid`;
  6. at least one step → `plan_empty`.

  On success it issues the `ExecutionManifest`.
- **Works.** 14 tests.
- **Limit (DR-04).** Step parameters are not validated: there is no kernel input schema.

### API and composition (`engine/control_plane/api.py`, `bootstrap.py`, `main.py`)
- **Works.**
  - Identity comes only from the API key; the body cannot override it. 503 without a pipeline, 401 on bad auth.
  - Webhook, MCP and event sources, and the confirmation reply, are wired.
  - The admin APIs cover API keys, endpoints, workspaces, users, memberships, connections, capabilities and grants.
- **Gaps.**
  - `/execute` runs S0–S11 only, and nothing calls S12 entry (DR-48).
  - No route returns the S15 envelope or a run's status (DR-49).
  - `main.py --worker` is a stub (DR-14).
  - The dead-letter operator has no route (DR-57).

## 3. S12 entry (`engine/stages/s12_entry/`, `adapters/postgres/admission.py`)
- **Logic.** `admit_run` runs the §7.1 checks (pure, nothing written), then durable admission (§7.2). Checks in
  order:
  1. S11 issued the manifest;
  2. 1a: every NOT NULL run value is present (C33);
  3. S8 authorised (never re-authorise);
  4. frozen binding(s) present;
  5. `join_mode == "all"` (D3);
  6. plan digest equals both hashes;
  7. 5a: no step consumes another's output (C36, broad regex) → `data_flow_unsupported`;
  8. 5b: each distinct binding row, read once, still at the manifest's version;
  9. item 6: verifiers built (D1; every W/D/IRREVERSIBLE needs an observation method, else
     `verifier_metadata_unavailable`);
  10. item 7: the pause safety net at database time;
  11. C20: a consumed confirmation must belong to this run.

  Admission then writes the run, steps, plan, frozen bindings, verifiers and ownership in one transaction.
- **Works.** M6 23, M5 30 (confirmation), plus the entry-denial envelope (CONF-020, M18).
- **Limits.**
  - Not called by the application (DR-48).
  - The C36 check is a broad regex: a parameter that merely looks like `step-1.output` is denied.
  - CONF-008: a catalog version bump denies plans awaiting confirmation (DR-15).

## 4. S12 step loop (`s12_execute/loop.py`, gate §8)

| Step | Logic | Evidence | Limits |
|---|---|---|---|
| 0 live check | `LiveAuthorizationCheck` before every step and every retry: S8's live checks, capability retired, binding inactive, `credential_valid` → REVOKED ends the run (C23, C35) | M14 28 | — |
| 1 admission | `admit_step`: gates 1–11 in order (C5, C30); QUEUE (capacity) and DELAY (circuit, pool, overload) retried up to `admission_max_attempts`, then `admission_exhausted` | M8 40 | DR-26, DR-55 |
| 2–3 eligibility, selection, lease | `filter_workers` (4b, 12b, 13b, 14, 17a–d; admin bypass only for 12b/13b/14); score = locality + free capacity; lease with fence token from one sequence; ownership compare-and-set | M8a 49, M7 15 | DR-54, DR-56 |
| 5 budget | reserve the step's cost (period-aware, never over `budget_pool`, I1) | M9 17 | — |
| 6 pre-flight | `deps.preflight(step, binding)`; failure cancels the step, releases the budget, skips dependants | M21 | DR-04 (always valid) |
| 7 start | step `pending → running` and reservation `reserved → locked` in one transaction (I-3); checkpoint hint | M9, M12 | — |
| 8 attempts | per attempt: live check → ledger lookup (hit returns cached; other op → `IdempotencyConflict`) → dispatch marker (C35; a marker without a record → UNCERTAIN) → guarded call → `ok` stores the ledger and succeeds; `timeout` → UNCERTAIN; non-retryable → stores and fails; retryable → backoff while under `retry_policy` ceiling (writes `never` → 1) | M11 46, M10 64 | — |
| 9 probe (S13) | on UNCERTAIN: EXECUTION episode; ledger first, then up to `probe_max_attempts` (3) probes with backoff; EXECUTED_SUCCESS → verify; EXECUTED_FAILURE → fail; NOT_EXECUTED → retry as the next attempt; exhausted → DEAD_LETTER `probe_exhausted`, budget LOCKED, PROBE dead letter (D4) | M13 13 | — |
| 10 verification (S13) | required layers by mutation and risk; FAIL → step failed, budget released, `data`/NONE dead letter; UNKNOWN → VERIFICATION episode (only layers not yet PASS), then dead letter VERIFY (or NONE if human) | M15 51 | DR-21 |
| 11 commit / release | success: reservation `locked → committed` with the step `completed` (reason `verified`); failures release | M12 | — |
| 12 checkpoint, lease release | checkpoint rows are hints only (CONF-044); lease released `work_complete` (or `fenced_out`) | M19 | — |

**Cross-cutting in the loop.** Topological order with ties broken by step index; one step at a time. Cancellation is
checked between retries (C16). Every log line carries the correlation ids (S5). Fault injection is inert unless a
test injects it.

**Inconsistency (DR-54).** `step_context(..., event_driven=False)` is hard-coded in the loop (`loop.py:291`) and the
recovery takeover (`loop.py:713`), and `execution_runs` stores no event-driven flag, so worker filter 14
(assignment) cannot apply its event-driven exemption.

## 5. Admission control detail (`admission_control.py`, `adapters/postgres/admission_snapshot.py`)

| Gate | Decision when failing | Source in production (`PostgresAdmissionSnapshot`) |
|---|---|---|
| 1 kill switch | REJECT `system_halted` | `tenants.kill_switch_engaged` |
| 2 tenant quota | REJECT | hard-coded pass (C39 quota is enforced at S12 entry instead) |
| 3 tenant active | REJECT `tenant_inactive` | `tenants.status` |
| 4 workspace active | REJECT | hard-coded pass |
| 5 mode allowed | REJECT | hard-coded pass |
| 6 provider allowed | REJECT | hard-coded pass |
| 7 worker capacity | QUEUE | `workers` (ACTIVE, `current_load < capacity`) |
| 8 circuit open | DELAY (C35) | hard-coded pass (the guard's breaker refuses at call time) |
| 9 DB pool pressure | DELAY | hard-coded pass |
| 10 budget available | REJECT `budget_exhausted` | **defect**: see below |
| 11 system overloaded | DELAY | hard-coded pass |

**Defect (DR-55, proposed DEF-006).** Gate 10 reads `execution_steps.effective_risk`, a 0–1 risk score, as
`step_cost` and compares it to `tenants.budget_pool`. For any pool ≥ 1 it is the same as "pool > 0", so the gate
cannot refuse a step that is too expensive. Money stays safe, because step 5's reservation enforces the real cost
(I1; zero over-reservations, M9), but the early REJECT the gate was written for never happens.

## 6. Workers, leases, fencing (`eligibility.py`, `selection.py`, `adapters/postgres/leases.py`, `renewal.py`)
- **Works.**
  - Leases carry fence tokens from one sequence (C25); capacity is never exceeded (I8); expired leases are
    transitioned by the next acquisition (C26).
  - Renewal takes a new larger token. During a long call, renewal every `lease_renewal_interval_s`; `LeaseLost`
    stops the step like `FencedOut` (CONF-045).
  - Recovery takeover re-applies CONF-046's released-lease grace under the ownership lock (fix `bdbc915`).
  - Evidence: M7 15, M8a 49, M20 12.
- **Limits.**
  - Selection uses locality and free capacity only: health, queue, fairness and cost have no inputs; the 0.7/0.5
    locality tiers never apply (DR-56).
  - `LoopSettings.lease_renewal_interval_s` defaults to `None` (no renewal) unless the runtime sets it from
    `ExecutionSettings` (DR-14).

## 7. Guard and adapters (`s12_execute/reliability.py`, `adapters/runtime/`)
- **Logic.** Bulkhead slot → breaker → budget (LOCKED) → retry-storm guard (attempt > 1) → `TimeoutManager`
  (the step deadline). Afterwards it normalises the result: an unknown class or a non-`AdapterResult` becomes
  `adapter_defect`, and `retryable` is recomputed. Records go to the breaker, health and billing. `client_error`
  never counts against the breaker. Probe and observe take a bulkhead slot and `probe_timeout_s` and skip
  breaker, budget and storm.
- **Works.** M10 64.
- **Limits.**
  - The mock adapter only (DR-38).
  - One adapter per guard (DR-42).
  - One bulkhead size for all providers; no rate limiter (adapters must limit themselves; package v2 does).
  - `probe_timeout_s` defaults to 0.5 s (DR-17).
  - Health and billing are in-memory (DR-30).
  - The old prototype `s12_execute/guard.py` still exists (DR-06).

## 8. Idempotency and retry (`attempts.py`, `retry_policy.py`, `adapters/postgres/idempotency.py`)
- **Works.**
  - Key `request_id:plan_step_id`, stable across attempts and recovery.
  - The ledger stores successes whole and failures as a class only.
  - The dispatch marker is committed before every call.
  - Retry ceilings: R 3 / W 2 / D 2 / IRREVERSIBLE 1, and 1 for `retry_safety: never`; backoff exponential for
    reads, fixed for writes.
  - Evidence: M11 46.
- **Limits.**
  - The key is global (DR-10).
  - A read's data is stored whole: no size bound in the ledger (the adapter package bounds reads to 16 KB).

## 9. S13 probe, verification, consolidation (`s13_reconciliation/`)
- **Probe.** As in loop step 9. M13 13.
- **Verification.**
  - Layers: schema, deterministic, provider_state (W/D/IRREVERSIBLE), semantic (risk ≥ 0.7 or IRREVERSIBLE), human
    (IRREVERSIBLE).
  - Schema and deterministic are local: PASS/FAIL only. The deterministic layer only checks that the identifier
    field is present.
  - provider_state calls `guard.observe` up to `max_attempts`; semantic parses into the strict enum; human →
    UNKNOWN (no channel, D4).
  - A FAIL is final (D6). After a probe-confirmed execution, only the layers that do not need the adapter result
    run (CONF-040).
  - Evidence: M15 51.
- **Consolidation.** Any DEAD_LETTER step (or CANCELLED `run_dead_lettered`) → run DEAD_LETTER. All completed →
  COMPLETED. Some completed and some failed/cancelled → PARTIAL. Otherwise FAILED. A run with a CANCELLED step is
  never COMPLETED (I13). Evidence: M16 31.
- **Inconsistency (DR-60).** The `verification.py` docstring says "text in a provider response can never reach the
  language model". But the semantic layer receives `observed_state`, which an adapter builds from provider data. The
  boundary holds only if each adapter limits `observed_state` to the plan's own fields (package v2 does). The gate
  §21 S8 test, provider text instructing PASS, cannot run until a real assessor exists (DR-21).
- **Limit.** No production `SemanticAssessor` (DR-21).
- **Superseded modules.** `s13_reconciliation/handler.py`, `s14_verification/handler.py` are "pre-existing, not
  certified" (DR-06).

## 10. S14 dead letter (`s14_dead_letter/`, `adapters/postgres/dead_letters.py`)
- **Works.**
  - Records with non-empty evidence (I11), `retry_mode` fixed at creation (PROBE / VERIFY / NONE, D5).
  - Retry never re-executes; inconclusive → back to pending, and after `max_retries` abandoned as UNDETERMINED with
    the budget committed (D4).
  - Resolution moves only the dead letter, the reservation and audit; run and step stay terminal (D4).
  - Explicit `rollback_execution` (D2): inverse through the full guard with `InverseBudget`, never for
    IRREVERSIBLE; a failed inverse → rollback dead letter NONE.
  - `DeadLetterOperator` (CONF-049): tenant-scoped, audited list / resolve / retry (PROBE and VERIFY only).
  - Evidence: M17 37, M21.
- **Limits.**
  - The operator is a service class with **no HTTP route** (DR-57).
  - No automatic rollback (DR-29).

## 11. S15 response (`s15_final_state/response.py`, `adapters/postgres/run_summary.py`)
- **Logic.** Pure mapping of a terminal run to an envelope:
  - COMPLETED → `ok`;
  - PARTIAL → `partial` (failed steps listed);
  - CANCELLED → `error` with a fixed message per reason (budget, user, credential, authorisation, kill switch,
    binding);
  - DEAD_LETTER → `error` "flagged for review";
  - FAILED → `error` with a fixed step message.

  `entry_denial_envelope` covers entry denials (`quota_exhausted` with `retry_after_ms`). Only codes, positions,
  operation names and states go in; the only id is `trace_id`.
- **Works.** M18 19, including injected secrets, traces and provider bodies absent from the envelope, the logs and
  the rows.
- **Limits.**
  - No step result data in the envelope: reads return nothing to the user (DR-40).
  - No route serves the envelope (DR-49).
  - `s15_final_state/handler.py` is a superseded prototype (DR-06).

## 12. Recovery, multi-runtime, start-up (`recovery.py`, `loop.recover_execution`, `startup.py`)
- **Works.**
  - The sweeper finds orphans through `s12_recovery_candidates` (ids only). A takeover gets a larger token and
    skips rows another sweeper holds (SKIP LOCKED).
  - In-flight resolution never re-executes blindly: probe or ledger; a recorded FAIL is never overturned
    (CONF-050); a tampered plan → NONE dead letter (CONF-043).
  - Crash at each of the 10 points recovers to completed with one side effect.
  - Two runtimes share work; killed processes are taken over.
  - Start-up refuses a superuser or BYPASSRLS role and unverifiable production mutations.
  - Evidence: M19 44, M20 12.
- **Limits.**
  - Nothing runs the sweeper or the start-up check in the product (DR-14).
  - Windows timing sensitivity of the multi-process cases (DR-31).

## 13. Cross-cutting
- **State machines (Appendix A).** One `transitions.validate` for every move; 114 legal edges with reasons, an
  exhaustive illegal sweep over 9 machines; the I5 checker runs in the goldens.
- **Tenant isolation (C34).** `tenant_id` and forced RLS on every S12 table; every repository statement names
  `tenant_id` (scan); cross-tenant read/forge/claim refused (M20).
- **Settings (S1).** `ExecutionSettings.from_env`, validated (C37 timeout ordering, TTL ≥ 3 × renewal).
- **Portability (S9).** No POSIX-only APIs or fixed paths (M20 scan).
- **Records.**
  - CONF-035 is `ruled` ("port the `tests_postgres` prototype S12 tests to the M12 interface; never delete or
    weaken one"), but the port was never done. `tests_postgres/test_step_loop.py` and `test_chain_full_stack.py`
    fail to import (`StepLoopDeps` no longer exists) (DR-58).
  - `tests_postgres/test_schema_audit.py::test_every_table_the_sql_in_src_names_exists` fails: its SQL parser reads
    the S12 function `s12_recovery_candidates(...)` and `FOR UPDATE OF` as table names (DR-59).
  - No certifier runs `tests_postgres`, so neither was caught.
