# SuprAgents S0–S11 — Installation and Operation Guide

This guide installs the SuprAgents pre-execution pipeline (stages S0–S11), explains what each
installation step does, and describes exactly what happens to a request once the service
runs. It is written so that a person **or another LLM/coding agent** can install, operate,
debug and extend the system without prior context. Every step was run end to end on Linux
before this guide was written (PostgreSQL 16, Python 3.11); the Windows commands are the
PowerShell equivalents and have not yet been run on Windows.

---

## 0. Orientation (read this first)

| Question | Answer |
|---|---|
| What is it? | A Python 3.11+ service that turns a user's request ("delete contact 42") into a validated, authorized, confirmed **ExecutionManifest** — the input of S12 (execution). |
| What does it NOT do? | It does **not** execute anything against providers. S12–S15 (execution, verification, dead letter, response) are not built here. |
| Where is the code? | `src/supragents/` (package), `tests/`, `verify_s0_s11.py`, `tools/offline/`, `tools/sql/`. |
| The one entry point | `python -m supragents <command>` (`migrate`, `check`, `llm-check`, `serve`, `create-api-key`). |
| The master switch (code) | `supragents.bootstrap.build_runner(database, intent_model)` wires every real adapter to the pipeline. |
| Runtime dependencies | PostgreSQL 16, Python packages `asyncpg`, `fastapi`, `uvicorn` (tests: `pytest`, `httpx`). DeepSeek API for S2. |
| Secrets | Only in `.env` (never committed): `DATABASE_URL`, `DEEPSEEK_API_KEY`, optionally `TEST_DATABASE_URL`. Everything else is built in. |
| Is it correct? | `python verify_s0_s11.py --sabotage` → must print **VERIFIED**. |
| Design rules | [README.md](README.md) "Code" section, [WORK_PACKAGES.md](WORK_PACKAGES.md), gate `S12_S15_EXECUTION_GATE.md`, specs `PIPELINE_STAGES.md`, `DATA_CONTRACTS.md`. |

---

## 1. Requirements

| Item | Version | Notes |
|---|---|---|
| Python | 3.11 or 3.12, 64-bit | `python --version`. On Windows, tick "Add python.exe to PATH". |
| PostgreSQL | 16 | Installed separately (Windows: the EDB installer; Linux: the `postgresql-16` package). It is **not** part of the Python bundle. |
| DeepSeek API key | — | Only for S2 (intent analysis). Without it, requests stop at S2 with `llm_unavailable`. |
| Disk | ~50 MB | Bundle 6 MB, virtual environment ~40 MB. |
| Network | Optional | Needed only to build the offline bundle and to call DeepSeek. |

---

## 2. Install — Route A: machine with internet

```powershell
# Windows PowerShell (Linux/macOS: same commands; activate with: source .venv/bin/activate)
git clone https://github.com/kiranapps2026/S12.git
cd S12
git checkout claude/peaceful-brown-9f3w18
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[test]"
python verify_s0_s11.py
```

`pip install -e ".[test]"` installs the `supragents` package from `src/` plus the test tools.
Continue with section 4 (PostgreSQL) and section 5 (configuration).

---

## 3. Install — Route B: offline machine

### 3.1 Build the bundle (on any machine WITH internet)

```powershell
python tools/offline/build_bundle.py --target windows --python 3.11
# or: --target linux, or no --target for "this machine"; --python must match the offline machine
```

Creates `offline_bundle/` and `offline_bundle.zip`:

| Content | What it is |
|---|---|
| `wheelhouse/` | Every Python package as an installable wheel (asyncpg, fastapi, uvicorn, pydantic, pytest, httpx, their dependencies, and `supragents` itself), for the chosen platform. |
| `source/` | `src/`, `tests/`, `pyproject.toml`, `verify_s0_s11.py`, `README.md`, `WORK_PACKAGES.md`, `.env.example`. |
| `install_offline.py` | The installer. |
| `SHA256SUMS` | A checksum for every file; the installer refuses a damaged bundle. |

