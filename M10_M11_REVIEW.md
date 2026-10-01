# M10 & M11 Deep Compliance Review

## Summary
- M10 tests: 55/55 passing
- M11 tests: 43/43 passing
- Overall status: GREEN

## M10 Findings

### [LOW] `_InvalidRetryPolicy` is dead code (never surfaced)
- **File**: src/engine/stages/s12_execute/retry_policy.py:25
- **Root cause**: `_InvalidRetryPolicy` is raised by `_ceiling()`, but `ceiling()` validates `retry_safety` before calling `_ceiling()`, and `_ceiling()` validates `mutation` before raising it. Since `run_attempts` catches all exceptions around `max_attempts()` and defaults to ceiling 1, this exception can never reach a caller. The public `InvalidRetryPolicy` at line 41 is also never reachable via the same path.
- **Impact**: None functionally — the private class is harmless. Slight confusion for maintainers reading the code.
- **Fix**: Either remove both exception classes or add a test that directly calls `_ceiling()` with an invalid mutation to justify the exception's existence.
- **Test coverage**: No test exercises invalid mutation input.

### [LOW] `UnusedImport` lint risk: `field` imported twice in engine reliability re-export
- **File**: src/engine/stages/s12_execute/reliability.py:12
- **Root cause**: `from dataclasses import dataclass, field` is at line 12, but `field` is not used in this module (only `dataclass` is used for `HealthEvent`, `BillingEvent`).
- **Impact**: No runtime impact; potential lint warning.
- **Fix**: Remove unused `field` import.
- **Test coverage**: N/A (import-only issue).

### [INFO] `ReservationState.LOCKED` comparison differs between files but is equivalent
- **File**: src/adapters/runtime/reliability.py:67 vs src/engine/stages/s12_execute/reliability.py:65
- **Root cause**: The adapter-adjacent version compares `status != ReservationState.LOCKED.value` (explicit string `"locked"`), while the engine re-export compares `status != ReservationState.LOCKED` (StrEnum member). Because `ReservationState` inherits from `StrEnum`, both `ReservationState.LOCKED == "locked"` and `"locked" == ReservationState.LOCKED` evaluate to `True`, so the behavior is identical.
- **Impact**: None — both work correctly. The engine version is slightly more Pythonic.
- **Fix**: No fix needed; minor style inconsistency for awareness.
- **Test coverage**: Covered by `test_budget_tracker_*` tests.

### [INFO] `BudgetTracker` silently coerces `step_id` to `None` for status-only lookups
- **File**: src/adapters/runtime/reliability.py:50-54 and src/engine/stages/s12_execute/reliability.py:49-53
- **Root cause**: When `BudgetTracker._lookup()` falls through to `reserver.status(tenant_id, reservation_id)`, it constructs a synthetic row with `step_id=None`. The subsequent `step_id != call.step_id` check will then always raise `BudgetStateError` for this path, even if the reservation exists and is LOCKED. This means the `status()` method path in BudgetTracker is **non-functional** for valid step checks.
- **Impact**: Any BudgetTracker wired with a reserver that only exposes `.status()` (not `.reservation()`) will always fail on `step_id` mismatch. The current tests always use `PostgresBudgetReserver` which has `.reservation()`, so this path is untested.
- **Fix**: Either document that `.status()` is legacy and unsupported for step-matching, or include `step_id` in the synthetic row. The test infrastructure should also not be allowed to reach this path without `.reservation()`.
- **Test coverage**: No test exercises the `.status()` code path.

### [INFO] Retry storm guard uses `kernel_op_id` not `provider_call_id` for tracking
- **File**: src/adapters/runtime/reliability.py:262
- **Root cause**: The guard passes `call.kernel_op_id` to `allow_retry(provider, operation)` while the spec (RELIABILITY §6) calls it `(provider, operation)`. This is consistent with the `InProcessRetryStormGuard` implementation which stores hits keyed by `(provider, kernel_op_id)`.
- **Impact**: None — it works as designed. The naming "operation" vs "kernel_op_id" is slightly imprecise in comments but not a bug.
- **Fix**: No fix needed; awareness only.
- **Test coverage**: Covered by `test_retry_storm_blocks_retries_not_first_attempts`.

