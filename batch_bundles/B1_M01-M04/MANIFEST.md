# B1 dependency folder — M1–M4: schema, fencing core, state machines

> **Agents: start here.** Read [`../README.md`](../README.md) (rules for every batch, the S12→S15 module map, the
> names the tests patch), then [`AGENT_GUIDE.md`](AGENT_GUIDE.md) (status, owner actions, files, rules for touching
> this code later), [`SCHEMA.md`](SCHEMA.md) (the exact as-built schema, what the database vs the code enforces, column
> usage per milestone, known gaps), then one milestone file at a time: [`M1`](milestones/M01_schema.md) · [`M2`](milestones/M02_fencing_core.md) · [`M3`](milestones/M03_machines_run_step_budget.md) · [`M4`](milestones/M04_machines_other.md).

Every file the B1 golden tests depend on, found by tracing what the tests import when they run (a pytest plugin that
records every loaded module), plus the migrations, the B1 sabotage patches and their helpers, and the reviews.
Snapshot of 2026-10-01, `s12-work` at `f4a8d5f`.

## How this folder differs from B3–B5

**B1 is already implemented on `s12-work`.** The source it depends on is the live code in `src/` (verified, owner sign-off pending), so this
folder does **not** carry a copy of `src/`: a second copy would go stale, and an agent might edit the wrong one. The
tables below list every source file with its class (frozen S0–S11, prototype reworked under CONF-011, or new S12 code)
and the last commit that changed it. The golden tests, sabotage patches, fixtures and reviews **are** copied here,
byte-identical to the repository, so the batch can be read in one place.

## Verified state (2026-10-01, plain `s12-work`, PostgreSQL 16, Python 3.11)

- Golden: **316 / 316 (M01 89, M02 18, M03 130, M04 79); sabotage 12 / 12 caught; C-M2 x5 PASS**.
- `pytest tests` 836 passed; `tests_agent` 93 passed; `tests_postgres` 330 passed; `tools/owner_certify.py` 19/19.
- `owner_certify_s12.py --milestone M9` (full): 18/21. The only failing rows are the owner rows **S12-PIN** (B2–B5
  golden files unpinned; three B1 fixtures changed since the pin) and **S12-REC** (STOP-001 `ruled`, STOP-002 `open`).
  See the owner actions in `AGENT_GUIDE.md`.
- Run the certifiers with `PYTHONPATH=src` (or after `pip install -e .`). Without it, `owner_certify.py` reports
  16/19 with 22 collection errors, which is an environment fault, not a regression.

## How to run

```
export TEST_DATABASE_URL=postgresql://postgres@localhost:5432/suprpg_test PYTHONPATH=$PWD/src   # name must end in _test
python -m pytest -q -p no:cacheprovider tests_golden/s12/M01_schema.py tests_golden/s12/M02_fencing_core.py tests_golden/s12/M03_machines_run_step_budget.py tests_golden/s12/M04_machines_other.py
GOLDEN_SABOTAGE=$PWD/tests_golden/sabotage/<patch> python -m pytest -q -p no:cacheprovider tests_golden/s12/<its file>
```

## Contents

### B1 golden tests (4)
- `tests_golden/s12/M01_schema.py`
- `tests_golden/s12/M02_fencing_core.py`
- `tests_golden/s12/M03_machines_run_step_budget.py`
- `tests_golden/s12/M04_machines_other.py`

### Sabotage patches (12)
- `tests_golden/sabotage/M01_cascade_delete.sql`
- `tests_golden/sabotage/M01_check_wider_than_enum.sql`
- `tests_golden/sabotage/M01_no_terminal_reason_trigger.sql`
- `tests_golden/sabotage/M01_two_open_episodes.sql`
- `tests_golden/sabotage/M02_check_without_lock.py`
- `tests_golden/sabotage/M02_settings_unvalidated.py`
- `tests_golden/sabotage/M02_skip_fence_check.py`
- `tests_golden/sabotage/M03_old_data_contracts_edges.py`
- `tests_golden/sabotage/M03_reason_ignored.py`
- `tests_golden/sabotage/M03_retry_is_a_transition.py`
- `tests_golden/sabotage/M04_closed_episode_moves.py`
- `tests_golden/sabotage/M04_expired_lease_renewed.py`

### Test fixtures (copied)
- `tests_golden/__init__.py`
- `tests_golden/conftest.py`
- `tests_golden/fixtures/__init__.py`
- `tests_golden/fixtures/appendix_a.py`
- `tests_golden/fixtures/code_scan.py`
- `tests_golden/fixtures/db.py`
- `tests_golden/fixtures/invariants.py`
- `tests_golden/s12/__init__.py`

### Reviews and conventions (copied)
- `docs/gates/S12_M0_PREFLIGHT.md`
- `docs/gates/S12_M1_SCHEMA_REVIEW.md`
- `tests_golden/README.md`

### Source: new S12 code (live in `src/`, not copied)

| File | Last change |
|---|---|
| `src/adapters/postgres/fencing.py` | `32fa999` |
| `src/adapters/postgres/migrations/015_s12_schema.sql` | `a8f8f58` |
| `src/adapters/postgres/transition_log.py` | `838ebcf` |
| `src/contracts/execution_states.py` | `8f38edb` |
| `src/engine/stages/s12_execute/settings.py` | `32fa999` |

### Source: prototype files reworked under CONF-011 (live in `src/`, not copied)

| File | Last change |
|---|---|
| `src/engine/stages/s12_execute/__init__.py` | `ab8d82c` |
| `src/engine/stages/s12_execute/transitions.py` | `8f38edb` |

### Source: frozen S0–S11 files they also load (31; never edit, S12-FRZ checks them byte for byte)
- `src/adapters/__init__.py`
- `src/adapters/postgres/__init__.py`
- `src/adapters/postgres/budget.py`
- `src/adapters/postgres/database.py`
- `src/adapters/postgres/migrate.py`
- `src/adapters/postgres/migrations/001_s0_s11_schema.sql`
- `src/adapters/postgres/migrations/002_api_keys.sql`
- `src/adapters/postgres/migrations/003_suspended_runs.sql`
- `src/adapters/postgres/migrations/004_pipeline_events.sql`
- `src/adapters/postgres/migrations/005_references.sql`
- `src/adapters/postgres/migrations/006_budget_reservations.sql`
- `src/adapters/postgres/migrations/007_event_gateway.sql`
- `src/adapters/postgres/migrations/008_verifier_metadata.sql`
- `src/adapters/postgres/migrations/009_execution_admission.sql`
- `src/adapters/postgres/migrations/010_step_loop.sql`
- `src/adapters/postgres/migrations/011_event_sources.sql`
- `src/adapters/postgres/migrations/012_admin_api.sql`
- `src/adapters/postgres/migrations/013_access_management.sql`
- `src/adapters/postgres/migrations/014_onboarding_usage_limits.sql`
- `src/adapters/postgres/migrations/__init__.py`
- `src/contracts/__init__.py`
- `src/contracts/codec.py`
- `src/contracts/errors.py`
- `src/contracts/frozen_binding.py`
- `src/contracts/plan_hash.py`
- `src/contracts/stage_outputs.py`
- `src/contracts/step_execution.py`
- `src/contracts/verifier.py`
- `src/contracts/worker.py`
- `src/engine/__init__.py`
- `src/engine/stages/__init__.py`
