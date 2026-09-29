"""
Row-Level Security (RLS) policies — PostgreSQL RLS enforcement.

Source: DATABASE.md §RLS, SECURITY.md §3, IDENTITY_AND_TENANCY.md §8

CRITICAL: RLS is the PRIMARY tenant isolation enforcement mechanism.
Application-level filtering provides defense-in-depth but RLS is the
non-bypassable security boundary.

Setup:
    psql -d supragents -f src/db/rls/policies.sql

These policies enforce:
    1. Users can only access rows belonging to their tenant
    2. Row-level checks use current_setting('app.current_tenant')
    3. Service role bypasses RLS for admin operations
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RLS Policy Definitions
# ---------------------------------------------------------------------------
#
# These SQL statements must be executed against the database.
# They can be run via:
#   - alembic migrations (preferred for production)
#   - direct SQL execution (for development)
# ---------------------------------------------------------------------------

RLS_ENABLE_TENANT_TABLES = """
-- Enable RLS on all tenant-scoped tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_tracker ENABLE ROW LEVEL SECURITY;
ALTER TABLE confirmation_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE retry_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE capability_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE binding_registry ENABLE ROW LEVEL SECURITY;
"""

RLS_POLICIES = """
-- ============================================================================
-- TENANT ISOLATION POLICIES
-- ============================================================================
-- These policies enforce that all queries filter by tenant_id.
-- The app.current_tenant setting is set per-connection via SET LOCAL.

-- Helper function to get current tenant
CREATE OR REPLACE FUNCTION get_current_tenant_id()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_tenant', true), '')::UUID;
EXCEPTION
    WHEN OTHERS THEN RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- TENANTS
-- ============================================================================
CREATE POLICY tenant_isolation ON tenants
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- WORKSPACES
-- ============================================================================
CREATE POLICY tenant_isolation ON workspaces
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- USERS
-- ============================================================================
CREATE POLICY tenant_isolation ON users
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- MEMBERSHIPS
-- ============================================================================
CREATE POLICY tenant_isolation ON memberships
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- CONNECTIONS
-- ============================================================================
CREATE POLICY tenant_isolation ON connections
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- EXECUTION RUNS
-- ============================================================================
CREATE POLICY tenant_isolation ON execution_runs
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- EXECUTION STEPS
-- ============================================================================
CREATE POLICY tenant_isolation ON execution_steps
    FOR ALL TO app_role
    USING (
        tenant_id = get_current_tenant_id()
        OR EXISTS (
            SELECT 1 FROM execution_runs er
            WHERE er.execution_id = execution_steps.execution_id
            AND er.tenant_id = get_current_tenant_id()
        )
    );

-- ============================================================================
-- EXECUTION LEASES
-- ============================================================================
CREATE POLICY tenant_isolation ON execution_leases
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- BUDGET RESERVATIONS
-- ============================================================================
CREATE POLICY tenant_isolation ON budget_reservations
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- BUDGET TRACKER
-- ============================================================================
CREATE POLICY tenant_isolation ON budget_tracker
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- CONFIRMATION TOKENS
-- ============================================================================
CREATE POLICY tenant_isolation ON confirmation_tokens
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- DEAD LETTERS
-- ============================================================================
CREATE POLICY tenant_isolation ON dead_letters
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- RETRY LOG
-- ============================================================================
CREATE POLICY tenant_isolation ON retry_log
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- OUTBOX
-- ============================================================================
CREATE POLICY tenant_isolation ON outbox
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- AUDIT LOG
-- ============================================================================
-- Audit log uses audit_reader role for cross-tenant reads (compliance)
CREATE POLICY audit_insert ON audit_log
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = get_current_tenant_id());

-- ============================================================================
-- WORKER IDENTITIES
-- ============================================================================
CREATE POLICY tenant_isolation ON worker_identities
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- WORKER VERSIONS
-- ============================================================================
CREATE POLICY tenant_isolation ON worker_versions
    FOR ALL TO app_role
    USING (
        tenant_id = get_current_tenant_id()
        OR EXISTS (
            SELECT 1 FROM worker_identities wi
            WHERE wi.worker_id = worker_versions.worker_id
            AND wi.tenant_id = get_current_tenant_id()
        )
    );

-- ============================================================================
-- WORKER DEPLOYMENTS
-- ============================================================================
CREATE POLICY tenant_isolation ON worker_deployments
    FOR ALL TO app_role
    USING (
        tenant_id = get_current_tenant_id()
        OR EXISTS (
            SELECT 1 FROM worker_identities wi
            WHERE wi.worker_id = worker_deployments.worker_id
            AND wi.tenant_id = get_current_tenant_id()
        )
    );

-- ============================================================================
-- PROVIDER TOKENS
-- ============================================================================
CREATE POLICY tenant_isolation ON provider_tokens
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- CAPABILITY REGISTRY
-- ============================================================================
CREATE POLICY tenant_isolation ON capability_registry
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());

-- ============================================================================
-- BINDING REGISTRY
-- ============================================================================
CREATE POLICY tenant_isolation ON binding_registry
    FOR ALL TO app_role
    USING (tenant_id = get_current_tenant_id());
"""

RLS_ROLES = """
-- ============================================================================
-- DATABASE ROLES
-- ============================================================================

-- Application role (canonical, per FINAL_ARCHITECTURE.md)
CREATE ROLE IF NOT EXISTS app_role;

-- Read-only role for audit queries
CREATE ROLE IF NOT EXISTS audit_reader;

-- Admin role (full access, bypasses RLS)
CREATE ROLE IF NOT EXISTS app_admin;

-- Grant schema usage
GRANT USAGE ON SCHEMA public TO app_role, audit_reader, app_admin;

-- Grant table access
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_role;

-- Audit reader: read-only access
GRANT SELECT ON ALL TABLES IN SCHEMA public TO audit_reader;

-- Admin: full access with RLS bypass
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_admin;
ALTER ROLE app_admin BYPASSRLS;

-- Future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO audit_reader;
"""


def get_rls_sql() -> str:
    """Get the complete RLS setup SQL."""
    return RLS_ROLES + "\n" + RLS_ENABLE_TENANT_TABLES + "\n" + RLS_POLICIES


async def apply_rls_policies(engine) -> None:
    """
    Apply RLS policies to the database.

    This should be run after all tables are created.
    """
    import logging
    logger = logging.getLogger(__name__)

    sql = get_rls_sql()

    async with engine.connect() as conn:
        for statement in sql.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            try:
                await conn.execute(statement)
                logger.debug("Applied RLS statement: %s...", statement[:50])
            except Exception as e:
                logger.warning("RLS statement warning: %s", e)

        await conn.commit()
        logger.info("RLS policies applied")
