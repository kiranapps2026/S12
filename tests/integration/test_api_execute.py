"""
HTTP entry (A8): one execution path, identity only from the authenticator, fail closed.
"""
from fastapi.testclient import TestClient

from app import create_app
from contracts.principal import Principal
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_pipeline_deps
from tests.fixtures.scenarios import make_scenario


class _Auth:
    def __init__(self, principal):
        self.principal = principal

    async def authenticate(self, credential):
        return self.principal if credential == "ok" else None


PRINCIPAL = Principal(tenant_id="tenant-A", workspace_id="ws-A", user_id="user-A",
                      membership_id="m-A", connection_id="conn-1", resource_scope="")
HEADERS = {"authorization": "Bearer ok"}
BODY = {"input_data": {"message": "list users"}}


def _client(scenario=None, auth=True, pipeline=True):
    sc = scenario or make_scenario()
    app = create_app(
        pipeline=build_pipeline(make_pipeline_deps(sc)) if pipeline else None,
        authenticator=_Auth(PRINCIPAL) if auth else None,
    )
    return TestClient(app)


def test_no_authenticator_configured_is_503():
    r = _client(auth=False).post("/api/v1/execute", json=BODY, headers=HEADERS)
    assert (r.status_code, r.json()["detail"]) == (503, "authentication_unavailable")


def test_unauthenticated_is_401():
    assert _client().post("/api/v1/execute", json=BODY).status_code == 401


def test_no_pipeline_is_503():
    r = _client(pipeline=False).post("/api/v1/execute", json=BODY, headers=HEADERS)
    assert (r.status_code, r.json()["detail"]) == (503, "pipeline_unavailable")


def test_body_cannot_carry_identity():
    body = {**BODY, "tenant_id": "tenant-EVIL"}
    assert _client().post("/api/v1/execute", json=body, headers=HEADERS).status_code == 422


def test_authenticated_run_completes():
    r = _client().post("/api/v1/execute", json=BODY, headers=HEADERS)
    j = r.json()
    assert r.status_code == 200
    assert (j["status"], j["final_stage"]) == ("NORMAL", "S11")
    assert j["execution_id"] and j["trace_id"] and j["confirmation_id"] is None


def test_body_cannot_choose_the_connection():
    body = {**BODY, "connection_id": "conn-EVIL"}
    assert _client().post("/api/v1/execute", json=body, headers=HEADERS).status_code == 422


def test_denied_run_reports_stage_and_reason():
    from tests.fixtures.deps import ConfigurableAuthState, make_s8_deps
    sc = make_scenario()
    deps = make_pipeline_deps(sc, s8=make_s8_deps(kill_switch=False, auth=ConfigurableAuthState(tenant="suspended")))
    app = create_app(pipeline=build_pipeline(deps), authenticator=_Auth(PRINCIPAL))
    j = TestClient(app).post("/api/v1/execute", json=BODY, headers=HEADERS).json()
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S8", "tenant_active_inactive")


def test_confirmation_pause_returns_confirmation_id():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    j = _client(sc).post("/api/v1/execute", json=BODY, headers=HEADERS).json()
    assert (j["status"], j["final_stage"], j["reason"]) == ("CLARIFY", "S10", "confirmation_required")
    assert j["confirmation_id"]


def test_old_engine_is_gone():
    import importlib.util
    assert importlib.util.find_spec("engine.control_plane.pipeline") is None


# ---- confirmation reply route ---------------------------------------------------------

HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)


def _reply(client, cid, approved=True, headers=HEADERS, **extra):
    return client.post(f"/api/v1/confirmations/{cid}", json={"approved": approved, **extra}, headers=headers)


def _pending(client):
    j = client.post("/api/v1/execute", json=BODY, headers=HEADERS).json()
    assert (j["status"], j["reason"]) == ("CLARIFY", "confirmation_required")
    return j["confirmation_id"]


def test_approving_a_pending_confirmation_completes_the_run_once():
    client = _client(make_scenario(**HIGH))
    cid = _pending(client)
    ok = _reply(client, cid).json()
    assert (ok["status"], ok["final_stage"]) == ("NORMAL", "S11") and ok["execution_id"]
    again = _reply(client, cid).json()
    assert (again["status"], again["reason"]) == ("DENY", "confirmation_mismatch")


def test_rejecting_cancels_the_run():
    client = _client(make_scenario(**HIGH))
    cid = _pending(client)
    j = _reply(client, cid, approved=False).json()
    assert (j["status"], j["reason"]) == ("DENY", "confirmation_rejected")
    assert _reply(client, cid).json()["reason"] == "confirmation_mismatch"


def test_reply_to_an_unknown_confirmation_is_404():
    r = _reply(_client(make_scenario(**HIGH)), "nope")
    assert (r.status_code, r.json()["detail"]) == (404, "confirmation_not_found")


def test_reply_needs_authentication_and_rejects_extra_fields():
    client = _client(make_scenario(**HIGH))
    cid = _pending(client)
    assert _reply(client, cid, headers={}).status_code == 401
    assert _reply(client, cid, user_id="someone-else").status_code == 422
    assert _reply(client, cid).status_code == 200


def test_reply_answers_503_when_nothing_is_wired():
    assert _reply(_client(pipeline=False), "x").status_code == 503
