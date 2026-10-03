"""A1 (ADAPTER_DOCS_REVIEW.md): the Worker Runtime start-up check judges an adapter per operation.

``verifiable(cls)`` accepts a class whose own body defines ``probe`` and ``observe``. An adapter that holds a shared
engine and delegates both to it passes that check for every operation, so it declares
``verifiable_operations()`` and the start-up check also requires the operation to be listed there:

  * a class without the declaration (``MockAdapter``) is judged exactly as before;
  * a declared class passes only for the operations it lists;
  * a declaration that raises, is not a collection, or is a bare string fails closed;
  * a missing adapter class, or one that fails the class-level check, is refused whatever it declares;
  * ``unverifiable_mutations`` and ``check_worker_runtime`` give the same answer (one shared decision).

The pure part needs no database; the last case uses real PostgreSQL (TEST_DATABASE_URL) and the golden M21 helpers,
read-only, like the other tests_agent/ files.
"""
from __future__ import annotations

import pytest

from adapters.runtime.mock_adapter import MockAdapter
from contracts.adapter_interface import BaseAdapter, ProbeOutcome
from contracts.step_execution import AdapterResult
from engine.stages.s12_execute.startup import _unverifiable, verifiable, verifiable_for


async def _call(self, kernel_op_id, params, binding, context, *, call_meta=None):
    return AdapterResult("ok")


async def _probe(self, kernel_op_id, params, binding, context, *, call_meta):
    return ProbeOutcome.INCONCLUSIVE


async def _observe(self, kernel_op_id, observation_spec, binding, context):
    return None


def _engine_backed(name: str, declaration) -> type:
    """An engine-backed adapter class: probe and observe in its **own** body (the start-up check reads the class's
    ``__dict__``, so inherited methods would fail it), plus a ``verifiable_operations`` declaration."""
    return type(name, (BaseAdapter,), {"call": _call, "probe": _probe, "observe": _observe,
                                        "verifiable_operations": declaration})


def _listing(*operations):
    return classmethod(lambda cls: frozenset(operations))


def _raises(cls):
    raise RuntimeError("profile failed to load")


_Delegating = _engine_backed("_Delegating", _listing("crm.contact_create", "crm.contact_delete"))
_Raising = _engine_backed("_Raising", classmethod(_raises))
_NotACollection = _engine_backed("_NotACollection", classmethod(lambda cls: 42))
_BareString = _engine_backed("_BareString", classmethod(lambda cls: "crm.contact_create"))
_AttributeSet = _engine_backed("_AttributeSet", frozenset({"crm.contact_create"}))
_Inherited = type("_Inherited", (_Delegating,), {})     # inherits probe/observe: the class-level check refuses it


class _NoProbe(BaseAdapter):
    async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
        return AdapterResult("ok")

    @classmethod
    def verifiable_operations(cls):
        return frozenset({"crm.contact_create"})


def test_class_without_declaration_is_judged_as_before():
    assert verifiable(MockAdapter)
    assert verifiable_for(MockAdapter, "crm.contact_create")
    assert verifiable_for(MockAdapter, "anything.at_all")


def test_declared_class_passes_only_listed_operations():
    assert verifiable(_Delegating)
    assert verifiable_for(_Delegating, "crm.contact_create")
    assert verifiable_for(_Delegating, "crm.contact_delete")
    assert not verifiable_for(_Delegating, "crm.task_create")


@pytest.mark.parametrize("cls", [_Raising, _NotACollection, _BareString])
def test_unreadable_declaration_fails_closed(cls):
    assert verifiable(cls)                                  # the class-level check alone would pass
    assert not verifiable_for(cls, "crm.contact_create")


def test_declaration_may_be_a_plain_collection():
    assert verifiable_for(_AttributeSet, "crm.contact_create")
    assert not verifiable_for(_AttributeSet, "crm.contact_delete")


def test_class_level_check_still_comes_first():
    assert not verifiable(_Inherited)
    assert not verifiable_for(_Inherited, "crm.contact_create")
    assert not verifiable(_NoProbe)
    assert not verifiable_for(_NoProbe, "crm.contact_create")
    assert not verifiable_for(None, "crm.contact_create")


def test_shared_decision_lists_each_unverifiable_binding():
    rows = [
        {"kernel_op_id": "crm.contact_create", "binding_id": "b1", "adapter_class": "CrmAdapter"},
        {"kernel_op_id": "crm.task_create", "binding_id": "b2", "adapter_class": "CrmAdapter"},
        {"kernel_op_id": "crm.contact_delete", "binding_id": "b3", "adapter_class": "Missing"},
        {"kernel_op_id": "mail.email_send", "binding_id": "b4", "adapter_class": "MockAdapter"},
    ]
    adapters = {"CrmAdapter": _Delegating, "MockAdapter": MockAdapter}
    assert _unverifiable(rows, adapters) == [("crm.contact_delete", "b3"), ("crm.task_create", "b2")]


def test_both_entry_points_agree_on_a_real_database(db_schema, run):  # noqa: F811
    from engine.stages.s12_execute.startup import StartupRefused, check_worker_runtime, unverifiable_mutations
    from tests_golden.s12.M12_loop import _admit, _state

    state = _state("agent-startup-per-op", "agentstartupperop")
    _admit(db_schema, run, state)
    ours = {b.binding_id for b in state.frozen_bindings}
    writes = sorted((b.kernel_op_id, b.binding_id) for b in state.frozen_bindings if b.effective_mutation != "R")
    assert writes
    db = db_schema.database()

    _OnlyFirstWrite = _engine_backed("_OnlyFirstWrite", _listing(writes[0][0]))

    listed = [pair for pair in run(unverifiable_mutations(db, {"MockAdapter": _OnlyFirstWrite})) if pair[1] in ours]
    assert listed == [pair for pair in writes if pair[0] != writes[0][0]]
    assert [pair for pair in run(unverifiable_mutations(db, {"MockAdapter": MockAdapter})) if pair[1] in ours] == []
    if listed:
        with pytest.raises(StartupRefused) as refused:
            run(check_worker_runtime(db, {"MockAdapter": _OnlyFirstWrite}))
        assert refused.value.reason == "unverifiable_mutation"


from tests_golden.conftest import db_schema, run  # noqa: E402,F401 - fixtures
