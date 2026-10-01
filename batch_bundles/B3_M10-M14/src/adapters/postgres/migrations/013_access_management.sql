-- User and grant management (Phase B4b): what an administrator needs to know about who created what, and a
-- flag that marks SERVICE users (the dedicated identities webhook endpoints and schedules run as, ruling R-AT).
ALTER TABLE users            ADD COLUMN display_name TEXT, ADD COLUMN is_service BOOLEAN NOT NULL DEFAULT FALSE,
                             ADD COLUMN created_by TEXT;
ALTER TABLE workspaces       ADD COLUMN created_by TEXT;
ALTER TABLE memberships      ADD COLUMN created_by TEXT, ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE connections      ADD COLUMN created_by TEXT, ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE capability_grants ADD COLUMN created_by TEXT, ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
