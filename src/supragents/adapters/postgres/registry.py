"""Capability registry: capabilities, bindings, kernel operations and their versions."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database
from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.registry import BindingRow, CapabilityMetadata, KernelOperation, RegistryVersions
from supragents.contracts.vocabulary import Mutation, RetrySafety, TruthState


class PostgresCapabilityRegistry:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def capabilities_for_intent(self, tenant_id: str, intent: str) -> tuple[CapabilityMetadata, ...]:
        async with self._db.transaction() as connection:
            rows = await connection.fetch(
                "SELECT capability_id, name, intent, mutation, risk_floor, risk_rule, risk_implied,"
                " truth_state FROM capabilities WHERE intent = $1 ORDER BY capability_id", intent)
        return tuple(CapabilityMetadata(**{
            **dict(row), "mutation": Mutation(row["mutation"]), "truth_state": TruthState(row["truth_state"]),
        }) for row in rows)

    async def bindings_for(self, tenant_id: str, capability_id: str) -> tuple[BindingRow, ...]:
        async with self._db.transaction() as connection:
            rows = await connection.fetch(
                "SELECT binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class,"
                " priority, EXTRACT(EPOCH FROM created_at)::float8 AS created_at, is_active"
                " FROM bindings WHERE capability_id = $1", capability_id)
        return tuple(BindingRow(**dict(row)) for row in rows)

    async def kernel_operation(self, kernel_op_id: str) -> KernelOperation | None:
        async with self._db.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety,"
                " truth_state, inverse FROM kernel_ops WHERE kernel_op_id = $1", kernel_op_id)
        if row is None:
            return None
        return KernelOperation(**{
            **dict(row), "mutation": Mutation(row["mutation"]),
            "retry_safety": RetrySafety(row["retry_safety"]), "truth_state": TruthState(row["truth_state"]),
        })

    async def known_intents(self, tenant_id: str) -> tuple[str, ...]:
        async with self._db.transaction() as connection:
            rows = await connection.fetch(
                "SELECT DISTINCT intent FROM capabilities WHERE truth_state = 'PRODUCTION_ENABLED'"
                " ORDER BY intent")
        return tuple(row["intent"] for row in rows)

    async def versions(self) -> RegistryVersions:
        async with self._db.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT capability_version, binding_version, risk_policy_version, authorization_version,"
                " worker_runtime_version, model_version FROM registry_versions")
        if row is None:
            raise DependencyUnavailable("registry_versions is empty")
        return RegistryVersions(**dict(row))
