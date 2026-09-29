# Review — Worker Management & Evolution Specification v1.1.0 → master-document propagation

**Reviewed**: `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` v1.1.0 (PROPOSED, 2026-09-29)
**Against**: `FINAL_ARCHITECTURE.md` v4.4.0, `S12_S15_EXECUTION_GATE.md` v9, `S12_S15_IMPLEMENTATION_PLAN.md` v2,
`WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md`, `DATA_CONTRACTS.md`, `IDENTITY_AND_TENANCY.md`, `PIPELINE_STAGES.md`,
`S12_SESSION0_PREFLIGHT_PROMPT.md`, `DATABASE.md`
**Date**: 2026-09-29
**Status**: RULINGS CONFIRMED AND PROPAGATED (2026-09-29). The owner confirmed RD-1…RD-18 (Part E, with the round-2 corrections) and instructed propagation. Part C was applied to the eight target documents, `DATABASE.md`, every Part D document and the spec itself (now v1.2.0); **Part F records what was applied**. Nothing from Parts A–D remains open except the recorded items in F.3.

---

## Summary

The spec is mostly additive, but it can't be propagated as written. The spec claims that
"nothing modifies S0–S11 certified artifacts". Several of its features contradict locked invariants
or the S12–S15 phase lock:

| # | Severity | Finding | Collides with |
|---|---|---|---|
| 1 | **Blocking** | The Browser/RPA path B0–B7 and the `runtime_type` routes that skip stages (`rules`, `data`, `human`, …) bypass S0–S11, and therefore S8 authorization and the S11 manifest | FINAL_ARCHITECTURE §37a Principle 8 ("exactly ONE execution path"), I-023, I-024; gate §7.1 entry checks (auth_passed, manifest, plan_hash); spec §7 rule 2 ("no layer may bypass the layer below") |
| 2 | **Blocking** | Worker-specific gates G12, G13 (worker level), G14 and G17 run in **admission**, but admission runs **before** worker selection, so no worker exists yet to check | WORKER_LIFECYCLE §10 "admission runs FIRST — before any worker is selected"; gate §8 steps 1→2 |
| 3 | **Blocking** | Batch resume re-executes `RUNNING` batches ("treated as failed") | Gate §13 step 3 ("never blindly re-executed"), I4, I16 — duplicate side effects |
| 4 | **Blocking** | Batch idempotency: every batch reuses `request_id:plan_step_id`, so batch 2 returns batch 1's cached result from the ledger | Gate C9, C17; FINAL_ARCHITECTURE I-021 |
| 5 | **Blocking** | Replanning (F31): S12 calls "S7" to replace the plan mid-run, and it replans on an inconclusive UNKNOWN | I-006 (immutable plan), I-017 (config snapshot), I9 (plan digest), gate §1 "MUST NOT re-resolve / run S8", gate §9 (INCONCLUSIVE ×3 → DEAD_LETTER), I6 |
| 6 | **Blocking** | G16 quota increments "on completion", so concurrent admissions overshoot a hard quota | Gate conflict principle 1 (never overspend); admission is stateless, so it can't reserve |
| 7 | **Blocking** | All FKs are typed `UUID`, but `tenants`, `users`, `workspaces` and `execution_runs` keys are `TEXT` (DATABASE.md), so the DDL fails | DATABASE.md; gate §7.3 FK-type rule |
| 8 | **Blocking** | New tables lack `tenant_id` (`execution_batches`, `worker_spawn_audit`, `worker_group_members`, `worker_config_versions`, `session_memory`) | Gate C34, I15; I-001 RLS pattern |
| 9 | High | P0 items F1–F9 and F31 change S1, S7, S9, ExecutionContext (`dry_run`) and NormalizedInput (`BatchSplit`) — all certified S0–S11 contracts | Gate §1 MUST NOT, §19.3 change control; I-009 |
| 10 | High | F20 introduces a second autonomy vocabulary (`observed…high_trust`) and changes S8 behavior | Existing `AutonomyLevel` (DATA_CONTRACTS §38, FINAL_ARCH §39) used by S13 layer selection; extension point #13 ("kernel authorization and risk rules are unaffected") |
| 11 | High | The "Seven-Layer Architecture Invariant" (spec §7) reuses "Layer 1…7" with a different meaning | FINAL_ARCHITECTURE §6 "7 Layers + Execution Kernel" (L1 = Provider Adapters there) |
| 12 | High | Parallel batches (`BATCH_CONCURRENCY=5`) and consolidation of batch results | Gate §8 ("parallel step execution is out of scope"), §14 deferred list, C36 (no data flow) |
| 13 | Medium | Stage misattribution: the spec says S7 creates batches, plans skills and replans. **S7 is Path Routing; S9 is Plan Creation** | PIPELINE_STAGES §9, §11 |
| 14 | Medium | Role names `TENANT_ADMIN` / `TENANT_OWNER` don't exist. Roles are workspace-scoped `owner`, `admin`, `member`, `viewer` | IDENTITY §5 `UserRole`; DATABASE `memberships.role` |
| 15 | Medium | Browser mutation classes `READ` / `IDEMPOTENT_WRITE` don't exist. Canonical classes are `R`, `W`, `D`, `IRREVERSIBLE`, and a click is not idempotent | FINAL_ARCH §18; MUTATION_SAFETY |
| 16 | Medium | The BrowserAdapter picks its provider (Playwright/Apify/BrowserUse) at call time | I-002/I-010 (binding frozen at S5); RESOLVE_LAYER |
| 17 | Medium | The milestone numbers conflate the plan's M0–M21 with FINAL_ARCH §30's M0–M4 evolution path ("skills at M0", "planner at M7", "marketplace at M21"; M0 is preflight-only, M7 is leases, M21 is certification). "W7" is EXECUTION_PLAN vocabulary, not a plan milestone | S12_S15_IMPLEMENTATION_PLAN §4 |

---

## Part A — Corrections to the spec itself (before propagation)

