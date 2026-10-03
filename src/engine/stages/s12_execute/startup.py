"""Worker Runtime start-up checks (DEF-003 / D-13, CONF-052 / D-12).

``check_worker_runtime`` runs two checks before the runtime starts accepting work:

1. ``privileged_role`` — the database role is not a superuser and has no BYPASSRLS.
2. ``unverifiable_mutation`` — every active binding of a PRODUCTION_ENABLED W/D/IRREVERSIBLE
   kernel operation has an adapter class registered that overrides both ``probe`` and ``observe``
   in its own class body, and, when the class declares ``verifiable_operations()``, lists that
   operation there.

The per-operation condition is additive: a class that does not declare ``verifiable_operations``
(``MockAdapter``) is judged by the class-level check alone, exactly as before. A class that holds a
shared engine and delegates ``probe`` and ``observe`` to it passes the class-level check for every
operation, so it must say which operations it can really probe and observe. Fail closed: a
declaration that raises or is not a collection makes every operation of the class unverifiable.

``StartupRefused`` is raised on the first failing check.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping

from contracts.adapter_interface import BaseAdapter

_PRODUCTION_MUTATIONS_SQL = (
    "SELECT b.binding_id, b.kernel_op_id, b.adapter_class, b.is_active, k.mutation"
    " FROM bindings b"
    " JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id"
    " WHERE k.truth_state = 'PRODUCTION_ENABLED'"
    "   AND k.mutation <> 'R'"
    "   AND b.is_active")


class StartupRefused(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def verifiable(adapter_class: type) -> bool:
    """True when the class overrides both ``BaseAdapter.probe`` and ``BaseAdapter.observe``."""
    return (adapter_class is not BaseAdapter
            and "probe" in adapter_class.__dict__
            and "observe" in adapter_class.__dict__)


def verifiable_for(adapter_class: type | None, kernel_op_id: str) -> bool:
    """True when ``adapter_class`` can probe and observe ``kernel_op_id``.

    The class-level check (``verifiable``) first; then, only if the class declares
    ``verifiable_operations``, the operation must be in what it returns.
    """
    if adapter_class is None or not verifiable(adapter_class):
        return False
    declared = getattr(adapter_class, "verifiable_operations", None)
    if declared is None:
        return True
    try:
        operations = declared() if callable(declared) else declared
    except Exception:  # noqa: BLE001 — a declaration that cannot be read verifies nothing
        return False
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Collection):
        return False
    return kernel_op_id in operations


def _unverifiable(rows, adapters: Mapping[str, type]) -> list[tuple[str, str]]:
    """The ``(kernel_op_id, binding_id)`` pairs of ``rows`` whose adapter is missing or cannot verify the operation."""
    return sorted((row["kernel_op_id"], row["binding_id"]) for row in rows
                  if not verifiable_for(adapters.get(row["adapter_class"]), row["kernel_op_id"]))


async def unverifiable_mutations(database, adapters: dict[str, type]) -> list[tuple[str, str]]:
    """Active bindings of PRODUCTION_ENABLED W/D/IRREVERSIBLE ops whose adapter is missing or not verifiable.

    Returns sorted ``(kernel_op_id, binding_id)`` pairs.
    ``database`` is the project's ``Database`` wrapper.
    """
    async with database._pool.acquire() as conn:
        rows = await conn.fetch(_PRODUCTION_MUTATIONS_SQL)
    return _unverifiable(rows, adapters)


async def check_worker_runtime(database, adapters: dict[str, type]) -> None:
    """Raise ``StartupRefused`` if the runtime cannot safely run."""
    async with database._pool.acquire() as conn:
        if await conn.fetchval(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"):
            raise StartupRefused("privileged_role")
        async with conn.transaction():
            rows = await conn.fetch(_PRODUCTION_MUTATIONS_SQL)
    if _unverifiable(rows, adapters):
        raise StartupRefused("unverifiable_mutation")
