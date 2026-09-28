# S12–S15 EXECUTION GATE — PHASE-LOCKED INSTRUCTION

Status: APPROVED FOR EXECUTION (after owner confirms Section 6)
Revision: v8 — v7 plus C23 (live authorization revalidation before new side effects), invariant I14
Execution mode: PHASE-LOCKED, SINGLE NODE
Authorized scope: S12 Execute, S13 Validate Result, S14 Dead Letter, S15 Response, plus the durable persistence and crash recovery they require
Out of scope: multi-node fleet, Redis, real providers, frontend, SDK

---

## 0. HOW TO READ THIS INSTRUCTION

1. Read the whole document before writing any code.
2. Sections 5 and 6 contain **rulings**. They are binding. They exist because the
   specification documents contradict each other in the S12–S15 area. When a ruling
   covers a contradiction, follow the ruling. Do not stop for a contradiction that a
   ruling already resolves.
3. Stop only for the conditions in Section 19, or for a contradiction that no ruling
   covers.
4. The S0–S11 certification rulings (R1–R8 of the previous gate) remain in force.
5. When this document says "record", add an entry to
   `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` with: ID, documents involved, the
   conflicting statements, the ruling applied, and "open question" if the owner must
   decide later.
6. Work in the commit order of Section 18. Every commit must leave the full test
   suite green, except where Section 18 explicitly allows temporary red.

---

## 1. PHASE LOCK

### You MAY

- Apply the documentation repairs C1–C23 in Section 5.
- Create additive database migrations for tables, columns and indexes needed by
  S12–S15 (Section 7.3).
- Implement S12, S13, S14, S15 and the components they call: admission, worker
  selection, lease and fencing, budget reservation, reliability guard, idempotency,
  probe and reconciliation, verification, consolidation, dead letter, response
  formatting.
- Implement a PostgreSQL-backed implementation of the existing confirmation-store
  interface (introduced in the S0–S11 gate under R6), without changing S10 logic.
- Persist the ExecutionManifest and the Plan at S12 entry (Section 7).
- Implement single-node crash recovery (Section 13).
- Implement a mock provider adapter for tests (Section 15.3).
- Add unit, contract, architecture, integration, concurrency and crash tests.
- Fix defects in S12–S15 code found by these tests.

### You MUST NOT

- Modify S0–S11 behavior, contracts or tests. If S12–S15 appears to require it,
  follow the change-control procedure in Section 19.3.
- Re-resolve bindings or recompute effective risk or mutation anywhere in S12–S15.
- Run the S8 stage, write a `SafetyResult`, or make any new authorization
  decision in S12–S15. S12 consumes `auth_passed` and `auth_result_id` from
  ExecutionContext as the original decision. The only permitted authorization
  activity is the read-only live revalidation defined in C23.
- Introduce Redis, a message broker, or any multi-node coordination.
- Call real provider APIs.
- Add new StageStatus values, new state names, or new transitions beyond the
  canonical state machines as corrected by Section 5.
- Store checkpoints on the filesystem (see C10).
- Execute compensating (inverse) operations automatically (see D3).
- Implement worker version or deployment lifecycle beyond reading the version fields
  S12 needs.
- Delete or weaken existing tests to restore green.

---

## 2. PRECONDITIONS — PREFLIGHT REPORT (NO CODE)

Before any change, produce a short preflight report containing:

1. The git tag or commit of the certified S0–S11 state. Run the full suite and
   confirm 0 failures, 0 skipped, 0 xfail.
2. A PostgreSQL 16+ instance reachable via `TEST_DATABASE_URL`. On Windows use Docker
   Desktop (`postgres:16`) or a native install. Confirm connectivity.
3. The list of existing S12–S15 files (stubs or partial code) and what each does.
4. The fields of the ExecutionManifest class as implemented in code.
5. Which `join_mode` values the certified S9 implementation can emit.
6. Whether the certified contracts expose an `AutonomyLevel` for the current
   execution, and from where.
7. The current `workers.capacity` values in any seed or fixture data, and whether
   code already maintains `workers.current_load`.

If item 1 or 2 fails, STOP. Items 3–9 are information for the rulings below.

8. Whether these documents exist anywhere in the repository or workspace:
   `HUMAN_IN_THE_LOOP.md`, `TRACING_AND_CONCURRENCY.md`,
   `SKILL_FACTORY_ARCHITECTURE.md`, `MEMORY_ARCHITECTURE.md`,
   `MASTER_ARCHITECTURE_FINAL.md`. BUILD_READINESS_MATRIX.md marks them COMPLETE.
   For each one found, list every statement that conflicts with a ruling in this
   gate (leases, fencing, confirmation re-entry, HITL, tracing). Do not resolve
   those conflicts yourself; report them. For each one not found, write "absent".
9. The Python version, operating system, and asyncio event loop in use, and
   whether the database driver (asyncpg) works under that loop.

**Evidence rule:** answer items 3–9 from the source code and database only, citing
`file:line` for each answer. Do not answer implementation questions from the
architecture documents. If the code does not contain the answer, write "not present
in code". An answer with neither a `file:line` citation nor "not present in code"
is invalid, and a preflight report containing any invalid answer is incomplete: fix
it before submitting.

**Environment rule:** run this gate inside the actual repository checkout (the
certified S0–S11 revision), not in a documents-only workspace.

---

## 3. SOURCE-OF-TRUTH ORDER

The general order from the S0–S11 gate still applies. For S12–S15, **domain
ownership overrides the general order**, because each domain has one document that
declares itself authoritative:

| Domain | Authoritative document |
|---|---|
| State machines (run, step, budget, lease, worker, dead letter, reconciliation) | STATE_TRANSITIONS.md, using enums from DATA_CONTRACTS.md |
| Table and column definitions | DATABASE.md |
| Retry ceilings, idempotency, checkpoint and resume semantics | MUTATION_SAFETY.md |
| Reliability guard layers, circuit breaker, bulkhead, timeouts | RELIABILITY.md |
| Admission, worker selection, verifier contract, execution ownership | WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md |
| Stage purpose, inputs, outputs, ordering | PIPELINE_STAGES.md |

Code sketches inside any document are **non-normative illustrations**. Where a code
sketch contradicts a table, matrix or rule in the authoritative document, the table,
matrix or rule wins.

---

## 4. VOCABULARY (MANDATORY)

| Term | Meaning in this phase |
|---|---|
| **Worker** | The durable, tenant-owned AI-worker identity in the `workers` table, per VOCABULARY_INDEX. It has state, capabilities, a lease and a heartbeat. |
| **Runner** | The operating-system process that hosts the S12–S15 engine. Identified by `runner_id` (UUID generated at process start), stored as `execution_ownership.runtime_instance_id`. **New term.** |
| **Lease** | A row in `worker_leases`. Grants one Runner the right to execute a step on behalf of one Worker. |
| **Fence token** | The monotonic `worker_leases.fence_token`, mirrored in `execution_ownership.fencing_token`. |
| **Step idempotency key** | `f"{request_id}:{step_id}"` (see C9). |

Never use "worker" to mean a process, machine, thread or asyncio task. Add the Runner
entry to VOCABULARY_INDEX.md in commit B.

---

## 5. DOCUMENTATION REPAIRS (RULINGS C1–C23)

Apply these as documentation edits in commit B. Each one is also recorded in the
blocker register. Implementation must follow the ruling, not the superseded text.

### C1 — Queue and dispatch

Conflict: FINAL_ARCHITECTURE tech table says "Queue: PostgreSQL + pg_cron" and the
scheduler "polls execution_queue". FINAL_ARCHITECTURE §37 says PostgreSQL is not a
message bus.

Ruling:
- PostgreSQL is the authority for all durable state and all claims (lease
  acquisition, fence tokens, state transitions).
- In this single-node phase, dispatch is in-process (asyncio). No polling loop is
  used for normal dispatch.
- One low-frequency recovery sweeper (Section 13) may query PostgreSQL for
  executions whose ownership lease expired. This is recovery, not message passing.
- A notification channel (Redis or queue) is deferred to the fleet phase. When added,
  it will be wake-up only; correctness must never depend on it.
- Update the tech table row to: "Queue: in-process dispatch (single node);
  PostgreSQL is the claim authority; notification channel deferred to fleet phase."

### C2 — Runner vocabulary

Add the Runner definition from Section 4 to VOCABULARY_INDEX.md. In the
PIPELINE_STAGES negative-path matrix, rename the row "Worker crash" to "Runner crash"
and "Stale worker" to "Stale Runner (heartbeat lost)".

### C3 — Budget model

Conflicts:
- PIPELINE_STAGES S12 action 4 reserves per step. Its budget rules say budget is
  reserved at S12 start, before any step, "atomic with plan validation".
  WORKER_LIFECYCLE §12 says reservation happens inside the guard's BudgetTracker.
- The BudgetReserver sketch commits from RESERVED and uses LOCKED only for UNKNOWN.
  STATE_TRANSITIONS §3 says RESERVED → LOCKED when the step begins execution, and
  RESERVED → COMMITTED is illegal.
- The sketch uses a `tenant_budget(reserved, remaining)` table that does not exist.
  DATABASE.md says the budget pool is `tenants.budget_pool`.

Ruling:
- Budget is reserved **per step**. `budget_reservations.step_id` is NOT NULL and
  `execution_steps.reservation_id` exists, so the schema is per step.
- Lifecycle per step, per STATE_TRANSITIONS §3:
  - PENDING: in memory only, before the insert.
  - RESERVED: row inserted, after lease acquisition, before pre-flight.
  - LOCKED: immediately before the adapter call.
  - COMMITTED: step reaches COMPLETED (after verification PASS).
  - RELEASED: step reaches FAILED, CANCELLED or SKIPPED, or the probe confirms
    NOT_EXECUTED.
- During UNKNOWN and probing, the reservation stays LOCKED.
- Availability: `available = tenants.budget_pool − Σ cost of that tenant's
  reservations in {reserved, locked, committed} created within the current
  budget_period`.
