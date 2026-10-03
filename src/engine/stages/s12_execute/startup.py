"""Worker Runtime start-up checks (DEF-003 / D-13, CONF-052 / D-12).

``check_worker_runtime`` runs two checks before the runtime starts accepting work:

1. ``privileged_role`` — the database role is not a superuser and has no BYPASSRLS.
2. ``unverifiable_mutation`` — every active binding of a PRODUCTION_ENABLED W/D/IRREVERSIBLE
   kernel operation has an adapter class registered that overrides both ``probe`` and ``observe``.

``StartupRefused`` is raised on the first failing check.
"""
from __future__ import annotations

from contracts.adapter_interface import BaseAdapter


class StartupRefused(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def verifiable(adapter_class: type) -> bool:
    """True when the class overrides both ``BaseAdapter.probe`` and ``BaseAdapter.observe``."""
    return (adapter_class is not BaseAdapter
            and "probe" in adapter_class.__dict__
            and "observe" in adapter_class.__dict__)


async def unverifiable_mutations(database, adapters: dict[str, type]) -> list[tuple[str, str]]:
    """Active bindings of PRODUCTION_ENABLED W/D/IRREVERSIBLE ops whose adapter is missing or not verifiable.

    Returns sorted ``(kernel_op_id, binding_id)`` pairs.
    ``database`` is the project's ``Database`` wrapper.
    """
    async with database._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT b.binding_id, b.kernel_op_id, b.adapter_class, b.is_active, k.mutation"
            " FROM bindings b"
            " JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id"
            " WHERE k.truth_state = 'PRODUCTION_ENABLED'"
            "   AND k.mutation <> 'R'"
            "   AND b.is_active")
    bad = []
    for row in rows:
        cls = adapters.get(row["adapter_class"])
        if cls is None or not verifiable(cls):
            bad.append((row["kernel_op_id"], row["binding_id"]))
    return sorted(bad)


async def check_worker_runtime(database, adapters: dict[str, type]) -> None:
    """Raise ``StartupRefused`` if the runtime cannot safely run."""
    async with database._pool.acquire() as conn:
        if await conn.fetchval(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"):
            raise StartupRefused("privileged_role")
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT b.binding_id, b.kernel_op_id, b.adapter_class, b.is_active, k.mutation"
                " FROM bindings b"
                " JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id"
                " WHERE k.truth_state = 'PRODUCTION_ENABLED'"
                "   AND k.mutation <> 'R'"
                "   AND b.is_active")
    bad = []
    for row in rows:
        cls = adapters.get(row["adapter_class"])
        if cls is None or not verifiable(cls):
            bad.append((row["kernel_op_id"], row["binding_id"]))
    if bad:
        raise StartupRefused("unverifiable_mutation")
