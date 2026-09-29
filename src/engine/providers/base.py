"""
Provider Adapter Interface — base class and error classification.

Source: PROVIDER_ADAPTERS.md, DATA_CONTRACTS.md §12, FINAL_ARCHITECTURE.md §15

CRITICAL: Adapters must NEVER raise exceptions. All errors must be returned
as KernelResult(status="UNKNOWN", outcome=...) so the reliability guard
can decide how to handle them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any


class AdapterErrorType(StrEnum):
    """Error classification for provider adapter errors."""
    TRANSIENT = "transient"           # Retry with backoff
    PERMANENT = "permanent"           # Do not retry
    RATE_LIMIT = "rate_limit"         # Retry after delay
    AUTH_FAILURE = "auth_failure"     # Credential issue, alert
    UNKNOWN = "unknown"               # Cannot classify, probe required


class MutationType(StrEnum):
    """Mutation classification for provider operations."""
    READ = "read"                       # Safe to retry
    IDEMPOTENT_WRITE = "idempotent_write"  # Safe to retry
    DELETE = "delete"                   # Depends on idempotency semantics
    IRREVERSIBLE = "irreversible"       # Never retry


@dataclass(frozen=True)
class ProviderCapability:
    """A capability exposed by a provider adapter."""
    name: str
    description: str
    mutation_type: MutationType
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    parameters: dict[str, Any] = None  # type: ignore
    metadata: dict[str, str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class BaseProviderAdapter(ABC):
    """
    Base class for all provider adapters.

    CRITICAL CONTRACT:
    1. NEVER raise exceptions — return KernelResult with error information
    2. On timeout → return UNKNOWN, never raise
    3. On connection failure → return UNKNOWN, never raise
    4. On auth failure → return error with AUTH_FAILURE classification
    5. All side effects must be idempotent or tracked for UNKNOWN resolution
    """

    provider_name: str = "unknown"
    supported_capabilities: list[str] = []

    @abstractmethod
    async def execute(self, capability: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a capability with the given parameters.

        Args:
            capability: Name of the capability to execute
            params: Parameters for the capability
            context: Execution context (tenant_id, etc.)

        Returns:
            Result dictionary with at least:
                - status: SUCCESS, PARTIAL, FAILURE, UNKNOWN, NOT_EXECUTED
                - outcome: ExecutionOutcome value
                - data: Result payload (if SUCCESS)
                - error: Error message (if not SUCCESS)
        """
        ...

    @abstractmethod
    async def read_state(self, capability: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """
        Read current state for a capability (for verification/probing).

        This is used by S13 verification to independently observe
        provider state. Adapters MUST implement this for probe-able
        capabilities.

        Args:
            capability: Name of the capability to read state for
            params: Parameters identifying the resource
            context: Execution context

        Returns:
            Current state dictionary
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check provider health.

        Returns:
            Dict with 'healthy' (bool), 'latency_ms' (float), 'details' (dict)
        """
        ...

    @abstractmethod
    async def get_capabilities(self) -> list[ProviderCapability]:
        """
        List capabilities exposed by this adapter.

        Returns:
            List of ProviderCapability objects
        """
        ...