### 3.2 Install (on the offline machine)

1. Install PostgreSQL 16 and Python 3.11 (from their own installers).
2. Copy `offline_bundle.zip`, unzip it, open a terminal in the unzipped folder.
3. Create `source\.env` from `source\.env.example` (section 5). All later commands run from
   the `source` folder, with the environment active: `.venv\Scripts\activate` then `cd source`.
4. Run:

```powershell
python install_offline.py            # verify, install, run the checks
python install_offline.py --migrate  # the same, and create the tables (needs DATABASE_URL)
python install_offline.py --skip-checks
```

### 3.3 What the installer does, step by step

| Step | Action | Fails when |
|---|---|---|
| 1 | Reads `SHA256SUMS` and re-hashes every file | Any file changed or is missing → "bundle is damaged" |
| 2 | Checks Python ≥ 3.11 | Older Python |
| 3 | Creates `.venv` in the bundle folder (standard `venv`, with pip) | No write permission |
| 4 | `pip install --no-index --find-links wheelhouse supragents[test]` — **nothing is downloaded** | Bundle built for another platform/Python version |
| 5 | Optional (`--migrate`): `python -m supragents migrate` | `DATABASE_URL` missing or database unreachable |
| 6 | Unless `--skip-checks`: runs `verify_s0_s11.py` inside `source/` | Any test fails → NOT VERIFIED |
| 7 | Prints how to activate the environment (`.venv\Scripts\activate`) | — |

After installation the machine has: a virtual environment with `supragents` and its
dependencies, the command `python -m supragents`, and (with `--migrate`) the tables.
No service is started and nothing runs in the background until you run `serve`.

---

## 4. PostgreSQL setup

Two database roles are used on purpose:

| Role | Used for | Why |
|---|---|---|
| **Owner** (e.g. `postgres`) | `migrate`, loading reference data | Creates and owns the tables. |
| **App role** (`supragents_app`) | `serve`, `check`, `create-api-key`, all requests | Tenant isolation uses PostgreSQL row-level security (RLS). **RLS does not apply to superusers**, so the service must never run as the owner or a superuser. |

```sql
-- As the PostgreSQL superuser (psql -U postgres):
CREATE DATABASE suprpg;
CREATE ROLE supragents_app LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
```

Create the tables **as the owner**:

```powershell
$env:DATABASE_URL = "postgresql://postgres:<owner-password>@localhost:5432/suprpg"
python -m supragents migrate
# → applied: 001_s0_s11_schema.sql, 002_llm_usage.sql, 003_suspended_runs.sql, 004_api_keys.sql
```

Then give the app role access (once, as the owner, `psql -U postgres -d suprpg`):

```sql
GRANT USAGE ON SCHEMA public TO supragents_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO supragents_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO supragents_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO supragents_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO supragents_app;
```

The app role gets no `DELETE` and no DDL: the pipeline never deletes rows.

Migrations are numbered SQL files in `src/supragents/adapters/postgres/migrations/`; each runs
once and is recorded in `schema_migrations`. Re-running `migrate` is safe ("already up to date").

---

## 5. Configuration (`.env`)

Copy `.env.example` to `.env` in the folder you run commands from. Only secrets and connection
strings go here; every other setting (DeepSeek endpoint, model, request options, thresholds)
is built into the code.

```ini
DATABASE_URL=postgresql://supragents_app:change-me@localhost:5432/suprpg
DEEPSEEK_API_KEY=sk-...
# optional, for the database test group; the database name MUST end in _test (it is wiped):
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/suprpg_test
```

- `postgresql+asyncpg://…` URLs are accepted too.
- Variables already set in the environment win over `.env`.
- `.env` is in `.gitignore`. Never commit it; GitHub push protection rejects pushes that contain keys.

---

## 6. First run

### 6.1 Load reference data (as the owner)

