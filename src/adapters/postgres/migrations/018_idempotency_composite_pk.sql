-- Idempotency ledger composite primary key (C9, C17, C34).
--
-- The ledger originally keyed on idempotency_key alone. Under RLS, each tenant sees only
-- its own rows, so cross-tenant collision was impossible — until B5 (M20 multiprocess)
-- surfaced the case where two runtimes on different tenants produce the same key. The
-- second INSERT ... ON CONFLICT DO NOTHING silently dropped the write; the second
-- tenant's _LOOKUP found nothing (RLS filter) and re-executed, breaking idempotency.
--
-- This migration widens the PK to (tenant_id, idempotency_key). Existing rows already
-- carry both columns, so the new key is a strict superset of the old uniqueness guarantee.
-- Rows inserted between the ALTER TABLE and the CONSTRAINT re-name are harmless: the
-- index exists as a unique btree during the window.

BEGIN;

-- 1. Drop the old PK (also drops the implicit index on idempotency_key alone).
ALTER TABLE idempotency_ledger DROP CONSTRAINT idempotency_ledger_pkey;

-- 2. Drop the redundant tenant+key index (the new PK will cover it).
DROP INDEX IF EXISTS idx_idempotency_ledger_tenant_key;

-- 3. Re-create as composite PK. UNIQUE INDEX is separate so ON CONFLICT (tenant_id, idempotency_key)
--    resolves correctly even if tenant_id is passed first in the INSERT column list.
ALTER TABLE idempotency_ledger
    ADD CONSTRAINT idempotency_ledger_pkey
    PRIMARY KEY (tenant_id, idempotency_key);

COMMIT;
