"""LiveAuthorizationCheck (gate C23): re-evaluate, against LIVE state, whether a run may still cause a
new side effect. It reuses S8's deterministic check functions (the logic exists once), never writes a
SafetyResult and never touches PipelineState. Budget, circuit breaker and mutation safety are NOT
re-checked here (they are enforced per step by C3, the guard and admission).

Fail closed: anything that cannot be read is REVOKED("authorization_revoked")."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from contracts.errors import DependencyUnavailable  # noqa: F401
from contracts.step_execution import Revoked
from engine.control_plane.scope import RunScopeFactory
from engine.stages.s8_safety_gate import checks

logger = logging.getLogger(__name__)

KILL_SWITCH = "kill_switch_engaged"
REVOKED = "authorization_revoked"
_LIVE_CHECKS = (checks.check_user_active, checks.check_tenant_active, checks.check_connection_active,
                checks.check_capability_granted, checks.check_resource_scope)


def _evaluate(context, binding, scope) -> Revoked | None:
    try:
        if scope.policy.kill_switch_engaged is not False:
            return Revoked(KILL_SWITCH)
    except Exception:  # noqa: BLE001
        return Revoked(KILL_SWITCH)
    for check in _LIVE_CHECKS:
        try:
            result = check(context, None, binding, scope.s8)
        except Exception:  # noqa: BLE001
            return Revoked(REVOKED)
        if result.passed is not True:
            return Revoked(REVOKED)
    return None


class PostgresLiveAuthorization:
    def __init__(self, scopes: RunScopeFactory) -> None:
        self._scopes = scopes

    async def check(self, *, tenant_id: str, workspace_id: str, user_id: str, connection_id: str | None,
                    binding) -> Revoked | None:
        try:
            scope = await self._scopes.for_run(tenant_id, workspace_id)
        except Exception:  # noqa: BLE001 — fail closed
            logger.warning("live authorization: scope unreadable")
            return Revoked(REVOKED)
        context = SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id,
                                  connection_id=connection_id)
        return await asyncio.to_thread(_evaluate, context, binding, scope)