The service has no admin API yet; tenants, users and the capability registry are loaded
with SQL. A complete example (tenant `acme`, user `acme.alice`, capabilities
`contact.list` / `contact.create` / `contact.delete`) is provided:

```powershell
psql -U postgres -d suprpg -f tools/sql/example_seed.sql      # offline bundle: source\tools\sql\example_seed.sql
```

What must exist for a request to pass (the example creates all of it):

| Table | Needed by | Rows |
|---|---|---|
| `tenants`, `workspaces` | S0.1, S5, S7, S8 | Your tenant and workspace (`policy_version_id` is required; `max_mutation` default `W` blocks deletes — set `D` or `IRREVERSIBLE` to allow them) |
| `users`, `memberships`, `connections` | S8 checks 1, 3, 5 | Status `active` |
| `capabilities`, `kernel_ops`, `bindings` | S3, S5 | `truth_state = PRODUCTION_ENABLED` |
| `capability_grants` | S8 check 4 | One per user and capability |
| `registry_versions` | S11 | Exactly one row |
| `system_settings` | S7, S8 | Created by the migration (kill switch off, deny threshold 0.95) |

### 6.2 Check, key, model, serve

```powershell
python -m supragents check
# → database OK; registry capability_version=cap-1

python -m supragents create-api-key --tenant acme --workspace acme.main --user acme.alice `
    --membership acme.alice.main --connection acme.alice.crm --scope "acme.main/*"
# → API key (shown once, store it safely): sk_supra_...

python -m supragents llm-check
# → DeepSeek OK: model=deepseek-flash tokens=... answer={"intent": "contact.list", ...}

python -m supragents serve --host 127.0.0.1 --port 8000
```

`llm-check` makes one small DeepSeek call. Run it once on a machine with internet: it confirms
the endpoint `https://api.deepseek.com/responses` and the reply format the adapter expects.

### 6.3 Send requests

```powershell
$h = @{ Authorization = "Bearer sk_supra_..." }
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/runs -Headers $h -ContentType "application/json" `
    -Body '{"text": "list my contacts", "conversation_id": "chat-1"}'
```

```bash
curl -X POST http://127.0.0.1:8000/v1/runs -H "Authorization: Bearer sk_supra_..." \
     -H "Content-Type: application/json" -d '{"text":"delete contact 42","conversation_id":"chat-1"}'
# → {"status":"confirm","message":"This will:\n1. crm.contact_delete (D, cost 5)\n\nReply YES ...",
#    "data":{"confirmation_id":"…","expires_at":…,"operations":[…]}, ...}

curl -X POST http://127.0.0.1:8000/v1/confirmations/<confirmation_id> \
     -H "Authorization: Bearer sk_supra_..." -H "Content-Type: application/json" -d '{"approved":true}'
