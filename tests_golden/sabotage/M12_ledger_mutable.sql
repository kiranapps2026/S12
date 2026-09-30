-- M12 sabotage: the execution ledger accepts UPDATE and DELETE (FINAL_ARCHITECTURE §40: append-only).
DROP TRIGGER IF EXISTS execution_events_no_update ON execution_events;
DROP TRIGGER IF EXISTS execution_events_no_delete ON execution_events;
