# S12–S15 M0 — Preflight report (gate commit A)

Gate `S12_S15_EXECUTION_GATE.md` Revision **v10** (header, line 4). Plan v3, milestone M0. No code changed.
Evidence is from the code and the database; documents are cited only where an item asks about documents.
Branch `s12-work`, which differs from tag `s0-s11-certified` (`f14a956`) only in `docs/gates/`, `tools/`
(new files) and `.github/workflows/tests.yml`; `src/`, `tests/`, `tests_postgres/`, `tools/owner_certify.py`
and `docs/implementation/` other than the owner's two-line fence fix in `DATA_CONTRACTS.md` (`165a42e`) are identical to the tag.

**Where this was produced.** In a Linux cloud container, not the owner's Windows VPS. The database was a fresh
PostgreSQL 16.13 cluster (local superuser `postgres`, trust authentication) with a new `suprpg_test` database
and all 14 migrations applied. Items 2, 9, P1 and the database half of item 11 describe *that* environment;
the owner must re-confirm them on the VPS (commands at the end).

## Preconditions

| # | Result | Evidence |
|---|---|---|
| Pre-1 git | PASS | tag `s0-s11-certified` = `f14a95626749ea85caadd7318aa1729f46d56565`; owner ran `owner_verify.ps1` there: 19/19 |
| Pre-2 suite at tag | PASS | worktree at the tag: `836 passed, 1 warning in 5.77s` (`tests`); `330 passed, 1 warning in 180.26s (0:03:00)` (`tests_postgres`) |
| Pre-3 PostgreSQL | PASS (container) | `PostgreSQL 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)`; asyncpg reports `ServerVersion(major=16, minor=0, micro=13)` |
| Pre-4 gate v10 | PASS | `S12_S15_EXECUTION_GATE.md:4` "Revision: v10" |

## Gate section 2 items

**1. Certified state.** See Pre-1/Pre-2. 0 failed, 0 skipped, 0 xfail.

**2. PostgreSQL.** See Pre-3 (container). On the VPS: owner re-confirms.

**3. Existing S12–S15 files.** All are prototype code (roadmap §4); none certified.

| File | Lines | What it does |
|---|---|---|
| `src/engine/stages/s12_entry/checks.py` | 169 | §7.1 entry checks 1–5b and 7, first failure decides (`checks.py:1-14`) |
| `src/engine/stages/s12_entry/verifiers.py` | 102 | builds step verifiers at entry (D1) |
| `src/engine/stages/s12_entry/admission.py` | 36 | entry checks then durable admission |
| `src/adapters/postgres/admission.py` | 174 | §7.2 one transaction: quota, run, manifest, plan, steps, ownership |
| `src/engine/stages/s12_execute/loop.py` | 282 | §8 step loop, topological order, cancellation and live-authorization checks |
| `src/engine/stages/s12_execute/transitions.py` | 53 | run, step, budget machines (`RUN` :11, `STEP` :19, `BUDGET` :29) |
| `src/engine/stages/s12_execute/guard.py` | 67 | reliability guard around one adapter call (C4, C31, C32) |
| `src/adapters/postgres/execution.py` | 126 | repository: load an admitted run; fenced, validated, logged writes |
| `src/adapters/postgres/budget_reserver.py` | 67 | reserve / lock / commit / release per step (C3, C31) |
| `src/adapters/postgres/live_authorization.py` | 55 | LiveAuthorizationCheck (C23) |
| `src/adapters/runtime/circuit_breaker.py` | 46 | in-process per-provider circuit breaker |
| `src/engine/stages/s12_worker_execution/handler.py`, `s13_reconciliation/handler.py`, `s14_verification/handler.py`, `s15_final_state/handler.py` | 114 / 66 / 94 / 63 | header "Pre-existing. Not certified. Superseded by the S12-S15 execution gate." (line 2 of each) |
| `src/engine/execution/__init__.py`, `src/engine/reliability/__init__.py` | 1 each | docstring only |

