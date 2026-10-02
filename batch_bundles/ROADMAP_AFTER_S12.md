# What is left after S12: the full remaining roadmap

Snapshot of 2026-10-01 (`s12-work`). Sources: the gate (`docs/implementation/S12_S15_EXECUTION_GATE.md` §1, §14,
§21, §22, C40, C41), the plan (`S12_S15_IMPLEMENTATION_PLAN.md` §4), `docs/proposals/ROADMAP_PHASES.md`,
`docs/implementation/SUPERSESSION_AWARE_BLOCKER_REGISTER.md`, `docs/gates/S12_RECORDS.md`, `S12_DEFECTS.md`,
`S12_STOPS.md`, and the batch guides in this folder.

This file only orders the work. It decides nothing. Where it maps an item into a phase that the source documents do
not name, it says **(proposed)**, and the owner decides at the M21 deferred register.

```text
Step 0  Owner close-out of M1–M9          (code done; owner rows open)
Step 1  The rest of the gate: M10–M21     (S12 loop → S13 → S14 → S15 → recovery → certification)
Step 2  Certification and tag             (owner: report §20, deferred register §21, tag s12-s15-certified)
Step 3  Deferred phases, in the gate's order (§21), with the roadmap leftovers placed into them
```

---

## Step 0: close M1–M9 (owner work, no new code)

M1–M9 are built and verified on `s12-work`:

- golden 490/490, sabotage 33/33;
- `tests` 836, `tests_agent` 93, `tests_postgres` 330, S0–S11 19/19 (with `PYTHONPATH=src`).

`owner_certify_s12.py --milestone M9` fails only the owner rows.

| Action | Detail |
|---|---|
| Pin the golden set | B2–B5 golden files, their sabotage patches and the helpers `_lease_base.py`, `_budget_base.py`, `_guard_base.py` are unpinned; `fixtures/db.py`, `invariants.py` and `README.md` changed since the B1 pin |
| Close STOPs | STOP-001 `ruled` → `applied`; STOP-002, STOP-004, STOP-005 open but their causes are resolved |
| ★ reviews | M1 schema (`S12_M1_SCHEMA_REVIEW.md`, `B1_M01-M04/SCHEMA.md`), M8a worker management |
| Decide **DEF-003** | the frozen confirmation store's UPDATEs lack a `tenant_id` predicate; forced RLS is the only guard |
| `owner_verify_s12.ps1 M1…M9` | only the owner moves milestone statuses |

Guides: `B1_M01-M04/`, `B2_M05-M09/`, `IMPROVEMENT_GUIDE_B1-B2.md`.

---

## Step 1: the rest of the gate (M10–M21)

S12 is **not** only M6–M14. M1–M5 are its foundation (schema, fencing, machines, confirmation check). The S13 work
spreads over M13 (probe and episodes, in the S13 package), M15 and M16. S14 is M17, S15 is M18, and M19–M21 cut across
every stage.

| Milestone | Stage | What | State on `s12-work` | Blocked by |
|---|---|---|---|---|
| M10 | S12 | adapter interface, mock adapter, reliability guard | golden + draft reference only | STOP-004/005 closure |
| M11 | S12 | idempotency ledger and retry | golden + draft | — |
| M12 | S12 | the loop, dependents, terminal reasons; closes **DEF-002, DEF-004**; ports `tests_postgres` (CONF-035) | golden + draft | — |
| M13 | S12/S13 | probe path, EXECUTION episodes | golden + draft | — |
| M14 ★ | S12 | live revalidation, cancellation | golden + draft | owner review |
| M15 | S13 | verification, VERIFICATION episodes | golden + draft | **CONF-005** |
| M16 | S13 | consolidation, quota refund | golden + draft | — |
| M17 | S14 | dead letters, explicit rollback | golden + draft | — |
| M18 | S15 | response envelope and redaction | golden + draft | CONF-020 (where the quota upgrade text goes) |
| M19 | all | crash recovery, 10 fault-injection points, sweeper | golden + draft | **CONF-042, 043, 044, 046, 047** |
| M20 | all | real subprocess kills, two Worker Runtimes, SKIP LOCKED, RLS | golden + draft | **CONF-045** |
| M21 ★ | all | 8 journeys, architecture suite, seams, metrics, performance baseline | golden + draft | owner final review |