- Reservation atomicity: in one transaction, `SELECT ... FROM tenants WHERE
  tenant_id = :t FOR UPDATE`, compute availability, and insert the reservation only
  if `available >= cost`. Otherwise the step fails with reason `budget_exhausted`,
  releasing the lease.
- "Atomic with plan validation" and "reserved at S12 start" are superseded. S11's
  budget check remains informational, as already specified.
- Name the component `BudgetReserver`. It is called by the reliability guard at the
  BudgetTracker layer position. There is one component, not two.
- Record the missing `tenant_budget` table, and the `amount` vs `cost` column-name
  mismatch in the DATABASE.md note.

### C4 — Reliability guard layers

Conflict: PIPELINE_STAGES numbers the layers as circuit breaker, retry storm, timeout,
health, billing. RELIABILITY §1 numbers them as CircuitBreaker, RetryStormGuard,
BudgetTracker, TimeoutManager, Bulkhead. It also says billing is recorded by
"Layer 5", which is Bulkhead.

Ruling:
- RELIABILITY §1 and §8 own the guard. Implement the five components by name,
  including the acquisition order in RELIABILITY §8 (Bulkhead slot first).
- Health recording and per-call billing happen in the guard wrapper after the adapter
  returns, for every outcome: success, failure or UNKNOWN.
- Code and docs refer to layers by component name, never by number. Update
  PIPELINE_STAGES S12 and the negative-path matrix ("Adapter timeout at S12
  Layer 4" becomes "TimeoutManager").

### C5 — Leases and fencing

Conflicts:
- The negative-path matrix says the lease is non-renewable. FINAL_ARCHITECTURE,
  VOCABULARY_INDEX and STATE_TRANSITIONS §5 say leases are renewed.
- Two lease tables exist: `worker_leases` (has `fence_token`) and `execution_leases`
  (no fence token).
- Two fence fields exist: `worker_leases.fence_token` and
  `execution_ownership.fencing_token`.

Ruling:
- Leases are renewable, per STATE_TRANSITIONS §5 (`active → active`, fence_token
  increments). The matrix row is wrong: lease *expiry* is non-recoverable, not
  renewal.
- `worker_leases` is the lease of record. `execution_leases` is not used in this
  phase; record it as a duplicate table.
- Fence tokens are monotonic per worker: a new token = max existing token for that
  worker + 1. Renewal increments the token and returns it to the holder.
- `execution_ownership` is the single row checked for fencing. On acquire and on
  every renewal, the Runner updates `execution_ownership.fencing_token` in the same
  transaction as the lease change, using compare-and-set on the previous token.
- **Every durable write** for an execution goes through one helper, `fenced_write()`.
  Examples are step state, reservation state, checkpoint, dead letter and run state.
  The helper includes the condition
  `execution_ownership.fencing_token = :holder_token AND
  execution_ownership.runtime_instance_id = :runner_id` in the same transaction. Zero
  matched rows raises `FencedOut`. After `FencedOut`, the Runner must stop all work on
  that execution and must not retry the write.
- A Runner that loses its lease while an adapter call is in flight cannot cancel the
  provider call. It must discard the result. The new owner determines the outcome by
  probing.
- Per-worker concurrency is bounded by `workers.capacity` (WORKER_LIFECYCLE §3:
  "max concurrent executions", default 1, invariant `current_load <= capacity`).
  Lease acquisition, in one transaction: lock the worker row with `SELECT ... FOR
  UPDATE`, count its `active` leases, insert the new lease only if the count is below
  `capacity`, and set `current_load` to the new count. Release and expiry decrement
  `current_load` in the same transaction as the lease change. A worker at capacity
  is not selectable; if all eligible workers are at capacity, admission returns QUEUE
  (gate 7, `worker_at_capacity`).
- Fence tokens stay monotonic per worker. Because each execution's
  `execution_ownership` row holds the token of its own lease, concurrent leases on
  one worker do not interfere with each other's fencing.

### C6 — Step state machine corrections

Conflicts inside STATE_TRANSITIONS §2:
- `UNKNOWN → FAILED` appears as both valid and illegal.
- `PENDING_PROBE → FAILED` ("probe error — cannot determine") would mark a possibly
  executed step as failed, allowing a duplicate retry.
- `TIMEOUT → DEAD_LETTER` bypasses the probe.
- MUTATION_SAFETY §7 resume flow uses `RUNNING → UNKNOWN`, which is not a valid
  transition.
- `FAILED → RUNNING` is illegal, yet the retry rules need retries.

Ruling:
- `UNKNOWN → FAILED` is **illegal**. The illegal list and the NO SILENT SUCCESS rule
  win.
- `PENDING_PROBE → FAILED` is allowed **only** on a definitive failure: the probe
  returns EXECUTED_FAILURE, a non-expired ledger record holds a definitive failure
  (Section 13), or verification returns FAIL (C19). An undetermined probe keeps the step in PENDING_PROBE for the
  next probe attempt, or moves it to DEAD_LETTER after max attempts.
- `TIMEOUT → DEAD_LETTER` is not used. Every timeout goes
  `RUNNING → TIMEOUT → PENDING_PROBE`.
- Crash recovery uses `RUNNING → PENDING_PROBE` (listed as valid), not
  `RUNNING → UNKNOWN`.
- **Retries happen inside RUNNING.** The step stays RUNNING across attempts and
  increments `execution_steps.attempt`. It transitions to FAILED only when the
  error is not retryable or retries are exhausted.
- For R (read) steps, a probe cannot observe anything, and re-execution has no side
  effects. `PENDING_PROBE → PENDING` is allowed with reason code
  `read_reexecution_safe`, within the step's retry budget.
- `RUNNING → PARTIAL` is not produced in this phase (no sub-operations). Record it as
  unused.

### C7 — ExecutionRun transitions

Conflict: the `VALID_TRANSITIONS` code in STATE_TRANSITIONS §1 includes
`PENDING_PROBE` and `TIMEOUT`. These are step states, not run states. The
`execution_runs.status` column comment omits PARTIAL.

Ruling: the transition matrix wins. Run states are exactly PENDING, RUNNING,
RECONCILING, COMPLETED, PARTIAL, FAILED, CANCELLED, DEAD_LETTER. PARTIAL is a valid
stored status.

### C8 — Consolidation

Conflict: the S13 consolidation table says "Any UNKNOWN → confirmed SUCCESS →
PARTIAL". The S13 action list ("CONFIRMED_SUCCESS → consolidate to SUCCESS") and
STATE_TRANSITIONS (`RECONCILING → COMPLETED` when all resolve to CONFIRMED_SUCCESS)
say otherwise.

Ruling: a step whose UNKNOWN resolved to CONFIRMED_SUCCESS counts as COMPLETED.
Correct the table row.

### C9 — Idempotency keys

Conflicts:
- MUTATION_SAFETY §5 makes `request_id` the idempotency key. One request has many
  steps, so the second step would return the first step's cached result.
- `compute_provider_call_id` returns `f"{request_id}:{attempt}"`. PIPELINE_STAGES
  says `provider_call_id` is a globally unique UUID.
- A per-attempt key defeats provider-side deduplication on retry.

Ruling:
- **Step idempotency key** = `f"{request_id}:{step_id}"`. It is stable across
  attempts and across crash recovery. It is used for the ledger lookup and passed to
  the provider as the idempotency key where the adapter supports one.
- **provider_call_id** = UUID v4 per adapter invocation. Tracing only.
- **attempt_id** = `att-{step_index}-{attempt_N}`, per PIPELINE_STAGES.
- **Request-level duplicate detection** uses `request_id` at S12 entry (Section 7.2).
- Record that `idempotency_ledger` has no `tenant_id` column (a scoping gap).

### C10 — Checkpoint storage

Conflict: MUTATION_SAFETY §7 shows a filesystem write pattern (`.tmp`, `fsync`,
`os.rename`). DATABASE.md has a `checkpoints` table and says the DB is the source of
truth.

Ruling: checkpoints are rows in `checkpoints`, written with `fenced_write()`. There
are no checkpoint files. A file-based checkpoint is not portable across nodes, and
`os.rename` onto an existing file fails on Windows. The filesystem pattern is
superseded.

### C11 — S12 sequence sketch defects

The S12 sketch in WORKER_LIFECYCLE §12 is non-normative and has defects. Do not copy
them:
- It iterates `plan.steps` in list order. Execute in **topological order of
  `depends_on`**, with ties broken by step index.
- On QUEUE it calls `continue`, which silently skips the step. A step is never
  skipped by admission (see Section 8, step 1).
- On lease failure it calls `continue`, which also silently skips the step. Lease
  failure is retried (see Section 8, step 3).
- There is no budget reservation, no idempotency check and no probe path. Section 8
  is the normative sequence.

### C12 — Verification location

Conflict: PIPELINE_STAGES treats S13 as the stage after S12. WORKER_LIFECYCLE §12
verifies each step inside the S12 loop.

Ruling: verifier **execution** happens per step inside the S12 loop, because
dependents and the budget commit need the verdict. The verification code lives in
the S13 package and is called from S12. The S13 **stage** performs consolidation,
layer aggregation and the VERIFICATION ledger events for the execution.

### C13 — RECONCILING usage

Conflict: S13 says to set the run to RECONCILING as soon as any step is UNKNOWN.
STATE_TRANSITIONS makes `RECONCILING → RUNNING` illegal. The MUTATION_SAFETY resume
flow needs to continue executing after probing.

Ruling:
- While other steps remain executable, probing happens with the run in RUNNING.
- The run enters RECONCILING only when every non-UNKNOWN step is terminal and at
  least one step is UNKNOWN or PENDING_PROBE.
- From RECONCILING the run must go to a terminal state, per the matrix.

### C14 — Crash-recovery budget release

Conflict: PIPELINE_STAGES budget rule 5 says crash recovery releases a LOCKED budget
via checkpoint. If the step actually executed, that makes the execution free and lets
the tenant overspend the pool.

Ruling: a LOCKED reservation is resolved only by the probe outcome:
- EXECUTED_SUCCESS → COMMITTED.
- EXECUTED_FAILURE or NOT_EXECUTED → RELEASED.
- Still unresolved → handled by D4.

### C15 — Budget exhaustion mid-execution

Conflict: the v1 draft of Section 8 consolidated the run after budget exhaustion.
STATE_TRANSITIONS §1 and PIPELINE_STAGES both say `RUNNING → CANCELLED` for
"budget exhausted mid-execution".

Ruling: follow STATE_TRANSITIONS. Budget exhaustion mid-execution moves the run to
CANCELLED with reason `budget_exhausted`. Completed steps stay COMPLETED and their
budget stays COMMITTED. S15 reports which steps completed before cancellation.

### C16 — User cancellation

The state machines define user cancellation (`PENDING → CANCELLED`,
`RUNNING → CANCELLED`, `RECONCILING → CANCELLED`), but no stage specifies how it
is requested or applied.

Ruling:
- Add `request_cancellation(execution_id, user_id)`. It records a cancellation
  request on the run (additive column `cancel_requested_at`). It does not require
  the lease. It only accepts requests from the run's own user and tenant.
- The Runner checks the flag before each step. An in-flight adapter call is never
  interrupted; it finishes, or times out and is probed.
- After the in-flight step reaches a terminal state, remaining PENDING steps become
  CANCELLED and the run moves to CANCELLED.
- Cancellation during RECONCILING is recorded but applied **after** all probes
  resolve, so no step or LOCKED reservation is left unresolved. If any step ends in
  DEAD_LETTER, DEAD_LETTER takes precedence over CANCELLED.
- A PENDING run (admitted but not started) moves directly to CANCELLED.

### C17 — Idempotency hit path

Problem: v2 placed the idempotency check before budget reservation (step 4) and
"skipped steps 5–9", which left the step's transitions undefined, and contradicted
itself about verification. A direct `PENDING → COMPLETED` would be illegal
(STATE_TRANSITIONS §2: must go through RUNNING).

Ruling:
- The ledger lookup happens inside step 8, immediately before the adapter call.
  By then the step is RUNNING and its reservation is LOCKED, so every path uses only
  legal transitions and the same reservation.
- A cached **success** follows the normal success path: verification (step 9),
  then `RUNNING → COMPLETED` and `LOCKED → COMMITTED`, checkpoint, dependents.
  Verification runs because the cached result may come from an attempt that crashed
  before verification completed; provider-state verification is idempotent.
- A cached **definitive failure** follows the non-retryable failure path:
  `RUNNING → FAILED`, `LOCKED → RELEASED`.
- No adapter call is made on a hit. The provider side-effect count does not change.
- Budget accounting invariant: see I12 (Section 17). It is stated in terms of step
  state, because whether a side effect happened is only known once uncertainty is
  resolved. A reservation released after NOT_EXECUTED may be followed by one new
  reservation for the retry.
- Request-level duplicates never reach the step loop: S12 entry returns the existing
  execution (Section 7.2), with zero new reservations and zero adapter calls.
- A ledger hit is recorded as a ledger event (`idempotency_hit`) with the step and
  attempt IDs.

### C18 — Reconciliation status scope

Problem: `PENDING_PROBE` exists in two canonical enums: `StepState.PENDING_PROBE`
(STATE_TRANSITIONS §2) and `ReconciliationStatus.PENDING_PROBE` (STATE_TRANSITIONS
§10, DATA_CONTRACTS §22). Both are canonical, so renaming either would invent a
state. Separately, `ReconciliationStatus` has terminal states (CONFIRMED_SUCCESS,
CONFIRMED_FAILURE), so a single run-level value cannot handle a second UNKNOWN step
after the first one resolved. `execution_runs` also has no column for it.

Ruling:
- Keep both canonical names. Code must always use the typed enums
  (`StepState.PENDING_PROBE`, `ReconciliationStatus.PENDING_PROBE`), never bare
  strings, and they are stored in different columns. An architecture test fails on
  any bare `"PENDING_PROBE"` string literal outside the enum definitions.
- Each uncertainty episode is its **own record** in the additive table
  `step_reconciliations(episode_id PK, tenant_id, execution_id, step_id, kind,
  status, outcome, attempts, opened_at, closed_at)`. Each record runs its own
  instance of the canonical ReconciliationStatus machine starting at NONE. Nothing
  is ever reset: resetting CONFIRMED_x → NONE would be an illegal transition.
  At most one open episode (closed_at IS NULL) per step, enforced by a partial
  unique index.
- `kind` is `EXECUTION` (outcome of the provider call unknown) or `VERIFICATION`
  (C19). `outcome` records the raw result (EXECUTED_SUCCESS, EXECUTED_FAILURE,
  NOT_EXECUTED, LEDGER_HIT, VERIFIED_PASS, VERIFIED_FAIL, EXHAUSTED).
- Episode lifecycle, with the step transition that accompanies each close:

  | Episode transition | Step transition |
  |---|---|
  | open: NONE → PENDING_PROBE | RUNNING → PENDING_PROBE, or RUNNING → TIMEOUT → PENDING_PROBE |
  | attempt: PENDING_PROBE → RECONCILING | (none) |
  | inconclusive: RECONCILING → PENDING_PROBE | (none) |
  | close success: RECONCILING → CONFIRMED_SUCCESS | PENDING_PROBE → COMPLETED (after verification if required) |
  | close failure: RECONCILING → CONFIRMED_FAILURE, outcome EXECUTED_FAILURE or VERIFIED_FAIL | PENDING_PROBE → FAILED |
  | close not-executed: RECONCILING → CONFIRMED_FAILURE, outcome NOT_EXECUTED | PENDING_PROBE → PENDING (retry) or PENDING_PROBE → PENDING → CANCELLED (no retry allowed) |
  | exhausted: episode closed with status left at PENDING_PROBE, outcome EXHAUSTED | PENDING_PROBE → DEAD_LETTER |

- A retry after NOT_EXECUTED that later becomes uncertain again opens a **new**
  episode record.
- Record: canonical ReconciliationStatus has no NOT_EXECUTED outcome and says
  CONFIRMED_FAILURE resolves the step to FAILED. For NOT_EXECUTED this ruling uses
  CONFIRMED_FAILURE (the operation did not take effect) with the step going to
  PENDING, which is a valid step transition ("probe confirmed not started"). Also
  record that an exhausted episode has no terminal ReconciliationStatus; it is
  closed by `closed_at` and `outcome = EXHAUSTED`.
- The run-level view is derived, not stored: a run is "reconciling" when any of its
  steps has an open episode. The run *state* RECONCILING still follows C13.
- Record: STATE_TRANSITIONS §10 says "the execution's reconciliation_status" but no
  column exists; this ruling scopes it per step.

### C19 — Execution uncertainty vs verification uncertainty

Problem: v3 treated any verification layer returning UNKNOWN as a timeout and sent
it to the provider execution probe. These are different questions. An execution
probe asks "did the provider operation happen?". A verification UNKNOWN arises
after the adapter reported a definitive result: the operation is known to have been
attempted and answered, but the verdict about its effect is missing (for example, an
inconclusive read-back, or malformed semantic-verifier output). A provider probe
cannot answer that, and the NOT_EXECUTED retry path must never be available.

Ruling:
- **Execution uncertainty** (adapter timeout, lost response, crash between adapter
  call and ledger record): episode `kind = EXECUTION`, handled by the provider
  probe per Section 9.
- **Verification uncertainty** (any verification layer UNKNOWN after the adapter
  returned a definitive result, or recovery of a step whose ledger record exists
  but whose verification did not finish): episode `kind = VERIFICATION`.
  - Step RUNNING → PENDING_PROBE (legal; the step is awaiting a determination).
  - The episode's attempts re-run **only the verification layers that are not yet
    PASS**. The provider execution probe is never called, and the adapter is never
    called.
  - Bounded: the verifier's own limits (3 attempts, 1 s apart, 5 s timeout, per
    WORKER_LIFECYCLE §7) per episode attempt, and at most 3 episode attempts.
  - All required layers PASS → close CONFIRMED_SUCCESS, step COMPLETED, budget
    COMMITTED.
  - Any layer FAIL → close CONFIRMED_FAILURE (VERIFIED_FAIL), step FAILED, budget
    RELEASED, dead letter `error_type = "data"`, as in Section 8 step 9.
  - Still UNKNOWN after the limit → outcome EXHAUSTED, step DEAD_LETTER,
    `error_type = "unknown_unresolved"`, D4 applies (budget stays LOCKED, because
    the side effect may well have happened).
  - Outcome NOT_EXECUTED is impossible for this kind. If code reaches it, raise.