**4. ExecutionManifest fields** (`src/contracts/execution_manifest.py:51`): `execution_id` :58, `trace_id` :59,
`plan_hash` :60, `capability_version` :61, `binding_version` :62, `policy_version` :63, `risk_policy_version` :64,
`authorization_version` :65, `auth_result_id` :66 (default `None`), `worker_runtime_version` :67 (default `""`),
`model_version` :68 (default `""`), `created_at` :69 (default `0.0`). The table `execution_manifests` has the same
fields plus `tenant_id` (`009_execution_admission.sql:61`).

**5. join_mode emitted by S9.** Only `"all"`: `s9_plan_creation/handler.py:129`; contract default `"all"`
(`stage_outputs.py:105`, `:158`, comment "all | any | threshold"); S4 also sets `"all"` (`s4_graph_classification/handler.py:105`, `:127`).
S12 entry denies anything else with `join_mode_unsupported` (`s12_entry/checks.py:124-126`).

**6. AutonomyLevel.** **Not present in code.** No `AutonomyLevel` or "autonomy" in `src/`, `tests/` or
`tests_postgres/`. Gate D6 (`S12_S15_EXECUTION_GATE.md:1442`): "If preflight item 6 shows no canonical AutonomyLevel
source, STOP and report." → **CONF-005 / STOP for M15** (see Conflicts).

