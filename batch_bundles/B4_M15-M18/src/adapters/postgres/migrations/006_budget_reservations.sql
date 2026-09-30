-- S8 budget check: availability = budget_pool - reservations of the current period
-- (DATABASE §budget_reservations, S12_S15_EXECUTION_GATE C3/C33). S12 owns writing this table
-- and adds the foreign keys to execution_runs / execution_steps when it creates them; until then
-- the table stays empty and S8 sees the whole pool. Tenant table: forced RLS.

ALTER TABLE tenants ADD COLUMN budget_period TEXT NOT NULL DEFAULT 'monthly'
    CHECK (budget_period IN ('daily','weekly','monthly'));

CREATE TABLE budget_reservations (
    reservation_id  TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id         TEXT NOT NULL,
    execution_id    TEXT NOT NULL,
    step_id         TEXT NOT NULL,
    cost            INTEGER NOT NULL CHECK (cost >= 0),
    status          TEXT NOT NULL DEFAULT 'reserved'
                    CHECK (status IN ('reserved','locked','committed','released')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at       TIMESTAMPTZ,
    committed_at    TIMESTAMPTZ,
    released_at     TIMESTAMPTZ
);
CREATE INDEX idx_reservations_tenant_period ON budget_reservations (tenant_id, created_at) WHERE status <> 'released';

ALTER TABLE budget_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON budget_reservations
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
