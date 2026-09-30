-- S12 step loop (gate §8): terminal reasons, dispatch marker, per-step budget uniqueness.
-- Deviations for the gate owner: execution_runs also records connection_id (the live authorization
-- check needs it; the run row had no place for it) and terminal_reason (why a run was cancelled).

ALTER TABLE execution_runs ADD COLUMN connection_id TEXT, ADD COLUMN terminal_reason TEXT;

ALTER TABLE execution_steps
    ADD COLUMN terminal_reason    TEXT,
    ADD COLUMN dispatched_attempt INTEGER,
    ADD CONSTRAINT chk_step_terminal_reason CHECK (terminal_reason IS NULL OR terminal_reason IN (
        'user_cancelled','admission_rejected','admission_exhausted','no_worker','lease_unavailable',
        'budget_exhausted','preflight_failed','not_executed_no_retry','dependency_failed',
        'run_dead_lettered','authorization_revoked','kill_switch_engaged','binding_invalid',
        'credential_invalid')),
    ADD CONSTRAINT chk_step_terminal_reason_required
        CHECK (status NOT IN ('cancelled','skipped') OR terminal_reason IS NOT NULL);

CREATE FUNCTION keep_terminal_reason() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.terminal_reason IS NOT NULL AND NEW.terminal_reason IS DISTINCT FROM OLD.terminal_reason THEN
        RAISE EXCEPTION 'terminal_reason is immutable once written';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER execution_steps_terminal_reason BEFORE UPDATE ON execution_steps
    FOR EACH ROW EXECUTE FUNCTION keep_terminal_reason();

-- one live (not released) reservation per step
CREATE UNIQUE INDEX uq_budget_reservation_open_step ON budget_reservations (step_id) WHERE status <> 'released';
