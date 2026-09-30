"""Live reads for worker selection (gate §8 step 2, C39; WORKER_LIFECYCLE §13; I-019).

``candidates`` returns the tenant's ACTIVE workers as ``WorkerCandidate`` with every time as database epoch seconds;
``database_now`` is the ``now`` the filters compare them with. ``is_workspace_admin`` reads the admin bypass live.
``required_runtime_types`` reads the binding row's runtime list once, at S12 entry (C39 17c): the frozen S0–S11
binding reader cannot be extended, and this module is the one adapter allowed to read runtime types (RD-9;
record CONF-019). Malformed JSON is passed through as found, so the filters remove the worker (fail closed).
"""
from __future__ import annotations

import json

from adapters.postgres.admin import ADMIN_ROLES
from adapters.postgres.database import Database
from contracts.worker import WorkerStatus
from engine.stages.s12_execute.eligibility import WorkerCandidate

_CANDIDATES = (
    "SELECT worker_id, workspace_id, capacity, current_load,"
    " date_part('epoch', paused_until) AS paused_until,"
    " date_part('epoch', scheduled_activation_at) AS scheduled_activation_at,"
    " assigned_user_id, capability_profile, settings, runtime_type"
    " FROM workers WHERE tenant_id = $1 AND state = $2 ORDER BY worker_id")
_NOW = "SELECT date_part('epoch', now())"
_IS_ADMIN = (
    "SELECT EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.user_id = m.user_id AND u.tenant_id = m.tenant_id"
    " WHERE m.tenant_id = $1 AND m.workspace_id = $2 AND m.user_id = $3 AND m.role = ANY($4::text[])"
    " AND m.is_active AND m.revoked_at IS NULL AND u.status = 'active')")
_REQUIRED_RUNTIME_TYPES = "SELECT required_runtime_types FROM bindings WHERE binding_id = $1 AND is_active"


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _profile(value) -> frozenset[str]:
    """``capability_profile`` is a JSON array of capability ids; anything else matches no capability."""
    decoded = _json(value)
    if isinstance(decoded, list) and all(isinstance(c, str) for c in decoded):
        return frozenset(decoded)
    return frozenset()


class PostgresSelectionReader:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def candidates(self, tenant_id: str) -> tuple[WorkerCandidate, ...]:
        async with self._db.tenant_transaction(tenant_id) as c:
            rows = await c.fetch(_CANDIDATES, tenant_id, WorkerStatus.ACTIVE)
        return tuple(WorkerCandidate(worker_id=r["worker_id"], workspace_id=r["workspace_id"], capacity=r["capacity"],
                                     current_load=r["current_load"], paused_until=r["paused_until"],
                                     scheduled_activation_at=r["scheduled_activation_at"],
                                     assigned_user_id=r["assigned_user_id"],
                                     capability_profile=_profile(r["capability_profile"]),
                                     settings=_json(r["settings"]), runtime_type=r["runtime_type"])
                     for r in rows)

    async def database_now(self) -> float:
        async with self._db.transaction() as c:
            return await c.fetchval(_NOW)

    async def is_workspace_admin(self, tenant_id: str, workspace_id: str, user_id: str | None) -> bool:
        """The admin bypass (C39): an active, unrevoked ``owner``/``admin`` membership of an active user, read live."""
        if user_id is None:
            return False
        async with self._db.tenant_transaction(tenant_id) as c:
            return bool(await c.fetchval(_IS_ADMIN, tenant_id, workspace_id, user_id, sorted(ADMIN_ROLES)))

    async def required_runtime_types(self, binding_id: str) -> tuple[str, ...]:
        """The binding's runtime list (empty = any). A missing or inactive binding row is an error: S12 entry has
        already denied such a run (C32). A value that is not a list of strings is refused rather than read as 'any'."""
        async with self._db.transaction() as c:
            row = await c.fetchrow(_REQUIRED_RUNTIME_TYPES, binding_id)
        if row is None:
            raise LookupError(f"binding {binding_id} is missing or inactive")
        value = _json(row["required_runtime_types"])
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise ValueError(f"binding {binding_id} required_runtime_types is not a list of runtime types: {value!r}")
        return tuple(value)
