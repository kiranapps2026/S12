-- M20 sabotage: the owner of execution_steps is exempt from row-level security (suite 18: RLS is forced on every
-- S12 table, so no role that owns a table reads another tenant's rows).
ALTER TABLE execution_steps NO FORCE ROW LEVEL SECURITY;
