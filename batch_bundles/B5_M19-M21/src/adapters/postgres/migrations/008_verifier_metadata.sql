-- How a kernel operation's effect is observed (WORKER_LIFECYCLE §7 observation-method registry).
-- Read by S12 entry to build verifiers (gate D1). A W/D/IRREVERSIBLE operation without an
-- observation method cannot be verified, and S12 refuses to run it.
ALTER TABLE kernel_ops
    ADD COLUMN observation_method            TEXT,
    ADD COLUMN observation_expects_absent    BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN observation_identifier_field  TEXT;
