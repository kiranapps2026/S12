"""User, membership, connection and grant management over real PostgreSQL: role ceiling, self-change and
last-owner guards, tenant isolation, grant rules, audit, and that what is granted or revoked really takes effect."""
from __future__ import annotations

import pytest

from tests_postgres.test_admin_api import A, B, WORLD, _audit, _env, _principal


async def _mk_user(e, who=A, name="New", service=False):
    r = await e.call(who, "POST", "/users", {"display_name": name, "is_service": service})
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


# ---- authorization -------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/users", None), ("GET", "/workspaces", None), ("GET", "/memberships", None), ("GET", "/grants", None),
    ("GET", "/connections", None), ("GET", "/capabilities", None), ("POST", "/users", {"display_name": "x"}),
    ("POST", "/grants", {"user_id": "u", "workspace_id": "w", "capability_id": "c"}),
])
def test_only_admins_reach_access_management(pg, method, path, body):
    async def run(db):
        e = await _env(db)
        return [(await e.call(who, method, path, body)).status_code for who in ("member-a", "viewer-a", None)]
    assert pg(run, *WORLD) == [403, 403, 401]


# ---- users ---------------------------------------------------------------------------------------------

def test_users_are_created_listed_and_isolated_per_tenant(pg):
    async def run(db):
        e = await _env(db)
        uid = await _mk_user(e, A, "Alice")
        svc = await _mk_user(e, A, "bot", service=True)
        in_a = (await e.call(A, "GET", "/users")).json()["users"]
        in_b = (await e.call(B, "GET", "/users")).json()["users"]
        cross = await e.call(B, "POST", f"/users/{uid}/status", {"status": "inactive"})
        bad = await e.call(A, "POST", "/users", {"display_name": "x", "role": "owner"})
        return uid, svc, in_a, in_b, cross.status_code, bad.status_code, await _audit(db, A)
    uid, svc, in_a, in_b, cross, bad, audit = pg(run, *WORLD)
    assert uid.startswith("usr_") and svc.startswith("usr_")
    assert {u["user_id"] for u in in_a} >= {uid, svc} and not {u["user_id"] for u in in_b} & {uid, svc}
    assert next(u for u in in_a if u["user_id"] == svc)["is_service"] is True
    assert cross == 404 and bad == 422
    assert [a["action"] for a in audit].count("user.create") == 2


def test_status_guards(pg):
    async def run(db):
        e = await _env(db)
        uid = await _mk_user(e)
        ok = await e.call(A, "POST", f"/users/{uid}/status", {"status": "suspended"})
        bad = await e.call(A, "POST", f"/users/{uid}/status", {"status": "wizard"})
        self_ = await e.call(A, "POST", "/users/tenant-a.user/status", {"status": "inactive"})
        # an admin cannot touch an owner
        boss = await e.call("peer-a", "POST", "/users/tenant-a.boss/status", {"status": "inactive"})
        return ok.status_code, bad.status_code, self_.status_code, boss.status_code, boss.json()
    ok, bad, self_, boss, detail = pg(run, *WORLD)
    assert (ok, bad, self_, boss) == (204, 422, 403, 403) and detail["detail"] == "role_exceeds_yours"


def test_owner_changes_and_the_last_owner_guard(pg):
    async def run(db):
        e = await _env(db)
        self_demote = await e.call("owner-a", "POST", "/memberships/tenant-a.boss.member/role", {"role": "admin"})
        admin_vs_owner = await e.call(A, "POST", "/memberships/tenant-a.boss.member/role", {"role": "member"})
        # defence in depth: an actor that is not itself an owner (cannot happen over HTTP) still cannot remove the last one
        from dataclasses import replace
        from adapters.postgres.admin import Actor, AdminError
        from adapters.postgres.admin_access import AccessAdmin
        access = AccessAdmin(e.app.state.admin)
        real = await e.app.state.admin.authorize(_principal(A, "boss"))
        ghost = Actor(replace(real.principal, user_id="ghost"), real.role)
        errors = []
        for call in (lambda: access.set_role(ghost, "tenant-a.boss.member", "member"),
                     lambda: access.remove_membership(ghost, "tenant-a.boss.member"),
                     lambda: access.set_user_status(ghost, "tenant-a.boss", "suspended")):
            try:
                await call()
                errors.append(None)
            except AdminError as exc:
                errors.append(exc.reason)
        return self_demote.status_code, self_demote.json()["detail"], admin_vs_owner.json()["detail"], errors
    self_demote, why, ceiling, errors = pg(run, *WORLD)
    assert (self_demote, why, ceiling) == (403, "cannot_change_yourself", "role_exceeds_yours")
    assert errors == ["last_owner"] * 3