- The human verification layer (D4) returns UNKNOWN immediately and without
  retries, because retrying cannot produce a human verdict in this phase.
- Schema and deterministic layers are local checks and must never return UNKNOWN;
  they return PASS or FAIL.

### C20 — `pending_confirmations` table vs the Confirmation contract

Problems found while specifying the PostgreSQL confirmation store:
- `pending_confirmations.execution_id` has a foreign key to `execution_runs`, but
  S10 persists the confirmation **before** S12 entry creates the `execution_runs`
  row (Section 7.2). The insert would fail. Creating the run earlier would change
  S0–S11, which is forbidden.
- The status column comment lists `pending, confirmed, rejected, expired`. The
  canonical confirmation states (STATE_TRANSITIONS §8) are `pending, consumed,
  rejected, expired`.
- The table lacks `user_id`, `conversation_id` and `plan_id`, which the frozen
  `Confirmation` contract carries and the S0–S11 wrong-user tests depend on.

Ruling:
- Do not create the foreign key from `pending_confirmations.execution_id` to
  `execution_runs`. Keep `execution_id` as a plain column. S12 entry verifies that
  the consumed confirmation's `execution_id`, `plan_hash` and `tenant_id` match the
  run being admitted, and denies with reason `confirmation_mismatch` otherwise.
- Store the canonical value `consumed`, never `confirmed`. Add a CHECK constraint
  restricting status to the four canonical values.
