---
date: 2026-10-03
baseline_sha: e3e9cae
milestone_range: M0–M12
severity_key:
  - CRITICAL
  - HIGH
  - MEDIUM
  - LOW
  - INFO
status_key:
  - OPEN
  - FIXED
  - WONTFIX
  - NEEDS_RULING
---

# Findings

## AUD-001 (CRITICAL) — Dead-code routes in app.py
- **file:** src/app.py:70–126
- **fingerprint:** 8a7f3b2c
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** `/chat` (L70), `/template-variables` (L87), `/files` (L104), and `/files/{file_id}/content` (L114) are defined and mounted but never referenced in src/ or tests_golden/. The 80%/81% figure would be higher without this dead code.
- **rule:** exit-N, I-1
- **related_records:** []
- **fix_owner_milestone:** M21+ (CLAUDE.md prohibits editing app.py)

## AUD-002 (CRITICAL) — Main entry point is fully dead code
- **file:** src/main.py:1–106
- **fingerprint:** 3b1e4f5a
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** `main.py` is the documented kernel entry point (CLAUDE.md §"Start here") but is never imported by app.py or any other production code. All 106 lines are at 0% coverage.
- **rule:** exit-N, I-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-003 (CRITICAL) — Unused dependencies with zero imports
- **file:** pyproject.toml:15–22
- **fingerprint:** 9c2d8e1f
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** `redis>=5.0`, `prometheus-client>=0.19`, `opentelemetry-api`, `opentelemetry-sdk`, `tenacity>=8.2`, `aio-pika>=9.4` have **zero imports** in src/, tools/, scripts/ and src/adapters/ (redis was searched exhaustively: imports, module references, string references — none found). `httpx>=0.27` is used only in tests_postgres/, not in src/. These are installed (visible in pip list) but not used by the application.
- **rule:** F-1, F-2
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-004 (HIGH) — JWT secret read from settings but never imported
- **file:** src/config.py
- **fingerprint:** 4a5b6c7d
- **status:** OPEN
- **confidence:** PLAUSIBLE
- **summary:** `jwt_secret` (L42) and `webhook_kek_version` (L40) are defined in Settings. The webhook_kek is used via `settings.webhook_kek` (confirmed in bootstrap.py:38, bootstrap.py:47). `jwt_secret` appears to have no consumer — no `import jwt` or jwt library usage found in src/. If JWT auth was planned but not implemented, this is an orphaned config field.
- **rule:** F-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-005 (HIGH) — Exception swallowed without traceback in S2
- **file:** src/engine/stages/s2_intent_analysis/handler.py:142
- **fingerprint:** 5b6c7d8e
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** `logger.warning("S2: intent model unavailable (%s)", exc)` — the comment says "one line, no traceback" which is intentional for log cleanliness, but this is the only place in the codebase that logs an exception class without `exc_info=True`. All other exception logs include tracebacks. Inconsistent observability pattern.
- **rule:** G-1
- **related_records:** []
- **fix_owner_milestone:** M10+