### [INFO] Mock adapter `raise_exception` and `adapter_defect` behave identically
- **File**: src/adapters/runtime/mock_adapter.py:210-216
- **Root cause**: Both `raise_exception` and `adapter_defect` behaviours raise `RuntimeError("mock adapter defect")`. The test only uses `raise_exception`.
- **Impact**: None functionally. The `adapter_defect` kind is redundant but harmless.
- **Fix**: No fix needed; could simplify by removing the `adapter_defect` branch.
- **Test coverage**: Only `raise_exception` is tested.

## M11 Findings

### [MEDIUM] No test validates `InvalidRetryPolicy` is raised for unknown mutation
- **File**: src/engine/stages/s12_execute/retry_policy.py:38
- **Root cause**: `_ceiling()` raises `_InvalidRetryPolicy` for unknown mutations, but `ceiling()` only calls `_ceiling()` after validating `retry_safety`. The exception is thus internal and untested. The public `InvalidRetryPolicy` class (line 41) is also never raised — `ceiling()` calls `_ceiling()` which raises `_InvalidRetryPolicy`, not `InvalidRetryPolicy`.
- **Impact**: Low — the code path is defensive. But if a caller ever passes a bad mutation, they get `_InvalidRetryPolicy` (private) instead of `InvalidRetryPolicy` (public). This is inconsistent.
- **Fix**: Make `ceiling()` validate mutation too, and raise `InvalidRetryPolicy` for bad mutations, or remove `_InvalidRetryPolicy`.
- **Test coverage**: None for invalid inputs.

### [MEDIUM] `max_attempts` accepts negative `step_max` and returns 1 via `max(effective, 1)`
- **File**: src/engine/stages/s12_execute/retry_policy.py:57
- **Root cause**: If `step_max` is negative (e.g., -1), `min(3, -1) = -1`, then `max(-1, 1) = 1`. So a negative `step_max` is silently clamped to 1, which happens to match the default behavior. This is not strictly a bug, but the silent coercion could mask misconfiguration.
- **Impact**: None in practice — `StepAttempt.step_max_attempts` is typed as `int | None` and tests only pass `None` or positive values.
- **Fix**: Add validation: `if step_max is not None and step_max < 1: raise ValueError(...)`.
- **Test coverage**: No test passes a negative `step_max`.

### [MEDIUM] `_adapter_result_for_outcome` for "uncertain" uses `"timeout"` as status when reason is `"timeout"`
- **File**: src/engine/stages/s12_execute/attempts.py:97
- **Root cause**: For `kind="uncertain"`, the function returns `AdapterResult("timeout" if reason == "timeout" else "error", ...)`. This means the status is `"timeout"` (not `"error"`), which is semantically unusual because `"uncertain"` is the `kind` in `AttemptOutcome`, while `result.status` is `"timeout"`. Consumers must check `kind` for the outcome category and `result.status` for the underlying status.
- **Impact**: No test failure. The test at M11 line 296 checks `out.kind == "uncertain"` and `out.reason == "timeout"` but does not inspect `out.result.status`. A consumer conflating `kind` and `result.status` could misinterpret the result.
- **Fix**: Document that `result.status` is the raw adapter status while `kind` is the normalized outcome. Consider using `"error"` for uncertain timeout results to avoid confusion, or add a test asserting `out.result.status == "timeout"`.
- **Test coverage**: Test asserts `kind` and `reason` but not `result.status`.

