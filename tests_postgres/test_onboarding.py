"""Invitations, rate limiting, usage metering and the reference writers over real PostgreSQL."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from adapters.postgres.admin_reference import PostgresResultWriter
from adapters.postgres.rate_limit import PostgresRateLimiter
from adapters.postgres.references import PostgresReferenceSource
from adapters.postgres.usage import MeteredIntentModel, UsageMeter
from bootstrap import build_runner
from contracts.errors import DependencyUnavailable
from engine.control_plane.api import RateLimits
from tests_postgres.test_admin_api import A, B, WORLD, _audit, _env
from tests_postgres.test_end_to_end import EchoIntentModel

WS_A = "tenant-a.ws"


async def _accept(e, token, name="New Person", who=None, headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=e.app), base_url="http://t") as client:
        return await client.post("/api/v1/invitations/accept", json={"token": token, "display_name": name}, headers=headers or {})


async def _invite(e, who=A, role="member", **extra):
    r = await e.call(who, "POST", "/invitations", {"workspace_id": WS_A, "role": role, **extra})
    return r


# ==== invitations ===========================================================================================

def test_an_invitation_is_redeemed_once_and_gives_the_invitee_their_own_identity_and_key(pg):
    async def body(db):
        e = await _env(db)
        made = await _invite(e, role="member", label="new hire")
        token = made.json()["token"]
        listing_before = (await e.call(A, "GET", "/invitations")).json()["invitations"]
        first = await _accept(e, token, "Bea")
        who = await e.auth.authenticate(first.json()["api_key"])
        second = await _accept(e, token)
        listing_after = (await e.call(A, "GET", "/invitations")).json()["invitations"]
        async with db.tenant_transaction(A) as c:
            user = dict(await c.fetchrow("SELECT display_name, is_service, status FROM users WHERE user_id = $1", first.json()["user_id"]))
            role = await c.fetchval("SELECT role FROM memberships WHERE membership_id = $1", first.json()["membership_id"])
            conn = await c.fetchval("SELECT status FROM connections WHERE connection_id = $1", first.json()["connection_id"])
        return made, listing_before, first, who, second, listing_after, user, role, conn, await _audit(db, A)
    made, before, first, who, second, after, user, role, conn, audit = pg(body, *WORLD)
    assert made.status_code == 201 and made.json()["token"].startswith("inv_supra_")
    assert before[0]["status"] == "pending" and "token" not in before[0] and "token_hash" not in before[0]
    assert first.status_code == 201 and (who.tenant_id, who.user_id, who.workspace_id) == (A, first.json()["user_id"], WS_A)
    assert second.status_code == 404 and second.json()["detail"] == "invitation_invalid"
    assert after[0]["status"] == "accepted" and after[0]["accepted_user_id"] == first.json()["user_id"]
    assert user == {"display_name": "Bea", "is_service": False, "status": "active"} and (role, conn) == ("member", "active")
    assert {"invitation.create", "invitation.accept"} <= {a["action"] for a in audit}


def test_only_admins_invite_and_never_above_their_own_role(pg):
    async def body(db):
        e = await _env(db)
        by_member = await e.call("member-a", "POST", "/invitations", {"workspace_id": WS_A, "role": "viewer"})
        by_viewer = await e.call("viewer-a", "POST", "/invitations", {"workspace_id": WS_A, "role": "viewer"})
        admin_owner = await _invite(e, A, "owner")           # the caller of tenant-a is an admin
        owner_owner = await _invite(e, "owner-a", "owner")
        bad_role = await _invite(e, A, "root")
        bad_ws = await e.call(A, "POST", "/invitations", {"workspace_id": "tenant-b.ws", "role": "member"})
        bad_ttl = await _invite(e, A, "member", ttl_hours=0)
        extra = await e.call(A, "POST", "/invitations", {"workspace_id": WS_A, "role": "member", "tenant_id": "tenant-b"})
        return [r.status_code for r in (by_member, by_viewer, admin_owner, owner_owner, bad_role, bad_ws, bad_ttl, extra)]
    assert pg(body, *WORLD) == [403, 403, 403, 201, 422, 404, 422, 422]


def test_expired_revoked_unknown_and_wrong_tenant_state_all_look_the_same(pg):
    async def body(db):
        e = await _env(db)
        expired = (await _invite(e)).json()
        revoked = (await _invite(e)).json()
        suspended = (await _invite(e)).json()
        async with db.transaction() as c:
            await c.execute("UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE invitation_id = $1", expired["invitation_id"])
        rev = await e.call(A, "DELETE", f"/invitations/{revoked['invitation_id']}")
        rev_again = await e.call(A, "DELETE", f"/invitations/{revoked['invitation_id']}")
        cross = await e.call(B, "DELETE", f"/invitations/{suspended['invitation_id']}")
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE tenants SET status = 'suspended' WHERE tenant_id = 'tenant-a'")
        results = [await _accept(e, t) for t in (expired["token"], revoked["token"], suspended["token"], "inv_supra_nope", "garbage-token-value")]
        return rev.status_code, rev_again.status_code, cross.status_code, [(r.status_code, r.json()["detail"]) for r in results]
    rev, again, cross, results = pg(body, *WORLD)
    assert (rev, again, cross) == (204, 404, 404)
    assert results == [(404, "invitation_invalid")] * 5


def test_two_people_racing_for_one_token_produce_exactly_one_identity(pg):
    async def body(db):
        e = await _env(db)
        token = (await _invite(e)).json()["token"]
        results = await asyncio.gather(*[_accept(e, token, f"P{i}") for i in range(6)])
        async with db.tenant_transaction(A) as c:
            created = await c.fetchval("SELECT count(*) FROM users WHERE created_by = $1 AND display_name LIKE 'P%'", "tenant-a.user")
        return [r.status_code for r in results], created
    codes, created = pg(body, *WORLD)
    assert sorted(codes) == [201, 404, 404, 404, 404, 404] and created == 1


def test_invitations_are_isolated_per_tenant(pg):
    async def body(db):
        e = await _env(db)
        await _invite(e)
        return (await e.call(B, "GET", "/invitations")).json()["invitations"]
    assert pg(body, *WORLD) == []


# ==== rate limiting =========================================================================================

def test_the_limiter_counts_per_bucket_resets_the_window_and_is_atomic_under_concurrency(pg):
    async def body(db):
        limiter = PostgresRateLimiter(db)
        first = [await limiter.hit("b1", 3, 60) for _ in range(5)]
        other = await limiter.hit("b2", 3, 60)
        zero = await limiter.hit("b3", 0, 60)
        burst = await asyncio.gather(*[limiter.hit("race", 5, 60) for _ in range(25)])
        short = [await limiter.hit("w", 1, 1)]
        short.append(await limiter.hit("w", 1, 1))
        await asyncio.sleep(1.2)
        short.append(await limiter.hit("w", 1, 1))
        return first, other, zero, burst, short
    first, other, zero, burst, short = pg(body)
    assert [d.allowed for d in first] == [True, True, True, False, False] and first[3].retry_after >= 1
    assert first[0].remaining == 2 and other.allowed and not zero.allowed
    assert sum(d.allowed for d in burst) == 5
    assert [d.allowed for d in short] == [True, False, True]


def _limits(user=3, tenant=100, invite=2):
    return RateLimits(user, tenant, invite, 60)


def test_the_api_answers_429_with_retry_after_per_user_and_per_tenant_and_fails_closed(pg):
    async def body(db):
        e = await _env(db)
        e.app.state.rate_limiter, e.app.state.rate_limits = PostgresRateLimiter(db), _limits(user=3, tenant=5)
        mine = [(await e.call(A, "GET", "/api-keys")).status_code for _ in range(4)]
        denied = await e.call(A, "GET", "/api-keys")
        other_user = (await e.call("owner-a", "GET", "/api-keys")).status_code       # same tenant, own user window
        other_tenant = (await e.call(B, "GET", "/api-keys")).status_code
        tenant_hits = [(await e.call("peer-a", "GET", "/api-keys")).status_code for _ in range(2)]
        over_tenant = (await e.call("owner-a", "GET", "/api-keys")).status_code      # tenant window (5) is now used up

        class Down:
            async def hit(self, *a):
                raise DependencyUnavailable("down")
        e.app.state.rate_limiter = Down()
        closed = (await e.call(B, "GET", "/api-keys")).status_code
        return mine, denied, other_user, other_tenant, tenant_hits, over_tenant, closed
    mine, denied, other_user, other_tenant, tenant_hits, over_tenant, closed = pg(body, *WORLD)
    assert mine == [200, 200, 200, 429] and denied.status_code == 429 and denied.json()["detail"] == "rate_limited"
    assert int(denied.headers["retry-after"]) >= 1
    assert other_user == 200 and other_tenant == 200 and tenant_hits == [200, 429] and over_tenant == 429 and closed == 503


def test_without_a_limiter_nothing_is_limited_and_the_invitation_route_is_limited_per_address(pg):
    async def body(db):
        e = await _env(db)
        unlimited = [(await e.call(A, "GET", "/api-keys")).status_code for _ in range(8)]
        e.app.state.rate_limiter, e.app.state.rate_limits = PostgresRateLimiter(db), _limits(invite=2)
        tries = [(await _accept(e, "inv_supra_nope")).status_code for _ in range(4)]
        return unlimited, tries
    unlimited, tries = pg(body, *WORLD)
    assert set(unlimited) == {200} and tries == [404, 404, 429, 429]


# ==== usage metering ========================================================================================

class Failing:
    async def complete(self, *a):
        raise DependencyUnavailable("model down")


def test_model_calls_are_recorded_against_the_tenant_user_and_request_and_only_when_they_succeed(pg):
    async def body(db):
        meter = UsageMeter(db)
        model = MeteredIntentModel(EchoIntentModel(), meter)
        with meter.scope(A, "tenant-a.user", "req-1"):
            await model.complete("contact.list", ("contact.list",), None)
            await model.complete("contact.list", ("contact.list",), None)
        with meter.scope(B, "tenant-b.user", "req-2"):
            await model.complete("contact.list", ("contact.list",), None)
        await model.complete("contact.list", ("contact.list",), None)                       # no scope: not attributable
        with meter.scope(A, "tenant-a.user", "req-3"):
            with pytest.raises(DependencyUnavailable):
                await MeteredIntentModel(Failing(), meter).complete("x", (), None)
        async with db.tenant_transaction(A) as c:
            a = [dict(r) for r in await c.fetch("SELECT request_id, model, total_tokens FROM llm_usage ORDER BY usage_id")]
        async with db.tenant_transaction(B) as c:
            b = await c.fetchval("SELECT count(*) FROM llm_usage")
        return a, b
    a, b = pg(body, *WORLD)
    assert a == [{"request_id": "req-1", "model": "echo", "total_tokens": 1}] * 2 and b == 1


def test_a_request_through_the_api_is_billed_and_the_usage_report_sums_it(pg):
    async def body(db):
        e = await _env(db)
        meter = UsageMeter(db)
        e.app.state.usage_meter = meter
        e.app.state.llm_price_per_million_tokens = 2000000.0
        e.app.state.pipeline = build_runner(db, MeteredIntentModel(EchoIntentModel(), meter))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=e.app), base_url="http://t") as client:
            for _ in range(3):
                run = await client.post("/api/v1/execute", json={"input_data": {"message": "contact.list"}},
                                        headers={"authorization": f"Bearer {e.keys['owner-a']}"})
                assert run.status_code == 200, run.text
        report = (await e.call("owner-a", "GET", "/usage?days=7")).json()
        other = (await e.call(B, "GET", "/usage")).json()
        bad = await e.call(A, "GET", "/usage?days=0")
        denied = await e.call("member-a", "GET", "/usage")
        return report, other, bad.status_code, denied.status_code
    report, other, bad, denied = pg(body, *WORLD)
    assert report["calls"] == 3 and report["total_tokens"] == 3 and report["by_user"][0]["user_id"] == "tenant-a.boss"
    assert report["estimated_cost"] == 6.0 and other["calls"] == 0 and "estimated_cost" in other and (bad, denied) == (422, 403)


# ==== reference writers =====================================================================================

def test_files_and_templates_are_written_by_admins_and_read_by_s1_and_results_by_the_system_writer(pg):
    async def body(db):
        e = await _env(db)
        f1 = await e.call(A, "POST", "/files", {"workspace_id": WS_A, "name": "report.pdf", "mime": "application/pdf", "size_bytes": 10})
        f2 = await e.call(A, "POST", "/files", {"workspace_id": WS_A, "name": "report.pdf", "mime": "application/pdf", "size_bytes": 99})
        bad = [await e.call(A, "POST", "/files", {"workspace_id": WS_A, **x}) for x in (
            {"name": "a/b", "mime": "text/plain", "size_bytes": 1}, {"name": "x", "mime": "nonsense", "size_bytes": 1},
            {"name": "x", "mime": "text/plain", "size_bytes": 10**10}, {"name": "x", "mime": "text/plain", "size_bytes": -1})]
        other_ws = await e.call(A, "POST", "/files", {"workspace_id": "tenant-b.ws", "name": "x", "mime": "text/plain", "size_bytes": 1})
        t1 = await e.call(A, "PUT", "/templates/greeting", {"value": "hello"})
        t2 = await e.call(A, "PUT", "/templates/greeting", {"value": "hello ws", "workspace_id": WS_A})
        badt = [await e.call(A, "PUT", f"/templates/{n}", {"value": v}) for n, v in (("1bad", "x"), ("ok", ""), ("ok", "a\x00b"))]
        source = PostgresReferenceSource(db)
        await PostgresResultWriter(db).record_result(tenant_id=A, user_id="tenant-a.user", conversation_id="c1", summary="first")
        await PostgresResultWriter(db).record_result(tenant_id=A, user_id="tenant-a.user", conversation_id="c1", summary="second")
        with pytest.raises(ValueError):
            await PostgresResultWriter(db).record_result(tenant_id=A, user_id="u", conversation_id="c", summary="x" * 4001)
        got = (await source.file(tenant_id=A, workspace_id=WS_A, name="report.pdf"),
               await source.variable(tenant_id=A, workspace_id=WS_A, name="greeting"),
               await source.previous_result(tenant_id=A, user_id="tenant-a.user", conversation_id="c1", index=1),
               await source.previous_result(tenant_id=A, user_id="tenant-a.user", conversation_id="c1", index=2),
               await source.file(tenant_id=B, workspace_id="tenant-b.ws", name="report.pdf"))
        listing = (await e.call(A, "GET", "/files")).json()["files"], (await e.call(A, "GET", "/templates")).json()["templates"]
        denied = [(await e.call("member-a", m, p, b)).status_code for m, p, b in (
            ("POST", "/files", {"workspace_id": WS_A, "name": "x", "mime": "text/plain", "size_bytes": 1}),
            ("PUT", "/templates/x", {"value": "y"}), ("GET", "/files", None))]
        return f1, f2, bad, other_ws, t1, t2, badt, got, listing, denied, await _audit(db, A)
    f1, f2, bad, other_ws, t1, t2, badt, got, listing, denied, audit = pg(body, *WORLD)
    assert f1.status_code == f2.status_code == 201 and f1.json()["file_id"] == f2.json()["file_id"]
    assert [r.status_code for r in bad] == [422] * 4 and other_ws.status_code == 404
    assert (t1.status_code, t2.status_code) == (204, 204) and [r.status_code for r in badt] == [422] * 3
    file, variable, first, second, leaked = got
    assert (file.name, file.mime, file.size_bytes) == ("report.pdf", "application/pdf", 99)
    assert (variable, first, second, leaked) == ("hello ws", "second", "first", None)
    assert len(listing[0]) == 1 and {t["workspace_id"] for t in listing[1]} == {None, WS_A} and denied == [403, 403, 403]
    assert {"file.register", "template.set"} <= {a["action"] for a in audit}
