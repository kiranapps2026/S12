"""Per-run dependencies that depend on the tenant (RLS, live kill switch, policy versions)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.kernel_policy import KernelPolicy, PolicyVersions
from engine.stages.s8_safety_gate.dependencies import S8Dependencies


@dataclass(frozen=True)
class RunScope:
    """Everything S5/S7/S8 read that is specific to one tenant and is read fresh per run."""
    policy: KernelPolicy
    s8: S8Dependencies
    policy_versions: PolicyVersions


class RunScopeFactory(Protocol):
    async def for_run(self, tenant_id: str, workspace_id: str) -> RunScope:
        """Build the scope for one run. Raise DependencyUnavailable if it cannot be read."""