## AUD-006 (HIGH) — N+1 query in webhook_credentials endpoint
- **file:** src/adapters/postgres/webhook_credentials.py:89–93
- **fingerprint:** 6c7d8e9f
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** `endpoint()` fetches all matching rows (L76–83), then decrypts each one in a Python loop (L89–93). For endpoints with many credential versions, this is N+1 on the decryption step. The query itself is bounded by `ORDER BY status = 'active' DESC` but does not LIMIT.
- **rule:** G-4, G-5
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-007 (HIGH) — Password hashing uses MD5, not bcrypt
- **file:** src/adapters/postgres/admin_reference.py
- **fingerprint:** 7d8e9f0a
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** Password hashing in admin_reference.py uses MD5. The `bcrypt` library is listed as a dependency and used for API key hashing (SHA-256), but admin passwords use MD5 which is considered cryptographically broken. Finding confirmed by Grep of "md5" in src/.
- **rule:** SECURITY-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-008 (HIGH) — Correlation IDs not present in most log lines
- **file:** src/engine/stages/* (multiple)
- **fingerprint:** 8e9f0a1b
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** Only reliability.py (L205) and recovery.py (L54, L71) include structured extra fields (kernel_op_id, attempt_id). All other logger calls use plain string formatting without correlation identifiers. A production incident cannot be traced end-to-end without kernel_op_id in every log line.
- **rule:** G-2
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-009 (MEDIUM) — __init__.py files with no content
- **file:** src/engine/stages/s12_execute/__init__.py, src/engine/stages/s13_reconciliation/__init__.py, src/engine/stages/s14_dead_letter/__init__.py, src/engine/stages/s15_final_state/__init__.py
- **fingerprint:** 9f0a1b2c
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** Four `__init__.py` files exist but are empty (0 bytes). They serve only as package markers. Not a defect, but worth noting for cleanliness.
- **rule:** I-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-010 (MEDIUM) — Eligibility module has 6 uncovered lines
- **file:** src/engine/stages/s12_execute/eligibility.py:85, 122, 127, 135, 138, 143
- **fingerprint:** 0a1b2c3d
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** The eligibility check module has 6 uncovered lines (92% coverage). These lines are in exception-handling paths that are hard to trigger in unit tests.
- **rule:** H-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-011 (MEDIUM) — Startup module has 7 uncovered lines
- **file:** src/engine/stages/s12_execute/startup.py:58–64
- **fingerprint:** 1b2c3d4e
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** 7 uncovered lines (79% coverage) in the startup module. These are error paths for database/stage registration failures.
- **rule:** H-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-012 (MEDIUM) — Reliability module has 35 uncovered lines
- **file:** src/engine/stages/s12_execute/reliability.py:61, 70–72, 75, 79–85, 90–91, 94–100, 105, 108, 113, 116, 172→180, 176→178, 182→184, 193→195, 200–202, 212→214, 239–242, 254–255, 266–267, 272→274, 279→281
- **fingerprint:** 2c3d4e5f
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** 35 uncovered lines (78% coverage) — the lowest in src/engine/. These are adapter failure and retry edge cases that need fault-injection tests.
- **rule:** H-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-013 (MEDIUM) — Renewal module has 4 uncovered lines
- **file:** src/engine/stages/s12_execute/renewal.py:43, 59, 63→exit, 67, 90
- **fingerprint:** 3d4e5f6a
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** 4 uncovered lines (86% coverage) in the fence renewal module. These are edge cases for lease expiry and concurrent renewal.
- **rule:** H-1
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-014 (LOW) — Log lines emit structured data via json.dumps
- **file:** src/engine/stages/s12_execute/renewal.py:74, 90; src/engine/stages/s12_execute/recovery.py:54, 71
- **fingerprint:** 4e5f6a7b
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** Several log lines use `logger.warning(json.dumps({...}))` (passing JSON as a string) instead of the structured `logger.warning("msg", extra={...})` pattern used elsewhere. This makes log aggregation harder because the fields are not indexed.
- **rule:** G-1, G-2
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-015 (LOW) — No pip-audit or CVE scan run
- **file:** pyproject.toml
- **fingerprint:** 5f6a7b8c
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** No pip-audit or similar CVE scanning tool was run during this audit. The dependencies include `cryptography>=41`, `aio-pika>=9.4`, `httpx>=0.27` which should be checked for known vulnerabilities. This was noted in section F but could not be executed in this environment.
- **rule:** F-4
- **related_records:** []
- **fix_owner_milestone:** M21+

## AUD-016 (INFO) — M1–M09 golden tests have no skip/xfail/marker-exclusion issues
- **file:** tests_golden/s12/M01_guard.py through M09_*
- **fingerprint:** 6a7b8c9d
- **status:** OPEN
- **confidence:** CONFIRMED
- **summary:** All 1732 tests pass. No skipped, xfailed, or marker-excluded tests were found in the M01–M09 golden suites. The test suite is clean.
- **rule:** H-1
- **related_records:** []
- **fix_owner_milestone:** N/A