Guides: `B3_M10-M14/`, `B4_M15-M18/`, `B5_M19-M21/`, `IMPROVEMENT_GUIDE_B3-B5.md`.

**Gaps inside the gate that have no owner yet. Decide them before or at M21:**

| Gap | Source | Why it matters |
|---|---|---|
| Production sources for the live admission snapshot and the pre-flight check | CONF-027 ("M21 at the latest") | the drafts and goldens inject both; nothing reads the real gates from the database |
| Pre-flight parameter validation | gate §8 step 6; roadmap D1e | no kernel input schema exists to validate against |
| An operator path to retry a dead letter | B4 review | `retry_dead_letter` exists with injected callables; nothing calls it in production |
| Soft-quota upgrade text | CONF-020 | an entry DENY never reaches the S15 envelope |

---

## Step 2: certification (owner)

- `owner_certify_s12.py` N/N PASS.
- The certification report per gate §20.
- **The deferred register** (gate §21): every §14 item and every open question, each with a target phase (Step 3).
- `owner_verify_s12.ps1`, then the owner creates tag `s12-s15-certified`.

Gate §22: "Only after this gate is certified may work begin on the next phase (configuration portability, then the
multi-node fleet). Do not cross the phase boundary."

---

## Step 3: the deferred phases (gate §21 order), with every leftover placed

The gate's order: documentation gaps → secrets and data governance → configuration portability → HITL and
notifications → LLM layer → multi-node fleet → observability and reliability → AI Worker product layer → adapter
packaging → AI-platform adapters, frontend, billing → SDK and CLI.

Below, **[gate]** = deferred by the gate itself (§14, C36, C40, C41, rulings); **[road]** = `ROADMAP_PHASES.md`;
**[reg]** = blocker register; **[S12]** = found during S12 (records, reviews, the batch guides).

### 3.1 Documentation gaps
- **[reg]** P1-E authorization algebra (effective-authorization intersection, IDENTITY_AND_TENANCY §8.3).
- **[reg]** P1-G kill-switch hierarchy for running executions.
- **[reg]** ADR-2 cross-tenant audit reads (`audit_reader` scope).
- **[reg]** ADR-6 delegation-depth persistence location.
- **[S12]** CONF-008: registry versioning. Today any registry bump denies every plan certified earlier.
- **[S12]** CONF-005: the AutonomyLevel source for verification-layer selection.
- **[road]** D1d: the real observation-metadata catalog for production write operations. Owner work; without it,
  verification cannot observe real writes.

### 3.2 Secrets and data governance
- **[road] B8 (urgent, owner):** revoke the DeepSeek test key committed on the `exciting-brahmagupta` and
  `peaceful-brown` branches.
- **[reg]** MC-058: credentials break tenancy.
- **[road]** B5: KEK rotation tool (re-wrap `wrapped_dek`), `event_log` retention **(proposed placement)**.
- **[S12]** DEF-003, if the owner accepted RLS as the only guard: revisit under change control.

### 3.3 Configuration portability
- **[S12]** admission retry timings and other hard-coded infrastructure constants into the settings object (§21 S1;
  `IMPROVEMENT_GUIDE_B1-B2.md` IMP-M08-1).
- **[road]** B5 rate limiting on `/execute`, `/confirmations` and webhooks **(proposed placement)**.

### 3.4 HITL and notifications
- **[gate]** the HITL channel for human verification (today the human layer dead-letters at once, D4).
- **[gate]** the notification channel; **alert delivery** (M17 only records an alert event and an ERROR log line).
- **[gate]** automatic rollback triggers (rollback stays explicit only, D2).

### 3.5 LLM layer (evaluation harness, model fallback, cost)
- **[gate]** vector memory / RAG on pgvector (ADR-14 and MR-1 decided; **MR-3, MR-4, MR-9 open**).
- **[gate]** LayaDecisionAdapter: blockers LB1–LB11.
- **[gate/road]** step-to-step data flow (C36 target phase "LLM layer / planning"; roadmap D2, P0-B):
  - `input_schema`/`output_schema` with a `secret` flag;
  - `StepOutputReference` / `StepParameterBinding`;
  - `plan_hash` over references (R-AG);
  - S12 resolving references at run time (entry check 5a changes).
  - D2 changes S0–S11 code, so it goes through change control.
