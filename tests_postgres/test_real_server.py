"""The production app as a separate OS process over real sockets, on PostgreSQL as a plain
(non-superuser) role: HTTP path, restart survival, multi-tenant isolation, concurrency.

The provider is the fake DeepSeek server (real adapter, real HTTP); everything else is real.
"""
from __future__ import annotations

import asyncio
import collections

import httpx

from tests_postgres.realserver import headers

STAGES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]


# ---- 1. the real server, curl-style ------------------------------------------------------------

def test_server_serves_the_http_path_end_to_end(stack_factory):
    st = stack_factory()
    c = st.client()
    assert c.get("/health").json()["status"] == "healthy"
    assert c.get("/ready").json() == {"status": "ready"}
    assert c.post("/api/v1/execute", json={"input_data": {"message": "list contacts"}}).status_code == 401
    assert st.ask("list contacts", client=c).status_code == 200
    ok = st.ask("list my contact list").json()
    assert (ok["status"], ok["final_stage"]) == ("NORMAL", "S11") and ok["execution_id"]
    # what the provider was actually sent: registry intents only, the user's text last, the key as a bearer
    sent = st.fake.requests[-1]
    assert "Allowed intent values: contact.create, contact.delete, contact.list, unknown, prohibited" \
        in sent["messages"][0]["content"]
    assert st.fake.auth_headers[-1] == "Bearer test-key-not-real"
    assert "Traceback" not in st.server.log()


def test_the_app_runs_as_a_plain_role_with_rls_in_force(stack_factory):
    st = stack_factory()
    st.ask("list contacts")
    assert st.server.proc.poll() is None                       # startup accepted the role
    a = st.rows("tenant-a", "SELECT DISTINCT tenant_id FROM pipeline_events")
    b = st.rows("tenant-b", "SELECT DISTINCT tenant_id FROM pipeline_events")
    assert a == [{"tenant_id": "tenant-a"}] and b == []       # B's session cannot see A's rows


# ---- 4. restart survival -----------------------------------------------------------------------

def test_a_paused_delete_survives_a_hard_kill_and_restart(stack_factory):
    st = stack_factory()
    paused = st.ask("delete contact John Smith").json()
    assert (paused["status"], paused["final_stage"], paused["reason"]) == ("CLARIFY", "S10", "confirmation_required")
    cid = paused["confirmation_id"]

    st.server.stop(kill=True)                                  # SIGKILL: no graceful shutdown
    from tests_postgres.realserver import Server
    fresh = Server(st.database_url, st.fake.endpoint).start()  # a new process, nothing in memory
    try:
        c = httpx.Client(base_url=fresh.url, timeout=30)
        ok = c.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=headers(st.keys["tenant-a"]))
        assert (ok.json()["status"], ok.json()["final_stage"]) == ("NORMAL", "S11")
        again = c.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=headers(st.keys["tenant-a"]))
        assert again.json()["reason"] == "confirmation_mismatch"          # single use, across restarts too
    finally:
        fresh.stop(kill=True)
    trail = [(r["stage"], r["status"]) for r in st.rows(
        "tenant-a", "SELECT stage, status FROM pipeline_events ORDER BY event_id")]
    assert trail[-3:] == [("S10", "normal"), ("S11", "normal"), ("S10", "deny")]


def test_an_expired_confirmation_stays_expired_after_a_restart(stack_factory):
    st = stack_factory()
    cid = st.ask("delete contact Jane").json()["confirmation_id"]
    st.server.stop(kill=True)
    import asyncio as _a
    import asyncpg
    async def expire():
        conn = await asyncpg.connect(st.database_url)
        await conn.execute("UPDATE pending_confirmations SET expires_at = now() - interval '1 second'")
        await conn.close()
    _a.run(expire())
    from tests_postgres.realserver import Server
    fresh = Server(st.database_url, st.fake.endpoint).start()
    try:
        r = httpx.post(f"{fresh.url}/api/v1/confirmations/{cid}", json={"approved": True},
                       headers=headers(st.keys["tenant-a"]), timeout=30)
        assert r.json()["reason"] == "confirmation_expired"
    finally:
        fresh.stop(kill=True)


def test_the_server_refuses_to_start_when_the_database_is_unreachable(stack_factory, database_url):
    from tests_postgres.realserver import Server
    bad = database_url.rsplit(":", 1)[0] + ":1/x"
    try:
        Server(bad, "http://127.0.0.1:1/x").start()
        raise AssertionError("server started against an unreachable database")
    except RuntimeError as exc:
        assert "cannot connect to the database" in str(exc) and "login-pw" not in str(exc)


# ---- 3. multi-tenant isolation over HTTP -------------------------------------------------------

