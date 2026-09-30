-- M1 sabotage: "terminal_reason can be rewritten". Drops every user trigger on execution_steps.
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN SELECT tgname FROM pg_trigger WHERE tgrelid = 'execution_steps'::regclass AND NOT tgisinternal LOOP
    EXECUTE format('DROP TRIGGER %I ON execution_steps', r.tgname);
  END LOOP; END $$;
