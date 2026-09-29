"""
HTTP entry (A8): one execution path, identity only from the authenticator, fail closed.
"""
from fastapi.testclient import TestClient

from app import create_app
from engine.control_plane.api import Principal
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_pipeline_deps
from tests.fixtures.scenarios import make_scenario


class _Auth:
    def __init__(self, principal):
        self.principal = principal

    async def authenticate(self, request):
        return self.principal if request.headers.get("authorization") == "Bearer ok" else None


PRINCIPAL = Principal(tenant_id="tenant-A", workspace_id="ws-A", user_id="user-A")
HEADERS = {"authorization": "Bearer ok"}
BODY = {"input_data": {"message": "list users"}, "connection_id": "conn-1"}


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


def test_denied_run_reports_stage_and_reason():
    r = _client().post("/api/v1/execute", json={"input_data": {"message": "x"}}, headers=HEADERS)
    j = r.json()                                   # no connection_id -> S8 denies
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S8", "connection_active_missing_id")


def test_confirmation_pause_returns_confirmation_id():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    j = _client(sc).post("/api/v1/execute", json=BODY, headers=HEADERS).json()
    assert (j["status"], j["final_stage"], j["reason"]) == ("CLARIFY", "S10", "confirmation_required")
    assert j["confirmation_id"]


def test_old_engine_is_gone():
    import importlib.util
    assert importlib.util.find_spec("engine.control_plane.pipeline") is None
