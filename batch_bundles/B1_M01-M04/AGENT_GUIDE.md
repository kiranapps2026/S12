# B1 agent guide: M1–M4 (schema, fencing core, state machines)

Read `../README.md` first: precedence, the ten rules, the S12→S15 module map and the names the tests patch. This file
covers what is specific to B1. Each milestone has its own file in `milestones/`.

## 1. Status: built; the code is done, the owner rows are not

**B1 is implemented on `s12-work`.** The agent must not rebuild it. Every later batch stands on it, so the job now is
to (a) keep it green, (b) change it only additively when a later card requires, and (c) let the owner close the
bookkeeping rows.

Verified on 2026-10-01 against plain `s12-work` (`f4a8d5f`), PostgreSQL 16, Python 3.11:

| Check | Result |
|---|---|
| Golden M01 / M02 / M03 / M04 | 89 / 18 / 130 / 79 passed (316) |
| Sabotage M01–M04 | 12 / 12 caught, none as an error |
| C-M2 (5 consecutive runs) | PASS |
| `pytest tests -q` (frozen S0–S11 suite, OWN-13) | 836 passed |
| `tests_agent` / `tests_postgres` | 93 / 330 passed |
| `tools/owner_certify.py` (S0–S11) | 19/19 |
| S12-FRZ (frozen S0–S11 source identical to the tag) | PASS |
| S12-DOC (document consistency) | PASS |
| **S12-PIN** | **FAIL: owner row** (see §2) |
| **S12-REC** | **FAIL: owner row** (STOP-001 is `ruled`, not `applied`) |

The autopilot log records each milestone as `MILESTONE Mx REACHED … except S12-PIN/S12-REC` (commits `a8f8f58` M1,
`838ebcf` M2, `b9e6123` M3, `8f38edb` M4). `docs/gates/s12_milestones.json` still says M1 `red_confirmed` and M2–M4
`not_started`. Only the owner's checkpoint (`tools/owner_verify_s12.ps1 Mxx`) moves a status. The agent never edits
that file.

> **Environment trap.** `owner_certify.py` (and so S12-S011) reports **16/19 with 22 collection errors** when the
> package is not importable. Run the certifiers with `PYTHONPATH=src` or after `pip install -e .`. Those 16/19 are an
> environment fault, not a code regression. Do not "fix" code for them.

## 2. Owner actions that close B1 (not agent work)

| # | Action | Why | Unblocks |
|---|---|---|---|
| O1 | Review the current golden set and run `python tools/owner_certify_s12.py --pin` (owner only) | Since the B1 pin: `tests_golden/README.md`, `fixtures/db.py` and `fixtures/invariants.py` changed (B2–B5 drafting added invariants and the `golden_app` role), and `fixtures/certified.py` and `fixtures/runtime_process.py` are new. S12-PIN lists each | S12-PIN for every milestone |
| O2 | Mark STOP-001 `applied` in `S12_STOPS.md` with the pin commit | STOP-001 ("start M1 unpinned") is `ruled`; a `ruled` STOP still fails S12-REC | S12-REC for M1–M4 |
| O3 | Confirm CONF-014 at the M1 ★ review (`idx_workers_workspace` created with the column) | The ruling reads "settled by existing text … owner to confirm at the M1 review" | M1 ★ review |
| O4 | M1 ★ review: the schema diff in `docs/gates/S12_M1_SCHEMA_REVIEW.md` (`\d+` of every table 015 creates or changes) | Plan §4 M1 ★ | M1 → `green` |
| O5 | `tools/owner_verify_s12.ps1 M1` … `M4` | Only the owner's checkpoint moves a status | M2–M4 → `green` |

## 3. Files B1 owns (as built)

