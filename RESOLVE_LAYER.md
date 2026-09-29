# RESOLVE Layer — Capability → Kernel → Binding → Adapter

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §14 Capability Model, §16 Registry, §18 Safety Model. *(section numbers corrected in audit round 2, D1)*  [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) — identity model, PrincipalChain. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §14 Binding, §13 CapabilityMetadata, §21 FrozenBindingIdentity, §5 ExecutionContext. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S5 Provider Resolution. [SECURITY.md](SECURITY.md) — §3 Authorization Model, §10 Guardrail Level 4. [DATABASE.md](DATABASE.md) — bindings, capabilities, kernel_ops tables.
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY
**Purpose**: Defines the canonical resolution contract that transforms a classified intent into an immutable, authorized, executable binding. This is the most failure-prone layer in the architecture — it must be deterministic, fail-closed, and produce a single immutable artifact consumed by all downstream stages.

**Status**: Design Complete — Critical blockers must be resolved before implementation

---

## Table of Contents

1. [The Clean RESOLVE Contract](#1-the-clean-resolve-contract)
2. [FrozenBindingIdentity — The Single Immutable Artifact](#2-resolutionidentity--the-single-immutable-artifact)
3. [Critical Blockers (Must Fix Before Implementation)](#3-critical-blockers-must-fix-before-implementation)
4. [Structural Inconsistencies](#4-structural-inconsistencies)
5. [Future-Scale Gaps](#5-future-scale-gaps)
6. [Resolution State Machine](#6-resolution-state-machine)
7. [Implementation Rules](#7-implementation-rules)
8. [CI Enforcement](#8-ci-enforcement)

---

## 1. The Clean RESOLVE Contract

Every execution MUST traverse this exact path. No shortcuts, no alternate routes, no fallbacks.

```
Intent (from S2)
    │
    ▼
Capability (human-facing: "create_contact")
    │  Lookup: intent → capability_id in registry
    │  FAIL: DENY / UNRESOLVED — never downgrade risk
    ▼
Authorized Capability (user has this capability?)
    │  Check: user's capability set includes this capability_id
    │  FAIL: DENY / UNAUTHORIZED
    ▼
Kernel Operation (executable: "ghl.create_contact")
    │  Lookup: capability_id → kernel_op_id in bindings
    │  MUST be 1:1 or deterministic 1:N
    │  FAIL: DENY / UNRESOLVED
    ▼
Effective Risk / Mutation
    │  Derive: max(capability.risk_floor, kernel_op.risk_floor, tag_implied)
    │  ONE authoritative derivation — never two independent sources
    ▼
Eligible Bindings (active bindings for this kernel_op)
    │  Filter: is_active = true, workspace enabled, not stale
    │  FAIL if zero eligible bindings: DENY / NO_BINDING
    ▼
Deterministic Binding (exactly ONE binding selected)
    │  Algorithm: priority → health → workspace policy → deterministic tiebreaker
    │  FAIL if ambiguous: DENY / AMBIGUOUS (route to CLARIFY)
    ▼
Provider + Account + Adapter
    │  Resolve: binding.provider → ENGINE_MAP → adapter module
    │  Verify: adapter exists, provider reachable
    │  FAIL: DENY / UNAVAILABLE
    ▼
Immutable Resolution (FrozenBindingIdentity — frozen, never changes)
    │
    ▼
Plan (S9 — FrozenBindingIdentity embedded in every step)
```

### The One Rule

> **Every execution MUST traverse the full canonical path. Alternate dispatch paths are impossible — not merely discouraged. CI enforces this.**

---

## 2. FrozenBindingIdentity — The Single Immutable Artifact

S5 produces exactly one artifact: a `FrozenBindingIdentity`. This is the ONLY resolution output consumed by S6, S7, S8, S9, S10, S11, S12. No stage re-resolves anything.

**Canonical definition** (see `DATA_CONTRACTS.md §6`):

```python
@dataclass(frozen=True)
class FrozenBindingIdentity:
    """The immutable binding identity — frozen at S5, never changes.

    Produced at S5. Consumed by S6-S12. This is the ONLY binding
    information the execution engine ever sees.
    """
    # ─── Identity chain ───────────────────────────────────────────────────────
    binding_id: str          # Selected binding row ID
    capability_id: str       # Human-facing capability ("create_contact")
    kernel_op_id: str        # Executable operation ("ghl.create_contact")

    # ─── Provider resolution ──────────────────────────────────────────────────
    provider: str            # Provider prefix ("ghl_public")
    engine_module: str       # Engine module path ("supr.kernel.engines.ghl")
    adapter_class: str       # Adapter class ("GHLPublicAdapter")

    # ─── Effective values (computed at S5, immutable thereafter) ───────────────
    effective_risk: float    # 0.0–1.0 (max of risk_floor, risk_rule, risk_implied)
    effective_mutation: str  # "R" | "W" | "D" | "IRREVERSIBLE"

    # ─── Metadata ─────────────────────────────────────────────────────────────
    resolved_at_stage: str   # Always "S5"
    selection_rank: int      # Tie-breaker rank (lower = selected)
```

### Audit Record (Separate from FrozenBindingIdentity)

Observability fields (`trace_id`, `request_id`, `task_id`, version strings, rejection reasons, eligibility counts) are stored in the `execution_evidence` table as a JSON blob — they do NOT go into `FrozenBindingIdentity`. `FrozenBindingIdentity` is the minimal set S12 needs; `execution_evidence` is the full audit trail.

### Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | FrozenBindingIdentity is `@dataclass(frozen=True)` | Type system + unit test |
| 2 | All fields populated at S5 — never modified after | Type system |
| 3 | S6-S12 consume FrozenBindingIdentity — never re-resolve | CI check + code review |
| 4 | effective_risk is float (0.0–1.0), NEVER int/0-100 | Type system + CI grep |
| 5 | Every field has a value — no None for required fields | Pydantic validation |
| 6 | engine_module maps to a real module in ENGINE_MAP | CI check |
| 7 | binding_id points to an active, non-stale binding | S5 validation |
| 8 | If FrozenBindingIdentity cannot be fully populated → DENY | S5 logic |

---

## 3. Critical Blockers (Must Fix Before Implementation)

### B-1: Capability-to-Kernel Authorization Mismatch

**Historical Failure**: The old implementation authorized the public capability (e.g., `create_contact`) but the dispatcher later selected a different, higher-risk `kernel_op` (e.g., `ghl.delete_contact`). The user had permission for the capability name, not the actual operation.

**Root Cause**: Authorization checked `capability_id` but execution used `kernel_op_id` — these were not guaranteed to correspond to the same risk level.

**Fix — Single Risk Authority**:

```python
@dataclass(frozen=True)
class EffectiveRisk:
    """Derived ONCE at S5. Never recalculated. Consumed by S6-S12.

    All risk values are float 0.0–1.0 (NOT integer 0-100).
    This matches FrozenBindingIdentity.effective_risk type.
    """

    mutation: str                    # From kernel_op (authoritative)
    effective_risk: float            # max() of all sources — float 0.0–1.0
    primary_source: str              # Which source had the highest risk
    capability_risk: float           # capabilities.risk_floor (0.0–1.0)
    kernel_risk: float               # kernel_ops.risk_floor (0.0–1.0)
    tag_implied_risk: float          # Sum of tag risk contributions (0.0–1.0)
    derivation: str                  # Human-readable: "max(0.3, 0.5, 0.0) = 0.5 from kernel"


def derive_effective_risk(
    capability: CapabilityMetadata,
    kernel_op: KernelOperation,
    context: ExecutionContext,
) -> EffectiveRisk:
    """ONE authoritative risk derivation. Called exactly once at S5."""
    capability_risk = capability.risk_floor   # float 0.0–1.0
    kernel_risk = kernel_op.risk_floor        # float 0.0–1.0
    tag_implied_risk = sum(tag_risk_values(context.tags))  # float, capped at 1.0

    effective_risk = max(capability_risk, kernel_risk, tag_implied_risk)
    effective_risk = min(effective_risk, 1.0)  # Cap at 1.0

    if effective_risk == kernel_risk and kernel_risk >= capability_risk:
        primary_source = "kernel"
    elif effective_risk == capability_risk and capability_risk >= kernel_risk:
        primary_source = "capability"
    else:
        primary_source = "tag"

    return EffectiveRisk(
        mutation=kernel_op.mutation,           # Kernel is authoritative for mutation
        effective_risk=effective_risk,         # Float 0.0–1.0, never int
        primary_source=primary_source,
        capability_risk=capability_risk,
        kernel_risk=kernel_risk,
        tag_implied_risk=tag_implied_risk,
        derivation=f"max({capability_risk}, {kernel_risk}, {tag_implied_risk}) = {effective_risk} from {primary_source}",
    )
```

**Rules**:
1. `kernel_op.mutation` is the authoritative mutation type — capability's mutation hint is advisory only
2. `effective_risk = max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)` — risk only goes up
3. `effective_risk` is a float (0.0–1.0) — never int, never Decimal, never 0-100
4. This function is called EXACTLY ONCE at S5. S6-S12 read from FrozenBindingIdentity.effective_risk.

---

### B-2: Fail-Open on Unresolved Capability/Binding

**Historical Failure**: When resolution failed (no binding found, capability unknown), the system would continue with default metadata, effectively downgrading risk and allowing execution.

**Fix — Fail-Closed Resolution**:

```python
class ResolutionResult:
    """Result of the S5 resolution process."""

    status: Literal["RESOLVED", "DENIED"]
    reason: str | None = None           # Why denied
    denial_type: str | None = None      # UNRESOLVED | UNAUTHORIZED | NO_BINDING | AMBIGUOUS | UNAVAILABLE
    resolution: FrozenBindingIdentity | None = None  # Populated only on RESOLVED


def resolve(context: ExecutionContext, intent: IntentResult) -> ResolutionResult:
    """S5: Canonical resolution. MUST produce RESOLVED or DENIED — never ambiguous."""

    # Step 1: Capability lookup
    capability = registry.capabilities.match(intent.text)
    if capability is None:
        return ResolutionResult(
            status="DENIED",
            reason=f"No capability matches intent '{intent.text}'",
            denial_type="UNRESOLVED",
        )

    # Step 2: Authorization check
    if not context.has_capability(capability.capability_id):
        return ResolutionResult(
            status="DENIED",
            reason=f"User lacks capability '{capability.capability_id}'",
            denial_type="UNAUTHORIZED",
        )

    # Step 3: Kernel operation lookup
    kernel_op = registry.kernels.get_by_capability(capability.capability_id)
    if kernel_op is None:
        return ResolutionResult(
            status="DENIED",
            reason=f"Capability '{capability.capability_id}' has no kernel operation",
            denial_type="UNRESOLVED",
        )

    # Step 4: Risk derivation
    effective_risk = derive_effective_risk(capability, kernel_op, context)

    # Step 5: Eligible bindings
    eligible = registry.bindings.get_eligible(
        kernel_op_id=kernel_op.kernel_op_id,
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
    )
    if not eligible:
        return ResolutionResult(
            status="DENIED",
            reason=f"No active binding for kernel '{kernel_op.kernel_op_id}'",
            denial_type="NO_BINDING",
        )

    # Step 6: Deterministic selection
    selected = select_deterministic_binding(eligible)
    if selected is None:
        return ResolutionResult(
            status="DENIED",
            reason="Multiple equally-eligible bindings — cannot determine",
            denial_type="AMBIGUOUS",
        )

    # Step 7: Provider resolution
    engine_module = ENGINE_MAP.get(selected.provider)    # module path
    adapter_class = extract_class_name(engine_module)     # class name from module
    if engine_module is None:
        return ResolutionResult(
            status="DENIED",
            reason=f"No ENGINE_MAP entry for provider '{selected.provider}'",
            denial_type="UNAVAILABLE",
        )

    # Step 8: Build immutable FrozenBindingIdentity
    resolution = FrozenBindingIdentity(
        trace_id=context.trace_id,
        request_id=context.request_id,
        task_id=context.task_id,
        capability_id=capability.capability_id,
        kernel_op_id=kernel_op.kernel_op_id,
        binding_id=selected.binding_id,
        provider=selected.provider,
        account_id=selected.account_id,
        engine_module=engine_module,
        adapter_class=adapter_class,
        effective_risk=effective_risk.effective_risk,      # float 0.0–1.0
        effective_mutation=effective_risk.mutation,        # R/W/D/IRREVERSIBLE
        capability_version=capability.version,
        kernel_version=kernel_op.version,
        binding_version=selected.version,
        adapter_version=get_adapter_version(engine_module),
        registry_version=registry.version,
        capability_authorized=True,
        binding_eligible_reason=selected.selection_reason,
        eligible_binding_count=len(eligible),
        rejection_reasons=[r.reason for r in eligible if r.binding_id != selected.binding_id],
        resolved_at=utc_now(),
        resolved_by="S5_ProviderResolution",
    )

    return ResolutionResult(status="RESOLVED", resolution=resolution)
```

---

### B-3: Unregistered Write-Capable Kernel Operations

**Historical Failure**: 7 kernel operations with write/delete capabilities had no corresponding capability registration. This meant they could be invoked through alternate paths without authorization.

**Fix — Invariant: Every Executable Kernel Has a Capability**:

```python
# Invariant enforced at startup + CI
def verify_kernel_capability_coverage(kernels: list[KernelOperation], capabilities: list[CapabilityMetadata]) -> None:
    """Every kernel with mutation in (W, D, IRREVERSIBLE) MUST have a registered capability."""
    registered_capability_kernels = {
        c.kernel_op_id for c in capabilities
    }

    violations = []
    for kernel in kernels:
        if kernel.mutation in ("W", "D", "IRREVERSIBLE"):
            if kernel.kernel_op_id not in registered_capability_kernels:
                violations.append(f"Write kernel '{kernel.kernel_op_id}' has no capability registration")

    if violations:
        raise RuntimeError(
            "UNREGISTERED WRITE KERNELS — Authorization bypass risk:\n"
            + "\n".join(violations)
        )


# CI enforcement
# grep -c 'mutation.*(W\|D\|IRREVERSIBLE)' db/kernel_ops.yaml | must equal count of write-capable capabilities
```

**Rules**:
1. Every kernel with `mutation in (W, D, IRREVERSIBLE)` MUST have a registered capability
2. Read-only kernels (R) may exist without a user-facing capability (internal operations)
3. CI checks this invariant at startup — build fails if violated
4. No kernel can be "discovered" at runtime without going through capability resolution

---

### B-4: Kernel Without Executable Binding

**Historical Failure**: A kernel operation could exist in the registry with no active binding. The system would resolve the kernel but have nowhere to execute it.

**Fix — Invariant: Every Executable Kernel Has an Active Binding**:

```python
def verify_kernel_binding_coverage(
    kernels: list[KernelOperation],
    bindings: list[BindingRow],
) -> list[str]:
    """Every executable kernel MUST have at least one active binding."""
    active_binding_kernels = {b.kernel_op_id for b in bindings if b.is_active}

    violations = []
    for kernel in kernels:
        if kernel.mutation in ("W", "D", "IRREVERSIBLE"):
            if kernel.kernel_op_id not in active_binding_kernels:
                violations.append(
                    f"Kernel '{kernel.kernel_op_id}' (mutation={kernel.mutation}) "
                    f"has no active binding"
                )

    return violations
```

**Rules**:
1. Every executable kernel (W, D, IRREVERSIBLE) MUST have ≥ 1 active binding
2. A kernel with zero active bindings is ineligible for resolution → DENY / NO_BINDING
3. This is checked at startup AND at S5
4. CI verifies this invariant

---

### B-5: Deterministic Binding Selection (Multiple Bindings)

**Historical Failure**: When multiple bindings matched a kernel operation, selection was nondeterministic — depending on dict ordering, DB row order, or timing.

**Fix — Deterministic Selection Algorithm**:

```python
@dataclass(frozen=True)
class BindingEligibility:
    """A binding evaluated for selection."""
    binding: BindingRow
    is_eligible: bool
    rejection_reasons: list[str] = field(default_factory=list)
    selection_score: int = 0           # Higher = preferred
    selection_reason: str = ""


def select_deterministic_binding(eligible: list[BindingEligibility]) -> BindingRow | None:
    """Select exactly ONE binding from eligible candidates.

    Algorithm (in order of precedence):
    1. Filter to only eligible bindings
    2. If zero → return None (DENY / NO_BINDING)
    3. If one → return it
    4. If multiple → apply deterministic tiebreaker:
       a. Highest priority (integer, lower = higher priority)
       b. Healthiest provider (from health check cache)
       c. Most recently verified binding
       d. Lexicographically smallest binding_id (guaranteed deterministic)
    5. If still tied after all criteria → return None (DENY / AMBIGUOUS)

    This algorithm ALWAYS produces the same result for the same input.
    """
    eligible_bindings = [e for e in eligible if e.is_eligible]

    if len(eligible_bindings) == 0:
        return None  # DENY / NO_BINDING

    if len(eligible_bindings) == 1:
        return eligible_bindings[0].binding

    # Sort by: priority ASC, health_score DESC, verified_at DESC, binding_id ASC
    def sort_key(e: BindingEligibility) -> tuple:
        return (
            e.binding.priority,                    # Lower priority number = higher priority
            -e.binding.provider_health_score,       # Higher health = better
            -(e.binding.last_verified_at or 0),     # More recent = better
            e.binding.binding_id,                   # Lexicographic tiebreaker
        )

    sorted_bindings = sorted(eligible_bindings, key=sort_key)

    # Check if top two are identical on all criteria (extremely unlikely with UUID tiebreaker)
    if len(sorted_bindings) >= 2:
        if sort_key(sorted_bindings[0]) == sort_key(sorted_bindings[1]):
            return None  # True tie — cannot determine

    return sorted_bindings[0].binding
```

---

### B-6: Single Risk Authority

**Historical Failure**: `capabilities.risk_floor` and `kernel_ops.risk_floor` drifted independently. The system used whichever was higher, but the "authoritative" source was unclear — making audits and reviews impossible.

**Fix — Single Derivation, Recorded Authority**:

```python
@dataclass(frozen=True)
class EffectiveRisk:
    """Derived ONCE at S5. Immutable. Recorded authority.

    All risk values are float 0.0–1.0 (NOT integer 0-100).
    This matches FrozenBindingIdentity.effective_risk type.
    """

    mutation: str           # From kernel_op — always authoritative for mutation type
    effective_risk: float   # max() of all sources — float 0.0–1.0, never int
    primary_source: str     # "capability" | "kernel" | "tag" | "combined"
    capability_risk: float  # Source value (0.0–1.0)
    kernel_risk: float      # Source value (0.0–1.0)
    tag_implied_risk: float # Source value (0.0–1.0)
    derivation: str         # "max(0.3, 0.5, 0.1) = 0.5 from kernel"
```

**Rules**:
1. `kernel_op.mutation` is the authoritative mutation type (W/D/IRREVERSIBLE)
2. `effective_risk = max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)` — risk only goes up
3. Risk only goes up — never down, never average, never negotiate
4. The `derivation` field is an auditable string showing the calculation
5. `primary_source` records which source was dominant
6. This is computed ONCE at S5 and stored in FrozenBindingIdentity.effective_risk

---

### B-7: No Alternate Dispatch Paths

**Historical Failure**: The engine had alternate dispatch paths that could bypass the canonical resolution. Some code paths called adapters directly, others used cached bindings, others used hardcoded provider mappings.

**Fix — CI-Enforced Canonical Path**:

```python
# CI check: verify ONLY the canonical resolver is called
# No adapter access from outside control/stages/s05_provider.py

# In engine/ — must be IMPOSSIBLE to call adapters without FrozenBindingIdentity
class StepExecutor:
    async def execute_step(self, step: PlanStep) -> KernelResult:
        # step MUST carry a FrozenBindingIdentity
        assert step.resolution is not None, "Step missing FrozenBindingIdentity — alternate dispatch?"

        # Adapter is loaded ONLY from FrozenBindingIdentity.adapter_class
        adapter = load_adapter(step.resolution.adapter_class)

        # Kernel op is from FrozenBindingIdentity.kernel_op_id
        result = await adapter.call(
            kernel_op_id=step.resolution.kernel_op_id,
            params=step.params,
            binding=load_binding(step.resolution.binding_id),
        )
        return result
```

**CI Enforcement Rules**:
```bash
# 1. No adapter import in engine/ except through FrozenBindingIdentity
grep -rn 'from engine.providers' src/engine/ --include='*.py'
# All imports must go through engine_module from FrozenBindingIdentity

# 2. No direct provider calls outside adapters
grep -rn 'httpx\|requests' src/engine/ --include='*.py'
# Only allowed in src/engine/providers/

# 3. No kernel_op_id hardcoding outside registry
grep -rn 'ghl\.\|notion\.\|airtable\.' src/engine/ --include='*.py'
# Must come from FrozenBindingIdentity or registry
```

---

## 3. Structural Inconsistencies

### I-1: Capability Naming vs Kernel Naming

**Problem**: Human-facing capability IDs (`create_contact`) and executable `kernel_op_id`s (`ghl.create_contact`) are sometimes treated interchangeably. They are NOT the same thing.

**Fix — Clear Separation**:

| Aspect | Capability ID | Kernel Op ID |
|--------|--------------|--------------|
| **Format** | `verb_noun` (e.g., `create_contact`) | `provider.operation` (e.g., `ghl.create_contact`) |
| **Audience** | Human-readable, user-facing | Machine-executable, provider-specific |
| **Scope** | One capability → one or more kernels | One kernel → one adapter method |
| **Stability** | Changes with UX | Changes with provider API |
| **Source** | YAML: `capabilities:` | YAML: `kernel_operations:` |

**Rule**: Capability IDs and kernel_op_ids are NEVER interchangeable. The capability → kernel mapping is 1:1 or 1:N (one capability maps to exactly one kernel in M0, but the structure allows 1:N for M1).

---

### I-2: kernel_meta.py vs DB Naming

**Problem**: Historical naming mismatches between `kernel_meta.py` (Python module names) and database records created runtime ambiguity.

**Fix — Single Naming Authority**:

```python
# The ONLY authoritative source for kernel_op_id naming is:
# Provider Package → generates → kernel_ops table + registry

# kernel_meta.py (or any Python module) MUST match the Provider Package exactly:
# kernel_meta.kernel_op_id == db.kernel_ops.kernel_op_id == registry.kernel_op_id

# CI check: load Provider Package, load DB, load registry — all must match
```

---

### I-3: Registry vs Database Authority

**Problem**: YAML-generated registry, DB records, adapter KERNEL_MAP, and provider artifacts each claimed to be the source of truth.

**Fix — Clear Source-of-Truth Hierarchy**:

```
┌─────────────────────────────────────────────────────┐
│  SOURCE OF TRUTH: kernel_definitions.yaml            │
│  (single file that generates everything)             │
└───────────────────────┬─────────────────────────────┘
                        │ generates
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
  registry/         db/kernel_ops    adapter KERNEL_MAP
  (in-memory)       (persistent)     (provider-side)
        │               │               │
        └───────────────┼───────────────┘
                        │ must match
                ┌───────▼────────┐
                │ CI verification │
                │ (grep + Python) │
                └────────────────┘
```

**Rules**:
1. `kernel_definitions.yaml` is the ONLY source of truth
2. Registry, DB, and adapter KERNEL_MAP are generated FROM YAML
3. CI verifies all three are in sync on every commit
4. No manual edits to DB or adapter maps — they are regenerated

---

### I-4: Binding Selection vs Provider Selection

**Problem**: Binding selection (which binding to use) and provider selection (which provider to call) were independent mechanisms that could conflict.

**Fix — Unified Resolution**:

```python
# Binding selection AND provider selection happen in ONE function:
# resolve() at S5 produces FrozenBindingIdentity with ALL of:
#   - binding_id (selected binding)
#   - provider (from binding)
#   - engine_module (from ENGINE_MAP via provider)
#   - account_id (from binding)

# There is NO separate "provider selection" step.
# Provider is always derived from the selected binding.
```

---

### I-5: Adapter Capability List vs Registry

**Problem**: `adapter.capabilities()` returned a list from the adapter, but the registry had its own capability/kernel records. These could drift.

**Fix — Registry is Authoritative, Adapter Reports Capabilities**:

```python
class BaseAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Report which kernel_op_ids this adapter CAN execute.
        This is a SUBSET of the registry's kernel_ops for this provider.
        Used for health checks — if adapter reports fewer ops than registry,
        those ops are marked DEGRADED (not removed).
        """
        pass


# CI check: adapter.capabilities() ⊆ registry.kernels_for(provider)
# If adapter reports fewer, mark missing as DEGRADED, not removed
```

---

## 4. Future-Scale Gaps

### G-1: Workspace/Tenant-Aware Resolution

**Problem**: Same capability may be enabled in Workspace A and disabled in Workspace B.

**Design**:
```python
@dataclass(frozen=True)
class WorkspaceCapabilityState:
    capability_id: str
    workspace_id: str
    tenant_id: str
    state: Literal["implemented", "enabled", "disabled", "retired"]
    enabled_at: str | None
    disabled_at: str | None
    reason: str | None


# Resolution eligibility check (added at S5):
def is_capability_enabled_for_workspace(
    capability_id: str,
    workspace_id: str,
    tenant_id: str,
) -> bool:
    """Check if capability is enabled for this workspace+tenant combination."""
    state = db.get_workspace_capability(capability_id, workspace_id, tenant_id)
    return state is not None and state.state == "enabled"
```

---

### G-2: Policy-Aware Binding Selection

**Problem**: Resolver selects bindings based on availability, not on whether the user/project/workspace policy permits that provider/account.

**Design**:
```python
@dataclass(frozen=True)
class BindingPolicy:
    """Policy constraints for binding selection."""
    allowed_providers: list[str]       # From workspace policy
    allowed_accounts: list[str]        # From user permissions
    blocked_providers: list[str]       # Explicit blocks
    blocked_accounts: list[str]        # Explicit blocks
    requires_approval: list[str]       # Providers requiring confirmation


def filter_bindings_by_policy(
    bindings: list[BindingEligibility],
    policy: BindingPolicy,
) -> list[BindingEligibility]:
    """Filter bindings through workspace/user policy."""
    result = []
    for eligibility in bindings:
        b = eligibility.binding
        reasons = list(eligibility.rejection_reasons)

        if b.provider in policy.blocked_providers:
            reasons.append(f"Provider '{b.provider}' blocked by policy")
        if b.account_id in policy.blocked_accounts:
            reasons.append(f"Account '{b.account_id}' blocked by policy")
        if b.provider not in policy.allowed_providers and policy.allowed_providers:
            reasons.append(f"Provider '{b.provider}' not in allowed list")

        result.append(BindingEligibility(
            binding=b,
            is_eligible=len(reasons) == 0,
            rejection_reasons=reasons,
        ))
    return result
```

---

### G-3: Binding Version Frozen Into Plan

**Problem**: Changing a binding after planning could alter execution silently.

**Design**:
```python
@dataclass(frozen=True)
class Plan:
    plan_id: str
    execution_id: str
    resolution: FrozenBindingIdentity   # Frozen at S5 — includes binding_version
    steps: list[PlanStep]
    # ... other fields

# Rule: If binding is modified after plan creation, the plan still uses
# the frozen binding_version from FrozenBindingIdentity.
# At S11 (Validate Plan), verify binding.version == resolution.binding_version
# If mismatch → DENY (binding was modified after planning)
```

---

### G-4: Provider Drift Detection

**Problem**: A verified binding can become stale even when the provider is reachable (endpoint changed, schema changed, auth method changed).

**Design**:
```python
@dataclass(frozen=True)
class BindingVerification:
    binding_id: str
    verified_at: str          # ISO 8601 UTC
    endpoint_reachable: bool
    schema_compatible: bool   # API response matches expected schema
    auth_valid: bool
    drift_detected: bool      # True if ANY check degraded since last verification

    @property
    def is_stale(self) -> bool:
        """Binding is stale if > 24h old or drift detected."""
        age_hours = (utc_now_ts() - iso_to_ts(self.verified_at)) / 3600
        return age_hours > 24 or self.drift_detected


# Health check (called periodically, not at resolution time):
async def verify_binding(binding: BindingRow) -> BindingVerification:
    """Full verification of binding health — not just reachability."""
    adapter = load_adapter(ENGINE_MAP[binding.provider])
    health = await adapter.health_check()

    return BindingVerification(
        binding_id=binding.binding_id,
        verified_at=utc_now(),
        endpoint_reachable=health.endpoint_reachable,
        schema_compatible=health.schema_compatible,
        auth_valid=health.auth_valid,
        drift_detected=(
            not health.schema_compatible
            or not health.auth_valid
            or binding.last_endpoint != health.current_endpoint
        ),
    )
```

---

### G-5: Dynamic Capability Versioning

**Problem**: Enabling/disabling/replacing a capability must not alter already-created plans.

**Design**:
```python
@dataclass(frozen=True)
class CapabilityVersion:
    """Versioned capability — changes don't affect existing plans."""
    capability_id: str
    version: str              # Semver: "1.2.3"
    state: CapabilityState    # implemented → enabled → disabled → retired
    effective_from: str       # ISO 8601 UTC — when this version became active
    effective_until: str | None  # ISO 8601 UTC — None = current
    replaced_by: str | None   # Next version's capability_id if replaced


# FrozenBindingIdentity captures capability_version at S5.
# If capability is later disabled, existing plans still reference
# the version that was active at resolution time.
# New executions see the updated state.
```

---

### G-6: Resolution Evidence

**Problem**: No record of why a capability, kernel, and binding were selected/rejected — making debugging impossible.

**Design**:
```python
@dataclass(frozen=True)
class ResolutionEvidence:
    """Complete evidence trail for a resolution decision."""
    trace_id: str

    # Capability resolution
    capability_candidates: list[str]       # All matching capabilities
    capability_selected: str               # The one chosen
    capability_rejection_reasons: dict[str, str]  # Why others were rejected

    # Kernel resolution
    kernel_candidates: list[str]           # All kernels for this capability
    kernel_selected: str                   # The one chosen

    # Binding resolution
    binding_candidates: list[str]          # All eligible bindings
    binding_selected: str                  # The one chosen
    binding_rejection_reasons: dict[str, str]
    binding_selection_algorithm: str       # "priority_then_health_then_recency"

    # Final
    resolution_id: str                     # FrozenBindingIdentity ID
    outcome: Literal["RESOLVED", "DENIED"]
    denial_type: str | None = None


# Emitted to execution_events table at S5 for full traceability.
```

---

## 5. Resolution State Machine

Capability lifecycle states:

```
implemented → enabled → disabled → retired
                ↑           │
                │           ↓
                └──── deleted (only if no active bindings)
```

| State | Meaning | Can Execute? | Transitions To |
|-------|---------|-------------|----------------|
| `implemented` | Defined but not yet active | No | enabled |
| `enabled` | Active and resolvable | Yes | disabled, retired |
| `disabled` | Temporarily inactive | No | enabled, retired |
| `retired` | Permanently inactive | No | (terminal) |

**Rules**:
1. `enabled` is the ONLY state that allows resolution
2. Transition from `enabled` → `disabled` does NOT affect existing plans (plans reference version, not live state)
3. Transition from `implemented` → `retired` requires explicit confirmation (destructive)
4. `retired` is terminal — cannot re-enable

---

## 6. Implementation Rules

### Rule 1: FrozenBindingIdentity is the Only Output of S5

```python
# CORRECT — S5 produces FrozenBindingIdentity
resolution = resolve(context, intent)
if resolution.status == "RESOLVED":
    plan = build_plan(resolution)  # Uses resolution, not re-resolving

# WRONG — S6 re-resolving
profile = TaskProfile()  # Should accept FrozenBindingIdentity, not re-lookup
```

### Rule 2: S6-S12 Never Re-Resolve

Every stage from S6 to S12 receives FrozenBindingIdentity as input. No stage independently looks up capabilities, kernels, or bindings.

### Rule 3: Fail-Closed at Every Step

If ANY resolution step fails, the result is `DENIED` with a specific denial type. Execution never continues with partial metadata.

### Rule 4: One Risk Derivation

`EffectiveRisk` is computed once at S5. S6 reads `FrozenBindingIdentity.effective_risk`. S8 validates against it. S10 uses it for confirmation decisions. No stage recalculates risk.

### Rule 5: No Alternate Dispatch

```python
# CORRECT — canonical path
adapter = load_adapter(resolution.adapter_class)  # from FrozenBindingIdentity.adapter_class
result = await adapter.call(resolution.kernel_op_id, params, binding)

# WRONG — direct dispatch (impossible in canonical architecture)
result = await ghl_client.search_contacts(params)  # CI will flag this
```

### Rule 6: Binding Version in Plan

```python
# At S11, validate binding hasn't changed:
def validate_plan(plan: Plan) -> ValidationResult:
    # Validate against the canonical resolution from S5 — NO database lookup
    assert plan.resolution is not None, "Plan missing FrozenBindingIdentity"
    # binding_version in the plan IS the canonical version; no alternate source
    # If binding has changed, S5 will detect it at re-resolution time
    return ValidationResult(is_valid=True, errors=[])
```

---

## 7. CI Enforcement

```bash
#!/bin/bash
# CI checks for RESOLVE layer invariants

set -e

echo "=== RESOLVE Layer CI Checks ==="

# 1. Every write kernel has a capability
python -c "
from registry.yaml_loader import load_kernel_definitions, load_capabilities
kernels = load_kernel_definitions()
caps = load_capabilities()
cap_kernels = {c.kernel_op_id for c in caps}
violations = [k.kernel_op_id for k in kernels if k.mutation in ('W','D','IRREVERSIBLE') and k.kernel_op_id not in cap_kernels]
if violations:
    print(f'FAIL: Write kernels without capabilities: {violations}')
    exit(1)
print('OK: All write kernels have capabilities')
"

# 2. Every executable kernel has an active binding
python -c "
from registry.yaml_loader import load_kernel_definitions
from db.connection import get_connection
kernels = load_kernel_definitions()
conn = get_connection()
active_bindings = {row[0] for row in conn.execute('SELECT kernel_op_id FROM bindings WHERE is_active=1')}
violations = [k.kernel_op_id for k in kernels if k.mutation in ('W','D','IRREVERSIBLE') and k.kernel_op_id not in active_bindings]
if violations:
    print(f'FAIL: Write kernels without active bindings: {violations}')
    exit(1)
print('OK: All write kernels have active bindings')
"

# 3. ENGINE_MAP covers all providers
python -c "
from registry.yaml_loader import load_kernel_definitions
from registry.engine_map import ENGINE_MAP
kernels = load_kernel_definitions()
prefixes = {k.kernel_op_id.split('.')[0] for k in kernels}
missing = prefixes - set(ENGINE_MAP.keys())
if missing:
    print(f'FAIL: Missing ENGINE_MAP entries for: {missing}')
    exit(1)
print('OK: ENGINE_MAP covers all provider prefixes')
"

# 4. No GHL fallback in ENGINE_MAP
python -c "
from registry.engine_map import ENGINE_MAP
if 'ghl' in ENGINE_MAP and 'fallback' in str(ENGINE_MAP['ghl']).lower():
    print('FAIL: GHL fallback detected in ENGINE_MAP')
    exit(1)
print('OK: No GHL fallback in ENGINE_MAP')
"

# 5. No float in risk/billing code
! grep -rn 'float\|Decimal' src/control/stages/s05_provider.py --include='*.py'
! grep -rn 'float\|Decimal' src/shared/risk.py --include='*.py'
! grep -rn 'float\|Decimal' src/billing/ --include='*.py'
echo "OK: No float arithmetic in risk/billing"

# 6. FrozenBindingIdentity is frozen
grep -q 'frozen=True' src/control/stages/s05_provider.py || {
    echo "FAIL: FrozenBindingIdentity is not frozen"
    exit 1
}
echo "OK: FrozenBindingIdentity is frozen"

# 7. No adapter imports in engine/ outside canonical path
ADAPTER_IMPORTS=$(grep -rn 'from engine.providers' src/engine/ --include='*.py' | grep -v 'test' | wc -l)
if [ "$ADAPTER_IMPORTS" -gt 0 ]; then
    echo "FAIL: Direct adapter imports in engine/ (found $ADAPTER_IMPORTS)"
    exit 1
fi
echo "OK: No direct adapter imports in engine/"

echo ""
echo "All RESOLVE layer CI checks passed!"
```

---

## 8. Quick Reference

### Resolution Flow (S5)

```
1. Intent → Capability        (registry lookup)
2. Capability → Authorized?   (user permission check)
3. Capability → Kernel Op     (capability-to-kernel mapping)
4. Kernel Op → Risk           (single derivation: max of all sources)
5. Kernel Op → Eligible Bindings (active, workspace-enabled, not stale)
6. Eligible Bindings → Deterministic Selection (priority → health → recency → UUID)
7. Binding → Provider         (from binding record)
8. Provider → Adapter Path    (from ENGINE_MAP)
9. All → FrozenBindingIdentity   (frozen, immutable)
```

### Denial Types

| Type | Meaning | S7 Route |
|------|---------|----------|
| `UNRESOLVED` | No capability matches intent | CLARIFY |
| `UNAUTHORIZED` | User lacks capability | DENY |
| `NO_BINDING` | No active binding for kernel | DENY |
| `AMBIGUOUS` | Multiple equally-eligible bindings | CLARIFY |
| `UNAVAILABLE` | Provider not in ENGINE_MAP | DENY |

### What S6-S12 Must NOT Do

| Action | Why |
|--------|-----|
| Re-resolve capability | FrozenBindingIdentity is the single source |
| Re-calculate risk | Risk is frozen at S5 |
| Re-select binding | Binding is frozen at S5 |
| Call adapter directly | Must go through FrozenBindingIdentity.engine_module/adapter_class |
| Modify FrozenBindingIdentity | It is frozen |

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [MASTER_ARCHITECTURE.md](../MASTER_ARCHITECTURE.md) | System architecture, layer model |
| [PIPELINE_STAGES.md](../PIPELINE_STAGES.md) | S3 (Capability), S5 (Provider), S6 (Task Profile) stages |
| [DATA_CONTRACTS.md](../DATA_CONTRACTS.md) | CapabilityMetadata, BindingRow, FrozenBindingIdentity |
| [PROVIDER_ADAPTERS.md](../PROVIDER_ADAPTERS.md) | Adapter contract, ENGINE_MAP |
| [MUTATION_SAFETY.md](../MUTATION_SAFETY.md) | Mutation types, retry rules |
| [RELIABILITY.md](../RELIABILITY.md) | 5-layer guard, circuit breakers |
| [TRACING_AND_CONCURRENCY.md](../TRACING_AND_CONCURRENCY.md) | Trace identity, event ledger |
| [SECURITY.md](../SECURITY.md) | Authorization, fail-closed |
| [FORENSIC_FINDINGS.md](../FORENSIC_FINDINGS.md) | F-001 through F-016 — historical failures |