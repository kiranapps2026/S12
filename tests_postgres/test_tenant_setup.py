"""Creating a tenant with its first owner: everything in one transaction, the key works, tenants stay isolated."""
from __future__ import annotations

import asyncio

import pytest

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.tenant_setup import TenantSetupError, create_tenant


def test_a_new_tenant_gets_a_workspace_an_owner_and_a_working_key(pg):
    async def body(db):
        made = await create_tenant(db, slug="acme", name="Acme", owner_name="Ada")
        principal = await PostgresApiKeyAuthenticator(db).authenticate(made["api_key"])
        async with db.tenant_transaction("acme") as c:
            role = await c.fetchval("SELECT role FROM memberships WHERE membership_id = $1", made["membership_id"])
            budget = await c.fetchval("SELECT budget_pool FROM tenants WHERE tenant_id = 'acme'")
            audit = await c.fetchval("SELECT action FROM admin_audit")
        async with db.tenant_transaction("tenant-a") as c:
            leaked = await c.fetchval("SELECT count(*) FROM users WHERE tenant_id = 'acme'")
        return made, principal, role, budget, audit, leaked
    made, principal, role, budget, audit, leaked = pg(body)
    assert (principal.tenant_id, principal.user_id, principal.membership_id) == ("acme", made["user_id"], made["membership_id"])
    assert (role, budget, audit, leaked) == ("owner", 10000, "tenant.create", 0)


@pytest.mark.parametrize("kw,message", [
    ({"slug": "A"}, "slug"), ({"slug": "tenant-a"}, "already exists"), ({"max_mutation": "X"}, "max_mutation"),
    ({"budget_pool": -1}, "budget_pool"), ({"owner_name": " "}, "owner_name"), ({"name": "x\x00y"}, "name")])
def test_bad_input_and_duplicates_are_refused_and_nothing_is_written(pg, kw, message):
    async def body(db):
        args = {"slug": "acme2", "name": "Acme", "owner_name": "Ada", **kw}
        try:
            await create_tenant(db, **args)
            error = None
        except TenantSetupError as exc:
            error = str(exc)
        async with db.tenant_transaction("acme2") as c:
            count = await c.fetchval("SELECT count(*) FROM tenants WHERE tenant_id = 'acme2'")
        return error, count
    error, count = pg(body)
    assert message in error and count == 0


def test_concurrent_creation_of_one_slug_makes_exactly_one_tenant(pg):
    async def body(db):
        results = await asyncio.gather(*[create_tenant(db, slug="race", name="R", owner_name="O") for _ in range(4)],
                                       return_exceptions=True)
        async with db.tenant_transaction("race") as c:
            n = await c.fetchval("SELECT count(*) FROM tenants WHERE tenant_id = 'race'")
        return results, n
    results, n = pg(body)
    assert n == 1 and sum(isinstance(r, dict) for r in results) == 1