- Add `user_id`, `conversation_id` and `plan_id` columns so the stored row carries
  every field of the `Confirmation` contract.
- Consumption is a single conditional update:
  `UPDATE ... SET status = 'consumed', consumed_at = now WHERE confirmation_id = :id
  AND status = 'pending' AND expires_at > now AND plan_hash = :h AND user_id = :u
  AND tenant_id = :t`. Exactly one row updated means success; zero means rejected.
- Record all three schema conflicts.

### C21 — Dead-letter storage vs the dead-letter state machine

Problems in DATABASE.md `dead_letters`:
- It has `resolved BOOLEAN` but no status column, so the canonical lifecycle
  `pending → retrying → resolved / abandoned` (STATE_TRANSITIONS §9) cannot be
  stored.
- The `error_type` comment lists `transient, permanent, data`; PIPELINE_STAGES S14
  also uses `unknown_unresolved`.
- There is nowhere to record the retry mode (D5) or the resolution outcome that D4
  needs to decide COMMITTED vs RELEASED.

Ruling (additive columns; keep `resolved` and keep it consistent):
- `status` TEXT NOT NULL DEFAULT 'pending', CHECK in
  (`pending`, `retrying`, `resolved`, `abandoned`). `resolved` (boolean) is set
  true exactly when `status` is `resolved` or `abandoned`.
- `error_type` CHECK in (`transient`, `permanent`, `data`, `unknown_unresolved`).
- `retry_mode` TEXT NOT NULL, CHECK in (`PROBE`, `VERIFY`, `NONE`), set at
  creation and never changed.
- `episode_id` (nullable) referencing the `step_reconciliations` episode that
  produced the record.
- `resolution_outcome` TEXT, CHECK in (`EXECUTED`, `NOT_EXECUTED`, `UNDETERMINED`),
  required when `status` becomes `resolved` or `abandoned`.
- Budget effect on resolution, only if the step's reservation is LOCKED:
  `EXECUTED` → COMMITTED; `NOT_EXECUTED` → RELEASED; `UNDETERMINED` or
  `abandoned` → COMMITTED (conservative).
- `abandoned` is reachable only from `retrying` (canonical). For `retry_mode =
  NONE`, a human resolves with `UNDETERMINED` when the outcome cannot be
  determined.
- `tenant_id` is absent in the existing table: add it to the S7 table as
  "existing, absent, record gap".
- Record all four schema conflicts.

### C22 — Step terminal reasons (register entry XS-1, accepted)

Source: `XS-1_REGISTER_ENTRY.md`. Its proposed ruling is accepted with the
refinements below. File XS-1 in the blocker register as RESOLVED BY C22.

Conflicts (from XS-1):
- STATE_TRANSITIONS §2 and DATA_CONTRACTS annotate step `PENDING → CANCELLED` as
  "user cancelled before start", but this gate cancels steps for system reasons
  (Section 8 steps 1, 5, 6 and 12; Section 9 NOT_EXECUTED without retry).
- The gate requires a specific reason, but `execution_steps` only has free-text
  `error`.
- The `execution_steps.status` comment omits `cancelled`.
- STATE_TRANSITIONS invariant I-1 omits `cancelled` from terminal step states.

Ruling:
- **Doc repairs (commit B):** annotate `PENDING → CANCELLED` as "did not start:
  cancelled by the user or by the system" in STATE_TRANSITIONS §2 and
  DATA_CONTRACTS. No new state or transition. Add `cancelled` to the
  `execution_steps.status` comment and to invariant I-1's terminal list.
- **Additive column** `execution_steps.terminal_reason TEXT NULL`, written in the
  same `fenced_write()` as the terminal transition.
- **Closed reason-code enum** `StepTerminalReason`, defined in DATA_CONTRACTS and
  enforced by a CHECK constraint. Initial values:
  `user_cancelled`, `admission_rejected`, `admission_exhausted`, `no_worker`,
  `lease_unavailable`, `budget_exhausted`, `preflight_failed`,
  `not_executed_no_retry`, `dependency_failed`, `run_dead_lettered`,
  `authorization_revoked`, `kill_switch_engaged` (the last two added by C23).
  Future phases may add values (the Laya note will add `reflex_*` codes); never
  remove or rename one.
- **Required when:** `CHECK (status NOT IN ('cancelled','skipped') OR
  terminal_reason IS NOT NULL)`. SKIPPED steps use `dependency_failed`. Reasons on
  other terminal states are optional in this phase.
- **Which reason a step gets:** the step that triggered a termination gets the
  specific reason. Collateral steps (remaining PENDING steps cancelled because of
  it) get the **same** reason as the trigger. Example: budget exhausted on step 3 →
  steps 3, 4, 5 all `budget_exhausted`. After a DEAD_LETTER step (Section 8 step 12)
  the collateral reason is `run_dead_lettered`. User cancellation (C16) gives
  `user_cancelled` to every remaining step.
- **Pre-flight detail:** the reason code is `preflight_failed`. The specific
  failure (schema invalid, resource scope) goes in `error` for diagnostics only.
  No logic may read `error`.
- **Immutable once written:** `fenced_write()` rejects any update of a non-null
  `terminal_reason`, and a `BEFORE UPDATE` trigger rejects it at the database
  level too.
- **SKIPPED stays reserved** for "dependency failed, step not needed". It must
  never be used for a required step that did not run, because consolidation treats
  COMPLETED + SKIPPED with no failures as SUCCESS.

### C23 — Live authorization revalidation before new side effects

Source: WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md "Re-entry Revalidation" (added
to the spec after v7). It requires that every re-entry point (dead-letter retry,
checkpoint resume, lease reacquisition after expiry, reconciliation of UNKNOWN)
re-evaluate authorization against live state before any further side effect, and
that a run whose authorization was revoked terminates instead of resuming.

Conflict: v7 forbade any re-authorization in S12–S15. The new spec text is
correct on security grounds (a grant revoked, tenant suspended or kill switch
engaged while a run waits must not be ignored), so this ruling adopts it and
defines exactly how it works without re-running S8.

Ruling:
- **Mechanism.** A read-only component `LiveAuthorizationCheck` evaluates, against
  live state: kill switch (C-ruling source: system/tenant configuration), user
  active, tenant active, connection active, capability granted, resource scope.
  It reuses the same deterministic check functions S8 uses, from a shared library
  module, so the logic exists once. It never writes a `SafetyResult`, never
  touches PipelineState and never changes ExecutionContext. It returns
  `ALLOW` or `REVOKED(reason)`. Budget, circuit breaker and mutation safety are
  not re-checked here; they are enforced per step by C3, the reliability guard and
  admission.
- **When it runs.** Immediately before initiating any **new side effect**:
  1. before every step's adapter call (Section 8, between steps 7 and 8), which
     covers normal execution, checkpoint resume and lease reacquisition;
  2. before a dead-letter retry with `retry_mode = VERIFY` or `PROBE` is allowed
     to lead to any further step execution (the probe or verification itself
     may run first, see below).
- **What is not a side effect.** Provider probes (Section 9) and verification
  re-runs (C19) only observe. They always run, even after revocation, because
  resolving uncertainty is required to settle budget (I12) and step state. They
  never lead to a new adapter call once revocation is detected.
- **Fail-closed.** If live state cannot be read, the result is
  `REVOKED("authorization_state_unavailable")`.
- **On REVOKED.**
  - No new adapter call is made.
  - An in-flight or uncertain step is still resolved (probe or verification) to a
    terminal state first.
  - All remaining PENDING steps → CANCELLED with `terminal_reason`
    `kill_switch_engaged` if the kill switch caused it, otherwise
    `authorization_revoked` (C22 enum, additive).
  - The run → CANCELLED (legal: `RUNNING → CANCELLED`, `RECONCILING → CANCELLED`),
    unless a step is DEAD_LETTER, which takes precedence (C16).
  - A ledger event `authorization_revoked` records the check that failed.
- **Snapshot role.** ExecutionContext, IntentSpecification, FrozenBindingIdentity
  and ExecutionManifest remain the reproducibility record. They are never used
  as the authorization answer at a revalidation point.
- **Doc repair (commit B).** Add to the WORKER_LIFECYCLE section: "Revalidation is
  performed by the read-only LiveAuthorizationCheck (S12–S15 gate C23). Probes and
  verification are observations, not side effects, and always run to settle
  uncertainty; they never lead to new adapter calls after revocation."

---

## 6. OWNER DECISIONS (CONFIRM OR CHANGE BEFORE HANDING OFF)

These are choices, not contradictions. The recommended option is pre-selected. The
owner may change any of them before this instruction is sent.

**D1 — Verifier origin.** The spec says the verifier is "built at S11, frozen in
ExecutionManifest", but ExecutionManifest has no verifier field and S11 is frozen.
- **Selected:** at S12 entry, build verifiers with a pure, deterministic
  `build_verifier(step, kernel_op_metadata)`. The metadata is read at the versions
  pinned in the manifest (`capability_version`, `binding_version`). Persist the
  verifiers with the execution (Section 7.3). If pinned metadata is unavailable,
  deny at S12 entry with reason `verifier_metadata_unavailable`.
- A test must prove the factory is deterministic and reads nothing outside the step
  and the pinned metadata.
- Record the doc conflict.

**D2 — Rollback.** Automatic rollback trigger conditions are not specified.
- **Selected:** no automatic compensating operations in this phase. For every
  completed W/D step with an `inverse`, record `undo_token`. Implement
  `rollback_execution(execution_id)` as an explicit operation. It verifies each
  original operation executed before compensating, runs inverses through the full
  reliability guard with key `f"{request_id}:{step_id}:inverse"`, never compensates
  IRREVERSIBLE, and dead-letters failed inverses. Test it in isolation. Nothing
  calls it automatically.

**D3 — Join modes.** The consolidation table does not define `any` or `threshold`.
- **Selected:** S12 executes `join_mode = "all"` only. Any other value is denied at
  S12 entry with reason `join_mode_unsupported`, before anything is persisted. If
  preflight item 5 shows S9 emits only `all`, this guard is a fail-closed safety net.

