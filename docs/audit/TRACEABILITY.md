# Traceability Matrix — S0–S11, M0–M12

Source documents: PIPELINE_STAGES.md, DATA_CONTRACTS.md, STATE_TRANSITIONS.md, SECURITY.md, RELIABILITY.md, S12_S15_EXECUTION_GATE.md (M0–M12 sections).

| Req ID | Spec File:Line | Implementing File:Line | Covered by Test | Status |
|---------|---------------|----------------------|-----------------|--------|
| MUT-001 | PIPELINE_STAGES.md:retry_ceiling | src/engine/stages/s12_execute/retry_policy.py:29–38 | M01_guard.py:test_retry_ceiling | MET |
| MUT-002 | PIPELINE_STAGES.md:irreversible_attempts | src/engine/stages/s12_execute/retry_policy.py:37 | M01_guard.py:test_irreversible_single_attempt | MET |
| MUT-003 | PIPELINE_STAGES.md:backoff_policy | src/engine/stages/s12_execute/retry_policy.py:60–69 | M01_guard.py:test_exponential_backoff | MET |
| ADM-001 | PIPELINE_STAGES.md:mutation_safety | src/engine/stages/s12_execute/admission.py:25–55 | M02_guard.py:test_admission_blocks_unsafe | MET |
| ADM-002 | PIPELINE_STAGES.md:budget_reservation | src/engine/stages/s12_execute/budget_guard.py:30–70 | M04_guard.py:test_budget_exhausted | MET |
| FNC-001 | DATA_CONTRACTS.md:fencing | src/adapters/postgres/fencing.py:25–80 | M05_guard.py:test_fence_exclusive | MET |
| IDM-001 | DATA_CONTRACTS.md:idempotency | src/adapters/postgres/idempotency.py:35–56 | M06_guard.py:test_idempotency_dedup | MET |
| IDM-002 | DATA_CONTRACTS.md:fenced_write | src/adapters/postgres/idempotency.py:56 | M06_guard.py:test_fenced_write | MET |
| SEC-001 | SECURITY.md:tenant_isolation | src/adapters/postgres/database.py:tenant_transaction | M07_guard.py:test_tenant_isolation | MET |
| SEC-002 | SECURITY.md:input_sanitization | src/contracts/data_sanitizer.py:77–100 | M07_guard.py:test_sanitization | MET |
| SEC-003 | SECURITY.md:webhook_encryption | src/adapters/postgres/webhook_credentials.py:53–68 | M07_guard.py:test_secret_encryption | MET |
| SEC-004 | SECURITY.md:api_key_hashing | src/adapters/postgres/api_keys.py:14–15 | M07_guard.py:test_key_hash | MET |
| REL-001 | RELIABILITY.md:circuit_breaker | src/engine/stages/s12_execute/circuit_breaker.py | M08_guard.py:test_circuit_breaker | MET |
| REL-002 | RELIABILITY.md:retry_with_backoff | src/engine/stages/s12_execute/reliability.py | M08_guard.py:test_retry_recovery | MET |
| REL-003 | RELIABILITY.md:dead_letter | src/engine/stages/s14_dead_letter/handler.py | M09_guard.py:test_dead_letter | MET |
| DLQ-001 | DATA_CONTRACTS.md:dead_letter_immutable | src/adapters/postgres/dead_letters.py:96 | M09_guard.py:test_dead_letter_immutable | MET |
| DLQ-002 | DATA_CONTRACTS.md:resolution_outcome | src/adapters/postgres/dead_letters.py:149 | M09_guard.py:test_resolution | MET |
| REC-001 | RELIABILITY.md:recovery_reauthorize | src/adapters/postgres/live_authorization.py | M09_guard.py:test_recovery_auth | MET |
| REC-002 | RELIABILITY.md:recovery_idempotency | src/adapters/postgres/idempotency.py | M09_guard.py:test_recovery_idempotency | MET |
| REN-001 | RELIABILITY.md:fence_renewal | src/engine/stages/s12_execute/renewal.py | M09_guard.py:test_renewal | MET |
| REN-002 | RELIABILITY.md:grace_period | src/engine/stages/s12_execute/renewal.py:default 24h | M09_guard.py:test_grace_period | MET |
| ST-001 | STATE_TRANSITIONS.md:terminal_only | src/contracts/execution_states.py:TERMINAL_STATES | M01_guard.py | MET |
| ST-002 | STATE_TRANSITIONS.md:valid_transitions | src/engine/stages/s12_execute/executor.py:state_machine | M01_guard.py | MET |

## MISSING / CONTRADICTED: None

All 23 requirements are MET. No MISSING or CONTRADICTED rows.
