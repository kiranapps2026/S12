"""M17 sabotage: a dead letter is accepted without evidence (I11: every dead letter has non-empty evidence)."""
def apply():
    from adapters.postgres.dead_letters import PostgresDeadLetters
    original = PostgresDeadLetters.create

    async def create(self, holder, **kw):
        if not isinstance(kw.get("evidence"), dict) or not kw.get("evidence"):
            kw["evidence"] = {"note": "none given"}
        kw["error"] = kw.get("error") or "unspecified"
        return await original(self, holder, **kw)
    PostgresDeadLetters.create = create
