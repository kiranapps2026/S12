"""M14 sabotage: binding and credential validity are not checked (C35: binding_invalid, credential_invalid)."""
def apply():
    from adapters.postgres.live_authorization import PostgresLiveAuthorization
    original = PostgresLiveAuthorization.check

    async def check(self, **kw):
        revoked = await original(self, **kw)
        return None if revoked is not None and revoked.reason in ("binding_invalid", "credential_invalid") else revoked
    PostgresLiveAuthorization.check = check
