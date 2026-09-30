# S12–S15 PHASE — SESSION 0: PREFLIGHT ONLY (gate commit A)

> **Worker-management repair (RD-18, 2026-09-29):** the prompt required gate revision v8, which made Session 0 STOP against the v9 gate; it now requires v10. It referred to gate items 3–9 only; it now covers 3–16. Its own items were numbered 10–15, clashing with gate items 10–14; they are renumbered P1–P6.

Repository root: `C:\Users\Administrator\Documents\1SuperAgents`
Documents: `C:\Users\Administrator\Documents\1SuperAgents\docs\implementation`
Gate tracking files: `C:\Users\Administrator\Documents\1SuperAgents\docs\gates`

`C:\Users\Administrator\Documents\AiagentsOS\rebuild` is NOT the project. Never read
from or write to it.

## 1. Standing rules (apply to every session of this phase)

1. Re-read `S12_S15_EXECUTION_GATE.md` at the start of every session and after any
   context summarization. Never rely on memory of earlier sessions.
2. Every reply ends with the report block in Section 6. A reply without it is
   incomplete.
3. Answer from the current code and database only, with `file:line` evidence, or
   write "not present in code". Do not answer implementation questions from the
   architecture documents.
4. Never change a test's expectation to match current behavior, never fabricate a
   stage's output in an integration test, never mark an item "documented" instead of
   DONE, never skip or xfail a required case.
5. Do not open or read `.env`, and do not read credentials from any file. Use
   `.env.example` for variable names only.

## 2. Document roles

| Document | Role in this phase | What to do with it |
|---|---|---|
| `S12_S15_EXECUTION_GATE.md` | **Binding.** Must be Revision **v10**. | Governs everything. If the header is not v10, STOP and report. |
| `s0_s11_autopilot/RULING_R-P_pause_check.md` | S0–S11 ruling (pause at S0.1). | Must be implemented and certified before this session; gate item 17. |
| `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` | **Reference only.** Gate C39–C41 govern. | Implement nothing outside C39. |
| `XS-1_REGISTER_ENTRY.md` | Already incorporated as gate ruling **C22**. | Do not treat it as a separate source. At commit B, file XS-1 in the register as "RESOLVED BY C22". |
| `LAYA_DECISION_ADAPTER.md` | **Deferred design note.** Its own header says it must not be implemented, migrated or tested in this phase. | Reference only. At commit B, file its entries LB1–LB11 in the register with target phase "LLM layer". Implement nothing from it. |
| `db create.txt` | **Superseded** by this prompt. It contains a plaintext password. | Must not exist in the repository. See preflight item P4. |

Owner confirmation: gate decisions D1–D6 (Section 6) are confirmed as written.

## 3. Environment

- The owner has set the environment variable `TEST_DATABASE_URL` to the
  `suprpg_test` database. Use it; do not construct connection strings yourself.
- If `suprpg_test` does not exist, STOP and report; the owner creates it.
- All tests run only against `suprpg_test`. Never connect to, modify or drop any
  other database on the server.
- Use the Python environment already installed. Do not install or upgrade packages
  without reporting first.

## 4. Preconditions — STOP if any fails

1. The repository root is a git repository. Report `git log --oneline -5`. The
   S0–S11 certification commit is tagged `s0-s11-certified`.
2. The full suite at that tag: 0 failed, 0 skipped, 0 xfail. Paste the raw pytest
   summary line.
3. `SELECT version();` through `TEST_DATABASE_URL` reports PostgreSQL 16 or higher.
4. The gate file header reads Revision v10.

## 5. Preflight items

Answer gate Section 2 items 3–17 (items 15–16 cover the C39 worker-management
columns, tables and key types; item 17 is the S0.1 pause check of S0–S11 ruling R-P —
STOP if it is absent), then these prompt items P1–P6. Where a gate item already
answers a prompt item (gate 9 ↔ P1, gate 11 ↔ P2), reference it and add only what it
does not cover (audit round 2 D11):

P1. **Environment.** Python environment path and version, OS, asyncio event loop,
    and whether asyncpg works under that loop. Compare `pip freeze` with
    `pyproject.toml` / requirements and list anything missing or mismatched.
P2. **Migrations.** Which migration tool the project uses (for example Alembic),
    where migrations live, and which tables currently exist in `suprpg_test`
    (`\dt` equivalent). The gate requires versioned, additive migrations; if no
    migration tool exists, say so and propose one. Do not create migrations yet.
P3. **Existing schema vs the gate.** For each table the gate touches
    (`execution_runs`, `execution_steps`, `execution_manifests`, `worker_leases`,
    `execution_ownership`, `budget_reservations`, `checkpoints`,
    `idempotency_ledger`, `pending_confirmations`, `dead_letters`, `workers`,
    `tenants`, `workspaces`, `users`, `memberships`, `event_subscriptions`,
    `operation_quotas`), report whether it exists in code-defined schema or migrations, with
    `file:line`, and list every difference from DATABASE.md that rulings C5, C20,
    C21, C22, C39 or Section 7.3 address. List every foreign key whose type differs
    from the referenced key (owner ruling RD-1: keys are `TEXT`).
P4. **Credential exposure.** Search the working tree **and git history** for
    committed credentials (database passwords, API keys, tokens), including any
    `db create.txt`. Report file paths and commit hashes only; never
    print a secret value. Do not rewrite history; the owner decides the remedy.
P5. **XS-1 and Laya cross-check.** Confirm with `file:line` that the four XS-1
    conflicts exist in the current docs (STATE_TRANSITIONS §2 annotation, I-1
    terminal list, `execution_steps.status` comment, absence of a reason column).
    Confirm that no code in the repository implements any part of the Laya note
    (`DecisionContract`, `LayaDecisionAdapter`, `ReflexChoice`, `step_decisions`).
P6. **Test manifest.** Save `pytest --collect-only -q` as
    `docs/gates/test_manifest_s12_baseline.txt` and commit it.

Then **STOP**. Do not start gate commit B.

## 6. Report block (mandatory)

```text
Phase: S12-A (preflight)
Preconditions 1–4: PASS/FAIL, each with evidence
Gate items 3–16: answer + file:line or "not present in code"
Prompt items P1–P6: answer + evidence
Conflicts or stop conditions found: list, or "none"
pytest summary line (raw, copied)
git commit hash
```
