# S12–S15 deferred register

Required by gate §21 ("Before certification, write every deferred item from Section 14 and every open question from
this gate into the blocker register with a target phase"). It also holds every item the S12 records ruled into the
register, and the items found while certifying M21 and cross-checking the first real adapters.

- **Status:** draft for the owner, written at `3c2a515` (M21 green at `ee9c334`), 2026-10-03.
- **Companion:** `docs/gates/S12_CERTIFICATION_REPORT.md`.
- **Format.** `DR-nn` ids are stable and never renumbered. A line leaves this register only by a later phase's commit
  that closes it (cite the commit), never by deletion.
- **Target phase**, in the order gate §21 fixes:
  1. documentation gaps
  2. secrets and data governance
  3. configuration portability
  4. HITL and notifications
  5. LLM layer (evaluation harness, model fallback, cost)
  6. multi-node fleet
  7. observability and reliability
  8. AI Worker product layer
  9. adapter packaging
  10. AI-platform adapters, frontend, billing
  11. SDK and CLI
- **Columns.** "Control now" says what holds in the certified phase. "Gate" marks items that must close before
  production (**GO-LIVE**) or before the adapter phase builds on them (**ADAPTERS**).

## 1. Documentation gaps

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-01 | `RUNNING → PARTIAL` is a legal edge that this phase never produces (no sub-operations) | gate §5 (step table note) | Appendix A keeps the edge; nothing writes it (I5) | |
| DR-02 | `execution_leases` duplicates `worker_leases`; only `worker_leases` is the lease of record | gate §5 (C25 note) | not read or written by S12 code | |
| DR-03 | `contracts/state_validators.py` (DATA_CONTRACTS §26) is non-canonical; delete it in the first post-S15 S0–S11 change-control batch | CONF-006 | architecture test (M3) forbids S12 code importing it | |
| DR-04 | The pre-flight has no kernel input schema: `PostgresPreflight` always returns valid. Define the schema in the registry (the `CapabilityMetadata.input_schema` contract exists; the database has no column), then implement the check | CONF-027, `adapters/postgres/preflight.py:9` | S11 validation and the adapters' own parameter checks (fail closed) | ADAPTERS |
| DR-05 | Deterministic golden case for the recovery-takeover race (a sweeper's stale candidate must not steal a live run between two steps, CONF-046 at the takeover). Today it is pinned by `tests_agent/test_recovery_takeover_conf046.py` and, only under load, by M20 `test_two_sweeping_processes_claim_every_orphaned_run_exactly_once` | fix `bdbc915`, test `ee9c334` | product fix in `leases.acquire`; agent regression test | |
| DR-06 | Prototype modules superseded by S12–S15: `engine/stages/s12_execute/guard.py` (old `ReliabilityGuard` on `StepAdapter`), `engine/stages/s12_worker_execution/handler.py` ("not certified, superseded"), `engine/providers/base.py` (`BaseProviderAdapter`). Remove under change control | cross-check 2026-10-03 | not on the S12 execution path | |
| DR-07 | Truth-model maintenance runbook: how `docs/truth_model/` is kept current when a later phase changes a state machine, contract or ruling | owner list | the truth model matches the code at this certification | |
| DR-08 | `docs/ADAPTER_IMPLEMENTATION_GUIDE.md` (commit `4181585`) is not usable as written: about 15 factual errors against the code and missing worker-runtime, routing, rate-limit, timeout, golden-scan and credential-store sections (review of 2026-10-03). Rewrite (v2) before agents use it | review 2026-10-03 | agents told to use `batch_bundles/LAYER_A/ADAPTER_SPECS/README.md` and `TEMPLATE.md` | ADAPTERS |

## 2. Secrets and data governance

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-09 | `confirmations.py` (frozen S0–S11) consume/expire/reject UPDATEs lack a `tenant_id` predicate; add it in the first post-S15 S0–S11 change-control batch, with DR-03 | DEF-003 (`wontfix` this phase), D-13 | forced RLS; the app role is NOSUPERUSER/NOBYPASSRLS; the Worker Runtime refuses a superuser or BYPASSRLS role (`startup.check_worker_runtime`, M21) | GO-LIVE |
| DR-10 | Composite idempotency-ledger key `(tenant_id, idempotency_key)`; the M11 change is made by the test-author session then | CONF-051 (D-11, alternative taken; migration 018 reverted `ce47e30`) | the key stays global (gate §8, C9); a key held by another tenant's row raises `IdempotencyConflict` | |
| DR-11 | Team-wide test API keys (`StaticCredentialProvider`: one token per provider for every tenant) must be removed and the tokens revoked. Replace them with an encrypted per-connection credential store (new migration; reuse the `WEBHOOK_KEK` envelope encryption of `webhook_credentials`) | owner decision 2026-10-03 (adapter test phase) | test workspaces only; keys never in git; lives only on `adapters-work` | **GO-LIVE** |
| DR-12 | Deployment must revoke EXECUTE on `s12_recovery_candidates` from PUBLIC and grant it to the runtime role only | CONF-042 | SECURITY DEFINER with pinned `search_path` (`pg_temp` last) | GO-LIVE |
| DR-13 | Data retention: the cleanup of `checkpoints.expires_at` / `idempotency_ledger.expires_at` runs manually; scheduling it is out of scope; it must never delete rows of a non-terminal run | gate §21 S7 | manual job only | |

## 3. Configuration portability

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-14 | **No production Worker Runtime.** `main.py --worker` is a stub, and `LoopDeps`, `ReliabilityGuard`, `RecoverySweeper` and lease renewal are composed only in test fixtures. Build the runtime composition (settings from the environment, Postgres stores, guard, sweeper, renewal, start-up checks, run pickup) as its own milestone with goldens | cross-check 2026-10-03 | every kernel component is certified; nothing runs admitted runs outside tests | **GO-LIVE**, ADAPTERS |
| DR-15 | Catalog versions: `kernel_ops` has no version column and `registry_versions` is a singleton, so a catalog version bump denies every plan awaiting confirmation. Operator rule: bump only when none are pending | CONF-008 | fail closed (deny), by ruling | |
| DR-16 | `kernel_ops.timeout_seconds` is stored but not used: every step runs under `Step.timeout` (default 30 s, never set by S9), capped by `S12_STEP_TIMEOUT_S` | cross-check 2026-10-03 | settings cap; C37 (`adapter_client_timeout_s < step_timeout_s`, `probe_timeout_s < step_timeout_s`) | ADAPTERS |
| DR-17 | The guard's default `probe_timeout_s` is 0.5 s, too short for real HTTP providers; deployments must set `S12_PROBE_TIMEOUT_S` (5–10 s) | cross-check 2026-10-03 | mock adapter only | ADAPTERS |

## 4. HITL and notifications

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-18 | HITL channel for the human verification layer | gate §14, D4 | the human layer returns UNKNOWN → DEAD_LETTER (`unknown_unresolved`, full evidence) | |
| DR-19 | Open question: no post-execution human-approval run state (a resolved dead letter never reopens a run) | gate D4 | run and step stay terminal; only the dead letter, the reservation and audit change | |
| DR-20 | Notification channel (part of the fleet item in gate §14) and alert delivery | gate §14 | ERROR logs and alert events only | |

## 5. LLM layer

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-21 | **No production `SemanticAssessor`.** The semantic verification layer is injected and `None` by default, so every step that requires it (risk ≥ `SEMANTIC_RISK` 0.7, or IRREVERSIBLE) ends UNKNOWN → VERIFICATION episode → dead letter | cross-check 2026-10-03, D6 | D6 rules hold (semantic may only FAIL or UNKNOWN; never overrides a deterministic FAIL; strict enum parse) | GO-LIVE for risk ≥ 0.7 |
| DR-22 | Vector memory / RAG: pgvector only, `MemoryScope` contract; MR-3 (embedding contract), MR-4 (pipeline rulings), MR-9 (`MemoryWriteBarrier`) still open | gate §14, ADR-14, MR-1 | nothing implemented, migrated or tested | |
| DR-23 | LayaDecisionAdapter: LB1, LB2, LB4, LB7, LB8, LB9, LB10, LB11 `DECISION_REQUIRED`; LB3 `PROPAGATION_REQUIRED`; LB5 `DECIDED` (pending propagation); LB6 `OPEN`; plus XS-1 and OD-L3. Gate §8 step 4 stays empty | gate §14, `LAYA_DECISION_ADAPTER.md` §register | design note only; nothing in `src/` (M21 architecture test) | |

## 6. Multi-node fleet

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-24 | Multi-node fleet | gate §14 | single node; several Worker Runtimes on one database are certified (M20: fencing, SKIP LOCKED sweeps, takeover) | |
| DR-25 | Distributed circuit breakers; per-(provider, operation) keying | gate §14, CONF-022 | `InProcessCircuitBreaker` keyed per provider, behind an injected interface (S3) | |
| DR-26 | Admission gates `provider_allowed` and `circuit_open` have no database source (hard-coded to pass in `PostgresAdmissionSnapshot`) | cross-check 2026-10-03, CONF-027 | the guard's breaker refuses calls (`circuit_open`) at call time | |
| DR-27 | Parallel step execution | gate §14 | sequential topological order | |
| DR-28 | Worker version and deployment lifecycle | gate §14 | `workers` rows managed by the admin API (M8a) | |

## 7. Observability and reliability

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-29 | Automatic rollback triggers | gate §14, D2 | explicit `rollback_execution()` only; inverses through the full guard; failed inverses dead-lettered (`origin = rollback`, `NONE`) | |
| DR-30 | Health and billing records are in-memory lists (`InProcessHealthMonitor`, `InProcessBilling`); the metrics hook is a no-op by default (S5) | gate §21 S5 | structured, correlated logs; no exporter | |
| DR-31 | Timing sensitivity on a loaded Windows host: event-loop stalls of about 250 ms were measured, and M20's multi-process cases need a quiet machine. Run the certification suites in Linux CI (gate §21 S9: "Linux CI is a later phase") | certification runs 2026-10-02/03 | owner verification on a quiet Windows machine; independent Linux runs | |
| DR-32 | Performance baseline recorded on Linux only (report §5); record the Windows figure on the certification host | gate §21 | record only, no threshold | |

## 8. AI Worker product layer

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-33 | Autonomy source for verification-layer selection (the `CONFIRM_ALL` → human branch) | CONF-005, CONF-041 | `required_verification_layers(mutation, risk)` without autonomy (golden M15) | |
| DR-34 | Join modes `any` and `threshold` | gate §14, D3 | `join_mode = "all"` only; anything else denied at S12 entry (`join_mode_unsupported`) | |
| DR-35 | Batch processing | gate C40 | not implemented (gate: "record it in the deferred register") | |
| DR-36 | Replanning (a replan is a new child execution; `parent_execution_id` lands with its first consumer) | gate C41, RD-11 | not implemented | |
| DR-37 | Worker management beyond C39: worker-level quotas; per-worker `execution_policy` retry and timeout keys; sub-agent spawning and `worker_spawn_audit`; worker groups; config versioning; state-change webhooks; L2 session memory; memory classification; progressive autonomy; PolicyEngine; templates, plans, entitlements and marketplace listing | gate §14 | C39 only (admission, eligibility, operation quota); M1 golden asserts the deferred tables are absent | |

## 9. Adapter packaging

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-38 | Real provider adapters. Notion and Airtable v2 exist as a package for `adapters-work` (61 offline tests, golden scans clean); not live-verified | gate §14; package 2026-10-03 | mock adapter only on `s12-work` | |
| DR-39 | **Single-capability plans reach S12 with `params == {}`**: S4 `_build_execution_steps` drops S2's `parameters` (also for `items`). Only multi-capability chains (M2a) carry parameters. Needs S0–S11 change control (§19.3) | cross-check 2026-10-03 (real S0–S11 run) | the adapters refuse an empty write (`values_required`) | **ADAPTERS** |
| DR-40 | The S15 envelope returns only `position`, `operation` and `status` per step, never result `data`, so a read operation's result never reaches the user | cross-check 2026-10-03, `s15_final_state/response.py` | reads execute; data stays in the ledger | ADAPTERS |
| DR-41 | Production enablement of mutations: `PRODUCTION_ENABLED` only for an operation whose adapter overrides `probe()` and `observe()`; enabled one operation at a time after conformance; production read-only until then | CONF-052 (D-12), C-16 | `tools/registry_readiness.py`; Worker Runtime start-up refusal (`unverifiable_mutation`, M21) | GO-LIVE |
| DR-42 | The guard holds one adapter; several providers in one runtime need a routing adapter, which needs golden M13's `.probe(` allow-list amended (test-author + pin) | cross-check 2026-10-03 | one provider per runtime | |
| DR-43 | Inverse coverage: an inverse runs with the create's binding and params; each provider's inverse must locate its target by the original key (Layer A §1.1) | D2, CONF-038 | `InverseBudget`; failed inverse → dead letter | |

## 10. AI-platform adapters, frontend, billing

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-44 | Browser / RPA adapters and skills | gate §14 | none | |
| DR-45 | Inbound provider events for Notion and Airtable (the gateway accepts `ghl`, `stripe`, `custom`; their signature schemes differ) | cross-check 2026-10-03, `EVENT_GATEWAY_AND_ROUTER.md` | event-driven runs from these providers impossible | |
| DR-46 | Billing beyond the in-process records (DR-30) | gate §21 | budget reservations (M9) are the money control | |

## 11. SDK and CLI

| ID | Item | Source | Control now | Gate |
|---|---|---|---|---|
| DR-47 | SDK and CLI for operators (dead letters are served by the admin API, CONF-049) | gate §21 order | admin API only | |

## Resolved in this phase (listed, not outstanding)

| ID | Item | Resolution |
|---|---|---|
| DR-R1 | Tenant scoping of `idempotency_ledger` | gate §14 / §21 S7: resolved. C34 puts `tenant_id` and forced RLS on every S12–S15 table (I15, M20 `test_every_s12_table_forces_row_level_security_on_its_tenant`) |
| DR-R2 | "Record gap" tables of gate §21 S7 (`execution_ownership`, `worker_leases`, `execution_steps`, `checkpoints`, `dead_letters`) | superseded by C34: every one carries `tenant_id` with forced RLS |
| DR-R3 | LOCKED money had no release path | CONF-049: tenant-scoped, audited admin API to list, resolve and retry (PROBE/VERIFY only) dead letters (M21) |
| DR-R4 | Real admission snapshot and pre-flight sources | CONF-027: `PostgresAdmissionSnapshot` and `PostgresPreflight` assigned to M21 and pinned (journey on real sources), except DR-04 and DR-26 |
| DR-R5 | DEF-002 (non-Appendix-A reasons in the loop) and DEF-004 (step start and budget lock in two transactions) | fixed by the M12 rework (checkpoint `591fc73`): step reason `started`; `step_started` / `step_completed` are reservation reasons allowed by A.3 (`transitions.py:80,83`); the start and the lock are one `set_step(..., budget_move="lock")` (I-3, M09 `test_lock_joins_the_callers_transaction`, M12). **Owner closes both rows in `S12_DEFECTS.md`** |
