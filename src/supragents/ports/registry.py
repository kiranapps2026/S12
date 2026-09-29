"""Capability registry port: the only source of capability, binding and risk data."""
from __future__ import annotations

from typing import Protocol

from supragents.contracts.registry import (
    BindingRow,
    CapabilityMetadata,
    KernelOperation,
    RegistryVersions,
)


class CapabilityRegistry(Protocol):
    async def capabilities_for_intent(
        self, tenant_id: str, intent: str
    ) -> tuple[CapabilityMetadata, ...]: ...

    async def bindings_for(self, tenant_id: str, capability_id: str) -> tuple[BindingRow, ...]: ...

    async def kernel_operation(self, kernel_op_id: str) -> KernelOperation | None: ...

    async def versions(self) -> RegistryVersions: ...
