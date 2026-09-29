# S0–S11 — Remaining Work Packages

**Status (2026-09-29):** the pipeline logic S0–S11 is complete. **Package A (PostgreSQL),
package B (circuit breaker) and the offline installer are done**; D (DeepSeek-V4.1, owner
choice) is next. Verify with `python verify_s0_s11.py --sabotage`. What remains is connecting it to the real
world. Each package below has its own folder, its own tests and one commit. None of them
changes stage logic.

| WP | Package | Folder | Implements (port) | Done when | Needs from owner |
|---|---|---|---|---|---|
| 0 | **Line of work** | — | — | Owner picks this branch or `s8-rewrite`; certifier and golden tests re-pinned for that layout (incl. amended R-V / S6 golden) | Branch decision |
| A ✅ | **PostgreSQL adapters** | `src/supragents/adapters/postgres/` | `ActivationStateReader`, `CapabilityRegistry`, `AuthorizationState`, `KernelPolicySource`, `PolicyVersionSource`, `MutationPolicy`, `ConfirmationStore` (R-Z), `EventSink` (ledger), `Clock` (database `NOW()`) | Each adapter passes the same contract tests as its fake, against a real PostgreSQL 16 (`tests/integration/postgres/`); migrations for the tables used; RLS on every tenant table | DB driver (recommended: `asyncpg`); a PostgreSQL instance for tests |
| B ✅ | **Circuit breaker state** | `src/supragents/adapters/runtime/` | `CircuitBreaker` | In-process, single node (gate C1); unit tests for open / half-open / closed | — |
| C | **Suspended runs** | `src/supragents/adapters/postgres/` | new port `SuspendedRunStore` | A run awaiting confirmation survives a restart: `resume_state` is stored and reloaded by execution id (PIPELINE_STAGES §12 "on worker restart") | — |
| D | **LLM adapter** | `src/supragents/adapters/llm/` | `IntentModel` (+ new `BillingRecorder` port for `llm.token` usage, PIPELINE_STAGES §4) | Structured-output call at temperature 0.1, timeout, capability list in the system prompt; contract tests with a recorded response; key only from the environment | **Decided: DeepSeek-V4.1** (API model id to be confirmed; set via environment) |
| E | **Entry and composition** | `src/supragents/app/` | — | Authenticated request → `EntryRequest`; `POST /runs`, `POST /confirmations/{id}/reply`; `RunResult` → Envelope (DATA_CONTRACTS §1); one composition root wiring every adapter; `.env.example` only | Web framework (recommended: FastAPI); how callers authenticate |

**Order:** 0 → A → B → C → D → E. A–C can start before D is decided; E comes last
because it wires everything.

**Rules for every package** (checked by `tests/architecture`): no stage logic changes;
adapters depend only on `contracts` and `ports`; no secrets in the repository; each
package extends `verify_s0_s11.py` with its test group; no module is added that nothing
uses.

**Out of scope here:** S12–S15 (governed by `S12_S15_EXECUTION_GATE.md`).

## Offline installation (done)

On a machine with internet: `python tools/offline/build_bundle.py --target windows --python 3.11`
(or `--target linux`, or omit for the current machine). Copy `offline_bundle.zip` to the
offline machine, unzip, and run `python install_offline.py` (add `--migrate` with
`DATABASE_URL` set to create the tables). It checks every file against `SHA256SUMS`,
creates `.venv`, installs only from the bundled wheels, and runs `verify_s0_s11.py`.
PostgreSQL 16 itself must be installed on the offline machine separately.

## Package A notes — where the schema differs from DATABASE.md

Migration `src/supragents/adapters/postgres/migrations/001_s0_s11_schema.sql` creates only
the tables S0–S11 use, with valid PostgreSQL types. Differences to confirm or fold into
DATABASE.md:

| Table | Difference | Why |
|---|---|---|
| tenants, users, connections | `status TEXT` (active, suspended, …) instead of `is_active BOOLEAN` | S8 needs the specific state (SECURITY §3), not a yes/no |
| tenants | adds `kill_switch_engaged`, `max_mutation`, `policy_version_id` | Tenant kill switch, mutation ceiling for S8 check 8, policy version for S5 |
| workspaces | adds `policy_version_id` (NULL = tenant's) | S5 policy versions |
| capabilities | adds `intent`; timestamps are `TIMESTAMPTZ` | S3 maps intent → capability; RD-2 |
| new | `system_settings`, `registry_versions`, `pipeline_events` | System kill switch and deny threshold; manifest versions; stage ledger |
| budget | S8 precheck compares with `tenants.budget_pool` only | Reservations arrive with S12 (gate C33) and are then subtracted |

Row-level security is on for every tenant table (`FORCE`). The application must connect as
a role that is **not** a superuser and does **not** own the tables; the tests prove
isolation with such a role.
