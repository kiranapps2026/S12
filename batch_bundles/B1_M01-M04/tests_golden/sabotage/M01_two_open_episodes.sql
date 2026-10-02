-- M1 sabotage: "a step may have two open episodes". Drops the partial unique index(es) on step_reconciliations.
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
            WHERE i.indrelid = 'step_reconciliations'::regclass AND i.indisunique AND i.indpred IS NOT NULL LOOP
    EXECUTE format('DROP INDEX %I', r.relname);
  END LOOP; END $$;
