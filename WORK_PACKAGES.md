# S0–S11 — Remaining Work Packages

**Status (2026-09-29):** the pipeline logic S0–S11 is complete and verified with test
doubles (`python verify_s0_s11.py --sabotage`). What remains is connecting it to the real
world. Each package below has its own folder, its own tests and one commit. None of them
changes stage logic.

| WP | Package | Folder | Implements (port) | Done when | Needs from owner |
|---|---|---|---|---|---|
| 0 | **Line of work** | — | — | Owner picks this branch or `s8-rewrite`; certifier and golden tests re-pinned for that layout (incl. amended R-V / S6 golden) | Branch decision |
| A | **PostgreSQL adapters** | `src/supragents/adapters/postgres/` | `ActivationStateReader`, `CapabilityRegistry`, `AuthorizationState`, `KernelPolicySource`, `PolicyVersionSource`, `MutationPolicy`, `ConfirmationStore` (R-Z), `EventSink` (ledger), `Clock` (database `NOW()`) | Each adapter passes the same contract tests as its fake, against a real PostgreSQL 16 (`tests/integration/postgres/`); migrations for the tables used; RLS on every tenant table | DB driver (recommended: `asyncpg`); a PostgreSQL instance for tests |
| B | **Circuit breaker state** | `src/supragents/adapters/runtime/` | `CircuitBreaker` | In-process, single node (gate C1); unit tests for open / half-open / closed | — |
| C | **Suspended runs** | `src/supragents/adapters/postgres/` | new port `SuspendedRunStore` | A run awaiting confirmation survives a restart: `resume_state` is stored and reloaded by execution id (PIPELINE_STAGES §12 "on worker restart") | — |
| D | **LLM adapter** | `src/supragents/adapters/llm/` | `IntentModel` (+ new `BillingRecorder` port for `llm.token` usage, PIPELINE_STAGES §4) | Structured-output call at temperature 0.1, timeout, capability list in the system prompt; contract tests with a recorded response; key only from the environment | Provider and model |
| E | **Entry and composition** | `src/supragents/app/` | — | Authenticated request → `EntryRequest`; `POST /runs`, `POST /confirmations/{id}/reply`; `RunResult` → Envelope (DATA_CONTRACTS §1); one composition root wiring every adapter; `.env.example` only | Web framework (recommended: FastAPI); how callers authenticate |

**Order:** 0 → A → B → C → D → E. A–C can start before D is decided; E comes last
because it wires everything.

**Rules for every package** (checked by `tests/architecture`): no stage logic changes;
adapters depend only on `contracts` and `ports`; no secrets in the repository; each
package extends `verify_s0_s11.py` with its test group; no module is added that nothing
uses.

**Out of scope here:** S12–S15 (governed by `S12_S15_EXECUTION_GATE.md`).
