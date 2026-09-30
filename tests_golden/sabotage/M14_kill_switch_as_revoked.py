"""M14 sabotage: a kill switch is reported as a plain revocation (C23: terminal reason kill_switch_engaged)."""
def apply():
    from adapters.postgres.live_authorization import PostgresLiveAuthorization
    from contracts.step_execution import Revoked
    original = PostgresLiveAuthorization.check

    async def check(self, **kw):
        revoked = await original(self, **kw)
        return Revoked("authorization_revoked") if revoked is not None else None
    PostgresLiveAuthorization.check = check