def test_tenants_and_users_cannot_touch_each_others_runs(stack_factory):
    st = stack_factory()
    a = st.ask("delete contact Ann", who="tenant-a").json()
    b = st.ask("delete contact Bob", who="tenant-b").json()
    ca, cb = a["confirmation_id"], b["confirmation_id"]

    assert st.reply(ca, who="tenant-b").status_code == 404                # B cannot see A's confirmation
    assert st.reply(cb, who="tenant-a").status_code == 404                # nor A B's
    other = st.reply(ca, who="other").json()                              # a second user of tenant A
    assert (other["status"], other["reason"]) == ("DENY", "confirmation_mismatch")
    assert st.reply(ca, who="tenant-a").json()["status"] == "NORMAL"      # the wrong tries did not burn it
    assert st.reply(cb, approved=False, who="tenant-b").json()["reason"] == "confirmation_rejected"

    for tenant in ("tenant-a", "tenant-b"):
        seen = st.rows(tenant, "SELECT DISTINCT tenant_id FROM suspended_runs")
        assert seen == [{"tenant_id": tenant}]
        assert {r["tenant_id"] for r in st.rows(tenant, "SELECT tenant_id FROM pipeline_events")} == {tenant}
        assert {r["tenant_id"] for r in st.rows(tenant, "SELECT tenant_id FROM pending_confirmations")} == {tenant}
    traces_a = {r["trace_id"] for r in st.rows("tenant-a", "SELECT trace_id FROM pipeline_events")}
    traces_b = {r["trace_id"] for r in st.rows("tenant-b", "SELECT trace_id FROM pipeline_events")}
    assert traces_a and traces_b and not (traces_a & traces_b)


# ---- 5. concurrency ----------------------------------------------------------------------------

def test_many_parallel_requests_from_two_tenants_all_complete_cleanly(stack_factory):
    st = stack_factory(delay=0.05)                                       # a provider that takes 50 ms
    n = 120

    async def go():
        async with st.async_client() as c:
            async def one(i):
                who = "tenant-a" if i % 2 == 0 else "tenant-b"
                msg = "list contacts" if i % 3 else "create contact"
                r = await c.post("/api/v1/execute", json={"input_data": {"message": msg}},
                                 headers=headers(st.keys[who]))
                return who, r
            return await asyncio.gather(*(one(i) for i in range(n)))

    results = asyncio.run(go())
    assert all(r.status_code == 200 for _, r in results), collections.Counter(r.status_code for _, r in results)
    assert {(r.json()["status"], r.json()["final_stage"]) for _, r in results} == {("NORMAL", "S11")}
    assert len({r.json()["execution_id"] for _, r in results}) == n     # no shared/duplicated runs
    per = collections.Counter(who for who, _ in results)
    for tenant in ("tenant-a", "tenant-b"):
        events = st.rows(tenant, "SELECT trace_id, stage FROM pipeline_events")
        assert len(events) == 12 * per[tenant]                          # every stage of every run, once
        by_trace = collections.defaultdict(list)
        for e in events:
            by_trace[e["trace_id"]].append(e["stage"])
        assert all(sorted(v, key=STAGES.index) == STAGES for v in by_trace.values())
    log = st.server.log()
    assert "Traceback" not in log and "Error" not in log, log[-2000:]


def test_a_confirmation_is_single_use_under_a_race(stack_factory):
    st = stack_factory()
    cid = st.ask("delete contact Race").json()["confirmation_id"]

    async def go():
        async with st.async_client() as c:
            return await asyncio.gather(*(
                c.post(f"/api/v1/confirmations/{cid}", json={"approved": True},
                       headers=headers(st.keys["tenant-a"])) for _ in range(25)))

    outcomes = collections.Counter(
        (r.json()["status"], r.json()["reason"]) for r in asyncio.run(go()))
    assert outcomes[("NORMAL", None)] == 1, outcomes                     # exactly one wins
    assert sum(outcomes.values()) == 25 and set(outcomes) <= {("NORMAL", None), ("DENY", "confirmation_mismatch")}
    assert st.rows("tenant-a", "SELECT status FROM pending_confirmations") == [{"status": "consumed"}]


def test_a_burst_of_pending_deletes_can_all_be_answered_in_parallel(stack_factory):
    st = stack_factory(delay=0.02)

    async def go():
        async with st.async_client() as c:
            paused = await asyncio.gather(*(
                c.post("/api/v1/execute", json={"input_data": {"message": f"delete contact n{i}"}},
                       headers=headers(st.keys["tenant-a"])) for i in range(40)))
            cids = [p.json()["confirmation_id"] for p in paused]
            done = await asyncio.gather(*(
                c.post(f"/api/v1/confirmations/{cid}", json={"approved": True},
                       headers=headers(st.keys["tenant-a"])) for cid in cids))
            return cids, done

    cids, done = asyncio.run(go())
    assert len(set(cids)) == 40
    assert {(d.json()["status"], d.json()["final_stage"]) for d in done} == {("NORMAL", "S11")}
    assert len({d.json()["execution_id"] for d in done}) == 40


def test_the_server_stays_healthy_after_the_burst(stack_factory):
    st = stack_factory()

    async def go():
        async with st.async_client() as c:
            await asyncio.gather(*(c.post("/api/v1/execute", json={"input_data": {"message": "list contacts"}},
                                          headers=headers(st.keys["tenant-a"])) for _ in range(150)))
    asyncio.run(go())
    assert httpx.get(f"{st.server.url}/ready", timeout=10).json() == {"status": "ready"}
    assert st.ask("list contacts").json()["status"] == "NORMAL"
