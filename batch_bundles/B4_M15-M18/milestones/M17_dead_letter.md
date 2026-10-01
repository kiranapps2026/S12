# M17: dead letters and the explicit rollback (gate commit J) ⚙

| | |
|---|---|
| Gate | §11, C21, C27, C29, D2, D4, D5; Appendix A.3, A.6; suite 11; invariants I11, I12 (dead-letter parts) |
| Rulings | CONF-024 (inverse key uses `plan_step_id`), CONF-038 (`InverseBudget` for inverse calls) |
| Golden | `tests_golden/s12/M17_dead_letter.py`: 37 cases (27 functions) |
| Sabotage | `M17_evidence_optional`, `M17_resolution_moves_step`, `M17_verify_retry_probes` |
| Depends on | M15 (VERIFY retries), M13 (PROBE retries), M16 (the run ends through the consolidator), M10 guard |
| Reference | `src/adapters/postgres/dead_letters.py` (194 lines), `src/engine/stages/s14_dead_letter/retry.py` (48), `rollback.py` (123), `reliability.py` `InverseBudget` |

## Files

| File | Action |
|---|---|
| `src/adapters/postgres/dead_letters.py` | **new**: `PostgresDeadLetters(database)` |
| `src/engine/stages/s14_dead_letter/__init__.py` | **new**, empty. Do not reuse the prototype `s14_verification` |
| `src/engine/stages/s14_dead_letter/retry.py` | **new**: `retry_dead_letter` |
| `src/engine/stages/s14_dead_letter/rollback.py` | **new**: `rollback_execution`, `RollbackStep`, `RollbackReport(compensated, skipped, failed)` |
| `src/engine/stages/s12_execute/reliability.py` | add `InverseBudget` (no adapter imports, no SQL) |
| `src/adapters/postgres/budget_reserver.py` | add `settle_dead_letter_reservation(conn, *, ...)`: settles a LOCKED reservation on the caller's connection, inside the resolution transaction |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopDeps.dead_letters=None`; create records at the points below |

The table `dead_letters` exists in migration 015 (`retry_mode`, `resolution_outcome`, `origin`, and the
`chk_dead_letters_outcome` / `chk_dead_letters_rollback` constraints). **No migration.**

## Interface (exact)

```python
class PostgresDeadLetters:
    async def create(self, holder, *, step_id, kernel_op_id, error_type, retry_mode, error, evidence,
                     reservation_id=None, attempt_id=None, episode_id=None, mutation="R") -> str   # dead_letter_id
    async def create_rollback(self, tenant_id, *, execution_id, step_id, kernel_op_id, error_type, error,
                              evidence, mutation) -> str
    async def get(self, tenant_id, dead_letter_id) -> DeadLetterRecord | None
    async def start_retry(self, tenant_id, id) -> DeadLetterRecord
    async def retry_inconclusive(self, tenant_id, id) -> None
    async def resolve(self, tenant_id, id, outcome) -> None
    async def abandon(self, tenant_id, id, outcome="UNDETERMINED") -> None

async def retry_dead_letter(tenant_id, id, *, dead_letters, probe, reverify) -> str      # status
async def rollback_execution(tenant_id, execution_id, *, database, guard, dead_letters,
                             confirm_executed) -> RollbackReport
class InverseBudget:  async def check(self, call: GuardedCall) -> None
```

## Logic and conditions

**When the loop creates a record** (only if `LoopDeps.dead_letters` is set):

| Situation | error_type / retry_mode | Evidence | Step state | Extra |
|---|---|---|---|---|
| retries exhausted | `transient` / NONE | `attempts`, `error_class` | FAILED | `attempt_id` of the last attempt |
| verification FAIL | `data` / NONE | `layers` | FAILED | the run follows its step states |
| EXECUTION episode EXHAUSTED | `unknown_unresolved` / PROBE | episode evidence | DEAD_LETTER | episode id and LOCKED `reservation_id`; alert |
| VERIFICATION episode EXHAUSTED | `unknown_unresolved` / VERIFY | layers | DEAD_LETTER | episode id and reservation; alert |
| human layer | `unknown_unresolved` / NONE | layers | DEAD_LETTER | episode id and reservation; alert |
| 401 / 403 / 404 / 422 (client error) | **no record** | | FAILED | |

**`create`:**

- One fenced write; a stale holder raises `FencedOut`.
- `ValueError`, nothing written, when: evidence is empty, `None` or not a dict; the error code is empty; or a value
  is outside its enum.
- Log the transition `None → pending (created)`.
- `permanent` and `unknown_unresolved` also write a `dead_letter_alert` event (with `dead_letter_id`) in the same
  transaction, and log at ERROR with `dead_letter_id` as a record attribute.
