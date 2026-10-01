# M18: S15 response and redaction (gate commit K) ⚙

| | |
|---|---|
| Gate | §12, §21 S6, suite 12; FINAL_ARCHITECTURE I-018; SECURITY §7; PIPELINE_STAGES §19 (matrix rows "Budget exhausted", "No eligible worker") |
| Rulings | CONF-039 (envelope error types for cancellation and revocation) |
| Golden | `tests_golden/s12/M18_response.py`: 16 cases (10 functions) |
| Sabotage | `M18_cancelled_hides_completed`, `M18_internal_ids_leak`, `M18_ledger_keeps_bodies` |
| Depends on | M16 terminal runs, M17 dead letters (redaction is checked in their evidence), M11 ledger |
| Reference | `src/contracts/envelope.py`, `src/engine/stages/s15_final_state/response.py` (90 lines), `src/adapters/postgres/run_summary.py` (30) |

## Files

| File | Action |
|---|---|
| `src/contracts/envelope.py` | **new**: `Envelope(status, data=None, message=None, error=None, metadata=None)`, `EnvelopeError(type, message, details=None, recoverable=True, suggested_action=None)` (DATA_CONTRACTS) |
| `src/engine/stages/s15_final_state/response.py` | **new**, pure: `StepSummary(position, operation, status, terminal_reason=None)`, `RunSummary(run_status, terminal_reason, trace_id, steps)`, `build_envelope(summary) -> Envelope` |
| `src/adapters/postgres/run_summary.py` | **new**: `PostgresRunSummaries(database).load(tenant_id, execution_id) -> RunSummary \| None` (steps in plan order; another tenant gets `None`) |
| `src/adapters/postgres/idempotency.py` | only if needed: a failure row stores its error **class**, never the provider body |
| `src/adapters/runtime/reliability.py`, `s12_execute/reliability.py` | only if a log line carries exception text: log the exception **type** only |

Leave the prototype `s15_final_state/handler.py` and the S0–S11 `ExecuteResponse` mapping for S12 entry denials as
they are (§12 first bullet; a known gap in the B4 review).

## Logic and conditions

**Mapping (`build_envelope`).** A listed step is `{"position", "operation", "status"}`, with a 1-based plan position
and the kernel operation name.

| Run status | `status` | `data` | `error` |
|---|---|---|---|
| COMPLETED | `ok` | `{"steps": [completed steps]}` | none |
| PARTIAL | `partial` | `{"steps": [completed]}` | `type="partial_execution"`, `details={"failed_steps": [failed and cancelled]}` |
| FAILED | `error` | | lists its failed and cancelled steps; if steps ended `no_worker`: message `"No worker is available for this task right now"` |
| CANCELLED | `error` | | `details["completed_steps"]` always lists the steps that completed before the cancellation |
| DEAD_LETTER | `error` | | `recoverable=False` |
| not terminal | raises `ValueError` | | |

Cancellation error types (CONF-039):

| terminal_reason | error.type | message |
|---|---|---|
| `budget_exhausted` | `budget_exceeded` | `"Budget limit reached — upgrade or reduce scope"` (`env.message == env.error.message`) |
| `authorization_revoked`, `credential_invalid` | `unauthorized` | fixed user-safe text |
| `binding_invalid` | `provider_unavailable` | fixed user-safe text |
| `user_cancelled`, `kill_switch_engaged`, any other | `execution_failed` | fixed user-safe text |

`metadata == {"trace_id": ...}` and nothing else.

**What must never appear** in the envelope, any log record, a dead letter's evidence, or any persisted row (the case
checks 9 tables):

- internal ids: execution, request, tenant, user, workspace, runtime, step, reservation (only `trace_id`);
- exception text and stack traces;
- provider response bodies, including an error body with a token in it;
- the credential (it comes only from the `CredentialProvider`, S6);
- what the verifier observed at the provider (keys, traces).

The case drives an adapter defect, a 401 with a body, and retries exhausted with a body (which creates a dead
letter).

## Traps

- Hiding completed steps of a CANCELLED run (sabotage `M18_cancelled_hides_completed`).
- Naming steps by internal step id (sabotage `M18_internal_ids_leak`). Use plan position and operation.
- Storing a failure's provider body in the ledger (sabotage `M18_ledger_keeps_bodies`; a past reference defect).
- `logger.error(f"... {exc}")` anywhere on the call path. Log `type(exc).__name__` with record attributes. M10's leak
  case fails as well.
- Dead-letter evidence that copies `AdapterResult.data` from an error.

## Done when

- [ ] 16/16 in `M18_response.py`; M01–M17 green.
- [ ] `owner_certify_s12.py --milestone M18`: all PASS, sabotage 3/3.
- [ ] B4 complete: 135/135 across M15–M18, 12/12 sabotage. Send the batch report.