### [INFO] Timeout is non-retryable in runner but `TIMEOUT` is in the guard's retryable set
- **File**: src/engine/stages/s12_execute/attempts.py:231 vs src/adapters/runtime/reliability.py:306-312
- **Root cause**: The guard's retryable set includes `ErrorClass.TIMEOUT` (line 311), but the runner's retryable check at line 231 only includes `{"not_dispatched", "rate_limited", "server_error"}`. So the guard marks a timeout as retryable, but the runner never retries it. This is correct behavior (timeouts should not be retried — MUTATION_SAFETY), but the guard's retryable set is broader than the runner's, creating a discrepancy.
- **Impact**: None — the runner is the authoritative retry decision maker. The guard's broader retryable set is harmless because the runner overrides it.
- **Fix**: Consider removing `ErrorClass.TIMEOUT` from the guard's retryable set for consistency, or add a comment explaining that the runner is the authoritative retry gate.
- **Test coverage**: Covered by `test_a_timeout_is_uncertain_never_retried_and_leaves_no_row`.

### [INFO] Ledger `store` exception handler silently swallows `FencedOut` on second store
- **File**: src/engine/stages/s12_execute/attempts.py:216, 247, 255
- **Root cause**: The `except Exception: pass` around `deps.ledger.store()` catches `FencedOut` along with all other exceptions. If the first store succeeds but the second (e.g., for a client error) fails with `FencedOut`, the step proceeds as if the store worked. This is unlikely in practice (same holder, same connection for `fenced_write`) but theoretically possible under race conditions.
- **Impact**: Very low — `fenced_write` uses the same fence holder, so a fenced-out would fail consistently. The silent swallow is consistent with the spec's approach of "best-effort" ledger recording.
- **Fix**: No fix needed. The broad `except` is intentional for best-effort ledger recording.
- **Test coverage**: No test exercises ledger store failure.

## Cross-cutting Issues

### [LOW] Duplicate implementations of BudgetTracker, ReliabilityGuard, TimeoutManager, etc.
- **Files**: src/adapters/runtime/reliability.py and src/engine/stages/s12_execute/reliability.py
- **Root cause**: The engine re-exports (or rather, duplicates) the reliability components so that `engine.stages.s12_execute` has no dependency from `engine` down to `adapters`. However, the two files are nearly identical (~95% code overlap), with minor differences in the `BudgetTracker.check()` status comparison (`.value` vs no `.value`). This creates a maintenance burden — a bug fix in one file must be manually replicated in the other.
- **Impact**: Medium maintenance risk. Both files are currently in sync, but divergence is likely over time.
- **Fix**: Consider extracting the shared implementation into `contracts.reliability` and having both files import and re-export, or have the engine module import from `adapters.runtime.reliability` (breaking the architectural layer boundary).
- **Test coverage**: Both files are exercised by the same tests, which currently pass.

### [LOW] `_InvalidRetryPolicy` is never surfaced (same finding in M11, confirmed in M10 context)
- See M10 [LOW] finding above — this is the cross-cutting version since `_InvalidRetryPolicy` lives in a shared module.

## Recommendations

1. **Consolidate `_InvalidRetryPolicy` / `InvalidRetryPolicy`**: Either remove the private exception class or route the public one through it. The current state has two exception classes where one suffices.

2. **Add a `max_attempts` validation test**: Pass a negative `step_max` to verify the clamping behavior, and decide whether to allow it or reject it.

3. **Add a `BudgetTracker` test for the `.status()` code path**: If the `.status()` path is legacy, document it and consider removing it. If it's used, write a test that exercises it.

4. **Add a test for `_adapter_result_for_outcome`**: Assert that `kind="uncertain"` with `reason="timeout"` produces `result.status == "timeout"` to lock in the current behavior.

5. **Remove unused `field` import** from `src/engine/stages/s12_execute/reliability.py:12`.

6. **Add ledger store failure resilience test**: Verify that a `FencedOut` during ledger store doesn't crash the runner.

7. **Consider a lint rule** for module-level mutable state detection, since the current test (`test_no_module_level_mutable_state_in_s12_code`) only catches assignments at module top level, not mutations of module-level objects from within functions.
