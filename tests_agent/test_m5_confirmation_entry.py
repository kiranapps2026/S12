"""Agent tests for M5 (never count for certification): where the C20 check sits in S12 entry, and what it reads."""
import asyncio
import dataclasses
import time

from contracts.confirmation_record import ConsumedConfirmation
from contracts.execution_manifest import Confirmation, ConfirmationOutcome
from engine.stages.s12_entry.checks import check_entry
from tests_golden.fixtures.certified import AllMetadata, ManifestBindings, NoPause, certified_state


class CountingReader:
    def __init__(self, row):
        self.row, self.calls = row, 0

    async def read(self, confirmation_id, *, tenant_id):
        self.calls += 1
        return self.row


def _confirmed(state, **row_changes):
    conf = Confirmation("c-agent", "u", "conv", "plan", state.execution_manifest.plan_hash, ({"op": "x"},),
                        time.time() + 60)
    state = dataclasses.replace(state, confirmation=ConfirmationOutcome(required=True, confirmation=conf))
    row = ConsumedConfirmation(**{"status": "consumed", "execution_id": state.plan.execution_id,
                                  "plan_hash": state.execution_manifest.plan_hash, "user_id": "u", **row_changes})
    return state, CountingReader(row)


def _check(state, reader, bindings=None):
    return asyncio.run(check_entry(state, bindings=bindings or ManifestBindings(), activation=NoPause(),
                                   metadata=AllMetadata(), confirmations=reader))


def test_a_matching_consumed_confirmation_is_read_once_and_admitted():
    state, reader = _confirmed(certified_state())
    decision = _check(state, reader)
    assert decision.allowed and reader.calls == 1


def test_an_earlier_failing_check_decides_and_the_store_is_not_read():
    state, reader = _confirmed(certified_state(), execution_id="another-run")
    decision = _check(state, reader, bindings=ManifestBindings("bind-other"))
    assert (decision.allowed, decision.reason) == (False, "binding_version_mismatch") and reader.calls == 0


def test_the_confirmation_check_runs_after_every_numbered_item():
    state, reader = _confirmed(certified_state(), execution_id="another-run")
    decision = _check(state, reader)
    assert (decision.allowed, decision.reason) == (False, "confirmation_mismatch") and reader.calls == 1


def test_no_required_confirmation_reads_nothing():
    reader = CountingReader(None)
    assert _check(certified_state(), reader).allowed and reader.calls == 0