**D4 — Unresolved UNKNOWN and the human verification layer.**
- **Selected:** a step still unresolved after max probes goes to step state
  DEAD_LETTER. Its reservation **stays LOCKED** while the dead letter is `pending` or
  `retrying`. On dead-letter `resolved`, the resolution records whether the operation
  executed, and the reservation becomes COMMITTED or RELEASED accordingly. On
  `abandoned`, it becomes COMMITTED (conservative).
- The human verification layer has no HITL channel yet. In this phase it returns
  UNKNOWN, which routes the step to DEAD_LETTER with `error_type = "unknown_unresolved"`
  and full evidence, per the S13 rule "a failure at any layer routes to DEAD_LETTER".
- The run's DEAD_LETTER status is terminal and does not reopen when the dead letter
  is resolved. Resolving or abandoning a dead letter may change only: the
  `dead_letters` row, the step's budget reservation (LOCKED → COMMITTED or
  RELEASED), and audit/ledger events. It must **never** change the run state or the
  step state (both are terminal). A test asserts that resolving a dead letter
  leaves `execution_runs.status` and `execution_steps.status` unchanged. Record "no post-execution human-approval run state" as an open
  question.

**D5 — Dead-letter retry.**
- **Selected:** a dead-letter retry never re-executes a step, because the run is
  terminal. Re-executing a failed request requires a new request through S0.
  What a retry may do depends on the dead letter's `retry_mode` (C21), set once at
  creation:
  - `PROBE` — the dead letter came from an unresolved `EXECUTION` episode. Retry
    calls the provider probe only.
  - `VERIFY` — the dead letter came from an unresolved `VERIFICATION` episode
    (non-human layers). Retry re-runs only the verification layers not yet PASS.
    It never calls the provider probe or the adapter.
  - `NONE` — no automatic retry: human-layer pending (D4), verification FAIL,
    retries exhausted on a definitive error, inverse failure (D2), permanent
    errors. These leave `pending` only through human resolution.
- Transient errors are already retried inside S12 before reaching the dead letter,
  so a definitive failure after exhausted retries is `NONE`, not `PROBE`.

**D6 — Semantic (LLM) verification layer.**
- **Selected:** the semantic layer may only produce FAIL or UNKNOWN when it
  disagrees. It can never turn a failing deterministic layer into PASS, because every
  required layer must pass independently. LLM output is parsed into the strict enum
  `{PASS, FAIL, UNKNOWN}`, and anything malformed becomes UNKNOWN. Tests use a mock
  LLM. If preflight item 6 shows no canonical AutonomyLevel source, STOP and report.
  Do not guess.

---

## 7. S12 ENTRY — FROM CERTIFIED PLAN TO DURABLE EXECUTION

### 7.1 Entry checks (before any write)

S12 receives the certified PipelineState. In order:

1. `validation_result` indicates S11 success, and the ExecutionManifest exists.
2. `execution_context.auth_passed is True` and `auth_result_id` is present.
   Otherwise deny with reason `authorization_missing`. Do not re-authorize.
3. `frozen_binding_identity` is present.
4. `plan.join_mode == "all"` (D3).
5. Recompute the canonical plan digest with the S11 verification function. It must
   equal `manifest.plan_hash` and `plan_hash` from S9. Otherwise deny with reason
   `plan_integrity`.
6. Build verifiers (D1).

Any failure returns `StageStatus.DENY` with the specific reason, and writes nothing.

### 7.2 Durable admission (one transaction)

1. Duplicate check: if an `execution_runs` row with the same `(tenant_id, request_id)`
   exists, return that execution's current status or result. Create nothing new.
2. Insert, in one transaction:
   - `execution_runs` (status PENDING)
   - `execution_manifests`
   - `execution_plans` (Section 7.3)
   - one `execution_steps` row per step (status `pending`, with `resolved_binding_id`,
     `effective_risk` and `effective_mutation` copied from the FrozenBindingIdentity,
     never recomputed)
   - `execution_ownership` (this Runner, no lease yet)
3. Transition the run PENDING → RUNNING.

### 7.3 Additive schema

Add, via migration:

- `execution_plans(execution_id PK FK execution_runs, tenant_id, plan_hash,
  canonical_plan JSONB, frozen_binding_identity JSONB, verifiers JSONB, created_at)`.
  This lets recovery reload the exact plan. On every load, recompute the digest and
  compare it to `plan_hash`. On mismatch during recovery, move the run to
  DEAD_LETTER with reason `plan_integrity` and alert. Do not execute any new step.
- A unique index on `execution_runs(tenant_id, request_id)`.
- An index on `worker_leases(worker_id)` filtered to active leases, to support the
  capacity count in C5.
- The storage required by the PostgreSQL confirmation store.
- `step_reconciliations` (C18), with a partial unique index allowing one open
  episode per step.
- `execution_steps.terminal_reason` with its CHECK constraints and the
  immutability trigger (C22).
- `dead_letters.status`, `retry_mode`, `episode_id`, `resolution_outcome`, and the
  `error_type` CHECK (C21).
- `execution_runs.cancel_requested_at` (C16), nullable.
- `idempotency_ledger.tenant_id` (Section 21 S7), nullable, plus an index on
  `(tenant_id, idempotency_key)`.

DATABASE.md mixes SQLite-style and PostgreSQL types (for example, `TEXT` tenant_id
referencing `UUID` columns). For tables touched in this phase:
- Write valid PostgreSQL DDL using the documented column names.
- Where a foreign-key type mismatch prevents creating the constraint, change the
  referencing column's type to match the referenced column. Change nothing else.
- Record every such change.

---

## 8. S12 STEP LOOP — NORMATIVE SEQUENCE

Steps execute one at a time in topological order (C11). Parallel step execution is
out of scope. Before each step, check for a cancellation request (C16). For each
step:

1. **Admission.** Call the admission controller. It is stateless: no reservation, no
   lease.
   - ACCEPT: continue.
   - DEGRADE: continue with the degraded features disabled. Any timeout reduction
     applies to the runtime effective timeout only and never modifies the Plan.
   - QUEUE or DELAY: wait `retry_after_ms`, then re-admit, up to a configured maximum.
     After the maximum, treat it as REJECT with reason `admission_exhausted`.
   - REJECT: this step and all remaining PENDING steps become CANCELLED. The run is
     consolidated (Section 10).
2. **Worker selection.** Use state-locality scoring per WORKER_LIFECYCLE §13. If no
   eligible ACTIVE worker exists, handle it as REJECT with reason `no_worker`.
3. **Lease.** Acquire a lease on the selected worker (C5). On failure, re-run
   selection and acquisition, up to a configured maximum. Then treat it as REJECT
   with reason `lease_unavailable`.
4. *(Removed in v3. The idempotency check now happens inside step 8, immediately
   before the adapter call. See C17.)*
5. **Budget reserve.** Reserve per C3. On `budget_exhausted`, the step becomes
   CANCELLED (it never ran), the lease is released, remaining steps become CANCELLED,
   and the run transitions to CANCELLED with reason `budget_exhausted` (C15).
6. **Pre-flight.** Validate params against the kernel input schema and check resource
   scope. On failure, release the budget, release the lease, and mark the step
   CANCELLED with the specific reason. It never ran.
7. **Step PENDING → RUNNING.** Budget RESERVED → LOCKED. Write the checkpoint.
8. **Execute through the reliability guard.** Immediately before each adapter call,
   look up the step idempotency key (C9, scoped by tenant per Section 21 S7). On a
   hit, use the cached definitive result instead of calling the adapter, and handle
   it exactly like an adapter result of the same kind (C17). Otherwise call the
   adapter, only through the guard, and store the idempotency record on a
   definitive result (success, or a non-retryable failure). Ledger rules:
   - The ledger insert is a durable execution write and goes through
     `fenced_write()`. A fenced-out Runner's result is discarded; the new owner
     learns the outcome by probing.
   - `idempotency_key` is the table's PRIMARY KEY (DATABASE.md), so it is already
     unique. Insert with `ON CONFLICT (idempotency_key) DO NOTHING`. If nothing was
     inserted, read the existing row: same `tenant_id`, `kernel_op_id` and result
     kind → treat as a hit; anything else → raise `IdempotencyConflict` (an
     invariant violation; stop condition).
   - Lookups filter on both `idempotency_key` and `tenant_id`.
   - **An expired ledger record counts as no record.** It never authorizes
     executing fresh. MUTATION_SAFETY §5's "key exists, expired → execute fresh"
     is superseded for this phase: a missing or expired record for a step that may
     already have run always leads to a probe (Section 13), never to a blind call.
   - Persist verification layer results for the step (layer, verdict, evidence
     reference) through `fenced_write()` before the step commit, so recovery can
     tell whether verification already passed. Renew the lease in the background at TTL/3. Handle outcomes:
   - Success: go to step 9.
   - Retryable error (MUTATION_SAFETY §3, within ceilings): stay RUNNING, back off,
     increment `attempt`, repeat step 8.
   - Non-retryable error or retries exhausted: step RUNNING → FAILED, budget →
     RELEASED.
   - Timeout: step RUNNING → TIMEOUT → PENDING_PROBE, then go to Section 9.
   - `FencedOut` at any point: stop all work on this execution immediately.
9. **Verification** (C12, S13 layers per `required_verification_layers`):
   - All required layers PASS: step → COMPLETED, budget LOCKED → COMMITTED.
   - Any layer FAIL: step → FAILED, budget → RELEASED, create a dead letter with
     `error_type = "data"` and evidence. Verification failure is not retryable.
   - Any layer UNKNOWN after the verifier's bounded attempts: open a
     `VERIFICATION` episode (C19). Do not call the provider probe.
10. **Record** `undo_token` for completed W/D steps that have an `inverse`.
11. **Checkpoint.** Write the checkpoint and release the lease.
12. **Dependents.** When a step ends FAILED, CANCELLED or DEAD_LETTER, its transitive
    dependents become SKIPPED. After any step reaches DEAD_LETTER, all remaining
    PENDING steps become CANCELLED. No further mutations run on uncertain state.

