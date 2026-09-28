# Validation

**Purpose**: The complete testing and validation strategy for the rebuild. Four tiers of testing, CI pipeline, contract testing, chaos testing, and coverage requirements. This ensures the system is correct before it ever reaches production.

---

## Table of Contents

1. [Testing Philosophy](#1-testing-philosophy)
2. [Four-Tier Testing Strategy](#2-four-tier-testing-strategy)
3. [Tier 1: Unit Tests](#3-tier-1-unit-tests)
4. [Tier 2: Contract Tests](#4-tier-2-contract-tests)
5. [Tier 3: Integration Tests](#5-tier-3-integration-tests)
6. [Tier 4: Chaos Tests](#6-tier-4-chaos-tests)
7. [CI Pipeline](#7-ci-pipeline)
8. [Coverage Requirements](#8-coverage-requirements)
9. [Test Infrastructure](#9-test-infrastructure)
10. [Validation Checklist](#10-validation-checklist)
11. [Architecture Test Harness](#11-architecture-test-harness)
12. [Architecture Acceptance Gate](#12-architecture-acceptance-gate)

---

## 1. Testing Philosophy

### Principles

| Principle | Rule |
|-----------|------|
| **Test behavior, not implementation** | Tests should verify what the code does, not how |
| **Deterministic tests** | No flaky tests. Every test must pass every time |
| **Fast feedback** | Unit tests run in < 5 seconds total |
| **Isolated tests** | No test depends on another test's state |
| **Real contracts** | Contract tests use real API responses (recorded) |
| **Fail-loud** | A failing test blocks the build |

### What NOT to Test

| Don't Test | Why |
|------------|-----|
| Third-party library internals | They have their own tests |
| Generated code structure | Test the generator, not the output |
| LLM output values | Non-deterministic — test structure only |
| Time-dependent logic without mocking | Use `freezegun` or `time-machine` |

---

## 2. Four-Tier Testing Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 4: Chaos Tests                                           │
│  Simulate failures: retry storms, circuit breaks, budget drain │
│  Run: Nightly / pre-deploy                                      │
├─────────────────────────────────────────────────────────────────┤
│  TIER 3: Integration Tests                                     │
│  End-to-end: message → response through full pipeline           │
│  Run: On every PR to main                                       │
├─────────────────────────────────────────────────────────────────┤
│  TIER 3.5: Billing Tests                                       │
│  Usage recording, pricing, invoicing, credits                   │
│  Run: On every commit that touches billing code                 │
├─────────────────────────────────────────────────────────────────┤
│  TIER 2: Contract Tests                                        │
│  Every kernel in every adapter against recorded responses       │
│  Run: On every commit                                           │
├─────────────────────────────────────────────────────────────────┤
│  TIER 1: Unit Tests                                            │
│  Pure logic: consolidation, retry, state machines, safety       │
│  Run: On every commit, pre-commit hook                          │
└─────────────────────────────────────────────────────────────────┘
```

### Tier Matrix

| Tier | What | When | Runtime |
|------|------|------|---------|
| 1 | Unit tests (pure logic) | Every commit | < 5s |
| 2 | Contract tests (adapter API) | Every commit | < 30s |
| 3 | Integration tests (full pipeline) | PR to main | < 2min |
| 3.5 | Billing tests (usage, pricing, invoices) | Every billing commit | < 1min |
| 4 | Chaos tests (failure injection) | Nightly / pre-deploy | < 5min |

---

## 3. Tier 1: Unit Tests

### Scope

Pure logic with no external dependencies. These are the tests that run on every commit and must complete in under 5 seconds.

### Required Unit Test Files

| File | Tests | Coverage Target |
|------|-------|-----------------|
| `tests/unit/test_consolidation.py` | All step state combinations | 100% |
| `tests/unit/test_retry_policy.py` | Retry decision matrix for all mutation types | 100% |
| `tests/unit/test_retry_backoff.py` | Exponential backoff + jitter | 100% |
| `tests/unit/test_state_transitions.py` | All valid/invalid state transitions | 100% |
| `tests/unit/test_sanitizer.py` | Injection detection and sanitization | 100% |
| `tests/unit/test_idempotency.py` | Key computation, ledger operations | 100% |
| `tests/unit/test_budget.py` | Reserve, commit, release, race conditions | 100% |
| `tests/unit/test_circuit_breaker.py` | State transitions, thresholds | 100% |
| `tests/unit/test_path_routing.py` | All confidence/risk/type combinations | 100% |
| `tests/unit/test_safety_gate.py` | Each check independently + combined | 100% |
| `tests/unit/test_plan_validator.py` | Each validation rule independently | 100% |
| `tests/unit/test_execution_context.py` | Frozen, field validation | 100% |

### Key Test: Consolidation (Exhaustive)

```python
class TestConsolidation:
    @pytest.mark.parametrize("states,expected", [
        # All same
        (["completed"], "ok"),
        (["failed"], "failed"),
        (["skipped"], "ok"),
        (["partial"], "partial"),
        # Two states
        (["completed", "completed"], "ok"),
        (["failed", "failed"], "failed"),
        (["skipped", "skipped"], "ok"),
        (["completed", "failed"], "partial"),
        (["completed", "skipped"], "ok"),
        (["completed", "partial"], "partial"),
        (["failed", "skipped"], "failed"),
        (["failed", "partial"], "partial"),
        (["skipped", "partial"], "partial"),
        # Three states
        (["completed", "failed", "skipped"], "partial"),
        (["completed", "skipped", "partial"], "partial"),
        (["failed", "skipped", "partial"], "partial"),
        # All four states
        (["completed", "failed", "skipped", "partial"], "partial"),
    ])
    def test_consolidation(self, states, expected):
        results = {f"step_{i}": StepResult(status=s) for i, s in enumerate(states)}
        assert consolidate(results) == expected
```

### Key Test: Retry Decision Matrix

```python
class TestRetryPolicy:
    @pytest.mark.parametrize("mutation,retry_safety,error_status,should_retry", [
        # R mutations — always retry on retryable errors
        ("R", "safe", 429, True),
        ("R", "safe", 500, True),
        ("R", "safe", 401, False),
        # W mutations — depends on retry_safety
        ("W", "safe", 429, True),
        ("W", "idempotent", 429, True),
        ("W", "never", 429, False),
        # D mutations — idempotent only
        ("D", "idempotent", 429, True),
        ("D", "never", 429, False),
        ("D", "never", 404, False),
        # IRREVERSIBLE — never retry
        ("IRREVERSIBLE", "safe", 429, False),
        ("IRREVERSIBLE", "safe", 500, False),
    ])
    def test_should_retry(self, mutation, retry_safety, error_status, should_retry):
        policy = RetryPolicy(mutation=mutation, retry_safety=retry_safety)
        error = ProviderError(status_code=error_status)
        assert policy.should_retry(error, attempt=1) == should_retry
```

### Key Test: Safety Gate (All 8 Checks)

```python
class TestSafetyGate:
    """Each test fails exactly ONE check."""

    def test_denies_inactive_user(self, gate, ctx_with_inactive_user):
        result = gate.check(profile, ctx_with_inactive_user)
        assert not result.allowed
        assert result.failed_check == "user_active"

    def test_denies_inactive_tenant(self, gate, ctx_with_inactive_tenant):
        result = gate.check(profile, ctx_with_inactive_tenant)
        assert not result.allowed
        assert result.failed_check == "tenant_active"

    def test_denies_open_circuit(self, gate, ctx, profile_with_open_circuit):
        result = gate.check(profile_with_open_circuit, ctx)
        assert not result.allowed
        assert result.failed_check == "circuit_breaker"

    # ... one test per check (8 total) ...
```

---

## 4. Tier 2: Contract Tests

### Scope

Every kernel operation in every adapter is tested against a recorded API response. This ensures adapters handle real API responses correctly.

### Recorded Responses

Real API responses are recorded weekly and stored as fixtures:

```
tests/fixtures/
  ├── ghl_public_live.json       # Recorded from GHL Public API
  ├── ghl_workflow_live.json     # Recorded from GHL Workflow API
  ├── notion_live.json           # Recorded from Notion API
  ├── google_calendar_live.json  # Recorded from Google Calendar
  ├── google_sheets_live.json    # Recorded from Google Sheets
  └── airtable_live.json         # Recorded from Airtable API
```

### Recording Process

```bash
# Weekly: update recorded responses
make update-test-fixtures
```

This runs each adapter against the live API and stores responses.

### Contract Test Pattern

```python
class TestGHLPublicContract:
    @pytest.fixture(scope="session")
    def recorded_responses(self):
        path = "tests/fixtures/ghl_public_live.json"
        if not os.path.exists(path):
            pytest.skip("No recorded fixtures — run 'make update-test-fixtures'")
        return json.load(open(path))

    @pytest.mark.parametrize("kernel_op_id", GHLPublicAdapter.capabilities())
    async def test_kernel_matches_recorded(self, kernel_op_id, adapter, recorded_responses):
        # Call adapter with recorded params
        result = adapter.call(kernel_op_id, {}, mock_binding)

        # Get recorded response for this kernel
        recorded = recorded_responses.get(kernel_op_id)
        if recorded is None:
            pytest.skip(f"No recorded response for {kernel_op_id}")

        # Validate structure matches
        assert result.status == recorded["status"], \
            f"Status mismatch: {result.status} != {recorded['status']}"
        if recorded["status"] == "ok":
            assert set(result.data.keys()) == set(recorded["data"].keys()), \
                f"Response keys mismatch for {kernel_op_id}"
```

### Adapter Contract Tests (Every Adapter)

| Test | What It Validates |
|------|------------------|
| `test_adapter_never_raises` | `call()` always returns KernelResult, never raises |
| `test_adapter_does_not_mutate_params` | Input params dict is not modified |
| `test_all_kernels_have_meta` | Every capability has KERNEL_MAP entry |
| `test_all_kernels_have_schema` | Every capability has input/output schema |
| `test_health_check` | `health_check()` returns valid HealthStatus |
| `test_capabilities_list` | `capabilities()` returns all kernel_op_ids |
| `test_validate_params_rejects_invalid` | Invalid params return error |
| `test_validate_params_accepts_valid` | Valid params return ok |

---

## 5. Tier 3: Integration Tests

### Scope

End-to-end tests that verify the complete pipeline: message → intent → capability → plan → execution → response.

### Required Integration Tests

| Test | What It Validates |
|------|------------------|
| `test_full_pipeline_fast` | FAST path: single read operation |
| `test_full_pipeline_workflow` | WORKFLOW path: multi-step write operation |
| `test_full_pipeline_confirm` | D/IRREVERSIBLE operation with confirmation |
| `test_full_pipeline_clarify` | Low confidence → clarify flow |
| `test_full_pipeline_deny` | Authorization failure → deny flow |
| `test_full_pipeline_rollback` | Mid-execution failure → rollback |
| `test_full_pipeline_partial` | Partial execution → consolidation |
| `test_full_pipeline_timeout` | Step timeout → dead letter |
| `test_budget_lifecycle_success` | reserve → commit → verify balance decreased |
| `test_budget_lifecycle_failure` | reserve → release → verify balance restored |
| `test_budget_lifecycle_timeout` | Step timeout → lock → sweep → verify released |
| `test_budget_lifecycle_lease_recovery` | Lease expire → probe → commit/release per step |
| `test_budget_concurrent_no_overspend` | Two concurrent reserves → neither exceeds pool |

### Integration Test Pattern

```python
class TestFullPipeline:
    @pytest.fixture
    def pipeline(self, db, adapters):
        """Complete pipeline with all components."""
        return AgentControlPlane(
            registry=CapabilityRegistry(db),
            engine=ExecutionEngine(adapters),
            safety=SafetyGate(),
            llm=MockLLM(),  # Deterministic mock
        )

    async def test_full_pipeline_fast(self, pipeline):
        envelope = await pipeline.execute(
            user_id="test_user",
            tenant_id="test_tenant",
            message="List my contacts",
            connection_id="test_conn",
        )
        assert envelope.status == "ok"
        assert envelope.data is not None
```

---

## 6. Tier 4: Chaos Tests

### Scope

Simulate failures to verify the system handles them correctly. Run nightly and before deployment.

### Required Chaos Tests

| Test | What It Simulates | Expected Behavior |
|------|-------------------|-------------------|
| `test_retry_storm` | 100 concurrent failures on one provider | RetryStormGuard blocks excess retries |
| `test_circuit_breaker_open` | 5 consecutive failures | Circuit opens, no more requests |
| `test_circuit_breaker_half_open` | Cooldown expires, probe succeeds | Circuit closes |
| `test_budget_exhaustion` | User budget reaches zero | Next request denied |
| `test_budget_lock_sweep` | Locked reservation > 24h old | Sweeper releases it, budget restored |
| `test_provider_failure_recovery` | Provider goes down then up | Circuit closes after recovery |
| `test_concurrent_idempotency` | Same key, concurrent requests | Only one executes |
| `test_checkpoint_corruption` | Crash during checkpoint write | Atomic write prevents corruption |
| `test_confirmation_token_reuse` | Token used twice | Second use rejected |

### Chaos Test Pattern

```python
class TestChaos:
    async def test_retry_storm(self, guard, failing_adapter):
        """Simulate 100 concurrent retries — storm guard should kick in."""
        for _ in range(100):
            result = await guard.execute_step(failing_step, failing_adapter, ctx)
            assert result.status == "error"

        # Verify storm guard logged the block
        storm_count = guard.retry_guard.get_blocked_count()
        assert storm_count > 0

    async def test_circuit_breaker_open(self, guard, failing_adapter):
        """After 5 failures, circuit should open."""
        for i in range(5):
            result = await guard.execute_step(failing_step, failing_adapter, ctx)
            assert result.status == "error"

        # 6th request should be blocked by circuit breaker
        result = await guard.execute_step(failing_step, failing_adapter, ctx)
        assert result.metadata.get("circuit_open") is True
```

---

## 7. CI Pipeline

### CI Jobs

```
┌──────────────────────────────────────────────────────────────────┐
│  PR / Push to any branch                                        │
│                                                                  │
│  Job 1: lint          ruff check + format                        │
│  Job 2: typecheck     mypy --strict                               │
│  Job 3: tier1         Unit tests (< 5s)                          │
│  Job 4: tier2         Contract tests (< 30s)                     │
│  Job 5: tier3         Integration tests (< 2min)                 │
│  Job 6: registry      Verify YAML ↔ DB ↔ generated files sync   │
│  Job 7: adapter       Verify all adapters have all 8 files       │
│  Job 8: engine_map    Verify ENGINE_MAP completeness             │
│  Job 9: security      Scan for injection patterns, secrets       │
│  Job 10: coverage     Enforce 80% minimum                        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Nightly (cron: 0 2 * * *)                                      │
│                                                                  │
│  Job 1: tier4         Chaos tests (< 5min)                       │
│  Job 2: live_test     One live test per adapter                  │
│  Job 3: stale_check   Check for stale/phantom capabilities       │
│  Job 4: backup        Database backup                            │
└──────────────────────────────────────────────────────────────────┘
```

### CI Enforcement Rules

| Check | Enforcement |
|-------|-------------|
| Lint (ruff) | Block merge on any error |
| Type check (mypy) | Block merge on any error |
| Unit tests | Block merge on any failure |
| Contract tests | Block merge on any failure |
| Integration tests | Block merge on any failure |
| Registry consistency | Block merge on any drift |
| Adapter completeness | Block merge on missing files |
| ENGINE_MAP completeness | Block merge on missing entries |
| Security scan | Block merge on credential leak |
| Coverage | Block merge if < 80% |

### GitHub Actions Workflow

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install ruff
      - run: ruff check engine/ logic/ servers/ shared/ tests/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install mypy
      - run: mypy --strict engine/ logic/ servers/ shared/

  tier1-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install pytest pytest-asyncio
      - run: pytest tests/unit/ -v --tb=short

  tier2-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pytest tests/contract/ -v --tb=short

  tier3-integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pytest tests/integration/ -v --tb=short

  registry-consistency:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: python -m tools.check_registry_consistency
      - run: python -m tools.check_adapter_completeness
      - run: python -m tools.check_engine_map

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: python -m tools.scan_for_credentials
      - run: python -m tools.scan_for_injection_patterns

  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install pytest pytest-cov
      - run: pytest --cov=engine --cov=logic --cov=servers --cov=shared --cov-fail-under=80
```

---

## 8. Coverage Requirements

### Coverage Targets

| Component | Target | Enforcement |
|-----------|--------|-------------|
| Pure logic (consolidation, retry, state machines) | 100% | CI blocks merge |
| Safety checks (SafetyGate, Authorizer) | 100% | CI blocks merge |
| Execution engine | 90% | CI blocks merge |
| Control plane stages | 85% | CI blocks merge |
| Adapters (contract tests) | 80% | CI blocks merge |
| Interface layer | 70% | CI blocks merge |
| Overall | 80% minimum | CI blocks merge |

### Coverage Commands

```bash
# Full coverage report
pytest --cov=engine --cov=logic --cov=servers --cov=shared --cov-report=html

# Check minimum
pytest --cov=engine --cov=logic --cov=servers --cov=shared --cov-fail-under=80

# Per-module coverage
pytest --cov=engine.control_plane --cov-fail-under=85
pytest --cov=engine.execution --cov-fail-under=90
```

---

## 9. Test Infrastructure

### Shared Fixtures (conftest.py)

```python
# tests/conftest.py

@pytest.fixture
def db():
    """In-memory SQLite database with schema."""
    database = Database(":memory:")
    database.run_migrations()
    yield database
    database.close()

@pytest.fixture
def mock_binding():
    """Mock binding for adapter tests."""
    return BindingRow(
        id="test-binding",
        capability_id="ghl.contact_search",
        kernel_op_id="ghl.contact_search",
        provider="ghl",
        priority=1,
        engine_module="engine.providers.ghl.kernel_meta",
        adapter_class="GHLPublicAdapter",
        endpoint="/contacts/",
        is_active=True,
    )

@pytest.fixture
def mock_context():
    """Mock execution context."""
    return ExecutionContext(
        request_id="test-request-id",
        task_id="test-task-id",
        tenant_id="test-tenant",
        user_id="test-user",
        conversation_id="test-conv",
        connection_id="test-conn",
        provider=None,
        resource_scope="user",
        correlation_id="test-correlation",
    )

@pytest.fixture
def mock_llm():
    """Deterministic mock LLM for control plane tests."""
    return MockLLM(responses={
        "intent_analysis": {
            "intent": "contact_search",
            "entities": {"query": "test"},
            "confidence": 0.95,
        },
    })
```

### MockLLM for Deterministic Tests

```python
class MockLLM:
    """Deterministic LLM mock for testing."""
    def __init__(self, responses: dict[str, Any]):
        self._responses = responses

    async def call(self, prompt_type: str, **kwargs) -> dict:
        return self._responses.get(prompt_type, {})

    async def structured_call(self, prompt_type: str, schema: dict, **kwargs) -> dict:
        response = self._responses.get(prompt_type, {})
        # Validate against schema (catches schema mismatches)
        validate(response, schema)
        return response
```

### Time Mocking

```python
# Use freezegun for time-dependent tests
import freezegun

@freezegun.freeze_time("2026-01-01T00:00:00Z")
def test_confirmation_expires():
    token = create_confirmation(expires_in=300)
    # Advance 6 minutes
    with freezegun.freeze_time("2026-01-01T00:06:00Z"):
        assert token.is_expired()
```

---

## 10. Validation Checklist

### Pre-Commit Checks (run automatically via pre-commit hook)

- [ ] `ruff check` passes
- [ ] `mypy --strict` passes
- [ ] Unit tests pass (`pytest tests/unit/`)
- [ ] Contract tests pass (`pytest tests/contract/`)
- [ ] `python -m tools.check_registry_consistency` passes
- [ ] `python -m tools.check_adapter_completeness` passes
- [ ] `python -m tools.check_engine_map` passes

### Pre-Merge Checks (CI)

- [ ] All pre-commit checks pass
- [ ] Integration tests pass (`pytest tests/integration/`)
- [ ] Coverage >= 80%
- [ ] Security scan passes (no credentials, no injection patterns)
- [ ] No generated files modified without regenerating all

### Pre-Deploy Checks

- [ ] All CI checks pass
- [ ] Chaos tests pass
- [ ] Live adapter tests pass
- [ ] Startup validation passes on staging
- [ ] Smoke test passes on staging

### Test Writing Rules

1. Every bug fix must have a regression test
2. Every new feature must have tests
3. Every edge case must be tested
4. Every error path must be tested
5. No test should depend on execution order
6. No test should depend on real time (use mocking)
7. No test should depend on external services (use fixtures)
8. Every xfail must have a reason
9. Every skip must have a reason
10. Never leave a failing test without explanation

---

## 11. Architecture Test Harness

### Purpose

The architecture test harness validates that the system design is correct before a single line of production code is written. It catches structural errors, security gaps, and execution semantics at the design level.

### Rule

**The harness must be defined before production code is written.**

### Six Test Categories

```
┌─────────────────────────────────────────────────────────────────┐
│  1. CONTRACT TESTS                                               │
│     schema → serialization → deserialization                     │
│     Validates that all data contracts are bidirectional          │
├─────────────────────────────────────────────────────────────────┤
│  2. PIPELINE TESTS                                               │
│     S0 → S15 (full pipeline)                                     │
│     Validates every stage handoff in the execution pipeline      │
├─────────────────────────────────────────────────────────────────┤
│  3. FAILURE TESTS                                                │
│     timeout, crash, disconnect, duplicate, stale lease           │
│     Validates that every failure mode has a defined recovery     │
├─────────────────────────────────────────────────────────────────┤
│  4. SECURITY TESTS                                               │
│     cross-tenant access, privilege escalation,                   │
│     worker impersonation, prompt injection                       │
│     Validates that every trust boundary is enforced              │
├─────────────────────────────────────────────────────────────────┤
│  5. CONCURRENCY TESTS                                            │
│     2 workers, 100 workers, 1,000 workers, 10,000 workers        │
│     Validates correctness under scaled parallel execution        │
├─────────────────────────────────────────────────────────────────┤
│  6. RECOVERY TESTS                                               │
│     kill worker, restart DB, replay execution, resume execution  │
│     Validates that the system recovers from infrastructure loss  │
└─────────────────────────────────────────────────────────────────┘
```

### Category Details

#### 1. Contract Tests

Verify that every schema round-trips correctly through serialization and deserialization.

| Test | Validates |
|------|-----------|
| Schema → JSON → Schema | No data loss in serialization |
| Schema → Protobuf → Schema | Binary serialization preserves all fields |
| Schema → DB row → Schema | Persistence layer preserves all fields |
| Cross-version schema | Old schema can read new data and vice versa |

#### 2. Pipeline Tests (S0 to S15)

Trace a request through every stage of the execution pipeline. Each stage must produce a valid output for the next stage.

| Test | Validates |
|------|-----------|
| S0→S1→...→S15 happy path | Complete pipeline with no errors |
| S0→S5 clarification | Clarification flow returns to S0 correctly |
| S0→S8 deny | Authorization failure terminates cleanly |
| S0→S12 rollback | Mid-execution failure triggers rollback |
| S0→S15 partial | Partial results consolidate correctly |

#### 3. Failure Tests

Inject failures at every layer and verify the system responds correctly.

| Failure Mode | Expected Response |
|--------------|-------------------|
| Timeout | Step marked failed, budget released, dead letter |
| Crash | Lease expires, another worker picks up, execution resumes |
| Disconnect | Queue entry remains, worker reconnects and resumes |
| Duplicate | Idempotency key prevents double execution |
| Stale lease | Fence prevents stale worker from committing |

#### 4. Security Tests

Attack the system from every trust boundary.

| Attack Vector | Defense |
|---------------|---------|
| Cross-tenant access | RLS blocks tenant A from reading tenant B data |
| Privilege escalation | SafetyGate rejects requests above user's role |
| Worker impersonation | Worker identity chain verified at every handoff |
| Prompt injection | Sanitizer detects and blocks injection patterns |

#### 5. Concurrency Tests

Scale worker count and verify correctness at each level.

| Workers | What It Validates |
|---------|-------------------|
| 2 | Basic concurrent correctness, no race conditions |
| 100 | Connection pool saturation, query contention |
| 1,000 | Lock contention, deadlock detection, bulkhead limits |
| 10,000 | Queue backpressure, memory limits, tenant fairness |

#### 6. Recovery Tests

Destroy infrastructure and verify the system recovers.

| Recovery Scenario | Expected Outcome |
|-------------------|------------------|
| Kill worker mid-execution | Lease expires, another worker picks up, execution completes |
| Restart database | Queue entries preserved, workers reconnect, execution resumes |
| Replay execution | Replaying from checkpoint produces identical results |
| Resume execution | Resuming from lease produces identical results |

### Validation Test Reference

- `test_harness_completeness()` — Verifies all six categories have at least one defined test case before implementation begins.

---

## 12. Architecture Invariant Tests

### Purpose

Every architecture invariant I-001 through I-021 must have a named test that verifies it, a CI gate that runs that test on every commit, and a failure mode that halts the pipeline if the invariant is violated.

### Invariant Test Suite

| Invariant | Test Name | Validates |
|-----------|-----------|-----------|
| I-001 | `test_tenant_isolation_rls()` | No cross-tenant data access under any circumstance |
| I-002 | `test_frozen_bindings_immutable()` | Frozen bindings cannot change during execution |
| I-003 | `test_single_budget_reservation()` | Only S12 performs budget reservation |
| I-004 | `test_zombie_worker_rejected()` | A stale worker cannot commit any state change |
| I-005 | `test_no_silent_success()` | UNKNOWN cannot become SUCCESS without verification |
| I-006 | `test_immutable_plan()` | A plan cannot mutate after confirmation |
| I-007 | `test_llm_cannot_authorize()` | LLM output cannot authorize an action |
| I-008 | `test_principal_chain_preserved()` | Every mutation is traceable to an authenticated principal |
| I-009 | `test_immutable_execution_context()` | ExecutionContext is immutable after S0 creation |
| I-010 | `test_immutable_frozen_binding()` | FrozenBindingIdentity is immutable after S5 creation |
| I-011 | `test_llm_call_budget()` | Only one LLM call per request (S2), max 2 with retry |
| I-012 | `test_adapter_no_authorization()` | No adapter can make authorization decisions |
| I-013 | `test_external_mutation_verified()` | Every external mutation must be verified before SUCCESS |
| I-014 | `test_memory_write_barrier()` | Memory writes must pass through MemoryWriteBarrier |
| I-015 | `test_single_source_of_truth()` | No document contradicts FINAL_ARCHITECTURE.md |
| I-016 | `test_no_customer_override()` | Customer configuration cannot override kernel invariants |
| I-017 | `test_manifest_frozen()` | Execution uses configuration versions frozen in manifest |
| I-018 | `test_secret_isolation()` | Provider credentials never enter execution context |
| I-019 | `test_server_authoritative_time()` | Distributed timing uses server time, not worker-local clocks |
| I-020 | `test_outbox_atomicity()` | State changes and events committed atomically |
| I-021 | `test_at_least_once_semantics()` | Execution is at-least-once; duplicate is safe, missing is not |

### Negative-Path Matrix

Every failure mode must have a defined recovery path. This matrix covers all 16 failure scenarios.

| # | Failure Mode | Detection | Recovery | Test |
|---|-------------|-----------|----------|------|
| 1 | S2 timeout | Step timeout guard | Retry with fallback model | `test_s2_timeout()` |
| 2 | S5 binding stale | lease_epoch vs fence_token | Re-resolve binding | `test_s5_stale_binding()` |
| 3 | S12 budget exhausted | Atomic reservation fails | Plan rejection, user notified | `test_s12_budget_exhausted()` |
| 4 | Worker crash mid-execution | Lease expiry | Another worker picks up via lease | `test_worker_crash()` |
| 5 | Provider API failure | Circuit breaker opens | Retry with backoff, then failover | `test_provider_failure()` |
| 6 | Database connection lost | Connection pool detects | Reconnect, resume from checkpoint | `test_db_connection_lost()` |
| 7 | UNKNOWN outcome (timeout) | S13 probe required | S13 establishes truth before SUCCESS | `test_unknown_outcome()` |
| 8 | Duplicate request | Request fingerprint match | Idempotent response, no double execution | `test_duplicate_request()` |
| 9 | Cross-tenant access attempt | RLS policy violation | Access denied, audit logged | `test_cross_tenant_blocked()` |
| 10 | Prompt injection in user input | Sanitizer detects | Request rejected, audit logged | `test_prompt_injection_blocked()` |
| 11 | Worker impersonation | PrincipalChain mismatch | Request rejected, alert raised | `test_worker_impersonation_blocked()` |
| 12 | Clock skew on lease | Server-authoritative time | Lease validated against server time | `test_clock_skew_detected()` |
| 13 | Silent success attempt | I-005 check in S13 | UNKNOWN→PROBE→CONFIRMED_SUCCESS | `test_silent_success_blocked()` |
| 14 | Frozen binding mutation | I-002 check in S5 | Execution halted, audit logged | `test_frozen_binding_mutation_blocked()` |
| 15 | Budget reservation double-spend | I-003 check in S12 | Second reservation rejected | `test_double_spend_blocked()` |
| 16 | LLM authorization attempt | I-007 check in SafetyGate | Authorization rejected, audit logged | `test_llm_authorization_blocked()` |

### No Silent Success Invariant (I-005)

The system must never report SUCCESS for an execution that has not been verified. This is the single most important correctness guarantee.

| Test | Scenario | Expected |
|------|----------|----------|
| `test_unknown_cannot_become_success()` | S13 receives UNKNOWN, no probe performed | System returns UNKNOWN, not SUCCESS |
| `test_probe_required_for_unknown()` | S13 receives UNKNOWN, probe initiated | PROBE → CONFIRMED_SUCCESS or CONFIRMED_FAILURE |
| `test_timeout_to_unknown()` | Step exceeds timeout | Status set to UNKNOWN, not FAILED |
| `test_no_silent_success_on_partial()` | Step returns partial result | Status set to PARTIAL, not SUCCESS |

### Guardrail Precedence Tests

The ten-level guardrail must be evaluated in the correct order. A higher-precedence guardrail cannot be bypassed by a lower-precedence one.

| Test | Validates |
|------|-----------|
| `test_identity_before_tenant_isolation()` | Identity check runs before tenant check |
| `test_kill_switch_before_authorization()` | Kill switch halts before authorization evaluates |
| `test_capability_before_policy()` | Capability scope checked before policy evaluates |
| `test_risk_before_budget()` | Risk/mutation evaluated before budget guard |
| `test_budget_before_reliability()` | Budget guard evaluated before retry/timeout |
| `test_reliability_before_execution()` | Reliability guard evaluated before execution begins |

### Principal Chain Tests

| Test | Validates |
|------|-----------|
| `test_principal_chain_preserved_through_delegation()` | Original principal preserved when worker delegates |
| `test_impersonation_blocked()` | Worker cannot execute as another worker |
| `test_delegation_requires_authorization()` | Delegation requires explicit authorization grant |
| `test_principal_chain_in_audit_log()` | Every mutation includes full principal chain |

### Worker Authorization Tests

Worker authorization is separate from user authentication. Workers authenticate via lease tokens, not passwords.

| Test | Validates |
|------|-----------|
| `test_worker_auth_vs_user_auth()` | Worker lease token authentication is distinct from user password auth |
| `test_stale_lease_rejected()` | Expired worker lease is rejected at authentication |
| `test_worker_capacity_respected()` | Worker cannot exceed max_concurrency |
| `test_worker_drain_prevents_new()` | Draining worker receives no new assignments |

### at-Least-Once Semantics Tests

| Test | Validates |
|------|-----------|
| `test_duplicate_execution_idempotent()` | Same request executed twice produces same result |
| `test_missing_execution_retried()` | Failed execution is retried (not silently dropped) |
| `test_request_fingerprint_prevents_duplicates()` | Duplicate fingerprint returns cached result |
| `test_at_least_once_not_exactly_once()` | System retries on failure, does not guarantee single execution |

### Database Constraint Tests

| Test | Validates |
|------|-----------|
| `test_worker_lease_epoch_matches_fence_token()` | worker.lease_epoch equals latest worker_leases.fence_token |
| `test_stale_worker_cannot_commit()` | Worker with lease_epoch < current fence_token cannot update state |
| `test_budget_reservation_amount_check()` | reservation.amount <= tenants.budget_pool |
| `test_execution_status_unknown_persisted()` | UNKNOWN and PROBE status values stored correctly |
| `test_no_duplicate_table_definitions()` | Every table defined exactly once in DATABASE.md |
| `test_worker_identity_state_transitions()` | WorkerIdentityStateValidator rejects illegal transitions |
| `test_worker_version_state_transitions()` | WorkerVersionStateValidator rejects illegal transitions |
| `test_only_one_current_version()` | Scheduler query returns exactly one CURRENT per worker |
| `test_admission_stateless()` | Admission gates leave no state — no budget reserved, no lease acquired |
| `test_verification_independent()` | Verifier observes actual provider state, not adapter self-report |
| `test_verification_never_skipped_for_mutations()` | W/D/IRREVERSIBLE always run verification |
| `test_ownership_transfer_monotonic()` | Fencing tokens are strictly monotonically increasing |

---

## 13. Architecture Acceptance Gate

### Purpose

A gate that must pass before any production code is written. Prevents building on a flawed foundation.

### ARCHITECTURE_READY

```
ARCHITECTURE_READY = TRUE only when:
```

#### A. STRUCTURAL

- [ ] no duplicate source of truth
- [ ] no unresolved document contradiction
- [ ] no undefined contract
- [ ] no circular dependency

#### B. SECURITY

- [ ] RLS defined
- [ ] identity chain defined
- [ ] authorization boundaries defined
- [ ] worker delegation defined

#### C. EXECUTION

- [ ] pipeline stages S0-S15 defined
- [ ] S12 admission control sequenced before worker selection
- [ ] S13 independent verification for mutations (worker claim != evidence)
- [ ] state locality scoring defined (advisory, not binding)
- [ ] UNKNOWN -> PROBE -> CONFIRMED flow enforced
- [ ] verification built at S11, executed at S13 (not constructed at S13)

#### D. WORKER LIFECYCLE

- [ ] WorkerIdentity state machine (REGISTERED -> ACTIVE -> DRAINING -> DRAINED -> TERMINATED)
- [ ] WorkerVersion state machine (9 states with rollout gates)
- [ ] Exactly one CURRENT version per WorkerIdentity
- [ ] Fencing token monotonicity enforced
- [ ] Execution ownership tracking table exists

#### E. DATA

- [ ] PostgreSQL 16 canonical
- [ ] Alembic canonical
- [ ] schema manifest reconciled
- [ ] indexes/constraints defined
- [ ] migration/rollback strategy defined

#### E. RELIABILITY

- [ ] timeout contract
- [ ] circuit breaker contract
- [ ] bulkhead contract
- [ ] budget contract
- [ ] recovery contract
- [ ] dead-letter contract

#### F. SCALE

- [ ] queue model
- [ ] scheduler model
- [ ] worker capacity
- [ ] tenant fairness
- [ ] backpressure
- [ ] 10k-worker test strategy

#### G. EVIDENCE

- [ ] E0 design complete for all components
- [ ] E1 build complete for M0 components
- [ ] E2 test complete for M0 components
- [ ] E3 failure test complete for M0 components

### Implementation Gates

| Gate | Rule |
|------|------|
| M0 → M1 | Implementation cannot proceed to M1 until M0 components reach E2 |
| M1 → M2 | Implementation cannot proceed to M2 until M1 components reach E2 |

### Validation Test Reference

- `test_architecture_acceptance_gate()` — Verifies all ARCHITECTURE_READY criteria are satisfied before implementation begins.

### A11 — Replay Determinism Contract

```
test_replay_determinism():
    # Record: execute a full pipeline with deterministic inputs
    execution = execute_pipeline(fixed_input, fixed_binding_hash="abc123")
    events_1 = get_event_log(execution.execution_id)

    # Replay: same inputs, same binding hash
    execution2 = execute_pipeline(fixed_input, fixed_binding_hash="abc123")
    events_2 = get_event_log(execution2.execution_id)

    # Assert: identical event sequence, identical outcomes
    assert events_1.sequence == events_2.sequence
    assert execution1.outcome == execution2.outcome
```

**Validation**: Replay with same inputs produces identical event log. Different inputs produce different event log. Binding hash mismatch causes different path.

### A12 — Idempotency Scope Test

```
test_idempotency_scope():
    # Same ExecutionContext, duplicate submission → same result, no double-charge
    ctx = create_context(tenant_id="t1", task_id="task-1")
    result1 = execute(ctx)

    # Duplicate submission with same execution_id
    result2 = execute(ctx)  # same execution_id

    assert result1 == result2
    assert get_budget_charges(ctx.execution_id) == result1.cost
    # NOT result1.cost * 2
```

**Validation**: Idempotency is enforced at the execution_id level. Same execution_id cannot double-charge budget.

### A15 — Tenant Fairness Test

```
test_tenant_fairness():
    # Tenant A: burst of 100 requests
    # Tenant B: steady stream of 10 requests
    # Tenant C: low-priority stream of 5 requests

    # Assert: Tenant B is not starved by Tenant A's burst
    # Assert: Tenant C is not starved by either
    # Assert: System load > 90% triggers DEGRADE for all tenants equally

    responses = parallel([
        burst_requests("tenant-a", count=100),
        steady_requests("tenant-b", count=10, interval=1s),
        low_requests("tenant-c", count=5)
    ])

    assert tenant_b_success_rate(responses) > 0.8
    assert tenant_c_success_rate(responses) > 0.8
```

**Validation**: Noisy tenant does not starve other tenants. Fairness is enforced at the admission gate.

---

*End of Validation.*
