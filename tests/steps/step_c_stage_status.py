"""
Step C: StageStatus vocabulary — verify DENY value and S8/S11 mapping.

Source: DATA_CONTRACTS.md §3, PIPELINE_STAGES.md §10/§13
"""

from __future__ import annotations

import pytest

from contracts.stage_registry import StageOutcome, StageStatus, OUTCOME_TO_STATUS, STAGE_REGISTRY


class TestStageStatusVocabulary:
    """StageStatus is the canonical vocabulary (DATA_CONTRACTS.md §3)."""

    def test_stage_status_has_deny(self):
        """StageStatus.DENY exists and value is 'DENY'."""
        assert hasattr(StageStatus, 'DENY')
        assert StageStatus.DENY.value == 'DENY'

    def test_stage_status_values(self):
        """StageStatus has all five required values."""
        required = {'NORMAL', 'CLARIFY', 'DENY', 'ERROR', 'PROBE'}
        actual = {s.value for s in StageStatus}
        assert required == actual, f"Missing or extra: {required.symmetric_difference(actual)}"

    def test_outcome_to_status_maps_cordon_to_deny(self):
        """StageOutcome.CORDON → StageStatus.DENY (S8/S11 are cordon points)."""
        assert OUTCOME_TO_STATUS[StageOutcome.CORDON] == StageStatus.DENY

    def test_outcome_to_status_complete(self):
        """Every StageOutcome maps to exactly one StageStatus."""
        for outcome in StageOutcome:
            assert outcome in OUTCOME_TO_STATUS, f"StageOutcome.{outcome} not mapped"
            mapped = OUTCOME_TO_STATUS[outcome]
            assert isinstance(mapped, StageStatus)

    def test_s8_is_cordon_point(self):
        """S8 is a cordon point. cordon_outcome is a descriptive label; routing is CORDON → DENY."""
        s8 = STAGE_REGISTRY.get("S8")
        assert s8 is not None
        assert s8.is_cordon is True
        assert s8.cordon_outcome in {"DEAD_LETTER", "FAILED", "CANCELLED", None}
        # Any cordon outcome routes through CORDON which maps to DENY
        assert OUTCOME_TO_STATUS[StageOutcome.CORDON] == StageStatus.DENY

    def test_s11_is_cordon_point(self):
        """S11 is a cordon point. cordon_outcome is a descriptive label; routing is CORDON → DENY."""
        s11 = STAGE_REGISTRY.get("S11")
        assert s11 is not None
        assert s11.is_cordon is True
        assert s11.cordon_outcome in {"DEAD_LETTER", "FAILED", "CANCELLED", None}
        # Any cordon outcome routes through CORDON which maps to DENY
        assert OUTCOME_TO_STATUS[StageOutcome.CORDON] == StageStatus.DENY
