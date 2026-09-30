-- M12 sabotage: dependents of a failed step become CANCELLED instead of SKIPPED (C22: SKIPPED, dependency_failed).
CREATE FUNCTION golden_sabotage_skip_as_cancel() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'skipped' THEN NEW.status := 'cancelled'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER golden_sabotage_skip_as_cancel BEFORE UPDATE ON execution_steps
    FOR EACH ROW EXECUTE FUNCTION golden_sabotage_skip_as_cancel();
