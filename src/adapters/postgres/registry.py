"""Capability registry: the only source of capability, binding and risk data (A4).

Implements contracts.capability.CapabilityRegistry over the registry tables. A capability
is offered only when it is PRODUCTION_ENABLED and has an active binding whose kernel
operation is PRODUCTION_ENABLED. Mutation is the more severe of capability and operation;
risk_floor the higher; cost is the bound kernel operation's cost.
"""
from __future__ import annotations

import types

from adapters.postgres.database import Database
from contracts.capability import BindingRow, CapabilityMetadata, CapabilityRegistry
from contracts.errors import DependencyUnavailable

_SEVERITY = types.MappingProxyType({"R": 0, "W": 1, "D": 2, "IRREVERSIBLE": 3})

_BEST_BINDING = """
SELECT DISTINCT ON (c.capability_id)
       c.capability_id, c.name, c.intent, c.mutation AS cap_mutation, c.risk_floor AS cap_floor,
       c.risk_rule, c.risk_implied, k.mutation AS op_mutation, k.risk_floor AS op_floor, k.cost
  FROM capabilities c
  JOIN bindings b ON b.capability_id = c.capability_id AND b.is_active
  JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id AND k.truth_state = 'PRODUCTION_ENABLED'
 WHERE c.truth_state = 'PRODUCTION_ENABLED' AND {where}
 ORDER BY c.capability_id, b.priority, b.binding_id
"""


def _metadata(row) -> CapabilityMetadata:
    more_severe = max(row["cap_mutation"], row["op_mutation"], key=_SEVERITY.__getitem__)
    return CapabilityMetadata(
        capability_id=row["capability_id"], name=row["name"], description="", namespace="",
        input_schema={}, output_schema={},
        risk_floor=max(row["cap_floor"], row["op_floor"]),
        risk_rule=row["risk_rule"], risk_implied=row["risk_implied"],
        mutation_type=more_severe, estimated_cost_units=row["cost"],
        tags=[row["intent"]],
    )


class PostgresCapabilityRegistry(CapabilityRegistry):
    def __init__(self, database: Database) -> None:
        self._db = database

    async def discover(self, intent: dict, tenant_id: str) -> list[CapabilityMetadata]:
        """Capabilities whose intent is the classified intent_type (exact match)."""
        async with self._db.transaction() as connection:
            rows = await connection.fetch(_BEST_BINDING.format(where="c.intent = $1"),
                                          intent.get("intent_type", ""))
        return [_metadata(r) for r in rows]

    async def known_intents(self, tenant_id: str) -> tuple[str, ...]:
        async with self._db.transaction() as connection:
            rows = await connection.fetch("""
                SELECT DISTINCT c.intent
                  FROM capabilities c
                  JOIN bindings b ON b.capability_id = c.capability_id AND b.is_active
                  JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id AND k.truth_state = 'PRODUCTION_ENABLED'
                 WHERE c.truth_state = 'PRODUCTION_ENABLED' ORDER BY c.intent""")
        return tuple(r["intent"] for r in rows)

    async def get_capability(self, capability_id: str) -> CapabilityMetadata | None:
        async with self._db.transaction() as connection:
            rows = await connection.fetch(_BEST_BINDING.format(where="c.capability_id = $1"),
                                          capability_id)
        return _metadata(rows[0]) if rows else None

    async def list_bindings(self, capability_id: str) -> list[BindingRow]:
        async with self._db.transaction() as connection:
            versions = await connection.fetchrow(
                "SELECT capability_version, binding_version, risk_policy_version, authorization_version"
                "  FROM registry_versions")
            rows = await connection.fetch("""
                SELECT b.binding_id, b.capability_id, b.kernel_op_id, b.provider, b.engine_module,
                       b.adapter_class, b.priority, b.is_active, k.risk_floor, k.inverse
                  FROM bindings b
                  JOIN kernel_ops k ON k.kernel_op_id = b.kernel_op_id
                  JOIN capabilities c ON c.capability_id = b.capability_id
                 WHERE b.capability_id = $1 AND b.is_active
                   AND k.truth_state = 'PRODUCTION_ENABLED'
                   AND c.truth_state = 'PRODUCTION_ENABLED'""", capability_id)
        if versions is None:
            raise DependencyUnavailable("registry_versions is empty")
        return [
            BindingRow(
                binding_id=r["binding_id"], capability_id=r["capability_id"],
                provider=r["provider"], adapter_class=r["adapter_class"],
                capability_version=versions["capability_version"],
                binding_version=versions["binding_version"],
                policy_version="",  # policy versions come from the run scope, not the binding
                risk_policy_version=versions["risk_policy_version"],
                authorization_version=versions["authorization_version"],
                effective_risk=r["risk_floor"], kernel_op_id=r["kernel_op_id"],
                engine_module=r["engine_module"], selection_rank=r["priority"],
                is_active=r["is_active"], inverse_kernel_op_id=r["inverse"],
            )
            for r in rows
        ]


class PostgresBindingVersionReader:
    """S12 entry (gate C32): the binding's version, read once by binding_id. The version is the
    registry's current binding version; a missing or inactive binding row has none."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def binding_version(self, binding_id: str) -> str | None:
        async with self._db.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT rv.binding_version FROM bindings b, registry_versions rv"
                " WHERE b.binding_id = $1 AND b.is_active", binding_id)
        return None if row is None else row["binding_version"]


class PostgresKernelOpMetadataReader:
    """Verifier metadata (gate D1), read at the versions the manifest pinned. The registry serves one
    version set (registry_versions); if it has moved on since S11 the pinned metadata is gone and the
    reader returns None, so S12 entry denies rather than build a verifier from other versions."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def read(self, kernel_op_ids, *, capability_version: str, binding_version: str):
        from contracts.verifier import KernelOpMetadata
        async with self._db.transaction() as connection:
            versions = await connection.fetchrow(
                "SELECT capability_version, binding_version FROM registry_versions")
            if versions is None:
                raise DependencyUnavailable("registry_versions is empty")
            if (versions["capability_version"], versions["binding_version"]) != (capability_version, binding_version):
                return None
            rows = await connection.fetch(
                "SELECT kernel_op_id, mutation, observation_method, observation_expects_absent,"
                "       observation_identifier_field"
                "  FROM kernel_ops WHERE kernel_op_id = ANY($1::text[]) AND truth_state = 'PRODUCTION_ENABLED'",
                list(kernel_op_ids))
        return {r["kernel_op_id"]: KernelOpMetadata(
            r["kernel_op_id"], r["mutation"], r["observation_method"],
            r["observation_expects_absent"], r["observation_identifier_field"]) for r in rows}