# → {"status":"ok","message":"Plan validated and ready for execution.","data":{"manifest":{…}}, ...}
```

| Endpoint | Body | Returns |
|---|---|---|
| `GET /health` | — | `{"status": "ok"}` |
| `POST /v1/runs` | `{"text": 1–8000 chars, "conversation_id": 1–200 chars}` | Envelope |
| `POST /v1/confirmations/{id}` | `{"approved": true \| false}` | Envelope; 404 if no request of **your tenant** waits on that id |

Identity (tenant, workspace, user, membership, connection, scope) comes **only from the API
key**. Extra fields in the body are ignored; they can never change who the caller is.

Envelope (DATA_CONTRACTS §1): `status` is one of `ok`, `confirm`, `clarify`, `deny`, `error`;
`message` is for the user; `error` has `type`, `message`, `recoverable`; `metadata` has
`trace_id` and, when the run stopped, `stage` and `reason`. HTTP 401 = bad key, 404 = unknown
confirmation, 422 = invalid body, 503 = infrastructure failure (no internal details returned).

---

## 7. What happens to a request

`POST /v1/runs` → the API turns the API key's identity and the text into an `EntryRequest` →
`PipelineRunner.run()` executes the stages below **in order**. After every stage the runner
logs one line and writes one row to `pipeline_events`. **Any stop (DENY / CLARIFY / ERROR)
ends the run immediately**; no later stage runs. An unexpected exception becomes an ERROR
stop (`internal_error:<Type>`); it is never mistaken for success.

| Stage | Does | Reads | Stops with (status: reason) |
|---|---|---|---|
| **S0** Entry | Creates the frozen ExecutionContext (new `trace_id`, `request_id`); **S0.1** pause check on database time | `tenants`, `workspaces` | DENY: `identity_missing:<field>`, `tenant_paused`, `workspace_paused`, `not_yet_active`, `activation_state_unavailable` |
| **S1** Normalize | Unicode-normalizes, strips control chars and markup, detects prompt injection | — | DENY: `injection_detected`; CLARIFY: `empty_request`, `request_too_long` (> 4000 chars) |
| **S2** Intent | The **only** LLM call: DeepSeek classifies the text into one of the registry's intents (JSON-schema output), retried once with feedback; tokens recorded | `capabilities`; DeepSeek; writes `llm_usage` | ERROR: `llm_unavailable`, `usage_unrecorded`; CLARIFY: `intent_unparseable` |
| **S3** Capability | Maps the intent to exactly one production-enabled capability (never from LLM data) | `capabilities` | CLARIFY: `no_capability`, `capability_not_enabled`, `ambiguous_capability` |
| **S4** Graph | One step per item in `parameters.items` (else one step): 1 = simple, 2–5 = chain, 6+ = complex | — | CLARIFY: `invalid_items` |
| **S5** Binding | Selects the binding (priority → created_at → id); computes risk = max of registry risks and the most dangerous mutation — **once**; records policy versions | `bindings`, `kernel_ops`, `tenants`, `workspaces` | CLARIFY: `provider_unavailable`, `kernel_operation_unavailable`; ERROR: `policy_versions_unavailable` |
| **S6** Task profile | Cost = cost per step × steps; confirmation needed if D/IRREVERSIBLE, cost > 20, risk > 0.7, or ≥ 3 providers | — | — |
| **S7** Path | Routing table: risk ≥ deny threshold → DENY; confidence < 0.5 → CLARIFY; complex → CLARIFY; simple, confidence ≥ 0.9, risk ≤ 0.3 → FAST; confidence ≥ 0.7 → WORKFLOW | `system_settings` | DENY: `risk_above_threshold`, `risk_threshold_invalid`, `policy_unavailable`; CLARIFY: `low_confidence`, `complex_not_supported`, `uncertain_intent` |
| **S8** Safety gate | Kill switch first (system or tenant), then 8 checks in order: user, tenant, connection active; capability granted; workspace membership; circuit breaker; budget; mutation ceiling. **Fail closed.** On allow: records `auth_passed`, `auth_result_id` | `system_settings`, `tenants`, `users`, `connections`, `capability_grants`, `memberships` | DENY: `kill_switch_engaged`, `user_inactive`, `tenant_inactive`, `connection_inactive`, `connection_expired`, `capability_denied`, `resource_scope_denied`, `circuit_open`, `budget_exceeded`, `mutation_not_permitted`, `<check>_unavailable` |
| **S9** Plan | Builds the step chain, new `execution_id` and `plan_id`, SHA-256 `plan_hash` | — | DENY: `safety_not_passed` |
| **S10** Confirmation | If needed: stores a pending confirmation (5 minutes) and **suspends** the run (saved in `suspended_runs`); the Envelope is `confirm`. On the reply: consumed atomically, once | `pending_confirmations`, `suspended_runs` | ERROR: `confirmation_rejected`, `confirmation_expired`, `confirmation_wrong_user`, `confirmation_not_found`, `confirmation_not_consumable`, `suspended_run_unrecorded`; DENY: `safety_not_passed` |
| **S11** Validation | Re-checks the plan hash, dependencies (no cycles), limits, budget, consumed confirmation; issues the **ExecutionManifest** with all versions | `registry_versions` | ERROR: `plan_invalid`; DENY: `safety_not_passed` |

**Confirmation flow.** A run needing confirmation returns `confirm` with a `confirmation_id`.
The run's state is stored in PostgreSQL, so the reply may arrive after a restart. `POST
/v1/confirmations/{id}` loads it (same tenant only), and S10 consumes the confirmation
atomically: a second reply, a reply after 5 minutes, or a reply by another user stops with
`error`. Only then do S11 and the manifest follow.

**Result.** A completed run returns `ok` with the manifest: `execution_id`, `trace_id`,
`tenant_id`, `workspace_id`, `plan_hash`, `binding_id`, `auth_result_id` and all versions
(`capability_version` … `model_version`, `policy_version` from S5). This is what S12 will
execute once it exists.

### 7.1 What is written to the database

| Table | Written when | Content |
|---|---|---|
| `pipeline_events` | After every stage | stage, status, reason, trace/request/tenant id, duration |
| `llm_usage` | Every DeepSeek call in S2 | tokens (`llm.token`), model, tenant, user, trace |
| `pending_confirmations` | S10 needs confirmation | exact operations, plan hash, expiry, status pending → consumed/rejected/expired |
| `suspended_runs` | Run suspended at S10 | the pipeline state as JSON (never pickle) |
| `api_keys` | `create-api-key` | SHA-256 hash of the key and its identity (the key itself is never stored) |

All tenant tables have **forced row-level security**: every query runs with
`app.current_tenant` set, so one tenant's rows are invisible to another. `api_keys` is read
before the tenant is known, so it has no RLS and holds only hashes.

---

## 8. Logs and debugging

`serve` logs one line per stage at INFO (non-normal outcomes at WARNING):

```
stage=S2 status=error reason=llm_unavailable trace=287c… request=073c… tenant=acme duration_ms=369.3
```

To follow one request: take `metadata.trace_id` from the Envelope, then

```sql
SELECT stage, status, reason, duration_ms FROM pipeline_events WHERE trace_id = '<trace_id>' ORDER BY event_id;
```

(as the owner, or as the app role after `SELECT set_config('app.current_tenant','acme',false);`).
Keys and secrets are never logged.

---

## 9. Verifying an installation

```powershell
python verify_s0_s11.py              # all test groups
python verify_s0_s11.py --sabotage   # also re-inserts 18 known bugs into a temporary copy; each must be caught
python verify_s0_s11.py --report result.md
```

| Group | Needs | Proves |
|---|---|---|
| contracts | — | write-once state, plan hash, codec, confirmation-store contract |
| unit | — | every stage alone, API, DeepSeek adapter (no network), settings, circuit breaker |
| journeys | — | full S0→S11 runs, every stop, the confirmation flow, suspended runs |
| architecture | — | no dead modules, layering, file ≤ 200 lines, function ≤ 40 lines, no test doubles or prints in `src` |
| postgres | `TEST_DATABASE_URL` (name ends in `_test`; it is wiped) | real adapters as a non-superuser (RLS), migrations, full runs, HTTP flow, API keys |
| deepseek | `DEEPSEEK_API_KEY` | one real DeepSeek call |

A group without its variable shows **NOT RUN** (never PASS). Exit code 0 = VERIFIED.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `error: DATABASE_URL not set` | No `.env` in the current folder | Create `.env` (section 5) or set the variable |
| `permission denied for schema public` on `migrate` | Migrating as the app role | Migrate as the owner (section 4) |
| `permission denied for table …` on `serve` | Grants missing | Run the GRANT block in section 4 |
| Every request `deny` / `activation_state_unavailable` | The key's tenant or workspace has no row | Load reference data (section 6.1) |
| `deny` / `mutation_not_permitted` for deletes | `tenants.max_mutation` is `W` (default) | `UPDATE tenants SET max_mutation = 'D' WHERE tenant_id = '…';` |
| `deny` / `capability_denied` | No `capability_grants` row | Add the grant |
| `error` / `llm_unavailable` at S2 | Wrong/missing key, no internet, or API format changed | `python -m supragents llm-check` |
| `clarify` / `no_capability` | The model answered `unknown` or an intent without a capability | Add the capability, or rephrase |
| Row-level security seems not to apply | Service runs as the owner or a superuser | Use `supragents_app` in `DATABASE_URL` |
| `bundle is damaged` | A file changed in transit | Copy the zip again |
| `No matching distribution` in the offline install | Bundle built for another OS/Python | Rebuild with the right `--target` and `--python` |
| Postgres tests refused | `TEST_DATABASE_URL` name does not end in `_test` | Use a dedicated `…_test` database |

---

## 11. Code map and rules for extending (for LLMs and developers)

```
src/supragents/
  contracts/      frozen dataclasses: vocabulary (enums), entry request, ExecutionContext,
                  registry records, stage outputs, PipelineState (write-once), plan hash, codec
  ports/          interfaces (typing.Protocol) to everything outside the pipeline
  policy/         pure rules: sanitizer, risk, confirmation rules
  stages/         one module per stage: async def run(state, deps) -> state
  pipeline/       deps bundle, STAGES sequence, PipelineRunner (the only place a run stops), RunResult
  adapters/       real implementations of ports: postgres/, llm/ (DeepSeek), runtime/ (circuit breaker)
  api/            FastAPI routes and Envelope mapping
  observability/  stage log line
  bootstrap.py    composition root (build_runner, build_intent_model)
  server.py       starts uvicorn with the composed app
  settings.py     .env + environment
  __main__.py     command line