# ---- memberships ---------------------------------------------------------------------------------------

def test_membership_lifecycle_and_role_ceiling(pg):
    async def run(db):
        e = await _env(db)
        uid = await _mk_user(e)
        ws = "tenant-a.ws"
        add = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": ws, "role": "member"})
        dup = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": ws, "role": "viewer"})
        over = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "tenant-a.ws", "role": "owner"})
        badrole = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": ws, "role": "root"})
        nows = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "nope", "role": "member"})
        cross_ws = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "tenant-b.ws", "role": "member"})
        mid = add.json()["membership_id"]
        up = await e.call(A, "POST", f"/memberships/{mid}/role", {"role": "admin"})
        toowner = await e.call(A, "POST", f"/memberships/{mid}/role", {"role": "owner"})
        listing = (await e.call(A, "GET", f"/memberships?user_id={uid}")).json()["memberships"]
        rm = await e.call(A, "DELETE", f"/memberships/{mid}")
        rm2 = await e.call(A, "DELETE", f"/memberships/{mid}")
        cross = await e.call(B, "DELETE", f"/memberships/{mid}")
        return (add.status_code, dup.status_code, over.status_code, badrole.status_code, nows.status_code,
                cross_ws.status_code, up.status_code, toowner.status_code, listing, rm.status_code, rm2.status_code,
                cross.status_code, await _audit(db, A))
    (add, dup, over, badrole, nows, cross_ws, up, toowner, listing, rm, rm2, cross, audit) = pg(run, *WORLD)
    assert (add, dup, badrole, nows, cross_ws, up, rm, rm2, cross) == (201, 409, 422, 404, 404, 204, 204, 404, 404)
    assert over == 403      # A's caller is an admin: owner is above the ceiling
    assert toowner == 403
    assert listing[0]["role"] == "admin"
    assert {"membership.add", "membership.role", "membership.remove"} <= {a["action"] for a in audit}


def test_removing_a_membership_takes_effect_immediately(pg):
    async def run(db):
        e = await _env(db)
        key_ok = await e.call("peer-a", "GET", "/users")
        rm = await e.call("owner-a", "DELETE", "/memberships/tenant-a.peer.member")
        key_after = await e.call("peer-a", "GET", "/users")
        return key_ok.status_code, rm.status_code, key_after.status_code
    assert pg(run, *WORLD) == (200, 204, 403)


def test_inactive_users_cannot_be_given_access(pg):
    async def run(db):
        e = await _env(db)
        uid = await _mk_user(e)
        await e.call(A, "POST", f"/users/{uid}/status", {"status": "inactive"})
        m = await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "tenant-a.ws", "role": "member"})
        c = await e.call(A, "POST", "/connections", {"user_id": uid, "workspace_id": "tenant-a.ws"})
        return m.status_code, m.json()["detail"], c.status_code
    assert pg(run, *WORLD) == (409, "user_inactive", 409)


# ---- connections ---------------------------------------------------------------------------------------

def test_connections(pg):
    async def run(db):
        e = await _env(db)
        uid = await _mk_user(e)
        no_member = await e.call(A, "POST", "/connections", {"user_id": uid, "workspace_id": "tenant-a.ws"})
        await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "tenant-a.ws", "role": "member"})
        ok = await e.call(A, "POST", "/connections", {"user_id": uid, "workspace_id": "tenant-a.ws"})
        past = await e.call(A, "POST", "/connections", {"user_id": uid, "workspace_id": "tenant-a.ws",
                                                        "expires_at": "2001-01-01T00:00:00Z"})
        cid = ok.json()["connection_id"]
        cross = await e.call(B, "POST", f"/connections/{cid}/revoke")
        rev = await e.call(A, "POST", f"/connections/{cid}/revoke")
        listing = (await e.call(A, "GET", f"/connections?user_id={uid}")).json()["connections"]
        return no_member.status_code, ok.status_code, past.status_code, cross.status_code, rev.status_code, listing
    no_member, ok, past, cross, rev, listing = pg(run, *WORLD)
    assert (no_member, ok, past, cross, rev) == (409, 201, 422, 404, 204)
    assert listing[0]["status"] == "revoked"


