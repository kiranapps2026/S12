"""
GOLDEN TEST FILE (OWNER). Pinned by hash; the agent must not edit it.
Rulings: runbook R-R (S10 writes ConfirmationOutcome), R-Z (store receives tenant_id and
execution_id), C20 (conditional consume: expiry, user and plan_hash must match).

Fixture contract (in addition to test_s6_task_profile.py header):
  scenario.confirmation_store  the PRODUCTION in-memory confirmation store instance that
      run_stage passes to S10, wrapped so it records every save call in
      `.saves` as tuples (confirmation, tenant_id, execution_id). The wrapper must delegate
      to the production store; it must not change results.
  consume(scenario, confirmation_id, *, user_id, plan_hash, now) -> str
      calls the production store's conditional consume and returns exactly one of:
      "consumed", "confirmation_expired", "confirmation_mismatch".
"""
import time

from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import consume, run_stage, state_ready_for

HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
LOW = dict(mutation="R", risk=0.1, steps=1, graph="simple", confidence=0.95)


def _required_state():
    sc = make_scenario(**HIGH)
    state = state_ready_for("S10", sc)
    out = run_stage("S10", state, sc)
    return sc, state, out


def test_s10_not_required_writes_outcome():
    sc = make_scenario(**LOW)
    out = run_stage("S10", state_ready_for("S10", sc), sc)
    assert out.confirmation.required is False
    assert out.confirmation.confirmation is None
    assert sc.confirmation_store.saves == []


def test_s10_required_creates_pending_confirmation():
    before = time.time()
    sc, state, out = _required_state()
    assert out.confirmation.required is True
    c = out.confirmation.confirmation
    s9 = state.get_stage_output("S9")
    ctx = state.execution_context
    assert (c.plan_id, c.plan_hash) == (s9.plan.id, s9.plan_hash)
    assert (c.user_id, c.conversation_id) == (ctx.user_id, ctx.conversation_id)
    assert c.consumed_at is None
    assert before + 295 <= c.expires_at <= time.time() + 305
    assert isinstance(c.operations, tuple)


def test_s10_store_receives_tenant_and_execution_id():
    sc, state, out = _required_state()
    assert len(sc.confirmation_store.saves) == 1
    saved, tenant_id, execution_id = sc.confirmation_store.saves[0]
    assert saved == out.confirmation.confirmation
    assert tenant_id == state.execution_context.tenant_id
    assert execution_id == state.get_stage_output("S9").execution_id


def test_s10_expired_denies():
    sc, state, out = _required_state()
    c = out.confirmation.confirmation
    result = consume(sc, c.confirmation_id, user_id=c.user_id, plan_hash=c.plan_hash,
                     now=c.expires_at + 1)
    assert result == "confirmation_expired"


def test_s10_wrong_user_denies():
    sc, state, out = _required_state()
    c = out.confirmation.confirmation
    result = consume(sc, c.confirmation_id, user_id="someone-else", plan_hash=c.plan_hash,
                     now=time.time())
    assert result == "confirmation_mismatch"


def test_s10_wrong_hash_denies():
    sc, state, out = _required_state()
    c = out.confirmation.confirmation
    result = consume(sc, c.confirmation_id, user_id=c.user_id, plan_hash="0" * 64,
                     now=time.time())
    assert result == "confirmation_mismatch"
    # the genuine consume still works exactly once afterwards
    assert consume(sc, c.confirmation_id, user_id=c.user_id, plan_hash=c.plan_hash,
                   now=time.time()) == "consumed"
    assert consume(sc, c.confirmation_id, user_id=c.user_id, plan_hash=c.plan_hash,
                   now=time.time()) == "confirmation_mismatch"
