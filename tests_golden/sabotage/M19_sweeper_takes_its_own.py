"""M19 sabotage: the sweeper also takes runs its own Worker Runtime owns (CONF-033: those are live in-process loops)."""
def apply():
    from engine.stages.s12_execute.recovery import RecoverySweeper
    original_init = RecoverySweeper.__init__

    def __init__(self, database, deps, *, batch=10):
        original_init(self, database, deps, batch=batch)
        self._sabotage_db, self._sabotage_batch = database, batch

    async def candidates(self):
        async with self._sabotage_db.transaction() as c:
            rows = await c.fetch("SELECT tenant_id, execution_id FROM s12_recovery_candidates($1, $2, $3)",
                                 "no-such-runtime", self._sabotage_batch, 0.0)
        return [(r["tenant_id"], r["execution_id"]) for r in rows]
    RecoverySweeper.__init__, RecoverySweeper.candidates = __init__, candidates
