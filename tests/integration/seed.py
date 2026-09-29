"""Reference data for the PostgreSQL tests: two tenants and the standard catalog."""
from __future__ import annotations

TABLES = ("api_keys", "suspended_runs", "llm_usage", "pipeline_events", "pending_confirmations", "capability_grants", "bindings", "kernel_ops",
          "capabilities", "registry_versions", "connections", "memberships", "users", "workspaces", "tenants")

CATALOG = (  # capability intent, mutation, risk, kernel op, cost
    ("contact.list", "R", 0.1, "crm.contact_list", 1),
    ("contact.create", "W", 0.2, "crm.contact_create", 3),
    ("contact.delete", "D", 0.5, "crm.contact_delete", 5),
)


async def reset_and_seed(connection) -> None:
    await connection.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    await connection.execute("UPDATE system_settings SET kill_switch_engaged = false, risk_deny_threshold = 0.95")
    for tenant in ("tenant-a", "tenant-b"):
        await _seed_tenant(connection, tenant)
    for intent, mutation, risk, op, cost in CATALOG:
        await connection.execute(
            "INSERT INTO capabilities VALUES ($1, $2, $2, $3, $4, 0, 0, 'PRODUCTION_ENABLED')",
            f"cap.{intent}", intent, mutation, risk)
        await connection.execute(
            "INSERT INTO kernel_ops VALUES ($1, $2, 0, $3, 30, 'safe', 'PRODUCTION_ENABLED', NULL)",
            op, mutation, cost)
        await connection.execute(
            "INSERT INTO bindings (binding_id, capability_id, kernel_op_id, provider, engine_module,"
            " adapter_class) VALUES ($1, $2, $3, 'crm', 'engines.crm', 'CrmAdapter')",
            f"bind.{intent}", f"cap.{intent}", op)
        for tenant in ("tenant-a", "tenant-b"):
            await connection.execute(
                "INSERT INTO capability_grants VALUES ($1, $2, $3, $4, $5, true, NULL)",
                f"grant.{tenant}.{intent}", tenant, f"{tenant}.ws", f"{tenant}.user", f"cap.{intent}")
    await connection.execute(
        "INSERT INTO registry_versions VALUES (true, 'cap-7', 'bind-3', 'risk-1', 'auth-4', 'rt-1', 'model-9')")


async def _seed_tenant(connection, tenant: str) -> None:
    await connection.execute(
        "INSERT INTO tenants (tenant_id, name, max_mutation, policy_version_id) VALUES ($1, $1, 'D', $2)",
        tenant, f"{tenant}.policy-1")
    await connection.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'main')",
                             f"{tenant}.ws", tenant)
    await connection.execute("INSERT INTO users (user_id, tenant_id) VALUES ($1, $2)", f"{tenant}.user", tenant)
    await connection.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id)"
                             " VALUES ($1, $2, $3, $4)", f"{tenant}.member", tenant, f"{tenant}.user", f"{tenant}.ws")
    await connection.execute("INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id)"
                             " VALUES ($1, $2, $3, $4)", f"{tenant}.conn", tenant, f"{tenant}.user", f"{tenant}.ws")