1. **Missing sections.** The TOC lists §9 "S0–S11 Protection List" and §10 "Implementation Sequence", but neither exists. Add them, or remove them from the TOC.
2. **Column types.** Use `TEXT` for every FK to `tenants`, `users`, `workspaces` and `execution_runs`. `workers.worker_id` is `UUID` in DATABASE.md but `TEXT` in WORKER_LIFECYCLE §3. Match whatever preflight item 11 finds in the code, per the gate §7.3 FK-type rule. Keep `TIMESTAMPTZ` for new time columns: the M1 trap forbids TEXT timestamps, and I-019 requires comparisons against database `NOW()`.
3. **Tenant column and RLS.** Add `tenant_id TEXT NOT NULL` and an RLS policy to `execution_batches`, `worker_spawn_audit`, `worker_group_members`, `worker_config_versions`, `session_memory` and `skill_definitions` (the last already has it). Add `workspace_id` wherever pause or quota scope needs it.
4. **Quota table integrity.** Add `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)` to `operation_quotas` (PG16), plus `CHECK (used_count >= 0 AND limit_value >= 0)`. Tie the periods to `budget_period` semantics (gate C33).
5. **Quota semantics (G16, Appendix A).** Today `effective_limit = MIN(...)` is compared with a single `used_count`, but each level has its own counter. Rewrite it as "reject/queue if **any** applicable level has `used_count >= limit_value`", and consume on **every** applicable level.
6. **Quota consumption point.** Don't consume after S13. Consume once per run at **durable admission (gate §7.2)**, inside the same transaction, with `UPDATE … SET used_count = used_count + 1 WHERE used_count < limit_value RETURNING …`. Zero rows means hard → deny at entry (`quota_exhausted`, writes nothing else), soft → QUEUE. G16 in the per-step admission becomes a read-only precheck. Whether failed runs are refunded is an owner choice; state it explicitly.
7. **Sub-agent limit (G15).** G15 is not an admission gate: spawning registers a worker; it doesn't admit an execution. Move it to `spawn_child_worker()`. Fix the depth off-by-one (`depth_level + 1 > max_depth`, not `>=`). Count only children in non-`TERMINATED` states. Lock the parent row (`SELECT … FOR UPDATE`) before counting to prevent races. Pick one source for max depth: `plans.max_sub_agent_depth` or `tenants.settings.max_depth`, not both. Change `budget_allocated DECIMAL` to integer minor units, because budgets are `INTEGER` minor units in `tenants.budget_pool`, and define how a child budget draws from the tenant pool; BudgetReserver has no sub-pools today. Child `capability_profile` ⊆ parent's, child grants ⊆ parent's grants, and `PrincipalChain.delegating_worker_id` = parent.
8. **Pause levels.** Make them consistent. F4 says three levels, G12 says four (with group), G13 says three, but `worker_groups` also has `scheduled_activation_at`. Either include groups in both G12 and G13, or drop the group column. A worker in several groups takes the MAX over all of them.
9. **Tenant and workspace settings.** `tenants.settings` and `workspaces.settings` are `TEXT` JSON, not JSONB, and their time format is undefined. Specify the key names and an ISO-8601 UTC format, or add typed columns instead of JSON keys (preferred).
10. **One worker taxonomy.** There are currently three overlapping ones: `worker_class` (execution/scheduler/system), `worker_type` (standard/event/hybrid/browser/rpa/vision, in templates and skills) and `runtime_type` (llm/rules/vision/browser/rpa/data/rag/code/human). The F19 list omits `rpa`, while §2.1 includes it. Recommendation: keep `worker_class` as is; `runtime_type` = which runtime and adapter family; drop `worker_type` and derive "event/hybrid" from active `WorkerSubscription` rows, which the spec already does for hybrid.
11. **G17 worker-type matrix.** "Event-based: Has capabilities = No" is impossible: any worker that executes a step needs the capability in `capability_profile` and a worker `CapabilityGrant` (IDENTITY §6 Worker Authorization). Event workers differ by trigger source, not by capabilities. Subscription matching already happens in the Event Gateway **before S0**, so G17 must not repeat it.
12. **Autonomy (F20).** Map onto the existing `AutonomyLevel` (`READ_ONLY`, `CONFIRM_ALL`, `SUPERVISED`, `FULLY_AUTONOMOUS`), or give the new concept a distinct name (e.g. `grant_trust_tier`) that can only **restrict** the manifest's `AutonomyLevel`. Any S8 or S10 behavior change is S0–S11 change control (gate §19.3). Mark it post-S15.
13. **Policy chain (§6.7).** It says "8-layer" but lists 9 layers. It also drops the existing levels User Role, User Grants, Worker Grants and Execution Mode (IDENTITY §5). "Company Policy" duplicates Tenant (the tenant is the company). Rebase it on the IDENTITY §5 chain and insert the new levels there. §7 puts the PolicyEngine in Layer 1 and marks Layer 1 "FROZEN". Resolve by making the PolicyEngine the guardrail level 6 extension point (#8), post-S15.
14. **Memory classes (§6.3).** The class name "Episodic" collides with memory layer L0 "Episodic Buffer" (FINAL_ARCH §21). `session_memory.memory_class DEFAULT 'episodic'` contradicts the spec's own table (episodic = L0→L1, not L2). F18 writes memory, so it must go through `MemoryWriteBarrier` (I-014), which Appendix D defers. That makes F18 P1-before-barrier impossible, so re-tier it. "Policy" and "Organizational" memory are informational copies: the PolicyEngine reads policy tables, never memory.
15. **Browser section.**
    - Drop B0–B7 and route browser/RPA through the one pipeline: recorded workflow = `SkillDefinition`, planned at S9 (FAST/WORKFLOW, no LLM needed), `BrowserAdapter` behind `BaseAdapter`. FINAL_ARCH §37a Principle 2 already lists browser automation, and §38 already lists `BrowserRuntimeAdapter`.
    - Playwright, Apify and BrowserUse become separate **bindings** frozen at S5, not adapter-internal routing.
    - Mutation classes: `browser_open`, `browser_extract`, `browser_screenshot`, `browser_wait` and `browser_filter` → `R`. ~~`browser_click`, `browser_type` and `browser_export` → `W` with `retry_safety = false`.~~ *(Round 3 correction: MUTATION_SAFETY Contract 4 requires every W/D to have an inverse, and most browser actions have none.)* `browser_type`, `browser_export` and navigation-only clicks → `R` (page-local); a click or submit that changes external state → `IRREVERSIBLE` unless an inverse capability exists (then `W`/`D`). An undeclared external-effect action is `IRREVERSIBLE` (fail-closed), so it is confirmed and never retried. Master copy: MUTATION_SAFETY §1.
    - Kernel metadata comes from the Provider Package (DATA_CONTRACTS header), not a `kernel_definitions.yaml`.
    - B3 names `execution_leases`, which C5 deprecated; the lease table is `worker_leases`.
    - If `BrowserExecutionContext` survives at all, a frozen dataclass can't hold `dict`/`list` (use tuples or `MappingProxyType`). Screenshots are artifacts (extension point #11), not context. `auth_passed` via "G3 + G4" confuses admission with authorization.
16. **Undefined references.** "V0–V4 path", the `skill_steps` table (only JSONB `composition` exists), `execution_runs.result` (no such column; consolidation is `execution_runs.consolidation`), `tenant.allowed_models` (not in `TenantPolicy`), and the `upgrade_prompt` field (not in `AdmissionDecision`; use `detail`, or amend the contract explicitly).
17. **"New" items that already exist (§6.8).** `causation_id` (DATA_CONTRACTS §29, FINAL_ARCH §37a Principle 7), `EventCorrelator` (EVENT_GATEWAY §7), sequence numbers (EVENT_GATEWAY). Mark them as existing, not new.
18. **Worker config and I-017.** Settings edits must affect **new** executions only. Record `worker_config_version_id` on each `execution_steps` row when the worker is leased (additive column), because the worker is chosen at S12 step 2, after the S11 manifest is frozen. F10 should reuse `ConfigurationVersion` (DATA_CONTRACTS §48) rather than a parallel scheme.
19. **Per-worker `execution_policy` (F16).** It may only **tighten** (a lower `max_retries`, a shorter timeout). It can never raise MUTATION_SAFETY ceilings or enable retries for `IRREVERSIBLE`/non-idempotent `D`. Circuit breakers are per provider (RELIABILITY), so drop `circuit_breaker_threshold` or make it provider-scoped.
20. **Webhooks (F15).** `worker_webhooks.secret TEXT` stores a plaintext secret (I-018). Store a reference resolved through `CredentialProvider` (gate §21 S6). Dispatch through the outbox (I-020). Validate URLs against SSRF (SECURITY).
21. **Dry run (F13).** Don't add a flag to `ExecutionContext`: it's frozen at S0 (I-009) and certified. Model dry-run as a **sandbox connection/binding** resolved at S5 (mock adapter). `execution_runs.dry_run` can then be a recorded, derived flag. No S0–S11 contract changes.

---

## Part B — Owner decisions required (record as rulings before editing masters)

| ID | Question | Recommendation |
|---|---|---|
| **WM-1** | Are worker-specific checks admission gates or worker-selection eligibility filters? | **Filters.** Tenant/workspace pause and activation (G12a/G13a) and the quota precheck (G16) stay in admission (no worker needed). Worker pause/activation (G12b/G13b), assignment (G14) and capability/runtime match (G17) filter candidates in gate §8 step 2. If none remain → REJECT, with the specific filter reason recorded in the ledger. |
| **WM-2** | What does a pause do to runs already RUNNING? | Pause blocks **new runs only**, with drain semantics like `DRAINING`: G12/G13 are evaluated at S12 entry and at worker selection for new leases, never as a mid-run REJECT that cancels steps. A hard stop stays the existing kill switch (C23). Otherwise a pause would cancel half-finished runs with `admission_rejected`. |
| **WM-3** | Which items are in S12–S15 scope? | **In, as gate v10 C39:** additive schema seams (§2.1 columns with defaults/NULL, `operation_quotas`), WM-1 checks, G16 hard quota at durable admission. *(Round 2: `parent_execution_id` deferred — RD-11; no new `StepTerminalReason` value was needed — gate C39.)* **Deferred (post-S15, register):** batch (F9), replanning (F31), spawning (F7), groups, webhooks, config versions, L2 memory, heterogeneous routing, autonomy, browser, skills, policy engine, templates, plans, marketplace. |
| **WM-4** | Browser/RPA: adapter under S0–S15, or amend I-023/Principle 8? | **Adapter under S0–S15.** Amending the invariant re-opens S0–S11 certification and removes S8 from browser executions. |
| **WM-5** | Batch model | A batch is **N ordinary PlanSteps** produced at S9 by the existing BATCH strategy (FINAL_ARCH §15, PIPELINE §21), each with its own `plan_step_id`. That gives a distinct idempotency key per batch plus the full step state machine, probe and recovery path, and the §10 consolidation (PARTIAL already exists). `execution_batches` becomes a read model, or is dropped; it gets no new state machine (gate §1 forbids new state names). |
| **WM-6** | Replanning model | Replan = a **new child execution** (`parent_execution_id`) that goes through S0→S15 with its own manifest. The parent consolidates normally (e.g. PARTIAL) and records the link. The kernel stays unchanged; I-006 and I-017 hold. |
| **WM-7** | Do failed or cancelled runs consume quota? | Recommend: consumed at durable admission; refunded only for runs that end CANCELLED with no step COMPLETED (a ledger event records the refund). |
| **WM-8** | Admin bypass scope | Bypass applies to membership role `owner`/`admin` **in the run's workspace**, read live (not from the snapshot). G14 compares against `PrincipalChain.original_principal_id`, not `user_id`, so worker-to-worker delegation keeps the human's assignment. |

---

## Part C — Per-file changes

Conventions: **APPEND** = new text. **CORRECT** = change existing text. Every propagated passage carries a marker
`> **Worker-management repair (WM-n / C39–C41)**` in the same style as the v9 markers.

### C.1 `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md`

**APPEND §16 Worker Management Settings** (after §15; update the TOC and "Document Relationships"):

- §16.1 Management columns on `workers` (corrected types per Part A-2). Include a statement that they are **mutable management state**, read only by S12 admission and worker selection, never by S0–S11, and never part of the ExecutionManifest.
- §16.2 Admission additions: G12a tenant/workspace pause and G13a tenant/workspace activation (entry-time, WM-2), and G16 quota precheck (read-only). Include the ordering rule: **REJECT-type gates before G7**. Otherwise a paused worker at capacity returns QUEUE, retries until `admission_exhausted`, and ends with the wrong reason.
- §16.3 Worker-selection eligibility filters (WM-1): worker pause/activation, assignment (G14, using `original_principal_id`), runtime/capability match (G17). Cross-reference §13 so locality is scored only over eligible workers.
- §16.4 Quota consumption at durable admission (Part A-5, A-6).
- §16.5 Three-level (or four-level) timestamp precedence, server time (I-019).
- §16.6 Sub-agent spawn check (moved out of admission, Part A-7) + `worker_spawn_audit`.
- §16.7–§16.9 Config versioning, webhooks and groups: mark them **DEFERRED (post-S15)** and keep only the table stubs.
- §16.10 Reason codes (below).

**CORRECT**
- §10 "Admission Gates (in order)" (line 756): add G12a, G13a and G16 rows, with a note that worker-level checks live in §16.3. Keep gate numbers stable, because C30 maps REJECTs by gate number.
- §3 Invariant 4 and §15 Rule 1 ("No WorkerIdentity Mutation After Creation", line 1165): reword to "`capability_profile`, `worker_class` and `tenant_id` are immutable. Management columns (§16.1) are mutable and versioned; a change affects only leases acquired after it (I-017)."
- §11 AdmissionDecision: list the new reason codes. Soft-quota upgrade guidance goes in `detail`; no new field.
- Pre-existing stale text found during this review (fix in the same pass): §15 Rule 7 (line 1209) names the maximum `worker_leases.fence_token` per worker as the authority. C25 changed where tokens come from (the `fence_token_seq` sequence) and what they are checked against (`execution_ownership.fencing_token`, per execution); `worker_leases.fence_token` still exists and records the token issued with each lease. The same stale sentence is in DATA_CONTRACTS §37. §3 schema types (`TEXT`/`REAL`) differ from DATABASE.md (`UUID`/`TIMESTAMP`, no `workspace_id`).

### C.2 `FINAL_ARCHITECTURE.md`

**CORRECT** (the spec's five edits, adjusted):
1. **§33 Worker Capacity:** add `effective_load`, but **not** `+ batch_count`. Batches are steps (WM-5), so they're already counted by leases. Child workers have their own capacity; don't add `child_count` to the parent's load unless the parent is blocked waiting on the children, and say which.
2. **§34 Terminology:** add WorkerGroup, `runtime_type` (with its values) and "Worker Runtime is deployment-target agnostic". Also note that "Worker Deployment" (§41 lifecycle model: a customer install) ≠ `WorkerDeployment` (WORKER_LIFECYCLE §5: a runtime instance). Pre-existing defect: the "Critical/Minor Conflicts" tables under §34 have lost their heading (they belong to the Conflict Resolution Log).
3. **Extension points:** the target is the **"Required Extension Points"** table (line 2709), not "§41". §41 appears three times (line 2192 Event Correlation; lines 2622–2623 Architecture Invariants, duplicated), and the TOC's "§41 Future Worker Platform Compatibility" heading is missing. Restore the heading, then map the spec's features onto existing rows (#1–#3 config, #5–#7 skills = F33, #8 PolicyEngine = F22, #13 autonomy = F20, #14 marketplace = F27, #15 entitlements = F26). Add rows only for batch (BATCH strategy), sub-agent delegation, worker groups and runtime-type routing.
4. **§21 Memory:** add the classification as a table **orthogonal to layers L0–L3**, with the renamed class (Part A-14) and the "memory is never read for authorization" invariant.
5. **§29 Decisions:** add progressive autonomy (restrict-only), heterogeneous workers (adapter/strategy selection, never stage skipping), and memory ≠ authorization. **Do not** add "kernel as control envelope, plan replaceable at any checkpoint": it contradicts I-006 and I-017. Record the child-execution replan model (WM-6) instead.

**APPEND**
- In §37a Principle 8 and the invariant table: an explicit line that browser/RPA/vision/human/rules workers are **not** exceptions to I-023/Principle 8 (WM-4).
- In §15: the BATCH strategy activation note (WM-5), still stubbed until its phase.

**Pre-existing defects to fix in the same pass**
- Principle 8 says "This is an architecture invariant (I-024)", but I-024 is Kernel Stability. The one-path rule is I-023, which covers events only; generalize it or add I-029.
- Invariant rows I-022…I-025 are duplicated (lines 2658–2666).
- Two "## 38." headings, and "38.." at line 1884.
- The §26 `workers` DDL (UUID/TIMESTAMP) disagrees with WORKER_LIFECYCLE §3 (TEXT/REAL).

**Do not import** the spec's §7 "Seven-Layer" model under that name (collision with §6). If kept, call it "Stability Tiers T1–T7" (round 2) and put it in §30 Evolution Path.

### C.3 `S12_S15_EXECUTION_GATE.md` → v10

- **C39 (new)** Worker management in S12: WM-1, WM-2, WM-7, WM-8, the corrected admission order, quota consumption at §7.2, and the C30 mapping for new gates. C30 mapping: tenant/workspace pause → REJECT at entry (writes nothing), never a mid-run cancel. Quota → deny at entry. Filters → `no_worker` with the filter reason in the ledger.
- **C40 (new)** Batch: rule it **out of this phase**, and record the WM-5 model for the planning phase. It sits alongside the existing "parallel step execution" entry in §14 "Still deferred" (line 1638).
- **C41 (new)** Replanning: rule it **out of this phase**. *(Round 2: `parent_execution_id` is not added in this phase — RD-11.)* Record WM-6.
- **C22 extension:** add `StepTerminalReason` values, or state that they map to existing ones: `worker_paused`, `worker_not_yet_active`, `not_assigned`, `quota_exhausted`, `capability_mismatch`. Recommend: entry denials carry them as `StageStatus.DENY` reasons (no step rows exist yet); selection-filter exhaustion stays `no_worker`, with the detail in the ledger. Update the C28 CHECK list.
- **§2 Preflight (correct the spec's references):** the spec's "item 3" and "item 16" don't match this gate. Item 3 is the S12–S15 file list, and the gate has items 1–14. Add **item 15** (for `workers`, `tenants`, `workspaces`, `execution_runs`: which §16.1/§2.2 columns exist, their types, and the FK type of every referenced key) and **item 16** (whether `operation_quotas`, `worker_spawn_audit`, `worker_groups`, `worker_group_members` or `execution_batches` exist; `file:line` or "not present in code").
- **§1 MAY:** add the C39 schema and filters. **MUST NOT:** add spawning, batch, replan and browser path explicitly.
- **§7.1 / §7.2:** entry checks G12a, G13a, and the quota consumption statement.
- **§7.3 Additive schema:** the §2.1 columns (with defaults), `operation_quotas` (tenant_id + RLS). *(Round 2: `parent_execution_id` deferred — RD-11; `worker_config_version_id` deferred with F10.)*
- **§8 step 2:** eligibility filters before locality scoring.
- **§14 Still deferred:** F7, F9, F10, F15, F17–F20, F22–F36.
- **§16 suites:** add a suite 20, "worker management" (tests listed under C.4).
- **§17 invariants:** **I17**: for every hard quota, `used_count ≤ limit_value`. **I18**: no lease was acquired on a worker that was paused, not yet active, or assigned to a different principal at acquisition time (database time).
- **§20 report:** add a line "Worker management (C39): PASS/FAIL (quota overshoots: 0, leases on ineligible workers: 0)".
- Header: revision v10 and "Previous revision: v9".

### C.4 `S12_S15_IMPLEMENTATION_PLAN.md` → v3

- **M1 (schema):** add the C39 columns and tables to Build and to Golden `M01_schema.py`: FK types valid, `tenant_id NOT NULL` + RLS on new tables, `operation_quotas` unique and check constraints.
- **M8a — Worker management admission and eligibility** (the spec's "M8.5"; use a letter suffix so file names sort: `M08a_worker_mgmt.py`). Golden tests:
  - tenant/workspace pause denies at entry and writes zero rows;
  - pause set mid-run does not cancel the run (WM-2);
  - a paused, unassigned or mismatched worker is never leased (I18);
  - admin bypass only for `owner`/`admin` in the run's workspace;
  - G14 uses `original_principal_id`;
  - REJECT-type gates are evaluated before capacity QUEUE;
  - 20 concurrent entries against `limit_value = 5` → exactly 5 admitted, over 5 runs (I17);
  - soft quota → QUEUE with `detail`.

  Sabotage patches: "check the quota at the stateless gate only", "filter after locality scoring", "use `user_id` for G14".
- **M9.5 batch and M12.5 spawning:** **don't add them** in this phase (WM-3). Batch depends on M11 (idempotency), M12 (loop), M16 (consolidation) and M19 (recovery), so "M9.5" would be mis-ordered anyway. List both in §7 Risks and the deferred register.
- **"W7":** replace with a register entry "post-S15 phase: worker management II (batch, spawning, groups, webhooks, config versions)". W0–W6 belong to EXECUTION_PLAN.md, not this plan.
- **§1 Preconditions:** add "owner rulings WM-1…WM-8 recorded; gate v10 installed".
- **§2 Document roles:** add `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` as **reference only; gate C39–C41 govern**.
- **§5.4:** I17 and I18 join the invariant checker at M8a.
- **§6 ★ reviews:** add M8a (it touches admission ordering).

### C.5 `S12_SESSION0_PREFLIGHT_PROMPT.md`

- **Correct (pre-existing, blocking):** "Must be Revision **v8**" (§2 and §4 item 4) → v10, or v9 if C39 is not adopted. As written, a v9 gate makes Session 0 STOP.
- **Correct:** "Answer gate Section 2 items 3–9" → "items 3–16". The prompt's own items 10–15 reuse numbers that gate items 10–14 already use with different content. Renumber the prompt's items P1–P6 to remove the ambiguity.
- **Append:** the worker-management item (gate items 15/16 above). Extend item 12's table list with `workspaces`, `users`, `memberships`, `operation_quotas` and `event_subscriptions`, and add "report every FK type mismatch that the C39 migrations would hit".

### C.6 `DATA_CONTRACTS.md`

- Number new sections **§50+**: the file already has duplicate §31s and a trailing §37, so don't reuse numbers.
- **Append:**
  - §50 `WorkerManagementProfile`: a read model of the §16.1 columns plus the typed `settings` schema (Appendix B of the spec). This avoids editing the frozen `WorkerIdentity` (§31).
  - §51 `OperationQuota` + consumption rule.
  - §52 new `StepTerminalReason` / admission reason codes (C39).
  - §53 `SkillDefinition` / `SkillStep` (DEFERRED): `capability_id` must resolve through the registry at S3/S5, and composition is planned at **S9**.
- **Do not append** `BatchSplit` (S1→S7): it changes certified `NormalizedInput`, and the stages are wrong. Record batch as BATCH-strategy PlanSteps (WM-5). **Do not append** `BrowserExecutionContext` (WM-4). If the owner rejects WM-4, it needs the Part A-15 fixes.
- `BatchConsolidation` → not needed: consolidation uses §10 of the gate. Record a batch summary only as a ledger event.
- Make the vocabulary consistent: the existing `AutonomyLevel` stays canonical (Part A-12).

### C.7 `IDENTITY_AND_TENANCY.md`

- **Append** in §5 Policy Hierarchy: a "Worker Management Settings" level below "Worker Capability Grants", **restrict-only**. `restricted_capabilities` narrows grants and never widens them. Say where it's enforced: this phase = S12 eligibility/pre-flight only; S8 enforcement = S0–S11 change control, later.
- **Append** the `workers.settings` JSONB contract (spec Appendix B), with Part A-19 (tighten-only `execution_policy`) and `llm_model` validated against a tenant model allow-list that must first be added to `TenantPolicy` (currently absent). `llm_model` and `skills_prompt` are consumed at S2 (the LLM call, S0–S11) — so they're inert until an S0–S11 change is certified. State it.
- **Append** to §6 Worker Authorization: assignment (`assigned_user_id`) restricts which `original_principal_id` a worker may serve; it never grants capabilities. Include the sub-agent rule: child grants ⊆ parent grants, and PrincipalChain records the parent as `delegating_worker_id`.
- **CapabilityGrant `autonomy_level` (F20):** don't add it to the frozen `CapabilityGrant`. Add a note under §5 pointing to the reconciled autonomy design (Part A-12, deferred).
- **Correct:** the spec's `TENANT_ADMIN` / `TENANT_OWNER` → `UserRole.OWNER` / `UserRole.ADMIN`, workspace-scoped (WM-8). Also align VOCABULARY_INDEX, which lists `TENANT_ADMIN`/`TENANT_OPERATOR`/`TENANT_VIEWER`.
- **Distinguish pause from kill switch** (§8.4): pause = no new runs (WM-2); kill switch = cancel now (C23).
- **Pre-existing:** §7 "Worker Lifecycle" (REGISTERED → ACTIVE ↔ DRAINING → STOPPED → DELETED, line 634) contradicts STATE_TRANSITIONS §4 and gate Appendix A.5 (DRAINED, TERMINATED). Fix it in the same pass.

### C.8 `PIPELINE_STAGES.md`

- **Do not add** the note "S0–S11 is the API path; browser/RPA uses B0–B7 which bypasses S0–S11". It contradicts FINAL_ARCH Principle 8 and I-023.
- **Append** instead, in §21 Execution Strategy Selection: "`runtime_type` selects the runtime adapter, binding family and strategy (via `RuntimeRoutingDecision`, DATA_CONTRACTS §42, frozen at S7). It never removes a stage: S8 authorization, S10 confirmation and S11 validation apply to every runtime type."
- **Append** to §14 S12: the eligibility-filter step (C39) and the entry-time pause/quota checks, with a pointer to gate §7–§8.
- **Append** to §19 Negative-Path Matrix these rows, each with user-safe wording:
  - worker paused
  - not yet active
  - not assigned
  - quota exhausted (hard / soft)
  - no eligible worker after filters
- **Correct the spec's stage references** when propagating: batch creation, skill planning and replanning belong to **S9**, not S7.

---

## Part D — Documents the spec omits but that also need updates

| Document | Why |
|---|---|
| `DATABASE.md` | **Authoritative for tables** (gate §3). All §2 DDL belongs here, not in WORKER_LIFECYCLE. |
| `STATE_TRANSITIONS.md` | Any batch or spawn state machine (or an explicit statement that none is added, WM-5) |
| `VOCABULARY_INDEX.md` | WorkerGroup, runtime_type, operation quota, pause vs kill switch. The "Skill" definition ("compiled, cached unit") conflicts with data-only `SkillDefinition` compositions. Role names. |
| `MUTATION_SAFETY.md` | Browser mutation classes and retry safety; the per-worker policy may only tighten |
| `SECURITY.md` | Webhook secrets and SSRF; assignment and admin-bypass rules |
| `PROVIDER_ADAPTERS.md` | BrowserAdapter as a `BaseAdapter`; provider = binding |
| `EVENT_GATEWAY_AND_ROUTER.md` | Pause and assignment interplay with subscription routing (does a paused worker still match events?) |
| `VALIDATION.md`, `BUILD_READINESS_MATRIX.md` | New suites and closure rows |
| `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` §18, `REPAIRS_APPLIED.md` | Record C39–C41 and WM-1…WM-8, plus every deferred feature with a target phase |
| `EXECUTION_PLAN.md` | Where a "W7" would live, if kept |

---

## Part E — Rulings draft (owner review round 1, 2026-09-29)

**Status**: CONFIRMED by the owner on 2026-09-29, with the round-2 corrections marked *(round 2)* below. RD-1, RD-11, RD-15 and RD-16 were revised in round 2 after the owner's cross-check. Each RD entry has been written into gate v10 (C39–C41) or the master documents as the "Lands in" column says; Part F lists the result.

### E.1 Draft rulings

| ID | Ruling | Replaces / resolves | Lands in |
|---|---|---|---|
| **RD-1** Key types | Every foreign-key column takes the type of the referenced key: `TEXT` for `tenant_id`, `user_id`, `workspace_id`, `execution_id`. *(Round 2)* **Owner choice: `workers.worker_id` and every column that references it are `TEXT`.** DATABASE.md declares `UUID` in `workers`, `worker_leases` and `worker_assignments` but `TEXT` in `worker_versions`, `worker_deployments`, `execution_ownership` and `event_subscriptions`; `TEXT` is the majority and matches every other key. This overrides the gate §7.3 default of changing the referencing column to match the referenced one. Preflight items 15/P3 report every mismatch in the real schema. | Part A-2; summary #7 | Spec v1.2.0 §2; gate C39; DATABASE.md |
| **RD-2** Timestamps | New time columns stay **`TIMESTAMPTZ`**, compared only with database `NOW()` (I-019). They are **not** converted to `REAL`: timestamps take no FK, and `REAL` would contradict C33 and the M1 "no TEXT timestamps" trap. Existing `REAL` columns are left as they are. | Owner suggestion "TIMESTAMPTZ→REAL" (withdrawn) | Spec v1.2.0 §2; gate C39 |
| **RD-3** Tenant and RLS | `tenant_id TEXT NOT NULL` + the standard RLS policy on `operation_quotas`, `worker_spawn_audit`, `worker_group_members`, `execution_batches`, `worker_config_versions` and `session_memory`. `worker_groups` and `skill_definitions` already carry `tenant_id` and need only the policy. Deferred tables get the columns in the spec now, so they're correct whenever they land. | Part A-3; summary #8; C34 | Spec v1.2.0 §2; gate C39 |
| **RD-4** Two-phase admission | **Phase 1, admission** (stateless; runs at S12 entry and again before every step, gate §8 step 1): G1–G11, plus G12a/G13a (tenant/workspace pause and activation) and a read-only G16 quota precheck. REJECT-type gates are evaluated before G7 (capacity QUEUE). **Phase 2, worker-eligibility filters** (pure; gate §8 step 2, after the candidate pool is built and before locality scoring): worker/group pause (G12b), worker activation (G13b), assignment (G14), runtime/capability match (G17). If no candidate remains → `no_worker`, with the filter reason in the ledger event. Gate numbers stay stable for the C30 mapping. | Part B WM-1; summary #2 | Gate C39; WORKER_LIFECYCLE §10, §13, §16 |
| **RD-5** Pause semantics | Pause and scheduled activation block **new runs and new leases only** (drain semantics). A pause set while a run is RUNNING does not cancel its steps. The hard stop remains the kill switch (C23). | WM-2 | Gate C39; IDENTITY §8.4 |
| **RD-6** Quota consumption | Consumed **once per run** in the durable-admission transaction (gate §7.2), protected by the `(tenant_id, request_id)` duplicate check, never in the per-step gate (which runs per step and per re-entry). Every applicable level is updated in one transaction, in the fixed lock order tenant → workspace → worker, with `UPDATE … SET used_count = used_count + 1 WHERE … AND used_count < limit_value RETURNING …`. Zero rows at any level → roll back: hard → entry DENY `quota_exhausted` (writes nothing), soft → QUEUE with upgrade text in `detail`. Refund: only for runs that end CANCELLED with no step COMPLETED, recorded as a ledger event. New invariant **I17**: `used_count ≤ limit_value` for every hard quota. | Part A-5/A-6; WM-7; summary #6; owner suggestion "at gate evaluation" (corrected) | Gate C39, §7.2, §17 |
| **RD-7** Admin bypass | Membership role `owner`/`admin` **in the run's workspace**, read live. G14 compares `assigned_user_id` with `PrincipalChain.original_principal_id`, not `user_id`. Spec role names `TENANT_ADMIN`/`TENANT_OWNER` are replaced. | WM-8; summary #14 | Gate C39; IDENTITY §5, §6 |
| **RD-8** One execution path | B0–B7 and every stage-skipping `runtime_type` route are removed. Browser/RPA/vision/human/rules/data workers run S0→S15. Recorded workflows are `SkillDefinition` compositions planned at **S9**. Speed-ups are made through FAST/REFLEX strategies with no LLM call, never by skipping stages. | WM-4; summary #1; I-023; Principle 8 | Spec v1.2.0 §6.5, §8; FINAL_ARCH §37a; PIPELINE §21 |
| **RD-9** What `runtime_type` does | `runtime_type` influences S7 routing (`RuntimeRoutingDecision`), S5 binding choice, and the RD-4 eligibility filter. **It never makes S12 choose an adapter:** the adapter comes from the binding frozen at S5 (I-002, I-010; no re-resolution in S12). Browser providers (Playwright/Apify/BrowserUse) are separate bindings. | Summary #16; owner suggestion "runtime_type selects the adapter in S12" (corrected) | Spec v1.2.0 §6.5, §8; PIPELINE §21 |
| **RD-10** Worker taxonomy | `runtime_type` is the **single new enum** (`llm, rules, vision, browser, rpa, data, rag, code, human`). No `WorkerType` enum exists in the documents, and none is added. Plan/event/hybrid is **derived** from active `WorkerSubscription` rows. `worker_class` is unchanged. `worker_type` is dropped from `worker_templates` and `skill_definitions`. | Part A-10/A-11; owner suggestion "merge runtime values into WorkerType" (corrected) | Spec v1.2.0 §2, §3; DATA_CONTRACTS §50 |
| **RD-11** Replanning | Out of scope for S12–S15. The model for later: a replan starts a **new child execution** through S0→S15 with its own manifest, admission and budget; the parent consolidates normally. *(Round 2)* `execution_runs.parent_execution_id` is **not** added in this phase: nothing in S12–S15 would read it, so it lands together with its first consumer (replanning or delegation). F0 and F31 move out of P0 (F31 → P2). | WM-6; summary #5 | Gate C41; spec v1.2.0 §1, §6.1 |
| **RD-12** Batch | Out of scope for S12–S15 (it depends on M11, M12, M16, M19; parallel steps are deferred; C36). Model for later: a batch = N ordinary PlanSteps from the BATCH strategy at S9, each with its own `plan_step_id`, so it gets its own idempotency key, recovery and §10 consolidation. It adds no new state machine. F9 moves P0 → post-S15. | WM-5; summary #3, #4, #12 | Gate C40; spec v1.2.0 §1, §4 |
| **RD-13** Spawning | Out of scope for S12–S15. F7 moves P0 → post-S15. G15 becomes a check inside `spawn_child_worker()`, not an admission gate, with the Part A-7 fixes. | Part A-7 | Gate §14 deferred list; spec v1.2.0 §1, §3 |
| **RD-14** Autonomy | The existing `AutonomyLevel` stays the only autonomy enum. Any per-grant concept is restrict-only under a distinct name, and deferred (it needs S0–S11 change control). | Part A-12; summary #10 | Spec v1.2.0 §6.6; DATA_CONTRACTS |
| **RD-15** Layer vocabulary | The spec's §7 "Seven-Layer Architecture" is renamed **"Stability Tiers T1–T7"** *(round 2: the spec's section ranks stability, and "Layer" is the word that collides)* and moved to FINAL_ARCHITECTURE §30 (Evolution Path). The name "Layer" stays reserved for §6. | Summary #11 | Spec v1.2.0 §7; FINAL_ARCH §30 |
| **RD-16** FINAL_ARCHITECTURE numbering | Keep every section number that other documents cite. *(Round 2)* Of the 16 references to §38/§39/§41/§45/§46 in other documents, most are unambiguous (DATA_CONTRACTS Owner lines §39, §45, §46; DATA_CONTRACTS:2458 `CorrelationRule` → §41 Event Correlation; REPAIRS_APPLIED:21, :41, :90 refer to DATA_CONTRACTS numbers). The genuinely ambiguous ones are: LAYA_DECISION_ADAPTER:16, :164, :168, :279, :809 (§38 — intended Runtime Contract); S12_S15_EXECUTION_GATE:1224 and REPAIRS_APPLIED:138 (§38 — intended the manifest section "38.."); S12_S15_IMPLEMENTATION_PLAN:49 ("invariants §41"). Renumber only the orphaned duplicate headings, restore the missing "Future Worker Platform Compatibility" heading, remove the duplicate rows I-022…I-025, and sweep all references **in the same commit**. Re-pin only after S0–S11 certification (plan §1 item 3). | Summary; Part C.2 pre-existing defects | FINAL_ARCH; every document citing it |
| **RD-17** Milestone references | Every milestone reference in the spec is rewritten to a plan v2/v3 milestone ID (M0–M21, M8a) or to "post-S15 phase: <name>". "W7" is removed; W-numbers belong to EXECUTION_PLAN.md. The spec has no standalone milestone table to delete: the references are scattered (§5.4, §6.2), and §10 is missing. | Summary #17 | Spec v1.2.0 |
| **RD-18** Session 0 prompt | Gate revision check v8 → v10, or v9 if C39 is not adopted (today it STOPs against v9). "Gate items 3–9" → "3–16". The prompt's own items 10–15 are renumbered P1–P6 so they no longer clash with gate items 10–14. Add the worker-management preflight items (gate 15/16). | Part C.5; owner points A, B | S12_SESSION0_PREFLIGHT_PROMPT.md |

### E.2 Priority changes to the spec's feature inventory

| Feature | Spec tier | Draft tier | Why |
|---|---|---|---|
| F0 `parent_execution_id` | P0 | Post-S15 *(round 2)* | No consumer in S12–S15; lands with replanning or delegation (RD-11) |
| F1–F5 settings, pause, activation, levels, assignment | P0 | P0 | RD-4, RD-5, RD-7 |
| F6 quota | P0 | P0 (hard quota + precheck) | RD-6 |
| F7 spawning | P0 | Post-S15 | RD-13 |
| F8 worker type enforcement | P0 | P0 as an RD-4 filter on `runtime_type`/capability | RD-4, RD-10 |
| F9 batch | P0 | Post-S15 | RD-12 |
| F31 replanning | P0 | P2 | Needs S12 first; circular (RD-11) |

### E.3 Adjusted resolution order

1. Owner confirms or changes RD-1 … RD-18.
2. Fix the Session 0 prompt (RD-18). The type audit depends on its preflight output.
3. Run the preflight; audit key types against the real schema (RD-1); keep timestamps `TIMESTAMPTZ` (RD-2).
4. FINAL_ARCHITECTURE numbering clean-up and reference sweep (RD-16).
5. Gate v10: C39 (RD-1…RD-7, I17, I18), C40 (RD-12), C41 (RD-11); deferred list (RD-13).
6. Spec v1.2.0: remove the browser bypass (RD-8, RD-9), taxonomy (RD-10), autonomy (RD-14), tiers (RD-15), milestones (RD-17), the Part A corrections and the E.2 tiers.
7. Plan v3: M1 schema additions, M8a, deferred register entries.
8. Apply the Part C edits to the master documents, with repair markers.
9. Re-pin, but only after S0–S11 is certified (plan §1 item 3).

---

## Part F — Propagation status (2026-09-29)

Every edit carries a `Worker-management repair (RD-n)` marker (or `(C39–C41)` in the gate), so it can be found with `grep -n "Worker-management repair"`.

### F.1 Applied — the eight target documents

| Document | New version | Applied | Status |
|---|---|---|---|
| `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md` | (header note) | §3 key-type note and invariant 5; §10 gates 12a/13a/16 and evaluation order; §11 reason codes; §13 worker-eligibility filters; §15 Rule 1 scope and **Rule 7 rewritten per C25 (E5)**; new **§16 Worker Management Settings** (columns, phase-1/phase-2 checks, quota consumption, precedence, deferred list, reason codes); TOC and relationships | ✅ UPDATED |
| `FINAL_ARCHITECTURE.md` | 4.4.0 → **4.5.0** | TOC rebuilt to match body; orphans renumbered **§37b** (manifest, was "38.."), **§37c** (conflict log, was 39), **§37d** (patterns, was 40), **§50** invariants (was the duplicate "41" ×2), **§51** extension points (heading restored); duplicate I-022…I-025 removed; **I-029** one execution path; Principle 8 reference fixed (I-024 → I-023/I-029) and browser/RPA line; §15 BATCH note; §21 memory classification (renamed "Historical"); §26 key-type note; §29 five decisions; §30 **Stability Tiers T1–T7**; §33 load note; §34 terms + restored "Documented Conflicts" heading; §51 rows 16–19 + feature mapping; unclosed code fence before Appendix A closed | ✅ UPDATED |
| `S12_S15_EXECUTION_GATE.md` | v9 → **v10** | Header; §0 C1–C41; §1 MAY/MUST NOT; §2 items **15–16**; **C39, C40, C41**; §7.1 item 7; §7.2 quota consumption; §7.3 v10 schema; §8 steps 1–2; §14 deferred list; §16 **suite 20**; §17 **I17, I18**; §20 report line; C38 table §38 → §37b; Appendix B | ✅ UPDATED |
| `S12_S15_IMPLEMENTATION_PLAN.md` | v2 → **v3** | Header and v3 note (M9.5, M12.5, W7 withdrawn); precondition 6; document roles (gate v10, FINAL v4.5.0, invariants §50, spec as reference only); M0 items 1–16; M1 schema + golden; **new M8a** with golden, sabotage, traps; §5 batches and invariant growth (I17/I18); ★ M8a; §7 risks; §8 owner step | ✅ UPDATED |
| `S12_SESSION0_PREFLIGHT_PROMPT.md` | — | Gate revision v8 → **v10** (both places); gate items 3–9 → **3–16**; own items renumbered **P1–P6**; P3 table list and FK-type check; report block | ✅ UPDATED |
| `DATA_CONTRACTS.md` | — | TOC entries §50–§53 (+ note on missing §38–§49 entries); `AutonomyLevel` canonical comment; **§37 fencing text rewritten per C25 (same defect as E5)**; new **§50 WorkerManagementProfile + RuntimeType**, **§51 OperationQuota**, **§52 reason codes**, **§53 SkillDefinition/SkillStep (DEFERRED)**; list of contracts deliberately not added | ✅ UPDATED |
| `IDENTITY_AND_TENANCY.md` | — | §5 hierarchy level "Worker Management Settings" (restrict-only); settings JSONB contract (inert keys marked); admin roles `owner`/`admin`; autonomy note; §6 rules 5–6 (assignment, sub-agents); **§7 Worker Lifecycle fixed to DRAINED/TERMINATED**; §8.4 pause ≠ kill switch | ✅ UPDATED |
| `PIPELINE_STAGES.md` | — | §14 "Worker Management in S12" pointer (stages S9 for batch/skills, never S7); §19 five negative-path rows; §21 `runtime_type` never removes a stage | ✅ UPDATED |

### F.1a Applied — `DATABASE.md` (2026-09-29, second pass)

| Area | Applied | Status |
|---|---|---|
| Key types (RD-1) | `workers.worker_id` and `workers.tenant_id` UUID → `TEXT`; `worker_leases.lease_id`, `worker_leases.worker_id`, `worker_assignments.assignment_id/worker_id/execution_id` UUID → `TEXT`; `task_id` UUID → `TEXT` in both tables. The pass found two mismatches beyond the review: `execution_ownership.lease_id TEXT` → `worker_leases.lease_id UUID`, and `worker_assignments.execution_id UUID` → `execution_runs.execution_id TEXT`. A mechanical check of every `REFERENCES` and `FOREIGN KEY` in the file now finds **0 type mismatches**. | ✅ UPDATED |
| Management columns (C39) | `workers`: `settings`, `assigned_user_id` (FK `users`), `paused_until`, `scheduled_activation_at`, `runtime_type` with CHECK; `tenants` and `workspaces`: `paused_until`, `scheduled_activation_at` (typed `TIMESTAMPTZ` columns, not JSON keys) | ✅ UPDATED |
| New table (C39) | `operation_quotas` with `tenant_id`, `UNIQUE NULLS NOT DISTINCT`, count/period/scope CHECKs, lookup index, consumption SQL, refund rule; list of deferred tables and columns **not** created (incl. `parent_execution_id`) | ✅ UPDATED |
| RLS, indexes, integrity, migrations | RLS enable + `tenant_isolation` policy on `operation_quotas`; index table rows; NOT NULL rows; "Operation Quota Constraint"; migration `018_worker_management.sql` | ✅ UPDATED |

Also applied (RD-16 reference sweep): `REPAIRS_APPLIED.md:138` "§13/§38" → "§13/§37b". The LAYA_DECISION_ADAPTER §38 references are now unambiguous (only one §38 remains: Runtime Contract) and were left unchanged.

### F.2 Round-2 corrections to this review (applied above)

| # | Correction | Where |
|---|---|---|
| 1 | "Platform Maturity Tiers" → **"Stability Tiers T1–T7"** | Part C.2, RD-15 |
| 2 | `parent_execution_id` **deferred** (no consumer in this phase) | Part B WM-3, C.3, RD-11, E.2 |
| 3 | Explicit owner choice: `workers.worker_id` and all referencing columns are **`TEXT`**, overriding the gate §7.3 default | RD-1 |
| 4 | The genuinely ambiguous cross-references listed by file:line instead of a count | RD-16 |
| 5 | Rule 7 description corrected: `worker_leases.fence_token` still exists; C25 changed the token source and the check target | Part C.1 |

### F.1b Applied — remaining documents and the spec (2026-09-29, third pass)

| Document | Applied | Status |
|---|---|---|
| `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` → **v1.2.0** | Rewritten per Part A and RD-1…RD-18: change table; feature tiers (E.2); corrected DDL (in-phase vs deferred); two-phase admission and eligibility; batch as PlanSteps; propagation record; replanning as child execution; skills at S9; memory classes; routing table without stage skipping; restrict-only autonomy; policy chain rebased on IDENTITY §5; Stability Tiers; browser/RPA under S0→S15; **new §9 S0–S11 Protection List and §10 Implementation Sequence**; corrected appendices. Status: REFERENCE — masters govern | ✅ UPDATED |
| `VOCABULARY_INDEX.md` | Terms: runtime_type, Worker Group, Pause, Kill Switch, Scheduled Activation, Eligibility Filter, Operation Quota, Stability Tier, Skill Composition; terms to avoid (WorkerType, TENANT_* roles, Seven-Layer, browser path, batch state); conflict rows; `User` role example fixed | ✅ UPDATED |
| `STATE_TRANSITIONS.md` | §4 note (pause/activation are not states); I-9 (eligible worker ↔ new lease), I-10 (hard quota bound); §16 invalid values (PAUSED, SCHEDULED, batch statuses); new §17 "no new state machines" | ✅ UPDATED |
| `MUTATION_SAFETY.md` | §1 browser/RPA classification (round-3 correction); §3 `worker_policy_ceiling` (lower-only) | ✅ UPDATED |
| `SECURITY.md` | New §12a worker-management security (settings ≠ authorization, assignment, audited admin bypass, pause vs kill switch, quota integrity, server time, one path, webhook secret refs + SSRF); TOC; checklist | ✅ UPDATED |
| `PROVIDER_ADAPTERS.md` | New §9 browser/RPA adapters: one adapter per provider, provider = binding, probe/observe, credentials, eligibility | ✅ UPDATED |
| `EVENT_GATEWAY_AND_ROUTER.md` | §14.7 pause does not change routing (events replayable), §14.8 plan/event/hybrid derived; two tests | ✅ UPDATED |
| `VALIDATION.md` | Worker-management test index (13 tests) | ✅ UPDATED |
| `BUILD_READINESS_MATRIX.md` → 1.1.0 | Rows 9, 10 updated; rows 25 (gate v10), 26 (spec v1.2.0, REFERENCE) | ✅ UPDATED |
| `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` | New Section 19: C39–C41, other rulings, deferred list, open items WM-O1…WM-O3 | ✅ UPDATED |
| `REPAIRS_APPLIED.md` | New "S12–S15 GATE v10 WORKER-MANAGEMENT REPAIRS" table (19 documents) | ✅ UPDATED |

### F.3 Still open (recorded, not blocking)

| Item | Where recorded |
|---|---|
| DATA_CONTRACTS duplicate §31 headings (not renumbered: cited elsewhere) | Register WM-O1 |
| FINAL_ARCHITECTURE had a TOC entry "§42 Schema and API Compatibility" with no section | Register WM-O2 |
| Skill Factory compile path for data-defined skill compositions | Register WM-O3 |
| `COMPONENTS_BLUEPRINT.md`, `EXECUTION_PLAN.md`, `RESOLVE_LAYER.md`, `RELIABILITY.md` not touched: no worker-management content required for S12–S15 (C39 changes no directory, resolution or guard rule) | — |
| Re-pin on the VPS only after S0–S11 certification | Plan §1 item 3 |