tests/  unit/ contracts/ journeys/ architecture/ integration/ live/ ; fakes/ (test doubles live ONLY here)
```

Rules the tests enforce — keep them when you change anything:

1. **One execution path.** Only `PipelineRunner` decides whether a run continues. Stages
   return a state; to stop, a stage calls `state.halted(stage, status, reason)`.
2. **Write-once state.** A stage writes only its own field via `state.with_output(...)`;
   context changes only through `with_context` (S2 `task_id`, S5 policy versions,
   S8 auth fields).
3. **Trust boundaries.** Risk, mutation and capabilities come from the registry, never from
   the request or the LLM. Identity comes from the API key, never from the body.
4. **Fail closed.** A port that cannot answer leads to DENY or ERROR, never to success.
5. **Layering.** contracts ← ports ← policy/stages ← pipeline ← adapters/api ← bootstrap/server/CLI
   (see `ALLOWED_IMPORTS` in `tests/architecture/test_architecture.py`).
6. **No dead code.** Every module must be reachable from `pipeline.runner`, `bootstrap` or
   `__main__`. No TODOs, no prints outside the CLI, no test doubles in `src`, no mutable
   module-level state, files ≤ 200 lines, functions ≤ 40 lines.
7. **New external system?** Add a port in `ports/`, an adapter in `adapters/`, a fake in
   `tests/fakes/`, wire it in `bootstrap.py`, and add tests (and a sabotage case in
   `verify_s0_s11.py` for any safety rule).
8. **New table?** Add the next numbered file in `adapters/postgres/migrations/`, with RLS
   for tenant data; add it to `tests/integration/seed.py` `TABLES`.

---

## 12. Known limitations

- S12–S15 are not implemented: a completed run produces a manifest, nothing is executed.
- No admin API: tenants, users, capabilities and grants are loaded with SQL.
- The S8 budget check compares with `tenants.budget_pool` only; reservations arrive with S12.
- The circuit breaker is in-process (single node).
- DeepSeek endpoint path and reply format are assumptions until `llm-check` succeeds once.
- Schema differences from `DATABASE.md` await owner confirmation (WORK_PACKAGES.md).
- The code is not yet certified by the owner's pinned certifier (WORK_PACKAGES package 0).
