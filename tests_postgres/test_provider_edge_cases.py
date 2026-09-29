"""Provider failure modes over REAL HTTP against a fake DeepSeek (real adapter, real app, real DB).

The provider's behaviour is chosen by a marker in the message ("[[429]] list contacts"). What is
being proven is how the pipeline reacts, not what DeepSeek really does: the real API's behaviour
for these cases must still be observed live (see the PR description).
"""
from __future__ import annotations

import time

import pytest

OK = ("NORMAL", "S11", None)


@pytest.fixture
def st(stack_factory):
    return stack_factory(model_timeout=1.0)


def _outcome(r):
    j = r.json()
    return j["status"], j["final_stage"], j["reason"]


def _stages(st, trace_id):
    return [(e["stage"], e["status"], e["reason"]) for e in st.rows(
        "tenant-a", "SELECT stage, status, reason FROM pipeline_events WHERE trace_id = $1 ORDER BY event_id",
        trace_id)]


# ---- answers the model can get wrong: S2 rejects them, retries once, then asks the user -------------

@pytest.mark.parametrize("marker,expected,upstream_calls", [
    ("empty-once",  OK, 2),                                            # empty, then fine on the retry
    ("trunc-once",  OK, 2),                                            # cut off, then fine
    ("empty",       ("CLARIFY", "S2", "intent_unparseable"), 2),
    ("trunc",       ("CLARIFY", "S2", "intent_unparseable"), 2),
    ("notjson",     ("CLARIFY", "S2", "intent_unparseable"), 2),      # prose instead of JSON
    ("wrongintent", ("CLARIFY", "S2", "intent_unparseable"), 2),      # an intent the registry never offered
    ("badconf",     ("CLARIFY", "S2", "intent_unparseable"), 2),      # confidence is not a number
])
def test_a_bad_answer_is_retried_once_then_the_user_is_asked(st, marker, expected, upstream_calls):
    text = f"[[{marker}]] list contacts {marker}"
    r = st.ask(text)
    assert r.status_code == 200 and _outcome(r) == expected
    assert st.fake.calls_for(f"list contacts {marker}") == upstream_calls
    if expected != OK:
        assert r.json()["execution_id"] is None                         # no plan for a request we did not understand
        assert _stages(st, r.json()["trace_id"])[-1] == ("S2", "clarify", "intent_unparseable")


def test_the_retry_carries_the_reason_the_first_answer_was_rejected(st):
    st.ask("[[empty-once]] list contacts feedback-check")
    first, second = [q for q in st.fake.requests if "feedback-check" in q["messages"][1]["content"]][:2]
    assert len(first["messages"]) == 2 and len(second["messages"]) == 3
    assert "previous answer was rejected" in second["messages"][2]["content"]


# ---- the provider itself failing: fail closed, never guess ------------------------------------------

@pytest.mark.parametrize("marker", ["429", "402", "401", "500", "503", "garbage", "nochoices", "filter"])
def test_a_provider_failure_stops_the_run_at_s2_without_guessing(st, marker):
    r = st.ask(f"[[{marker}]] list contacts fail-{marker}")
    assert r.status_code == 200 and _outcome(r) == ("ERROR", "S2", "llm_unavailable")
    assert st.fake.calls_for(f"fail-{marker}") == 1                     # an outage is not retried as if it were a bad answer
    body = r.text
    assert "simulated" not in body and "gateway" not in body           # no upstream error text reaches the client
    assert r.json()["execution_id"] is None
    assert _stages(st, r.json()["trace_id"])[-1] == ("S2", "error", "llm_unavailable")
    assert [s for s, *_ in _stages(st, r.json()["trace_id"])] == ["S0", "S1", "S2"]     # nothing after S2 ran


def test_a_slow_provider_is_cut_off_by_the_timeout(st):
    t0 = time.time()
    r = st.ask("[[slow]] list contacts slow")
    assert _outcome(r) == ("ERROR", "S2", "llm_unavailable")
    assert time.time() - t0 < 4                                          # the provider sleeps 5 s; the 1 s timeout wins


def test_the_server_keeps_serving_after_every_kind_of_failure(st):
    for marker in ("429", "garbage", "slow", "empty", "filter", "500"):
        st.ask(f"[[{marker}]] list contacts")
    ok = st.ask("list contacts after the storm")
    assert _outcome(ok) == OK
    assert st.server.proc.poll() is None and "Traceback" not in st.server.log()


# ---- the API key ------------------------------------------------------------------------------------

def test_the_key_is_sent_to_the_provider_and_never_leaks(st):
    for marker in ("ok", "429", "500", "garbage", "empty"):
        r = st.ask(f"[[{marker}]] list contacts key-{marker}")
        assert "test-key-not-real" not in r.text
    assert set(st.fake.auth_headers) == {"Bearer test-key-not-real"}
    assert "test-key-not-real" not in st.server.log()                   # not in the server's logs either


def test_a_provider_error_does_not_leak_into_the_event_log(st):
    r = st.ask("[[402]] list contacts")
    events = st.rows("tenant-a", "SELECT reason FROM pipeline_events WHERE trace_id = $1", r.json()["trace_id"])
    assert all("simulated" not in (e["reason"] or "") and "402" not in (e["reason"] or "") for e in events)


# ---- a failure never opens a door -------------------------------------------------------------------

def test_a_provider_outage_never_lets_a_delete_through(st):
    r = st.ask("[[500]] delete contact Everyone")
    assert _outcome(r) == ("ERROR", "S2", "llm_unavailable")
    assert st.rows("tenant-a", "SELECT count(*) AS n FROM pending_confirmations") == [{"n": 0}]
    assert st.rows("tenant-a", "SELECT count(*) AS n FROM suspended_runs") == [{"n": 0}]
