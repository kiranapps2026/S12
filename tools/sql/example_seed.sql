-- Example data for a first run: one tenant "acme" with one workspace, one user, and three
-- capabilities (list = read, create = write, delete = delete). Run as the database OWNER
-- after "python -m supragents migrate". Safe to adapt; ids are plain text.

BEGIN;

INSERT INTO tenants (tenant_id, name, policy_version_id, max_mutation, budget_pool)
VALUES ('acme', 'Acme Ltd', 'acme-policy-1', 'D', 10000);   -- 'D': deletes allowed (default 'W')

INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('acme.main', 'acme', 'Main');
INSERT INTO users (user_id, tenant_id) VALUES ('acme.alice', 'acme');
INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role)
VALUES ('acme.alice.main', 'acme', 'acme.alice', 'acme.main', 'owner');
INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id)
VALUES ('acme.alice.crm', 'acme', 'acme.alice', 'acme.main');

-- Registry (global): capability = what users ask for; kernel_op = the operation; binding = which adapter.
INSERT INTO capabilities (capability_id, name, intent, mutation, risk_floor, risk_rule, risk_implied, truth_state) VALUES
 ('cap.contact.list',   'List contacts',  'contact.list',   'R', 0.1, 0, 0, 'PRODUCTION_ENABLED'),
 ('cap.contact.create', 'Create contact', 'contact.create', 'W', 0.2, 0, 0, 'PRODUCTION_ENABLED'),
 ('cap.contact.delete', 'Delete contact', 'contact.delete', 'D', 0.5, 0, 0, 'PRODUCTION_ENABLED');

INSERT INTO kernel_ops (kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety, truth_state) VALUES
 ('crm.contact_list',   'R', 0, 1, 30, 'safe',       'PRODUCTION_ENABLED'),
 ('crm.contact_create', 'W', 0, 3, 30, 'idempotent', 'PRODUCTION_ENABLED'),
 ('crm.contact_delete', 'D', 0, 5, 30, 'never',      'PRODUCTION_ENABLED');

INSERT INTO bindings (binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class) VALUES
 ('bind.contact.list',   'cap.contact.list',   'crm.contact_list',   'crm', 'engines.crm', 'CrmAdapter'),
 ('bind.contact.create', 'cap.contact.create', 'crm.contact_create', 'crm', 'engines.crm', 'CrmAdapter'),
 ('bind.contact.delete', 'cap.contact.delete', 'crm.contact_delete', 'crm', 'engines.crm', 'CrmAdapter');

-- What alice may do (S8 check 4).
INSERT INTO capability_grants (capability_grant_id, tenant_id, workspace_id, user_id, capability_id)
SELECT 'grant.alice.' || capability_id, 'acme', 'acme.main', 'acme.alice', capability_id FROM capabilities;

-- Versions stamped into every ExecutionManifest (S11).
INSERT INTO registry_versions (capability_version, binding_version, risk_policy_version,
                               authorization_version, worker_runtime_version, model_version)
VALUES ('cap-1', 'bind-1', 'risk-1', 'auth-1', 'runtime-1', 'deepseek-flash');

COMMIT;