After the loop, consolidate (Section 10).

---

## 9. UNKNOWN, PROBE AND RECONCILIATION

- The adapter probe returns exactly one of: EXECUTED_SUCCESS, EXECUTED_FAILURE,
  NOT_EXECUTED, INCONCLUSIVE.
- This section covers `EXECUTION` episodes. `VERIFICATION` episodes follow C19.
- Each episode is a `step_reconciliations` record with its own ReconciliationStatus
  lifecycle (C18 table).
- **Ledger before probe.** Before calling the provider probe, look up the step
  idempotency key. A hit is a definitive result: treat it as EXECUTED_SUCCESS or
  EXECUTED_FAILURE according to the cached result, without probing.
- Probe results:
  - EXECUTED_SUCCESS: step PENDING_PROBE → COMPLETED (after verification if
    required), budget → COMMITTED, reconciliation → CONFIRMED_SUCCESS.
  - EXECUTED_FAILURE: step → FAILED, budget → RELEASED, reconciliation →
    CONFIRMED_FAILURE.
  - NOT_EXECUTED: step → PENDING, budget → RELEASED. The step may be retried within
    its retry ceiling. IRREVERSIBLE and non-idempotent D steps are never retried:
    they become CANCELLED.
  - INCONCLUSIVE: retry the probe with backoff, max 3 attempts. Then step →
    DEAD_LETTER, error_type `unknown_unresolved`, and D4 applies.
- Probing happens with the run in RUNNING, except as described in C13.
- Every UNKNOWN must pass through PENDING_PROBE. There are no shortcuts.
- **Recovery** of an in-flight step follows the single decision rule in Section 13,
  step 3. No other section defines recovery behavior.

---

## 10. S13 — CONSOLIDATION

Apply the S13 consolidation table as corrected by C8. CANCELLED and SKIPPED steps
count as not completed. Specifically:

| Condition | Run status | Outcome |
|---|---|---|
| Any step DEAD_LETTER | DEAD_LETTER | FAILURE |
| All steps COMPLETED (or COMPLETED + SKIPPED with no failures) | COMPLETED | SUCCESS |
| At least one COMPLETED and at least one FAILED/CANCELLED | PARTIAL | PARTIAL |
| No step COMPLETED | FAILED | FAILURE |

- Transition the run using the legal matrix only. RUNNING or RECONCILING to terminal
  is permitted.
- Emit VERIFICATION_STARTED and VERIFICATION_COMPLETED ledger events, with the layer
  results.
- After consolidation, no reservation for this run may remain RESERVED. LOCKED is
  permitted only under D4.

---

## 11. S14 — DEAD LETTER

- Create a dead letter record for:
  - retryable errors whose retries are exhausted
  - `unknown_unresolved` steps
  - verification FAIL
  - human-layer pending (D4)
  - inverse failures (D2)
- Do not create one for 401, 403, 404 or 422. Those are reported to the user, per the
  negative-path matrix.
- **A dead-letter record is not the same thing as the step state DEAD_LETTER.**
  Only unresolved uncertainty (an episode ending EXHAUSTED, or the human layer)
  puts the *step* in DEAD_LETTER. Verification FAIL, exhausted retries on a
  definitive error and inverse failures leave the step FAILED (or the inverse
  unexecuted) and create a dead-letter record for review and evidence only.
  Consolidation (Section 10) looks at step states, not at dead-letter records.
- Dead letter lifecycle per STATE_TRANSITIONS §9, stored as specified in C21.
  Retry behavior depends on `retry_mode` (D5).
- Every dead letter has evidence: attempts, probe results, verifier observations, and
  error classification.
- Dead letters are never dropped. Record an alert event for `permanent` and
  `unknown_unresolved`. The alert delivery channel is out of scope; use a recorded
  event plus a log line.

---

## 12. S15 — RESPONSE

- Map run status to envelope: COMPLETED → `ok`, PARTIAL → `partial`, FAILED,
  CANCELLED and DEAD_LETTER → `error`. S12 entry denials use the mapping established
  for DENY in the S0–S11 gate.
- `partial` lists the failed or cancelled steps using user-safe descriptions.
- For a CANCELLED run, the `error` envelope also lists steps that completed before
  cancellation, because their side effects already happened.
- Never include raw exception text, stack traces, provider response bodies, secrets,
  tokens or internal IDs other than `trace_id`.
- User messages follow the negative-path matrix wording where a row applies.

---

## 13. SINGLE-NODE CRASH RECOVERY

- On Runner start, generate a new `runner_id` and start the recovery sweeper, which
  runs at the interval in FINAL_ARCHITECTURE (under 30 seconds).
- The sweeper finds runs in RUNNING or RECONCILING whose ownership lease is expired or
  absent. For each one:
  1. Take ownership: acquire a new lease with a higher fence token, and do the
     `execution_ownership` compare-and-set.
  2. Reload the plan from `execution_plans` and verify the digest (Section 7.3).
  3. Handle the in-flight step first. It is never blindly re-executed. This is the
     single recovery decision rule; no other section defines one:

     ```text
     step in RUNNING / TIMEOUT / UNKNOWN / PENDING_PROBE
        │
        ├─ open episode exists → continue that episode (same kind)
        │
        └─ no open episode → look up the step idempotency key
              ├─ ledger record exists, verification not recorded as PASS
              │     → step → PENDING_PROBE (if not already)
              │     → open VERIFICATION episode (C19)
              │     → provider probe NOT called, adapter NOT called
              │
              ├─ ledger record = success, all required layers recorded as PASS
              │     → step → PENDING_PROBE → COMPLETED, budget → COMMITTED
              │     → record an episode opened and closed in one transaction:
              │       NONE → PENDING_PROBE → RECONCILING → CONFIRMED_SUCCESS,
              │       kind VERIFICATION, outcome LEDGER_HIT
              │
              ├─ ledger record = definitive failure
              │     → step → PENDING_PROBE → FAILED, budget → RELEASED
              │     → episode recorded the same way, closed CONFIRMED_FAILURE,
              │       kind EXECUTION, outcome LEDGER_HIT
              │
              └─ no ledger record, or ledger record expired
                    → step → PENDING_PROBE (RUNNING, TIMEOUT and UNKNOWN all have
                      a direct legal transition to PENDING_PROBE; C6)
                    → open EXECUTION episode → provider probe (Section 9)
     ```
  4. Continue the loop from the first PENDING step.
- Expired leases transition `active → expired`. They are never reactivated.
- The DB state is the source of truth. The checkpoint is a hint.

---

## 14. ITEMS DEFERRED FROM THE S0–S11 GATE

### Now in scope

- `pending_confirmations` persistence: implement the PostgreSQL confirmation store
  behind the existing interface. Re-run the S0–S11 confirmation tests against both
  the in-memory and the PostgreSQL implementation. Include concurrent consumption,
  with exactly one winner under real transactions.
- `execution_manifests` persistence (Section 7.2).
- Restart recovery (Section 13).
- Database concurrency verification (Section 16).
- Leases and fencing, budget reservation, checkpoint and recovery, adapter execution,
  and the UNKNOWN/probe path.

### Still deferred (record; do not implement)

- Multi-node fleet and the notification channel
- Distributed circuit breakers
- Worker version and deployment lifecycle
- The HITL channel for human verification
- Automatic rollback triggers
- `any` and `threshold` join modes
- Parallel step execution
- Real provider adapters
- LayaDecisionAdapter (design note `LAYA_DECISION_ADAPTER.md`, status DEFERRED;
  target phase: LLM layer). File its blocker entries LB1–LB11 in the register with
  that target phase. Nothing from it is implemented, migrated or tested here. In
  particular, Section 8 step 4 stays empty in this phase (the note's LB9 proposes
  it for a decision position later).
- Alert delivery
- ~~Tenant scoping of `idempotency_ledger`~~ — RESOLVED IN THIS PHASE (Section 21
  S7); list it in the report as resolved, not outstanding

---

## 15. TEST INFRASTRUCTURE

### 15.1 Database

- Every lease, budget, fencing, confirmation, recovery and concurrency test runs
  against real PostgreSQL via `TEST_DATABASE_URL`.
- SQLite or in-memory fakes are not acceptable for these, because they lack
  `FOR UPDATE` and real transaction isolation.
- Each test runs in an isolated schema or database that is created and dropped per
  test module.
- Lease expiry uses database server time. Tests use short TTLs (1–2 seconds), not a
  mocked clock. Pure unit tests may inject a fake clock.

### 15.2 Fault injection

- Add named injection points that raise `SimulatedCrash` in test mode only:
  - `after_lease_acquire`
  - `after_budget_reserve`
  - `after_budget_lock`
  - `after_adapter_call_before_ledger` (adapter returned; ledger not yet written)
  - `after_ledger_before_verification` (ledger written; verification not started)
  - `during_verification`
  - `after_verification_before_step_commit`
  - `after_commit_before_checkpoint`
  - `during_probe`
- In-process crash test: discard the Runner instance and its memory, start a fresh
  Runner (new `runner_id`), and let recovery run.
- At least three tests must kill a real Runner subprocess (`subprocess.Popen` then
  `.kill()`, which works on Windows and Linux) at a mid-execution point, then recover
  in a new process.
- Injection points must be compiled out or inert outside test mode. An architecture
  test enforces this.

### 15.3 Mock provider adapter

A programmable adapter with a side-effect ledger that counts **actual executions per
step idempotency key**. Required behaviors:

| Behavior | Effect |
|---|---|
| `success` | Executes, returns success |
| `fail_500_then_success(n)` | n × 500, then success |
| `rate_limit_429(n)` | n × 429, then success |
| `auth_401` | Non-retryable failure |
| `validation_422` | Non-retryable failure |
| `timeout_executed` | Executes, then times out before responding |
| `timeout_not_executed` | Times out without executing |
| `probe_inconclusive` | Probe always INCONCLUSIVE |
| `verify_mismatch` | Executes, but observation contradicts expected state |
| `slow(ms)` | Delays, for lease renewal and fencing tests |

