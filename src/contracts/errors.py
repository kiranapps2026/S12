"""
Error hierarchy — canonical error types for SuprAgents.

Source: FINAL_ARCHITECTURE.md §19, DATA_CONTRACTS.md §9
"""

from __future__ import annotations


class SuprAgentsError(Exception):
    """Base exception for all SuprAgents errors."""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


# --- Infrastructure Errors (Transient) ---

class ProviderTimeoutError(SuprAgentsError):
    """Provider call exceeded timeout."""
    def __init__(self, message: str, provider: str = "", timeout_seconds: float = 0.0) -> None:
        super().__init__(message, code="PROVIDER_TIMEOUT")
        self.provider = provider
        self.timeout_seconds = timeout_seconds


class ProviderConnectionError(SuprAgentsError):
    """Cannot connect to provider."""
    def __init__(self, message: str, provider: str = "") -> None:
        super().__init__(message, code="PROVIDER_CONNECTION")
        self.provider = provider


class ProviderRateLimitError(SuprAgentsError):
    """Provider rate limit exceeded."""
    def __init__(self, message: str, provider: str = "", retry_after: float = 0.0) -> None:
        super().__init__(message, code="PROVIDER_RATE_LIMIT")
        self.provider = provider
        self.retry_after = retry_after


# --- Authorization Errors (Permanent) ---

class AuthorizationError(SuprAgentsError):
    """Authorization check failed."""
    def __init__(self, message: str, check_name: str = "") -> None:
        super().__init__(message, code="AUTHORIZATION_DENIED")
        self.check_name = check_name


class TenantIsolationError(SuprAgentsError):
    """Cross-tenant access attempted."""
    def __init__(self, message: str, tenant_id: str = "", attempted_tenant: str = "") -> None:
        super().__init__(message, code="TENANT_ISOLATION")
        self.tenant_id = tenant_id
        self.attempted_tenant = attempted_tenant


# --- Contract Errors (Permanent) ---

class ContractViolationError(SuprAgentsError, ValueError):
    """PipelineState write contract violation (R-F).

    Raised when a stage writes to a field it doesn't own, overwrites a
    set field, or writes a value of the wrong type.
    Inherits from ValueError so existing try/except ValueError blocks still work.
    """
    def __init__(
        self,
        message: str,
        stage_id: str = "",
        field: str = "",
        expected_type: str = "",
        actual_type: str = "",
    ) -> None:
        super().__init__(message, code="CONTRACT_VIOLATION")
        self.stage_id = stage_id
        self.field = field
        self.expected_type = expected_type
        self.actual_type = actual_type


class CapabilityNotFoundError(SuprAgentsError):
    """No capability matches the intent."""
    def __init__(self, message: str, intent: str = "") -> None:
        super().__init__(message, code="CAPABILITY_NOT_FOUND")
        self.intent = intent


class BindingNotFoundError(SuprAgentsError):
    """No binding available for capability."""
    def __init__(self, message: str, capability_id: str = "") -> None:
        super().__init__(message, code="BINDING_NOT_FOUND")
        self.capability_id = capability_id


class WorkerNotAvailableError(SuprAgentsError):
    """No worker available for execution."""
    def __init__(self, message: str) -> None:
        super().__init__(message, code="WORKER_NOT_AVAILABLE")


# --- Execution Errors ---

class ExecutionError(SuprAgentsError):
    """Base execution error."""
    pass


class ResolutionError(ExecutionError):
    """Capability resolution failed."""
    def __init__(self, message: str, capability_id: str = "") -> None:
        super().__init__(message, code="RESOLUTION_ERROR")
        self.capability_id = capability_id


class LeaseAcquisitionError(ExecutionError):
    """Failed to acquire execution lease."""
    def __init__(self, message: str, execution_id: str = "") -> None:
        super().__init__(message, code="LEASE_ACQUISITION")
        self.execution_id = execution_id


class BudgetExceededError(ExecutionError):
    """Budget limit exceeded."""
    def __init__(self, message: str, budget_type: str = "", remaining: float = 0.0) -> None:
        super().__init__(message, code="BUDGET_EXCEEDED")
        self.budget_type = budget_type
        self.remaining = remaining


class StateTransitionError(SuprAgentsError):
    """Illegal state transition attempted."""
    def __init__(self, message: str, machine: str = "", from_state: str = "", to_state: str = "") -> None:
        super().__init__(message, code="ILLEGAL_STATE_TRANSITION")
        self.machine = machine
        self.from_state = from_state
        self.to_state = to_state


# --- Verification Errors ---

class VerificationError(SuprAgentsError):
    """Verification failed."""
    pass


class ProbeTimeoutError(VerificationError):
    """Verification probe timed out."""
    def __init__(self, message: str, layer: str = "", attempt: int = 0) -> None:
        super().__init__(message, code="PROBE_TIMEOUT")
        self.layer = layer
        self.attempt = attempt


class ContradictoryObservationError(VerificationError):
    """Provider state contradicts expected state."""
    def __init__(self, message: str, expected: str = "", actual: str = "") -> None:
        super().__init__(message, code="CONTRADICTORY_OBSERVATION")
        self.expected = expected
        self.actual = actual


# --- Safety Errors ---

class SafetyGateError(SuprAgentsError):
    """Safety gate check failed."""
    def __init__(self, message: str, check_name: str = "") -> None:
        super().__init__(message, code="SAFETY_GATE")
        self.check_name = check_name


class MutationNotAllowedError(SafetyGateError):
    """Mutation type not allowed for this context."""
    def __init__(self, message: str, mutation_type: str = "") -> None:
        super().__init__(message, check_name="mutation_safety")
        self.mutation_type = mutation_type


class ConfirmationRequiredError(SafetyGateError):
    """Confirmation required but not provided."""
    def __init__(self, message: str) -> None:
        super().__init__(message, check_name="confirmation")


class KillSwitchActiveError(SafetyGateError):
    """Kill switch is active."""
    def __init__(self, message: str, switch_id: str = "") -> None:
        super().__init__(message, check_name="kill_switch")
        self.switch_id = switch_id


class DependencyUnavailable(SuprAgentsError):
    """A required dependency (database, provider) could not answer. Callers fail closed."""
    def __init__(self, message: str) -> None:
        super().__init__(message, code="DEPENDENCY_UNAVAILABLE")
