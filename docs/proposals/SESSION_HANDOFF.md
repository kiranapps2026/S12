# Session handoff (2026-09-30)

Branch `s0-s11-repair` (PR #2 into `s0-s11-baseline`, never merge unless the owner asks). Gate: `python tools/owner_certify.py` = 19/19
(on Windows set `PYTHONUTF8=1`). CI: `.github/workflows/tests.yml` (PostgreSQL 16, certifier + `tests` + `tests_postgres`).
Integrity files (certifier, golden tests, pins, `owner_verify.ps1`, spec documents) are changed only on the owner's explicit instruction.
Never ask for or repeat passwords/keys; the DeepSeek key is a test key the owner will revoke later.

## Finished
- S0–S11 repair, M2a multi-capability chains, live proof (`test_live_chain.py`, `test_live_full_stack.py`, 6/6 each).
- S12 prototype (entry checks, verifiers, durable admission, step loop, fencing): built, NOT certified, not called by the API.
- Phase A rulings applied to the runbook, gate (G1–G8) and DATABASE.md; specs re-pinned.
- Phase B4: admin API (keys, endpoint secrets, schemas, schedules, audit, users, memberships, connections, grants; role ceiling, service users).
- Phase C: schedule, MCP and API event sources; per-event-type payload schemas.
- Migrations 001–013 (32 tables); DATABASE.md describes 001–013; `tests_postgres/test_schema_audit.py` keeps src SQL and schema in agreement.
- CI workflow; flaky test fixed (`555` matched random hex).
- Tools: `registry_readiness.py`, `propose_observation.py`, `setup_database.py` (`--reset-password --write-env`), `sync_and_check.ps1`, `run_live_chain.ps1`.
- Windows: certifier 19/19 confirmed on the owner's machine (needs `PYTHONUTF8=1`; the scripts set it).

## Pending
1. Owner: finish `python tools\setup_database.py --reset-password --write-env` (was at the password prompt), then `sync_and_check.ps1`.
2. Owner writes the REAL catalog (`docs/catalog/catalog.yaml`, template `catalog.example.yaml`), then `python tools/load_catalog.py docs/catalog/catalog.yaml --apply` and `registry_readiness.py` = 0 blocked (D1d). The `suprpg` registry is empty until then.
3. Owner runs `tools/owner_verify.ps1` (hard-coded path `C:\Users\Administrator\Documents\1SuperAgents`; set `PYTHONUTF8=1`) and tags `s0-s11-certified`. Hold the tag until item 2 is done. Then S0–S11 code is frozen.
4. `tools/owner_pin.ps1` has a stale hash (integrity file; needs the owner's instruction).
5. Built after the first handoff (`ONBOARDING.md`, migration 014): `tools/create_tenant.py` (first tenant + owner + key), invitations, PostgreSQL rate limits (429), LLM usage metering + `/admin/usage`, file-metadata and template writers, `PostgresResultWriter` (for S15 to call). Still not built: IdP linking, invitation email delivery, per-tenant limits, usage caps/invoicing, file content storage, the S15 caller of `record_result`.
6. Owner rulings still working: M2 rulings R-AB…R-AL, event/admin rulings R-BB…R-BP.
7. S12–S15: not certified (milestones M0–M21). Needs the worker/lease/checkpoint/retry/dead-letter tables (a draft of the worker and lease migration was parked outside the repo and can be rewritten), adapters, admission controller, recovery. After the tag only (Phase D2/D3).
8. One unexplained intermittent failure in one `tests_postgres` run (not reproduced in 8 later full runs); check CI logs if it recurs.
9. PR #2 check-ins run hourly (`send_later`); re-arm silently while the PR is open.