**7. workers.capacity / current_load.** No `workers` table exists (`009_execution_admission.sql:6`: "no foreign keys
to workers / worker_leases / worker_versions (those tables do not exist yet)"). No seed or fixture sets a capacity.
The contract `WorkerIdentity` (`src/contracts/worker.py:47`) has `max_concurrent: int = 10` (:59) and
`current_load: int = 0` (:60); **no code maintains `current_load`** (its only occurrence is :60).
Settings: `worker_max_concurrent = 10` (`src/config.py:75`).

**8. Documents.** `HUMAN_IN_THE_LOOP.md`, `TRACING_AND_CONCURRENCY.md`, `SKILL_FACTORY_ARCHITECTURE.md`,
`MEMORY_ARCHITECTURE.md`, `MASTER_ARCHITECTURE_FINAL.md`: **absent** (not tracked, not on the container's file system).

**9. Python / OS / loop / driver (container).** Python 3.11.15; Linux 6.18 x86_64 (glibc 2.39);
loop `_UnixSelectorEventLoop`; asyncpg 0.31.0 connects and queries under it; pytest `asyncio_mode = "auto"`
(`pyproject.toml:42`). No event-loop policy is set in code (none found). The VPS (Windows, default
`ProactorEventLoop`) must be checked by the owner.

**10. Confirmation store after R-Z.** Present, with a wording difference (**CONF-003**):
- store: `PostgresConfirmationStore.save(self, confirmation, tenant_id, execution_id)` (`src/adapters/postgres/confirmations.py:20`),
  both required and validated non-empty (:21-22); protocol `s10_confirmation/store.py:25`; in-memory `store.py:43`.
  They are positional-or-keyword, **not keyword-only** as item 10 and C20 state. S10 calls it positionally:
  `store.save(confirmation, ctx.tenant_id, plan_result.execution_id)` (`s10_confirmation/handler.py:79`).
- consume: `consume(self, confirmation_id, *, tenant_id, user_id, plan_hash, now=None)` (`confirmations.py:32`),
  keyword-only `tenant_id`; no `execution_id` (C20 places the execution check at S12 entry). The single conditional
  update is at `confirmations.py:39-42`; it filters by `user_id` and `plan_hash`, and `tenant_id` through
  `tenant_transaction` (RLS), not a `tenant_id =` predicate.
- test: `tests/stages/test_s10_confirmation.py:58` `test_s10_store_receives_tenant_and_execution_id`.
Not a STOP: R-Z's substance (tenant and execution id reach the store) is implemented and tested.

**11. Migration tool and tables.** No Alembic. Own runner: `src/adapters/postgres/migrate.py:17`
`apply_migrations()` applies `src/adapters/postgres/migrations/NNN_*.sql` once each in name order, recording them in
`schema_migrations` (:20-29). Revision history: `001_s0_s11_schema` … `014_onboarding_usage_limits` (14 files).
Tables in `suprpg_test` after all 14 (container):

| Table | Exists | Defined at | Columns (NN = NOT NULL) | CHECK / key constraints |
|---|---|---|---|---|
| execution_runs | yes | `009:10`, +`010:5` | execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id, conversation_id NN; plan_id; status, actor_type, actor_id NN; consolidation; budget_spent NN; duration_ms, started_at, completed_at; created_at NN; cancel_requested_at, connection_id, terminal_reason | status ∈ {pending, running, reconciling, completed, partial, failed, cancelled, dead_letter}; actor_type ∈ {user, worker, system}; FKs tenants/users/workspaces; unique `(tenant_id, request_id)` (`009:32`); RLS forced |
| execution_steps | yes | `009:36`, +`010:8-9` | step_id, plan_step_id, execution_id, tenant_id, kernel_op_id, resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, attempt, created_at NN; plan_id, reservation_id, data, error, undo_token, duration_ms, terminal_reason, dispatched_attempt | status ∈ 11 StepState values; mutation ∈ {R, W, D, IRREVERSIBLE}; 0 ≤ risk ≤ 1; terminal_reason ∈ 14 values; cancelled/skipped ⇒ reason; unique `(execution_id, plan_step_id)`; trigger `keep_terminal_reason` (`010:18-26`); RLS forced |
| execution_manifests | yes | `009:61` | see item 4, all NN except auth_result_id | FKs; `execution_manifests_immutable` trigger (`009:134`); RLS forced |
| checkpoints | **no** | — | — | — |
| pending_confirmations | yes | `001:125` | confirmation_id, tenant_id, execution_id, user_id, conversation_id, plan_id, plan_hash, operations (jsonb), status, expires_at, created_at NN; consumed_at | status ∈ {pending, consumed, rejected, expired}; execution_id <> ''; FK tenants only (no FK to execution_runs, per C20); RLS forced |
| dead_letters | **no** | — | — | — |
| idempotency_ledger | **no** | — | — | — |
| audit_log | **no** | — | — (`admin_audit`, `012:9`, exists for admin actions) | — |
| workers | **no** | — | — | — |
| worker_leases | **no** | — | — | — |
| execution_ownership | yes | `009:88` | execution_id, tenant_id, runtime_instance_id, fencing_token (bigint), checkpoint_sequence, updated_at NN; worker_id, lease_id | FKs execution_runs, tenants; RLS forced; **no `fence_token_seq`** |
| budget_reservations | yes | `006:9` | reservation_id, tenant_id, user_id, execution_id, step_id, cost, status, created_at NN; locked_at, committed_at, released_at | cost ≥ 0; status ∈ {reserved, locked, committed, released}; FK tenants; RLS forced |
| tenants | yes | `001:14`, +`006:6` | tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id, created_at, budget_period NN; paused_until, scheduled_activation_at | status ∈ 6 values; budget_pool ≥ 0; max_mutation ∈ 4; budget_period ∈ {daily, weekly, monthly}; RLS forced |
| kernel_ops | yes | `001:80`, +`008:5-7` | kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety, truth_state, observation_expects_absent NN; inverse, observation_method, observation_identifier_field | mutation ∈ 4; risk 0–1; cost > 0; timeout > 0; retry_safety ∈ {safe, idempotent, never}; truth_state ∈ 4; FK inverse → kernel_ops; **no RLS** (global registry) |

Also present and touched by the gate: `execution_plans` (`009:77`), `state_transitions` (`009:99`,
`entity_type ∈ {run, step}` only), `operation_quotas` (`009:113`). No foreign key anywhere uses `ON DELETE CASCADE`.

**12. Provider-adapter base class.** `BaseProviderAdapter(ABC)` (`src/engine/providers/base.py:53`):
`execute(self, capability, params, context) -> dict` (:69), `read_state(self, capability, params, context) -> dict` (:88),
`health_check()` (:107), `get_capabilities()` (:117). **No `call`, no `probe`, no `observe`** method anywhere in `src/`.
`read_state` is the closest to an observation method.

**13. Kernel-operation metadata.**
- `inverse`: read by the registry (`src/adapters/postgres/registry.py:76`, `:96`), carried by S9 (`s9_plan_creation/handler.py:89`, `:102`, `:117`),
  checked by S11 (`s11_plan_validation/handler.py:72`), used by the loop for undo tokens (`s12_execute/loop.py:248-249`).
- `retry_safety`: stored (`001:80`, CHECK above) and validated by the catalog loader (`catalog.py:17`, `:69-70`, `:142`);
  **never read by S0–S12 execution code**.
- input schema: `CapabilityMetadata.input_schema` (`contracts/capability.py:29`) and `ProviderCapability.input_schema`
  (`providers/base.py:41`); the registry fills it with `{}` (`registry.py:34`). No schema is stored or validated (R-AE).
- versioning: **not versioned per row.** `kernel_ops` has no version column; one global row `registry_versions`
  (`001:104`, singleton). `PostgresKernelOpMetadataReader.read(..., capability_version, binding_version)` (`registry.py:123`)
  returns `None` when the registry's current versions differ from the manifest's (:127-132), so S12 entry denies rather
  than build a verifier from other metadata. Consequence: any registry version bump denies every plan certified before it.

**14. StateTransitionValidator.** Two implementations (**CONF-006**):
- `src/contracts/state_validators.py:41` `StateTransitionValidator` (DATA_CONTRACTS §26), 16 machines registered (:53-385):
  execution_run, execution_step, budget_reservation, worker_identity, worker_version, worker_deployment, lease, capability,
  binding, confirmation, dead_letter, reconciliation, circuit_breaker, verification, admission_decision, worker_subscription.
  Its run machine (:72-92) uses budget states (PENDING, RESERVED, COMMITTED, LOCKED, …); its step machine (:94-118) uses
  `SUCCESS`, `TIME_OUT`, `PROBE_FAILED` and allows `UNKNOWN → FAILED` and `RUNNING → UNKNOWN`, which Appendix A.2 forbids.
  Only use in production code: `src/main.py:25`, `:48` (logs the machine count).
- `src/engine/stages/s12_execute/transitions.py` (prototype): run and step tables equal Appendix A.1 and A.2 exactly
  (checked mechanically); budget equals A.3 plus the in-memory `pending → reserved/released` edges A.3 mentions.

**15. Worker-management columns (C39).**

| Column (gate §7.3) | Present? |
|---|---|
| workers.settings, assigned_user_id, paused_until, scheduled_activation_at, runtime_type, workspace_id | **no** (no `workers` table) |
| bindings.required_runtime_types | **no** (bindings has binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class, priority, is_active, created_at) |
| tenants.paused_until, scheduled_activation_at | yes, `TIMESTAMPTZ` NULL (`001:23-24`) |
| workspaces.paused_until, scheduled_activation_at | yes, `TIMESTAMPTZ` NULL (`001:33-34`) |
| execution_runs C39 columns | none required; `parent_execution_id` correctly absent |

Key types: `tenants.tenant_id TEXT` (`001:15`), `workspaces.workspace_id TEXT` (`001:29`), `users.user_id TEXT` (`001:39`);
`workers.worker_id`: table absent. **No foreign key in the database has a type different from its referenced key**
(query over `pg_constraint`: 0 rows). No RD-1 mismatch.

**16. Worker-management tables.** `operation_quotas`: exists (`009:113`) with a **deviation** (**CONF-007**): no
`worker_id` column, so no `CHECK (worker_id IS NULL)` and the unique key is `(tenant_id, workspace_id, resource_type,
period_start)` instead of including `worker_id`. `worker_spawn_audit`, `worker_groups`, `worker_group_members`,
`execution_batches`, `worker_config_versions`: **not present in code** (no match in `src/`, `tests/`, `tests_postgres/`).

**17. S0.1 pause check (R-P).** Present, at a different place than item 17 names (**CONF-004**):
- check: `src/engine/control_plane/pipeline_state_runner.py:182-186` ("S0.1", runs after S0 is recorded and before S1),
  also for confirmation replies (:215); logic `src/engine/stages/s0_entry/activation.py:26` `inactive_reason`, :42
  `activation_denial`; not in `s0_entry/handler.py`.
- tests: `tests/stages/test_s0_activation.py` (not `test_s0_entry.py`): `test_reason_table` :49 (parametrized),
  `test_a_paused_tenant_runs_nothing_after_s0` :66, `test_a_finished_pause_runs_normally` :75,
  `test_the_deny_happens_before_the_scope_is_read` :80, `test_unreadable_activation_state_denies` :94,
  `test_a_missing_reader_denies` :101, `test_a_pause_also_blocks_the_reply_to_a_waiting_confirmation` :108; 19 cases, all pass.
Not a STOP: the check exists and is tested.

## Prompt items P1–P6

**P1 Environment** (container; see item 9). Clean virtual environment from `pyproject.toml` `[dev]`: asyncpg 0.31.0,
fastapi 0.142.1, pydantic 2.13.5, httpx 0.28.1, cryptography 50.0.1, pytest 9.1.1, uvicorn 0.54.0. Nothing missing.
The container's *system* Python has a broken `cryptography` (`_cffi_backend` missing), which fails 14 API tests
there; irrelevant to the VPS but a reason to always use the project `.venv`.

**P2 Migrations.** See item 11. The gate's "versioned, additive migrations" are satisfied by the numbered-SQL runner;
new S12 migrations must be new files (015+); editing 001–014 (all inside the tag) is an M1 trap.

**P3 Schema vs gate** (the differences C5, C20, C21, C22, C39 or §7.3 address):
- C5 / C25: `execution_ownership.fencing_token` exists, but no `fence_token_seq`, no `worker_leases`, no `workers.lease_epoch`.
- C20: satisfied (no FK to `execution_runs`, canonical `consumed`, `user_id`/`conversation_id`/`plan_id` columns).
- C21: `dead_letters` absent.
- C22: satisfied for steps (terminal_reason, CHECK, immutability trigger); `execution_runs.terminal_reason` has no CHECK and no trigger.
- §7.3: `step_reconciliations`, `checkpoints`, `idempotency_ledger` absent; `state_transitions.entity_type` allows only run and step
  (lease, dead letter, episode, confirmation will need it widened, additively).
- C39: see items 15–16 (no `workers`, no `bindings.required_runtime_types`, `operation_quotas` without `worker_id`).
- Missing tables from the P3 list: `checkpoints`, `idempotency_ledger`, `dead_letters`, `workers`, `worker_leases`, `event_subscriptions`.
- RD-1 key types: no mismatch (item 15).

**P4 Credential exposure** (paths and commits only; no values printed). Working tree at `s12-work`: none (no `sk-` keys,
no `.env` tracked, no `db create.txt`; placeholders only in `.env.example:25` and `tools/setup_database.py:6`, `:62`). History:

| Commit | Path | What | Branch |
|---|---|---|---|
| `0d1bc82` | `.env` | `DEEPSEEK_API_KEY`, 35 chars, real-looking | `claude/exciting-brahmagupta-r3gu19` |
| `37f07d6` | `src/env` | same key value (same hash) | `claude/exciting-brahmagupta-r3gu19` |
| `de759eb` | `.env.example` | same key value (same hash) | `claude/peaceful-brown-9f3w18` |
| `adec209` | `INSTALLATION.md` | two PostgreSQL URLs with passwords (`postgres`, `supragents_app`), one placeholder-like | `claude/peaceful-brown-9f3w18` |
| `158a377` | `tests/unit/test_settings.py` | 13-char `DEEPSEEK_API_KEY` test value (likely a dummy) | `claude/peaceful-brown-9f3w18` |
| `b86ef15`, `b3045be` | tests / `.env.example` | placeholder values only | `s0-s11-repair`, `s12-work` |

`db create.txt`: never committed (no history match). Remedy is the owner's (revoke the DeepSeek key; rotate the two
database passwords if they were ever real; decide whether to delete the two `claude/*` branches). No history rewritten.

**P5 XS-1 and Laya.** All four XS-1 conflicts are **already repaired** in the pinned documents, so none still exists:
(1) STATE_TRANSITIONS §2 annotation reads "did not start: cancelled by the user or by the system" (`STATE_TRANSITIONS.md:129`),
same in `DATA_CONTRACTS.md:1250`, `:1294`; (2) reason column: `DATABASE.md:513` (`terminal_reason`, repair C22) and code
`010_step_loop.sql:8`; (3) status comment lists `cancelled` (`DATABASE.md:499`); (4) I-1 lists `cancelled` (`STATE_TRANSITIONS.md:529`).
Laya: `DecisionContract`, `LayaDecisionAdapter`, `ReflexChoice`, `step_decisions`: **not present in code** (no match in
`src/`, `tests/`, `tests_postgres/`, `tools/`).

**P6 Test manifest.** `docs/gates/test_manifest_s12_baseline.txt`: 836 test ids, sorted, from
`pytest tests --collect-only -q` (addopts cleared so the ids are one per line).

## Conflicts and stop conditions found

Recorded in `docs/gates/S12_RECORDS.md`. Each needs a ruling before the milestone named.

| ID | Item | Finding | Needed by | Proposal |
|---|---|---|---|---|
| CONF-003 | 10 | R-Z store takes `tenant_id`/`execution_id` positional-or-keyword; gate says keyword-only | M5 | Accept as satisfying R-Z (required, validated, tested). Changing it is S0–S11 code (§19.3). |
| CONF-004 | 17 | R-P check lives in the runner as S0.1 (`pipeline_state_runner.py:182`), tests in `test_s0_activation.py`, not the S0 handler / `test_s0_entry.py` | M8a | Accept; the gate text names the wrong file. |
| CONF-005 | 6 | **No AutonomyLevel source.** Gate D6 says STOP and report | M15 | Owner decides the source (for example a tenant or workspace setting) or drops autonomy from layer selection. Does not block M1–M14. |
| CONF-006 | 14 | `contracts/state_validators.py` contradicts Appendix A (run machine uses budget states; step machine has SUCCESS/TIME_OUT/PROBE_FAILED, UNKNOWN→FAILED) and is loaded by `main.py` | M3 | Treat it as non-canonical: S12 code must not import it (architecture test in M3/M21); `transitions.py` is the base. Deletion is S0–S11 change control, after S15. |
| CONF-007 | 16 | `operation_quotas` has no `worker_id` column, no `CHECK (worker_id IS NULL)`, unique key without `worker_id` | M1 | M1 adds the column, the CHECK and the new unique index in migration 015 (additive). |
| CONF-008 | 13 | Kernel-op metadata is not versioned; a registry version bump denies every plan certified before it | M6 | Accept for this phase (fail closed); record in the deferred register. |

Also for the owner, not conflicts: item 12 (no `call`/`probe`/`observe`; M10 builds them), item 7 (no `workers` table;
M1/M7), P4 (credentials).

Stop conditions: items 1, 2, 10 and 17 pass, so the preflight itself does not stop. **D6 (CONF-005) is a STOP for M15**
and is reported here as the gate requires.

## Report block

```text
Phase: S12-A (preflight)
Preconditions 1–4: PASS (tag f14a956; suite 836+330 passed; PostgreSQL 16.13 in container; gate v10 at line 4)
Gate items 3–17: answered above with file:line or "not present in code"
Prompt items P1–P6: answered above
Conflicts or stop conditions found: CONF-003..CONF-008; D6 STOP for M15 (no AutonomyLevel)
pytest summary line: ======================== 836 passed, 1 warning in 5.77s ========================
git commit hash: (the commit that adds this report on s12-work)
```

## Owner re-checks on the VPS (items 2, 9, P1, 11)

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -c "import sys,platform,asyncio,asyncpg;print(sys.version,platform.platform(),asyncpg.__version__,type(asyncio.new_event_loop()).__name__)"
.\.venv\Scripts\python.exe -m pytest tests_postgres -q      # proves asyncpg works under the Windows loop
psql "$env:TEST_DATABASE_URL" -c "select version();" -c "\dt"
```