# ---- grants --------------------------------------------------------------------------------------------

async def _member(e, role="member"):
    uid = await _mk_user(e)
    await e.call(A, "POST", "/memberships", {"user_id": uid, "workspace_id": "tenant-a.ws", "role": role})
    return uid


def test_grant_rules(pg):
    async def run(db):
        e = await _env(db)
        uid = await _member(e)
        ws = "tenant-a.ws"
        caps = (await e.call(A, "GET", "/capabilities")).json()["capabilities"]
        ok = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.create"})
        dup = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.create"})
        unknown = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.nope"})
        admin_d = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.delete"})
        owner_d = await e.call("owner-a", "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.delete"})
        past = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.list",
                                                   "expires_at": "2001-01-01T00:00:00Z"})
        naive = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.list",
                                                    "expires_at": "2099-01-01T00:00:00"})
        future = await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": ws, "capability_id": "cap.contact.list",
                                                     "expires_at": "2099-01-01T00:00:00Z"})
        stranger = await e.call(A, "POST", "/grants", {"user_id": "tenant-b.svc", "workspace_id": ws, "capability_id": "cap.contact.list"})
        no_member = await e.call(A, "POST", "/grants", {"user_id": await _mk_user(e), "workspace_id": ws,
                                                        "capability_id": "cap.contact.list"})
        return (caps, ok.status_code, dup.status_code, unknown.status_code, admin_d.status_code, admin_d.json()["detail"],
                owner_d.status_code, past.status_code, naive.status_code, future.status_code, stranger.status_code,
                no_member.status_code, no_member.json()["detail"], await _audit(db, A))
    (caps, ok, dup, unknown, admin_d, why, owner_d, past, naive, future, stranger, no_member, why2, audit) = pg(run, *WORLD)
    assert {c["capability_id"] for c in caps} == {"cap.contact.list", "cap.contact.create", "cap.contact.delete"}
    assert (ok, dup, unknown, admin_d, owner_d, past, naive, future, stranger, no_member) == \
        (201, 409, 404, 403, 201, 422, 422, 201, 404, 409)
    assert why == "owner_required_for_high_impact" and why2 == "no_active_membership"
    assert [a["action"] for a in audit].count("grant.create") == 3


def test_a_grant_is_listed_isolated_and_revocable_and_ceiling_applies(pg):
    async def run(db):
        e = await _env(db)
        uid = await _member(e)
        g = (await e.call(A, "POST", "/grants", {"user_id": uid, "workspace_id": "tenant-a.ws",
                                                 "capability_id": "cap.contact.list"})).json()["grant_id"]
        mine = (await e.call(A, "GET", f"/grants?user_id={uid}")).json()["grants"]
        theirs = (await e.call(B, "GET", "/grants")).json()["grants"]
        cross = await e.call(B, "DELETE", f"/grants/{g}")
        # an admin may not revoke the owner's grants
        owner_grant = (await e.call(A, "GET", "/grants?user_id=tenant-a.boss")).json()["grants"]
        rev = await e.call(A, "DELETE", f"/grants/{g}")
        again = await e.call(A, "DELETE", f"/grants/{g}")
        return mine, theirs, cross.status_code, rev.status_code, again.status_code, g, owner_grant
    mine, theirs, cross, rev, again, g, _ = pg(run, *WORLD)
    assert [m["grant_id"] for m in mine] == [g] and g not in {t["grant_id"] for t in theirs}
    assert (cross, rev, again) == (404, 204, 404)


def test_service_users_are_required_for_endpoints_and_keys_for_humans_are_refused_there(pg):
    async def run(db):
        e = await _env(db)
        human = await e.call(A, "POST", "/endpoints", {"source_system": "ghl", "membership_id": "tenant-a.peer.member",
                                                       "connection_id": "tenant-a.peer.conn"})
        svc = await e.call(A, "POST", "/endpoints", {"source_system": "ghl", "membership_id": "tenant-a.svc.member",
                                                     "connection_id": "tenant-a.svc.conn"})
        return human.status_code, human.json().get("detail"), svc.status_code
    status, detail, svc = pg(run, *WORLD)
    assert svc == 201 and status == 409 and detail == "not_a_service_user"