- No alert for `transient` or `data`.

**`create_rollback`:** `origin = rollback`, `retry_mode = NONE`, no fence (the run is terminal); evidence still
required.

**Lifecycle (Appendix A.6).** Validate every move and log it. An illegal move raises the M03/M04
`IllegalStateTransition` (not `ValueError`) and writes nothing.

| Move | Allowed from | Condition |
|---|---|---|
| `start_retry` → `retrying (retry_started)` | pending | retry_mode PROBE or VERIFY only, else `ValueError` |
| `retry_inconclusive` → `pending` | retrying | `retry_count + 1` |
| `resolve` → `resolved (human_resolved)` | pending | known outcome |
| `resolve` → `resolved (retry_resolved)` | retrying | known outcome |
| `abandon` → `abandoned` | retrying only | outcome default UNDETERMINED |

**Budget effect of a resolution.** It applies only when the record holds a **LOCKED** reservation, in the same
transaction, with the A.3 `dead_letter_*` reasons:

| Outcome | Reservation |
|---|---|
| EXECUTED | COMMITTED |
| NOT_EXECUTED | RELEASED |
| UNDETERMINED or abandoned | COMMITTED |

- A resolution **never changes the run or the step** (D4).
- A record of a FAILED step moves no budget.
- Another tenant reads nothing and resolves nothing.
- Two concurrent resolutions settle the record and its budget once: lock the record row first.

**`retry_dead_letter`:**

- PROBE: call `probe(record)` only.
- VERIFY: call `reverify(record)` only. The adapter and the probe get 0 calls.
- NONE: never retried, nothing written.

| Answer | Result |
|---|---|
| EXECUTED_SUCCESS / EXECUTED_FAILURE / PASS / FAIL | resolved EXECUTED (budget committed) |
| NOT_EXECUTED | resolved NOT_EXECUTED (budget released) |
| INCONCLUSIVE / UNKNOWN / an exception | back to pending (`retry_count + 1`) |
| `retry_count` reaches `max_retries` (3) | abandoned UNDETERMINED, budget committed |

**`rollback_execution` (D2):**

- Explicit only: nothing in the product calls it automatically. A run that is not terminal is refused.
- Walk the completed steps in **reverse order**. For each:
  - IRREVERSIBLE: skipped, never compensated.
  - Otherwise await `confirm_executed(RollbackStep)` first. Unconfirmed: no inverse, `skipped`.
  - Confirmed: run the inverse through the **full guard** with key `{request_id}:{plan_step_id}:inverse`, built with
    `InverseBudget`. Never compensate twice. Emit event `rollback_step`.
- A failed inverse → `create_rollback(...)`. It changes no run, step or budget.
- Return `RollbackReport(compensated, skipped, failed)` (plan step ids).

**`InverseBudget.check`:** pass only when `call.reservation_id is None` **and** the idempotency key ends with
`:inverse`. Anything else raises `BudgetStateError` (fail closed).

## Schema notes (all columns exist since migration 015; see `../../B1_M01-M04/SCHEMA.md`)

- **Evidence is stored in `dead_letters.context`** (JSONB, NOT NULL, default `'{}'`). The `evidence=` argument is
  written there and invariant I11 reads it. An empty `{}` is what the default gives, so the "non-empty evidence" rule
  is enforced only by `create` (and checked by I11), not by the database.
- `status` defaults to `pending`; `resolved` must equal `status in (resolved, abandoned)` (`chk_dead_letters_resolved`),
  so every status move also writes `resolved`.
- `retry_mode` is NOT NULL with no default: `create` must always pass one.
- `mutation_type` defaults to `R`, so pass the step's mutation. `is_idempotent` (default false) and `next_retry_at`
  are written by no code in this phase; do not read them as information.
- FKs to the run, step, reservation and episode exist, so a record cannot name a missing episode.

**Unfenced by design:** `create_rollback` and `settle_dead_letter_reservation` write for a terminal run, where no
runtime owns the execution. They are the only unfenced writes this milestone adds (README rule 7).

## Traps

- Accepting a record without evidence (sabotage `M17_evidence_optional`, invariant I11).
- Re-opening the step on resolution (sabotage `M17_resolution_moves_step`).
- Probing on a VERIFY retry (sabotage `M17_verify_retry_probes`).
- Expecting `ValueError` for illegal A.6 moves: the pinned type is `IllegalStateTransition`.
- Putting the step in DEAD_LETTER for transient or data records. Only unresolved uncertainty does that (§11).

## Done when

- [ ] 37/37 in `M17_dead_letter.py`; M01–M16 green; I11 and I12 pass.
- [ ] `owner_certify_s12.py --milestone M17`: all PASS, sabotage 3/3.
