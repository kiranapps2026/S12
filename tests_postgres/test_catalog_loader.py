"""Loading a catalog into PostgreSQL: one transaction, no deletes, versions must move with the content, and what is loaded
really lets a request run from S0 through S11 and into S12 admission."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from adapters.postgres import catalog
from tests_postgres.test_admission import A, CHAIN, _admit, _certified

EXAMPLE = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs" / "catalog" / "catalog.example.yaml").read_text(encoding="utf-8"))
EMPTY = ("TRUNCATE capability_grants, bindings, capabilities, kernel_ops, registry_versions CASCADE",)


async def _rows(db, sql):
    async with db.transaction() as c:
        return [dict(r) for r in await c.fetch(sql)]


def test_a_catalog_is_applied_once_and_reapplying_it_changes_nothing(pg):
    async def body(db):
        first = await catalog.apply(db, copy.deepcopy(EXAMPLE))
        again = await catalog.apply(db, copy.deepcopy(EXAMPLE))
        ops = await _rows(db, "SELECT kernel_op_id, observation_method, observation_expects_absent, inverse FROM kernel_ops ORDER BY 1")
        versions = await _rows(db, "SELECT capability_version, model_version FROM registry_versions")
        return first, again, ops, versions
    first, again, ops, versions = pg(body, *EMPTY)
    assert len(first.add["kernel_ops"]) == 3 and not again.content_changes and not again.versions_change
    assert {o["kernel_op_id"]: (o["observation_method"], o["observation_expects_absent"], o["inverse"]) for o in ops} == {
        "crm.contact_create": ("get_contact", False, "crm.contact_delete"),
        "crm.contact_delete": ("get_contact", True, None), "crm.contact_list": (None, False, None)}
    assert versions == [{"capability_version": "cap-1", "model_version": "model-1"}]


def test_changing_content_without_bumping_the_versions_is_refused_and_writes_nothing(pg):
    async def body(db):
        await catalog.apply(db, copy.deepcopy(EXAMPLE))
        changed = copy.deepcopy(EXAMPLE)
        changed["kernel_ops"][1]["cost"] = 9
        with pytest.raises(ValueError, match="versions did not"):
            await catalog.apply(db, changed)
        unchanged_cost = (await _rows(db, "SELECT cost FROM kernel_ops WHERE kernel_op_id = 'crm.contact_create'"))[0]["cost"]
        changed["versions"]["capability"] = "cap-2"
        await catalog.apply(db, changed)
        new_cost = (await _rows(db, "SELECT cost FROM kernel_ops WHERE kernel_op_id = 'crm.contact_create'"))[0]["cost"]
        return unchanged_cost, new_cost
    assert pg(body, *EMPTY) == (3, 9)


def test_an_invalid_catalog_writes_nothing_and_rows_missing_from_the_file_are_kept(pg):
    async def body(db):
        bad = copy.deepcopy(EXAMPLE)
        del bad["kernel_ops"][1]["observation"]
        with pytest.raises(ValueError, match="observation.method"):
            await catalog.apply(db, bad)
        empty = await _rows(db, "SELECT count(*) AS n FROM kernel_ops")
        await catalog.apply(db, copy.deepcopy(EXAMPLE))
        smaller = copy.deepcopy(EXAMPLE)
        smaller["kernel_ops"] = smaller["kernel_ops"][:1]
        smaller["capabilities"], smaller["bindings"] = smaller["capabilities"][:1], smaller["bindings"][:1]
        smaller["versions"]["binding"] = "bind-2"
        plan = await catalog.plan(db, smaller)
        await catalog.apply(db, smaller)
        kept = await _rows(db, "SELECT count(*) AS n FROM kernel_ops")
        return empty, plan, kept
    empty, plan, kept = pg(body, *EMPTY)
    assert empty == [{"n": 0}] and sorted(plan.missing_from_file["kernel_ops"]) == ["crm.contact_create", "crm.contact_delete"]
    assert kept == [{"n": 3}]


def test_a_loaded_catalog_runs_a_request_through_s11_and_a_chain_through_s12_admission(pg):
    async def body(db):
        await catalog.apply(db, copy.deepcopy(EXAMPLE))
        async with db.tenant_transaction(A) as c:
            for intent in ("contact.list", "contact.create", "contact.delete"):
                await c.execute("INSERT INTO capability_grants VALUES ($1,$2,$3,$4,$5,true,NULL)", f"g.{intent}", A, "tenant-a.ws",
                                "tenant-a.user", f"cap.{intent}")
        state = await _certified(db, CHAIN)
        outcome = await _admit(db, state)
        return outcome
    outcome = pg(body, *EMPTY)
    assert outcome.status == "ADMITTED" and outcome.run_status == "running"