| File | Class | Milestone (last commit) | What it holds |
|---|---|---|---|
| `src/contracts/execution_states.py` | S12 new | M1 `a8f8f58`, M4 `8f38edb` | 16 `StrEnum`s: the persisted state and reason vocabularies (M01 interface; `CircuitBreakerState` M4) |
| `src/adapters/postgres/migrations/015_s12_schema.sql` | S12 new | M1 `a8f8f58` | `fence_token_seq`; `workers`, `worker_leases`, `step_reconciliations`, `dead_letters`, `idempotency_ledger`, `checkpoints`; C39 columns; `operation_quotas.worker_id`; transition-log machine CHECK; RLS |
| `src/adapters/postgres/fencing.py` | S12 new | M2 `838ebcf`, M9 `32fa999` | `FenceHolder`, `check_fence`, `fenced_write` |
| `src/adapters/postgres/transition_log.py` | S12 new | M2 `838ebcf` | `log_transition(connection, *, …)` |
| `src/engine/stages/s12_execute/settings.py` | S12 new | M2, M8a, M9 | `ExecutionSettings.from_env` (C37 ordering) |
| `src/engine/stages/s12_execute/transitions.py` | prototype (CONF-011) | M3 `b9e6123`, M4 `8f38edb` | `validate(machine, from, to, *, reason, closed=False)`, `IllegalStateTransition`, the nine machines |
| `src/adapters/postgres/execution.py` | prototype | M2 (fenced, tenant-filtered); **M12 adds `PostgresExecutionStore`** (`load`, `transition_step`, `transition_run`, `cancel_requested`, plan decode with both hashes) | the loop's store; additive only |
| Prototype repositories reworked in M2/M4 | prototype | M2, M4 | `adapters/postgres/{admission,budget_reserver,execution}.py` write through `fenced_write` and filter on `tenant_id`; `loop.py`, `guard.py`, `circuit_breaker.py`, `s12_worker_execution/handler.py` use the enums (no bare literals) |

The schema from **before** the tag also counts as B1's base: migrations `009_execution_admission.sql`
(`execution_runs`, `execution_steps`, `execution_manifests`, `execution_plans`, `execution_ownership`,
`state_transitions`, `operation_quotas`) and `010_step_loop.sql` (the step `terminal_reason` CHECK and its trigger).
Both are inside the tag: **never edit 001–014** (CONF-010 explains why 30 M01 cases already passed on them).

## 4. What later batches import from B1 (contracts the M10–M21 golden files use)

| Symbol | Imported by | Must stay |
|---|---|---|
| `adapters.postgres.fencing.FenceHolder`, `fenced_write` | M10–M21 goldens (8 imports), every repository | the four fields and their order; `fenced_write(database, holder, write)` |
| `engine.stages.s12_execute.transitions.IllegalStateTransition`, `validate` | M17 golden (illegal A.6 moves), every repository | the exception type (not `ValueError`) |
| `engine.stages.s12_execute.transitions.RUN` / `STEP` / `BUDGET` | M17 reference (`settle_dead_letter_reservation`) | mappings of from-states that still have outgoing edges |
| `engine.stages.s12_execute.settings.ExecutionSettings.from_env` | M21 golden | env names; C37 checks; M19 adds `recovery_sweep_interval_s` |
| `contracts.execution_states.*` | everything | values (CHECKs depend on them) |
| the schema 001–015 | every later milestone | see [`SCHEMA.md`](SCHEMA.md): B3–B5 need **no** change to it, only migrations 016 and 017 |

## 5. Rules for touching B1 code from a later batch

B1 is the foundation everything else imports. A later card may extend it only like this:

| B1 artefact | Allowed later change | Never |
|---|---|---|
| `contracts.execution_states` | **Add** an enum or a member when a card needs one (e.g. M16 `ConsolidationOutcome`). The schema CHECK must then come from it in a **new** migration (C28) | Rename or remove a member; change a value; hand-write a CHECK |
| Migrations | A **new** file 016, 017, … (M12 adds 016, M19 adds 017) | Edit 001–015; `ON DELETE CASCADE` on an execution table; a `TEXT` timestamp in a new table; a deferred table (`worker_spawn_audit`, `execution_batches`, `parent_execution_id`, …) |
| `fenced_write` / `check_fence` | Callers may join a transaction with `check_fence(connection, holder)` (M9 does it) | A session-middleware fence (C25); a fence check without the row lock (`FOR SHARE`); writing before the check |
| `log_transition` | — | Writing a transition row without `transitions.validate` first |
| `transitions.validate` | **Add** an edge or reason only if Appendix A has it (a gate amendment). Machine names are fixed | A RUNNING → RUNNING retry edge (C24); DATA_CONTRACTS' pre-v9 edges; importing `contracts/state_validators.py` (CONF-006) |
| `ExecutionSettings` | **Add** a field with a default and its env var (M8a quota, M19 sweep interval) | Read settings in S0–S11 code; drop the C37 checks |