- **[road]** B6: LLM usage billing (`llm.token`) **(proposed placement)**.
- **[road]** B2: observe real empty, truncated and content-filtered provider replies.
- **[gate]** replanning as a child execution (C41, RD-11); `parent_execution_id` arrives with its first consumer.

### 3.6 Multi-node fleet
- **[gate]** multi-node fleet, a fleet dispatcher behind `ExecutionDispatcher`.
- **[gate/reg]** distributed circuit breakers, per (provider, operation) (ADR-5).
- **[reg]** P1-C scheduler bounded queue, fairness and backpressure.
- **[gate]** worker version and deployment lifecycle (`workers.heartbeat_at`, `drain_state`, `runtime_version`,
  `last_assignment_at`: present, unused).
- **[S12]** CONF-045 lease renewal during a step (if not ruled in M20); CONF-044 / **[reg]** ADR-11 checkpoints
  beyond a hint.
- **[gate/road]** parallel step execution; DAGs, fan-out/fan-in, `any`/`threshold` joins (roadmap D3, after S15).

### 3.7 Observability and reliability
- **[gate]** a real exporter behind the `MetricsHook` (no-op in this phase); tracing.
- **[gate]** use the M21 per-step baseline (p50/p95) as the starting reference.
- **[road]** Phase F monitoring **(proposed placement)**.

### 3.8 AI Worker product layer
- **[gate]** worker management beyond C39:
  - worker-level quotas; per-worker retry and timeout policy;
  - sub-agent spawning and `worker_spawn_audit`;
  - batch (C40: N ordinary steps, no batch table);
  - worker groups, config versioning, state-change webhooks;
  - L2 session memory, memory classification;
  - progressive autonomy, PolicyEngine;
  - templates, entitlements, marketplace listing.
- **[road]** C3 EventRouter and subscription matching; C4 event replay after a pause. No gate milestone owns them,
  although the roadmap says they "belong to S12/S13" **(proposed placement)**.
- **[road]** B7: writers for `conversation_results` and `files` (no real `$ref`/`$file` resolves yet)
  **(proposed placement)**.
- **[road]** B4 remainder: tenant creation, invitations, IdP linking **(proposed placement)**.

### 3.9 Adapter packaging
- **[gate]** real provider adapters, with per-kernel probe and observe methods (**[reg]** RES-5).

### 3.10 AI-platform adapters, frontend, billing
- **[gate]** browser/RPA adapters and skills.
- Frontend; billing beyond `llm.token`.

### 3.11 SDK and CLI

### Release (roadmap Phase F; runs alongside Step 2 and every later tag)
- Deployment configuration (secrets, CORS, KEK), runbook, monitoring, the certification report and tag.
- **[road]** A7: whether the S12 prototype code stays in this tree.

---

## Data model leftovers (from `B1_M01-M04/SCHEMA.md`)

These columns exist and nothing reads or writes them. Each belongs to the phase named:

| Columns | Phase |
|---|---|
| `workers.worker_class`, `runtime_version`, `heartbeat_at`, `last_assignment_at`, `drain_state` | 3.6 fleet |
| `checkpoints.*`, `execution_ownership.checkpoint_sequence` | 3.6 (CONF-044, ADR-11) |
| `dead_letters.is_idempotent`, `next_retry_at` | 3.4 (operator retry, HITL) |

`state_transitions.reason` is nullable; making it NOT NULL is a 016+ migration and needs a ruling (3.1).

---

## When each deferred workstream happens (and what it reopens)

None of these is built now. Gate §14 says "Still deferred (record; do not implement)", and §22 forbids crossing the
phase boundary before the `s12-s15-certified` tag. Each one goes into the M21 deferred register with the phase below.

