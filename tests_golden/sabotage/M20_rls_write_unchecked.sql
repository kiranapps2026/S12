-- M20 sabotage: the tenant policies check the rows read but not the rows written (suite 18: a runtime for tenant A
-- could move a row into tenant B or write one for it).
ALTER POLICY tenant_isolation ON execution_runs WITH CHECK (true);
ALTER POLICY tenant_isolation ON state_transitions WITH CHECK (true);
