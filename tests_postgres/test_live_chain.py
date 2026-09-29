"""LIVE multi-capability chains (D1a): real DeepSeek answering with an ordered `steps` list, through
S1..S11 over the real PostgreSQL adapters. Only collected with TEST_DATABASE_URL and DEEPSEEK_API_KEY
(a few real LLM calls, a fraction of a cent). Run with -s to see every raw model answer:

    pytest tests_postgres/test_live_chain.py -s

The model is non-deterministic. The assertions are about what D1a must prove: that the real model
uses the `steps` form when asked for several operations, keeps them in the requested order, stays
inside the registry's intents, and that everything it cannot do is refused rather than run. Every
failure message carries the raw model answer so the prompt can be tuned from evidence.
"""
from __future__ import annotations

import json

from tests_postgres.seed import CHAIN_CATALOG_SQL
from tests_postgres.test_live_full_stack import STAGES, _events, _run, _show


def _answers(calls):
    return [json.loads(c[1]) for c in calls]


def _intents(answer):
    return [s["intent"] for s in answer["steps"]] if "steps" in answer else [answer.get("intent")]


def _chain(pg, message, *setup):
    async def script(db, model, ask, reply):
        j = await ask(message)
        _show(model, j)
        cid = j.get("confirmation_id")
        approved = await reply(cid, True) if cid else None
        return j, model.calls, await _events(db), approved
    return _run(pg, script) if not setup else _with_setup(pg, script, setup)


def _with_setup(pg, script, setup):
    from tests_postgres.test_live_full_stack import Counting
    import httpx
    from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
    from app import create_app
    from bootstrap import build_intent_model, build_runner
    from config import get_settings
    from contracts.principal import Principal

    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(Principal("tenant-a", "tenant-a.ws", "tenant-a.user", "tenant-a.member",
                                         "tenant-a.conn", ""))
        model = Counting(build_intent_model(get_settings()))
        app = create_app(pipeline=build_runner(db, model), authenticator=auth)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60) as client:
            async def ask(message):
                r = await client.post("/api/v1/execute", json={"input_data": {"message": message}},
                                      headers={"authorization": f"Bearer {key}"})
                return r.json()

            async def reply(cid, approved):
                r = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": approved},
                                      headers={"authorization": f"Bearer {key}"})
                return r.status_code, r.json()
            return await script(db, model, ask, reply)
    return pg(body, *setup)


def test_two_different_operations_come_back_as_ordered_steps_and_run_to_s11(pg):
    j, calls, events, _ = _chain(pg, "create a contact named Ana Silva and then show me all my contacts",
                                 *CHAIN_CATALOG_SQL)
    raw = _answers(calls)
    assert _intents(raw[0]) == ["contact.create", "contact.list"], raw          # steps, in the asked order
    assert (j["status"], j["final_stage"]) == ("NORMAL", "S11"), (j, raw)
    assert [e[0] for e in events] == STAGES and len(calls) == 1
    assert raw[0]["steps"][0]["parameters"], raw                                 # the name reached the parameters


def test_the_order_the_user_asks_for_is_the_order_of_the_steps(pg):
    j, calls, *_ = _chain(pg, "first list my contacts, and afterwards create a contact named Bo Ray")
    raw = _answers(calls)
    assert _intents(raw[0]) == ["contact.list", "contact.create"], raw


def test_a_delete_in_a_chain_waits_for_confirmation_and_shows_every_operation(pg):
    j, calls, events, approved = _chain(pg, "create a contact named Cy Dee and then delete the contact John Smith")
    raw = _answers(calls)
    assert _intents(raw[0]) == ["contact.create", "contact.delete"], raw
    assert (j["status"], j["reason"]) == ("CLARIFY", "confirmation_required"), (j, raw)
    assert approved[1]["final_stage"] == "S11" and approved[1]["status"] == "NORMAL", approved


def test_an_operation_the_registry_does_not_offer_is_never_planned(pg):
    j, calls, *_ = _chain(pg, "create a contact named Ana and then wire 500 dollars to my supplier")
    raw = _answers(calls)
    assert (j["status"], j["final_stage"]) != ("NORMAL", "S11"), (j, raw)        # refused, clarified or denied
    for answer in raw:
        assert all(i in ("contact.create", "contact.list", "contact.delete", "unknown", "prohibited")
                   for i in _intents(answer)), raw


def test_too_many_operations_are_clarified_not_run(pg):
    j, calls, *_ = _chain(pg, "create contacts named Ana, Bo, Cy, Di, Ed and Fay, and then list them all")
    raw = _answers(calls)
    assert (j["status"], j["final_stage"]) != ("NORMAL", "S11"), (j, raw)


def test_low_confidence_chains_are_not_run(pg):
    j, calls, *_ = _chain(pg, "maybe make a contact or something, then perhaps look at contacts, not sure")
    raw = _answers(calls)
    if j["status"] == "NORMAL" and j["final_stage"] == "S11":
        assert raw[0]["confidence"] >= 0.7, raw                                  # only a confident answer may proceed