| Workstream | Gate phase | Earliest start | Forces S0–S11 re-certification? |
|---|---|---|---|
| **2a** step-to-step data flow (roadmap D2, register P0-B): `StepOutputReference` / `StepParameterBinding`; `input_schema`/`output_schema` with a `secret` flag (D2a); the six S9 validation rules; `plan_hash` over references (R-AG), C36 replacement (R-AH), secret classification (R-AI); S12 resolves references at run time; S10 shows them | LLM layer / planning (C36's target) | after the S12–S15 tag | **yes**: S4, S9, S10 change (§19.3). It also **re-certifies S12–S15**, because entry check 5a, the loop, recovery and idempotency change |
| **2b** branching graphs (roadmap D3): DAGs, fan-out/fan-in, `join_mode` `any`/`threshold`, parallel steps, S7 routing for `complex` | after 2a ("after S15") | after 2a ships | yes (S7 routing, S9 planning) |
| **2c** real provider adapters (register RES-5, MC-048): one adapter per provider behind `BaseAdapter`; per-kernel `probe()` and `observe()`; error classification; the D1d observation catalog | adapter packaging (9th in the gate order) | after the tag; the owner may move it earlier | no: it plugs in behind `BaseAdapter`, and the guard contains failures |
| **2d** memory / RAG (ADR-14 decided): pgvector, per-tenant partitions, `MemoryScope`, tier-2 object store | LLM layer | after MR-3 (embedding contract), MR-4 (pipeline rulings), MR-9 (`MemoryWriteBarrier`) are ruled | only if MR-4 puts vector discovery into S3, or counts embeddings against I-011 |
| **2e** LayaDecisionAdapter (LB1–LB11): REFLEX choice steps in S12 and event noise filtering before S0 only | LLM layer | after the LB rulings | yes for LB1 (`decide()`), LB2, LB6, LB7, LB8, LB10 (frozen contracts) |
| **2f** multi-node fleet: ADR-5 breaker persistence (PostgreSQL + advisory locks); P1-C queue, fairness and backpressure; a dispatcher beyond `InProcessDispatcher`; ADR-6; worker version and drain lifecycle; the M21 p50/p95 as baseline | multi-node fleet | after the tag | no: behind the §21 S2, S3, S4 seams |
| **2g** HITL channel, notifications and alert delivery, automatic rollback triggers (open question D4) | HITL and notifications | after the tag | no |
| **2h** worker management beyond C39 and the product layer (worker quotas, `execution_policy` keys, sub-agents and `worker_spawn_audit`, batch C40, replanning C41, groups, config versioning, webhooks, L2 memory, progressive autonomy, PolicyEngine, browser/RPA, templates, entitlements, marketplace, `skills_prompt`/`llm_model` at S2, tenant model allow-list) | AI Worker product layer | after the tag | partly: progressive autonomy, PolicyEngine and the S2 consumption change certified code |

**Cross-cutting rule.** 2a, 2b, 2d (MR-4), 2e and parts of 2h modify certified S0–S11 code. Each goes through gate
§19.3:

- name the insufficient frozen contract;
- say why it cannot be solved inside the later phase;
- propose the smallest extension;
- state the re-certification impact.

Never edit certified code inline.

**Two corrections to earlier drafts of this list:**

- **2c:** in this phase adapters return `contracts.step_execution.AdapterResult`, not `KernelResult` (ruling CONF-021).
  The default probe is INCONCLUSIVE, so today every uncertainty dead-letters after three probes. Real `probe()` and
  `observe()` methods are what make the UNKNOWN path useful in production.
- **2g:** verification already has a human layer (M15). It is UNKNOWN at once and dead-letters as
  `human_verification_pending` (D4). What is missing is the HITL **channel** that lets a person answer it.

### What belongs to now, without starting deferred work

1. **Keep the seams intact during M10–M21:**
   - frozen binding at S5 and entry check 5a → 2a;
   - `ExecutionDispatcher` → 2f;
   - breaker behind an interface → ADR-5;
   - `MetricsHook` → observability;
   - step 4 of the loop left empty → Laya (LB9);
   - `rollback_execution()` explicit only → 2g.

   Breaking a seam now means rework later.
2. **Record each workstream** in the M21 deferred register with the phase above.
3. **Owner work that needs no code:**
   - D1d, the real observation-metadata catalog (2c depends on it; `tools/registry_readiness.py` exits 1 until it is
     filled);
   - B8, revoke the DeepSeek test key;
   - the design rulings MR-3/4/9 and LB1–LB11 (they gate 2d and 2e).

### A sequencing decision for the owner

The gate's order puts real adapters (2c) 9th, after the fleet and observability. Without them, and without D1d,
nothing real executes or verifies. If production use matters before the fleet, move adapter packaging and D1d earlier
in the deferred register; the owner orders those phases. 2a must stay in its phase, because it reopens S0–S11.