After any such change, re-run M01–M04 and their 12 sabotage patches (§6). A B1 regression is a STOP-worthy event
under "the PASS count went down".

## 6. Conflict avoidance (B1-specific)

| Risk | Rule |
|---|---|
| A rule only code enforces | The database does not enforce: a non-null transition reason, one active lease per execution, token order, fenced writes, the budget ceiling, commit-only-from-LOCKED. A writer that bypasses the code path breaks them silently; see the enforcement map in `SCHEMA.md` |
| One vocabulary, two spellings | Every state and reason string in S12–S15 code comes from `contracts.execution_states`. M04's scan fails on a bare literal. Machine names (`run`, `step`, `dead_letter`, …) are exempt (CONF-013); a `DEAD_LETTER` state literal is not |
| A CHECK drifting from its enum | CHECK sets are generated from the enums (C28). Sabotage `M01_check_wider_than_enum.sql` proves an upper-case `PENDING_PROBE` is caught |
| Two validators | `transitions.validate` is canonical. `contracts/state_validators.py` is non-canonical (CONF-006): S12 code must not import it; deletion after S15 via change control |
| A retry as a transition | A retry is an **event** (`step_attempt`, M11), never `running → running` (sabotage `M03_retry_is_a_transition`) |
| `UNKNOWN` written | No code path writes `StepState.UNKNOWN` (M03 architecture case). Uncertainty is `timeout` / `pending_probe` |
| Frozen vs prototype | Frozen = `src/` at `s0-s11-certified` minus the `PROTOTYPE` list in `tests_golden/fixtures/code_scan.py` (CONF-011). S12-FRZ fails on any byte change to a frozen file |
| `ruff --fix` on a directory | It once rewrote two frozen files. Fix files one by one |

## 7. Commands

```bash
export TEST_DATABASE_URL=postgresql://…/suprpg_test PYTHONPATH=$PWD/src   # name must end in _test
python tools/owner_certify_s12.py --selftest
python tools/owner_certify_s12.py --milestone M4 --fast        # G-M1..G-M4
python tools/owner_certify_s12.py --milestone M4               # + C-M2 (x5) + X-M4 sabotage
python -m pytest -q tests_golden/s12/M01_schema.py tests_golden/s12/M02_fencing_core.py \
    tests_golden/s12/M03_machines_run_step_budget.py tests_golden/s12/M04_machines_other.py
GOLDEN_SABOTAGE=$PWD/tests_golden/sabotage/M02_skip_fence_check.py python -m pytest -q tests_golden/s12/M02_fencing_core.py
python -m pytest tests -q && python tools/owner_certify.py      # 836 and 19/19 must hold
```

## 8. Milestone files

| Milestone | Cases | Sabotage | File |
|---|---|---|---|
| M1 schema ★ | 89 | 4 | [milestones/M01_schema.md](milestones/M01_schema.md) and [SCHEMA.md](SCHEMA.md) (full as-built schema, enforcement map, column usage, gaps) |
| M2 fencing core | 18 (x5) | 3 | [milestones/M02_fencing_core.md](milestones/M02_fencing_core.md) |
| M3 machines I | 130 | 3 | [milestones/M03_machines_run_step_budget.md](milestones/M03_machines_run_step_budget.md) |
| M4 machines II | 79 | 2 | [milestones/M04_machines_other.md](milestones/M04_machines_other.md) |

Batch target (met): **316/316, 12/12**, plus the standing exit rules of plan §4 (S0–S11 19/19, frozen code unchanged,
invariants after every integration case).
