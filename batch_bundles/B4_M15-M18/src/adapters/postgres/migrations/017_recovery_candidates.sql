-- Recovery discovery (gate §13, §21 S4; rulings CONF-042, CONF-046). Row-level security scopes every S12 table to one
-- tenant, so a sweeper connected as the application role cannot see another tenant's orphaned runs. This one function,
-- owned by the migration role, returns only (tenant_id, execution_id) pairs of runs in running/reconciling that are
-- orphaned, excluding runs owned by the calling runtime (a live in-process loop, CONF-033). Orphaned is judged by the
-- run's latest lease (CONF-046):
--   * active and unexpired: never (its owner is alive);
--   * active but lapsed, or expired: at once (its owner stopped renewing it);
--   * released: only p_orphan_after_s after its release (a live loop releases its lease between steps and leases the
--     next one at once);
--   * none: only p_orphan_after_s after the ownership row was written (its admitting runtime is about to lease it).
-- It reads nothing else and writes nothing; every claim then happens in a tenant-scoped transaction, under RLS,
-- through the lease CAS. Being SECURITY DEFINER, its search_path is pinned to this schema with pg_temp last, so a
-- caller's temporary table cannot stand in for a real one.
CREATE FUNCTION s12_recovery_candidates(p_runtime_instance_id TEXT, p_limit INTEGER, p_orphan_after_s DOUBLE PRECISION)
RETURNS TABLE (tenant_id TEXT, execution_id TEXT)
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT r.tenant_id, r.execution_id
      FROM execution_runs r
      JOIN execution_ownership o ON o.tenant_id = r.tenant_id AND o.execution_id = r.execution_id
      LEFT JOIN LATERAL (SELECT l.status, l.expires_at, l.released_at FROM worker_leases l
                          WHERE l.tenant_id = r.tenant_id AND l.execution_id = r.execution_id
                          ORDER BY l.fence_token DESC, l.acquired_at DESC LIMIT 1) latest ON true
     WHERE r.status IN ('running', 'reconciling')
       AND o.runtime_instance_id IS DISTINCT FROM p_runtime_instance_id
       AND CASE
             WHEN latest.status IS NULL
               THEN o.updated_at < now() - make_interval(secs => GREATEST(p_orphan_after_s, 0))
             WHEN latest.status = 'released'
               THEN latest.released_at < now() - make_interval(secs => GREATEST(p_orphan_after_s, 0))
             WHEN latest.status = 'expired' THEN true
             ELSE latest.expires_at <= now()
           END
     ORDER BY o.updated_at, r.execution_id
     LIMIT GREATEST(p_limit, 0)
$$;

DO $$
BEGIN
    EXECUTE format('ALTER FUNCTION s12_recovery_candidates(TEXT, INTEGER, DOUBLE PRECISION) SET search_path = %I, pg_temp',
                   current_schema());
END
$$;