The side-effect ledger honors idempotency keys the way a real provider would: a
repeated key does not execute twice.

---

## 16. REQUIRED TEST SUITES

1. **State machines.** For every canonical machine as corrected in Section 5 (run,
   step, budget, lease, worker, dead letter, reconciliation): every valid transition
   succeeds and every other pair raises `IllegalStateTransition`. Generate the pairs
   exhaustively.
2. **Architecture.** Extend the S0–S11 architecture tests to S12–S15:
   - No resolver, risk or mutation recomputation.
   - No S8 stage handler imports or calls. The only permitted import from S8 is the
     shared check library used by `LiveAuthorizationCheck` (C23).
   - No direct adapter calls outside the reliability guard.
   - No durable execution writes outside `fenced_write()`.
   - No filesystem checkpoint code.
   - Fault injection inert outside test mode.
3. **S12 entry.** Each check in 7.1 fails closed with its specific reason and writes
   nothing. Duplicate `request_id` returns the existing execution. Plan tampered
   between S11 and S12 is denied.
4. **Budget.**
   - Reserve, lock, commit and release paths.
   - Exhaustion.
   - 20 concurrent reservations against a small pool: never over-reserved.
   - C14 behavior.
   - D4 behavior.
   - Conservation invariant after every test.
5. **Leases and fencing.**
   - Acquire, renew (token increments), release, expire.
   - Active leases per worker never exceed `capacity` under concurrency (test with
     capacity 1 and capacity 3), and `current_load` always equals the active count.
   - Stale Runner fenced out: its writes after losing the lease affect 0 rows, and
     it stops.
   - Lease lost mid-call: the result is discarded and the new owner probes.
6. **Idempotency.**
   - A cached step result prevents re-execution.
   - Retries reuse the same key.
   - Two steps in one request get different keys.
   - The provider side-effect count is 1 per key for W, D and IRREVERSIBLE.
   - **Crash A** at `after_adapter_call_before_ledger`: no ledger record exists.
     Recovery opens an `EXECUTION` episode and **must probe**. With the mock in
     `success` mode the probe returns EXECUTED_SUCCESS: provider side effects = 1,
     reservations for the step = 1, COMMITTED once, adapter not called again.
   - **Crash B** at `after_ledger_before_verification`: ledger record exists.
     Recovery opens a `VERIFICATION` episode: probe **not** called, adapter not
     called, verification runs, step COMPLETED, reservation COMMITTED once.
   - **Crash C** at `during_verification` and
     `after_verification_before_step_commit`: same expectations as Crash B.
   - Cached definitive failure: step FAILED, reservation RELEASED, no adapter call.
   - Duplicate request at S12 entry: existing execution returned, 0 new
     reservations, 0 adapter calls, 0 new step rows.
   - Every transition on the hit path is legal (checked by I5).
   - Two Runners race to insert the same ledger key (one of them fenced out):
     exactly one row exists; the fenced-out insert is rejected by
     `fenced_write()`; a conflicting row raises `IdempotencyConflict`.
   - Expired ledger record at recovery: the probe is called; the adapter is not
     called blindly.
   - Recovery with ledger = definitive failure: step FAILED, reservation RELEASED,
     no probe, no adapter call.
7. **Retry.** The MUTATION_SAFETY §3 matrix per mutation type and error class,
   including IRREVERSIBLE never retried and non-idempotent D never retried. The step
   stays RUNNING across attempts.
8. **UNKNOWN and probe.** All four probe outcomes. The read re-execution path.
   Inconclusive to DEAD_LETTER after 3 probes. No UNKNOWN reaches a terminal state
   without PENDING_PROBE (audited from the transition log).
9. **Verification.**
   - Layer selection per mutation, risk and autonomy.
   - Deterministic FAIL cannot be overridden by semantic PASS.
   - Malformed LLM output becomes UNKNOWN.
   - The verifier factory is deterministic (D1).
   - Verification UNKNOWN (inconclusive read-back; malformed semantic output) opens
     a `VERIFICATION` episode; the provider probe is called 0 times and the adapter
     0 extra times; PASS on re-attempt → COMPLETED; persistent UNKNOWN →
     DEAD_LETTER with budget LOCKED.
   - Schema and deterministic layers never return UNKNOWN.
   - Resolving a dead letter never changes run or step state (D4).
10. **Consolidation.** Every row of Section 10.
11. **Dead letter.** Creation rules, evidence completeness, lifecycle, budget
    resolution on resolved and abandoned, and per `retry_mode`:
    - `PROBE` retry calls the probe, never the adapter or the verifier alone;
    - `VERIFY` retry calls the verifier only: provider probe 0 calls, adapter 0
      calls;
    - `NONE` has no automatic retry and leaves `pending` only via resolution;
    - a verification-FAIL record leaves the step FAILED and the run consolidated by
      step states (not DEAD_LETTER);
    - I12 holds in every dead-letter state.
12. **S15.** The mapping, plus the redaction test: inject exceptions containing
    secrets or stack traces and assert none reach the envelope.
13. **Confirmation store (PostgreSQL).** All S0–S11 confirmation tests, plus 20
    concurrent consumers with exactly one winner.
14. **Crash recovery.** Every injection point in 15.2, plus 3 subprocess kills. After
    recovery: the Section 17 invariants hold, and no W, D or IRREVERSIBLE step
    executed twice.
15. **Full journeys, S0 → S15:**
    - Happy path, multi-step with dependencies.
    - Retry then success.
    - Timeout-executed resolved by probe.
    - Timeout-not-executed then retry.
    - Verification mismatch leading to PARTIAL.
    - Budget exhaustion mid-plan.
    - Inconclusive probe leading to DEAD_LETTER.
    - Crash mid-plan then resume to COMPLETED.
16. **Terminal reasons (C22).** Every system cancellation path in Sections 8 and 9
    writes the expected `terminal_reason`, including collateral steps. The database
    rejects a CANCELLED or SKIPPED step with a null or unknown reason. A second
    write to a non-null `terminal_reason` is rejected by both `fenced_write()` and
    the trigger. Invariant I-1 passes for runs containing CANCELLED steps. A run
    with a CANCELLED required step never consolidates to COMPLETED.
16b. **Live revalidation (C23).** For each of: kill switch engaged, user
    deactivated, tenant suspended, connection deleted, grant revoked, live state
    unreadable — engaged between two steps: no further adapter call; remaining
    steps CANCELLED with the correct `terminal_reason`; run CANCELLED. Same while a
    step is UNKNOWN: the probe still runs and resolves the step first, then no new
    adapter call. Crash recovery after revocation: the sweeper resolves, then
    cancels, never resumes. `LiveAuthorizationCheck` writes nothing (assert no
    PipelineState, SafetyResult or ExecutionContext change).
16a. **Cancellation (C15, C16).** Cancel before start, between steps, during an
    in-flight step, and during RECONCILING. Budget exhaustion mid-plan ends
    CANCELLED. Cancellation by another user or tenant is rejected.
17. **Two Runners, one database.** Start two Runner processes against the same
    `suprpg_test` database. Assert: each execution has exactly one owner at a time;
    when one Runner is killed, the other's sweeper takes over its executions; no
    step executes twice; all invariants hold. This proves the fleet foundations
    on one machine before the multi-node phase.
18. **Tenant isolation.** A Runner operating for tenant A cannot read or modify tenant
    B executions, reservations, leases or dead letters. If RLS is enabled, it
    enforces this at the database level.

---

## 17. GLOBAL INVARIANTS (CHECKER)

Implement `assert_system_invariants(db)`. Call it at the end of every integration,
concurrency and crash test.

| ID | Invariant |
|---|---|
| I1 | Per tenant and period: Σ cost of reserved + locked + committed ≤ `budget_pool` |
| I2 | No reservation is RESERVED for a terminal run. LOCKED only where D4 applies. |
| I3 | No step is non-terminal in a terminal run |
| I4 | Provider side-effect count ≤ 1 per step idempotency key for W, D and IRREVERSIBLE |
| I5 | Every recorded transition is legal under Section 5 |
| I6 | Every UNKNOWN step passed through PENDING_PROBE |
| I7 | No `active` lease for a terminal run. No `expired` lease was reactivated. |
| I8 | Fence tokens are strictly increasing per worker; active leases per worker ≤ `capacity` and equal `current_load` |
| I9 | Every persisted plan's digest equals its `plan_hash` |
| I10 | Every step's `resolved_binding_id`, `effective_risk` and `effective_mutation` equal the persisted FrozenBindingIdentity |
| I11 | Every dead letter has non-empty evidence |
| I12 | Budget per step, by step state (C17, D4, C21). A "live" reservation is one in {reserved, locked, committed}. **Non-terminal step:** at most one live reservation. **COMPLETED:** exactly one live reservation, and it is COMMITTED. **FAILED, CANCELLED, SKIPPED:** zero live reservations. **DEAD_LETTER** with its dead letter `pending` or `retrying`: exactly one live reservation if the step ever reached LOCKED, and it is LOCKED; zero otherwise. **DEAD_LETTER** with its dead letter `resolved` or `abandoned`: zero live reservations, or exactly one COMMITTED, matching the recorded resolution outcome (C21). |
| I13 | Every CANCELLED or SKIPPED step has a `terminal_reason` from the closed enum (C22); no `terminal_reason` changed after it was written; no run with a CANCELLED step consolidated to COMPLETED |
| I14 | No adapter call occurs after a `LiveAuthorizationCheck` returned REVOKED for that run; every run with a REVOKED result ends CANCELLED or DEAD_LETTER; every uncertain step in such a run was resolved before the run became terminal (C23) |

The transition log for I5 and I6 is written by the single transition function of
each state machine, into `audit_log` or the existing ledger mechanism.

---

## 18. COMMIT ORDER

