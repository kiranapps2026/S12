"""ConfirmationStore contract (ruling R-Z). Any store implementation must pass these."""
from __future__ import annotations

import asyncio

import pytest

from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import ConfirmationStatus
from tests.fakes.confirmations import InMemoryConfirmationStore
from tests.fakes.runtime import FakeClock

IDS = dict(tenant_id="tenant-a", user_id="user-1")


def _store_with_one(clock=None):
    clock = clock or FakeClock()
    store = InMemoryConfirmationStore(clock)
    confirmation = Confirmation("c-1", "user-1", "conv-1", "plan-1", "hash-1", (), clock.now() + 300)
    asyncio.run(store.save(confirmation, tenant_id="tenant-a", execution_id="exec-1"))
    return store, clock


def test_save_requires_keyword_tenant_and_execution_id():
    store, _ = _store_with_one()
    confirmation = Confirmation("c-2", "u", "c", "p", "h", (), 0.0)
    with pytest.raises(TypeError):
        asyncio.run(store.save(confirmation, tenant_id="tenant-a"))
    for bad in ({"tenant_id": "", "execution_id": "e"}, {"tenant_id": "t", "execution_id": ""}):
        with pytest.raises(ValueError):
            asyncio.run(store.save(confirmation, **bad))


def test_consume_is_single_use():
    store, _ = _store_with_one()
    assert asyncio.run(store.consume("c-1", plan_hash="hash-1", **IDS)) is True
    assert asyncio.run(store.consume("c-1", plan_hash="hash-1", **IDS)) is False
    assert store.status("c-1") is ConfirmationStatus.CONSUMED


@pytest.mark.parametrize("override", [{"tenant_id": "tenant-b"}, {"user_id": "user-2"}, {"plan_hash": "other"}])
def test_consume_rejects_mismatch_and_leaves_record_pending(override):
    store, _ = _store_with_one()
    args = {**IDS, "plan_hash": "hash-1", **override}
    assert asyncio.run(store.consume("c-1", **args)) is False
    assert store.status("c-1") is ConfirmationStatus.PENDING


def test_expired_confirmation_cannot_be_consumed():
    store, clock = _store_with_one()
    clock.advance(300)
    assert asyncio.run(store.consume("c-1", plan_hash="hash-1", **IDS)) is False
    assert store.status("c-1") is ConfirmationStatus.EXPIRED


def test_find_is_tenant_scoped():
    store, _ = _store_with_one()
    assert asyncio.run(store.find(tenant_id="tenant-b", execution_id="exec-1")) is None
    assert asyncio.run(store.find(tenant_id="tenant-a", execution_id="exec-1")).status is ConfirmationStatus.PENDING
