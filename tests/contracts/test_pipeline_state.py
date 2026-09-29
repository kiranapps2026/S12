"""PipelineState rules: ownership, write-once, types, halts and context whitelist."""
from __future__ import annotations

import dataclasses

import pytest

from supragents.contracts.errors import ContractViolation
from supragents.contracts.outputs import NormalizedInput, PathRouting
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.state import FIELD_OWNER, STAGE_SEQUENCE, PipelineState
from supragents.contracts.vocabulary import PathDecision, StageStatus
from supragents.pipeline.stages import STAGES
from tests.builders import Harness, entry

NORMALIZED = NormalizedInput("t", False, (), False)


def test_stage_sequence_is_s0_to_s11_and_matches_the_runner():
    assert STAGE_SEQUENCE == tuple(f"S{i}" for i in range(12))
    assert tuple(stage_id for stage_id, _ in STAGES) == STAGE_SEQUENCE
    assert set(FIELD_OWNER.values()) == set(STAGE_SEQUENCE)


def test_only_the_owner_writes_a_field():
    with pytest.raises(ContractViolation, match="may not write"):
        PipelineState(entry_request=entry()).with_output("S2", normalized_input=NORMALIZED)


def test_fields_are_write_once():
    state = PipelineState(entry_request=entry()).with_output("S1", normalized_input=NORMALIZED)
    with pytest.raises(ContractViolation, match="write-once"):
        state.with_output("S1", normalized_input=NORMALIZED)


def test_values_are_type_checked():
    with pytest.raises(ContractViolation, match="expects"):
        PipelineState(entry_request=entry()).with_output("S7", path_routing={"decision": "fast"})


def test_unknown_field_is_rejected():
    with pytest.raises(ContractViolation, match="unknown field"):
        PipelineState(entry_request=entry()).with_output("S7", routing=PathRouting(PathDecision.FAST, None))


def test_halt_is_recorded_once_and_never_normal():
    state = PipelineState(entry_request=entry())
    with pytest.raises(ContractViolation):
        state.halted("S1", StageStatus.NORMAL, "x")
    halted = state.halted("S1", StageStatus.DENY, "x")
    with pytest.raises(ContractViolation, match="already halted"):
        halted.halted("S2", StageStatus.ERROR, "y")


@pytest.mark.parametrize("stage, field", [("S3", "task_id"), ("S2", "auth_passed"), ("S8", "tenant_id")])
def test_context_replacement_is_whitelisted(stage, field):
    state = Harness().state_before("S1")
    with pytest.raises(ContractViolation, match="may not replace"):
        state.with_context(stage, **{field: "x"})


def test_context_is_frozen():
    context = Harness().state_before("S1").execution_context
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.tenant_id = "other"


def test_reply_only_resumes_before_s10():
    h = Harness()
    reply = ConfirmationReply("c", "user-1", True)
    completed = h.run().state
    with pytest.raises(ContractViolation):
        completed.with_reply(reply)