| Commit | Content | Suite state |
|---|---|---|
| A | Preflight report (Section 2). No code. | green |
| B | Doc repairs C1–C23, decisions D1–D6 recorded, vocabulary | green |
| C | Migrations (7.3), repositories, `fenced_write()`, the state-machine transition functions and their tests (suite 1) | green |
| D | PostgreSQL confirmation store (suite 13), S12 entry and durable admission (suite 3) | green |
| E | Workers, leases, fencing, admission, selection (suite 5) | green |
| F | BudgetReserver (suite 4) | green |
| G | Reliability guard, mock adapter, idempotency, retry (suites 6, 7) | green |
| H | S12 loop and probe path (suite 8) | new journeys may be red until I |
| I | S13 verification and consolidation (suites 9, 10) | green |
| J | S14 dead letter (suite 11) | green |
| K | S15 (suite 12) | green |
| L | Crash recovery, fault injection, invariants checker (suites 14, 16) | green |
| M | Full journeys (suite 15), architecture suite (2), certification run | green |

The S0–S11 suite must stay green at every commit.

**Session boundary:** after commit H, STOP and return a progress report (suites
passing, recorded blockers, open questions). Do not start commit I until the owner
authorizes it. Suite 17 (two Runners) and the Section 21 additions belong to commits
L and M unless noted otherwise in Section 21.

---

## 19. STOP CONDITIONS AND CHANGE CONTROL

### 19.1 STOP and report if

- Preflight item 1 or 2 fails.
- Preflight item 6 triggers a stop (D6).
- A contradiction is found that no ruling in Section 5 or 6 covers.
- Any invariant in Section 17 cannot be made to hold.
- A W, D or IRREVERSIBLE step executes twice in any test.
- A fenced-out Runner succeeds in any durable write.
- An S0–S11 test fails and the cause is not a trivial import path.

### 19.2 How to report

Give the file and line, the conflicting statements, the options, your recommended
option, and the impact on certification. Then wait.

### 19.3 Change control for S0–S11

If S12–S15 appears to need a change to a certified S0–S11 contract, do not make it.
Report:
1. Which frozen contract is insufficient.
2. Why it cannot be solved inside S12–S15.
3. The smallest possible extension.
4. The regression and re-certification impact.

---

## 20. CERTIFICATION REPORT TEMPLATE

```text
S12–S15 CERTIFICATION

Preflight:                 PASS/FAIL
Doc repairs C1–C23:        PASS (list any not applied + why)
Owner decisions D1–D6:     as confirmed: <list>

State machines:            PASS/FAIL   (transitions tested: N)
Architecture:              PASS/FAIL   (violations: N)
S12 entry:                 PASS/FAIL
Budget:                    PASS/FAIL   (concurrency runs: N, over-reservations: 0)
Leases/fencing:            PASS/FAIL   (fenced-out writes succeeded: 0)
Idempotency:               PASS/FAIL   (duplicate side effects: 0)
Retry matrix:              PASS/FAIL
UNKNOWN/probe:             PASS/FAIL   (UNKNOWN bypassing PENDING_PROBE: 0)
Verification:              PASS/FAIL
Consolidation:             PASS/FAIL
Dead letter:               PASS/FAIL
S15 redaction:             PASS/FAIL
Confirmation store (PG):   PASS/FAIL   (concurrent winners per token: 1)
Crash recovery:            PASS/FAIL   (injection points: N/8, subprocess kills: N/3)
Cancellation:              PASS/FAIL
Two Runners:               PASS/FAIL   (double executions: 0, takeovers: N)
Tenant isolation:          PASS/FAIL
Journeys S0→S15:           N/8 PASS
Invariants I1–I14:         PASS/FAIL   (checked in N tests)
Scale-readiness S1–S9:     PASS/FAIL   (list any not met)
Performance baseline:      p50/p95 S12 overhead per step = X/Y ms (recorded, no threshold)

S0–S11 regression:         X/Y PASS
Full regression:           X/Y PASS
Skipped: 0   XFail: 0

Recorded blockers:         <IDs>
Open questions:            <IDs>
Deleted tests:             <name, reason, replacement> or none

Final:                     CERTIFIED / NOT CERTIFIED
```

---

## 21. SCALE-READINESS REQUIREMENTS (SEAMS, NOT FEATURES)

The next phases add configuration portability, a multi-node fleet, observability,
secrets management and data governance. This gate must not implement those phases.
It must avoid building anything that would have to be torn out for them. Each item
below is an interface plus one simple implementation, or a rule, not a new feature.

**S1 — Configuration.** All infrastructure settings (database URL, pool sizes,
lease TTL, sweeper interval, probe limits, admission limits) come from one settings
object populated from environment variables. No hard-coded hosts, ports, paths or
credentials anywhere in `src/`. An architecture test scans for them.

**S2 — Dispatch seam.** Dispatch goes through an `ExecutionDispatcher` interface.
This phase ships only `InProcessDispatcher`. The engine never imports asyncio task
scheduling for dispatch directly.

**S3 — No hidden process-local state.** Circuit breaker, retry-storm guard,
bulkhead and health monitor state sit behind injected interfaces. No module-level
mutable globals, no singletons created at import time. An architecture test
enforces it. Single-node in-memory implementations are fine; they must be
replaceable by distributed ones later without touching S12 code.

**S4 — Sweeper safe under concurrency.** Takeover selects candidate runs with
`FOR UPDATE SKIP LOCKED` so several Runners' sweepers never claim the same
execution. Suite 17 verifies it.

**S5 — Structured, correlated logs.** Every log line from S12–S15 is structured
(JSON) and carries `trace_id`, `execution_id`, and where applicable `step_id`,
`attempt_id`, `provider_call_id`, `runner_id`, `tenant_id`. Ledger events and
transition-log rows carry the same IDs. A metrics hook interface exists (counters
for step outcomes, probes, dead letters, fenced-out writes); a no-op implementation
is acceptable. No tracing exporter is required in this phase.

**S6 — Credentials and redaction.** Adapters receive provider credentials only
through a `CredentialProvider` interface keyed by tenant and connection. Credentials
never appear in Plan params, checkpoints, `execution_plans`, dead-letter evidence,
ledger events or logs. Extend suite 12: inject secrets into adapter errors and
provider responses, then assert they are absent from the S15 envelope **and** from
logs, dead-letter evidence and persisted rows.

**S7 — Tenant-scoped data.** DATABASE.md's row-level security policies filter on a
`tenant_id` column of the table itself, so tenant ownership derived through a join
is not enough for RLS. Rule: every **new table** that stores tenant data carries a
`tenant_id` column (NOT NULL) and gets the same RLS policy pattern as existing
tenant tables. New **columns** on existing tables do not need their own tenant field.
During migration review, fill in this table explicitly and include it in the
certification report:

| Structure | New or existing | tenant_id | RLS policy | Notes |
|---|---|---|---|---|
| `execution_plans` | new | required | required | |
| `step_reconciliations` | new | required | required | |
| `pending_confirmations` | existing | present | verify | C20 changes |
| `idempotency_ledger` | existing | added (nullable, see below) | not in this phase | |
| `execution_ownership` | existing | absent | none | scoped via `execution_id`; record gap |
| `worker_leases` | existing | absent | none | scoped via `worker_id`; record gap |
| `execution_steps`, `checkpoints` | existing | absent | none | scoped via `execution_id`; record gap |
| `dead_letters` | existing | absent | none | C21 columns added; scoped via `execution_id`; record gap |
| new columns (`cancel_requested_at`, etc.) | column | n/a | n/a | |
| indexes | n/a | n/a | n/a | |

Do not add `tenant_id` to existing tables marked "record gap" in this phase; they
are scheduled for the data-governance phase. Tenant isolation for them is enforced
in application code (every query is scoped through a run whose `tenant_id` matches)
and verified by the tenant-isolation suite. Additionally,
close the recorded idempotency gap now, because it is additive and cheap: add a
nullable `tenant_id` column to `idempotency_ledger`, write it on every insert, and
scope every lookup by `tenant_id`. Record this as a resolved blocker. Existing
retention fields (`checkpoints.expires_at`, `idempotency_ledger.expires_at`) are
honored by a cleanup job that can be run manually; scheduling it is out of scope.
The cleanup job must never delete a ledger record or checkpoint belonging to a run
that is not terminal.

**S8 — Untrusted provider output.** Provider responses and verifier observations
are untrusted data. When the semantic verification layer (D6) sends them to an LLM,
they are wrapped as delimited data, never concatenated into instructions. Add a test
where a provider response contains text instructing the verifier to return PASS
while the deterministic layers FAIL; the step must end FAILED. A semantic PASS is
never the sole basis for COMPLETED on an IRREVERSIBLE step.

**S9 — Portability.** Code must run unchanged on Windows and Linux. No POSIX-only
APIs (`fork`, `SIGTERM` handlers without a Windows path, hard-coded `/` paths). Use
`pathlib`. Subprocess crash tests use `Popen.kill()`. Record the OS used for
certification; Linux CI is a later phase.

**Performance baseline (record only).** In the certification run, measure p50 and
p95 S12 overhead per step (admission through checkpoint, excluding the mock
adapter's own delay) over at least 200 steps. There is no pass threshold; the
numbers become the baseline for the fleet-reliability phase.

**Deferred register.** Before certification, write every deferred item from Section
14 and every open question from this gate into the blocker register with a target
phase, using this phase order: documentation gaps → secrets and data governance →
configuration portability → HITL and notifications → LLM layer (evaluation harness,
model fallback, cost) → multi-node fleet → observability and reliability → AI Worker
product layer → adapter packaging → AI-platform adapters, frontend, billing → SDK
and CLI.

---

## 22. FINAL AUTHORIZATION

This phase establishes single-node durable execution:

```text
S11 certified manifest
  → S12 entry (verify, persist, admit)
  → per step: admission → worker → lease/fence → idempotency → budget
              → guarded execution → probe on UNKNOWN → verification
              → commit/release → checkpoint
  → S13 consolidation
  → S14 dead letter
  → S15 response
  + crash recovery that never re-executes blindly
```

Only after this gate is certified may work begin on the next phase (configuration
portability, then the multi-node fleet). Do not cross the phase boundary
automatically.
