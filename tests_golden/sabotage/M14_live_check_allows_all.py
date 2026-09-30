"""M14 sabotage: the live check always allows (C23: revalidate against live state before every step and call)."""
def apply():
    from adapters.postgres.live_authorization import PostgresLiveAuthorization

    async def check(self, **kw):
        return None
    PostgresLiveAuthorization.check = check
