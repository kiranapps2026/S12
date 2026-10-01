"""LiveAuthorizationCheck (gate C23, C30, C35; rulings CONF-030, CONF-031): re-evaluate, against LIVE state, whether a
run may still cause a new side effect.

It reuses S8's deterministic check functions (the logic exists once), never writes a SafetyResult, never touches
PipelineState and writes no row. Budget, circuit breaker and mutation safety are not re-checked here (C3, the guard
and admission enforce them per step); a provider outage is never a revocation (C35, CONF-032).

Order: kill switch → the S8 live checks (user, tenant, connection, grant, resource scope) → capability retired
(``truth_state`` DEPRECATED) → the frozen binding's row (missing or inactive: ``binding_invalid``) → the connection's
credential (``CredentialProvider.credential_valid`` not True: ``credential_invalid``). Fail closed: anything that
cannot be read is ``authorization_revoked``. The name of the failing check is logged, never stored (CONF-031).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from adapters.postgres.database import Database
from contracts.execution_states import StepTerminalReason as T
from contracts.step_execution import Revoked
from engine.control_plane.scope import RunScopeFactory
from engine.stages.s8_safety_gate import checks

logger = logging.getLogger(__name__)

_LIVE_CHECKS = (checks.check_user_active, checks.check_tenant_active, checks.check_connection_active,
                checks.check_capability_granted, checks.check_resource_scope)
_RETIRED = "DEPRECATED"


def _revoked(reason: str, check: str) -> Revoked:
    logger.warning("live authorization revoked", extra={"live_check": check, "reason": reason})
    return Revoked(reason)


def _evaluate(context, binding, scope) -> Revoked | None:
    try:
        if scope.policy.kill_switch_engaged is not False:
            return _revoked(T.KILL_SWITCH_ENGAGED, "kill_switch")
    except Exception:  # noqa: BLE001 — fail closed
        return _revoked(T.KILL_SWITCH_ENGAGED, "kill_switch_unreadable")
    for check in _LIVE_CHECKS:
        try:
            result = check(context, None, binding, scope.s8)
        except Exception:  # noqa: BLE001 — fail closed
            return _revoked(T.AUTHORIZATION_REVOKED, f"{check.__name__}_unreadable")
        if result.passed is not True:
            return _revoked(T.AUTHORIZATION_REVOKED, check.__name__)
    return None


class PostgresLiveAuthorization:
    def __init__(self, scopes: RunScopeFactory, *, database: Database, credentials) -> None:
        self._scopes, self._database, self._credentials = scopes, database, credentials

    async def check(self, *, tenant_id: str, workspace_id: str, user_id: str, connection_id: str | None,
                    binding) -> Revoked | None:
        try:
            scope = await self._scopes.for_run(tenant_id, workspace_id)
        except Exception:  # noqa: BLE001 — fail closed
            return _revoked(T.AUTHORIZATION_REVOKED, "scope_unreadable")
        context = SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id,
                                  connection_id=connection_id)
        revoked = await asyncio.to_thread(_evaluate, context, binding, scope)
        if revoked is not None:
            return revoked
        try:
            async with self._database.tenant_transaction(tenant_id) as conn:
                truth = await conn.fetchval("SELECT truth_state FROM capabilities WHERE capability_id = $1",
                                            binding.capability_id)
                active = await conn.fetchval("SELECT is_active FROM bindings WHERE binding_id = $1",
                                             binding.binding_id)
        except Exception:  # noqa: BLE001 — fail closed
            return _revoked(T.AUTHORIZATION_REVOKED, "registry_unreadable")
        if truth is None or truth == _RETIRED:
            return _revoked(T.AUTHORIZATION_REVOKED, "capability_retired")
        if active is not True:
            return _revoked(T.BINDING_INVALID, "binding_inactive")
        try:
            valid = await self._credentials.credential_valid(tenant_id, connection_id)
        except Exception:  # noqa: BLE001 — fail closed
            return _revoked(T.AUTHORIZATION_REVOKED, "credential_unreadable")
        if valid is not True:
            return _revoked(T.CREDENTIAL_INVALID, "credential_valid")
        return None
