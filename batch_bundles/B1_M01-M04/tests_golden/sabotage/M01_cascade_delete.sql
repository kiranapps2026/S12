-- M1 sabotage: "execution history deleted with its run" (ON DELETE CASCADE on an execution table, P1-H).
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid = 'dead_letters'::regclass AND contype = 'f'
            AND confrelid = 'execution_runs'::regclass LOOP
    EXECUTE format('ALTER TABLE dead_letters DROP CONSTRAINT %I', r.conname);
  END LOOP;
  ALTER TABLE dead_letters ADD FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id) ON DELETE CASCADE;
END $$;
