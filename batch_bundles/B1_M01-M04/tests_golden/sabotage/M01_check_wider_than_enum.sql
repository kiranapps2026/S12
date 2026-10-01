-- M1 sabotage: "a CHECK hand-written instead of generated from the enum" (accepts the upper-case PENDING_PROBE, C28).
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT c.conname FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.conrelid = 'execution_steps'::regclass AND c.contype = 'c' AND array_length(c.conkey, 1) = 1
              AND a.attname = 'status' LOOP
    EXECUTE format('ALTER TABLE execution_steps DROP CONSTRAINT %I', r.conname);
  END LOOP;
  ALTER TABLE execution_steps ADD CHECK (status IN ('pending','running','completed','partial','failed','cancelled',
    'skipped','timeout','unknown','pending_probe','dead_letter','PENDING_PROBE'));
END $$;
