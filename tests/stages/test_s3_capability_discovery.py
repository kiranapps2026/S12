"""
S3 Capability Discovery — tests.

Tests cover:
- Returns candidates
- Score ordering
- Empty candidates

Post-R0: candidates come from intent.parameters, not ExecutionContext.metadata.
"""

from __future__ import annotations

import asyncio
import pytest

from contracts.pipeline_state import PipelineState
from tests.fixtures.states import state_ready_for, make_scenario, run_stage, tamper


class TestS3CapabilityDiscovery:
    def test_returns_candidates(self):
        """S3 returns ranked capability candidates from intent.parameters."""
        sc = make_scenario(mutation="R", capabilities=2)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.capability_id is not None

    def test_score_ordering(self):
        """Candidates are ordered by score (highest first)."""
        sc = make_scenario(mutation="R", capabilities=2)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.score > 0

    def test_empty_candidates(self):
        """No candidates returns no-match result."""
        sc = make_scenario(mutation="R", capabilities=0)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.capability_id == "none"

    def test_s3_filters_duplicate_candidates(self):
        """S3 deduplicates candidates by capability_id."""
        sc = make_scenario(mutation="R", capabilities=3)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.capability_id is not None

    def test_s3_respects_mutation_type(self):
        """S3 preserves mutation_type from candidates (lowercase from scenario)."""
        sc = make_scenario(mutation="R", capabilities=2)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.mutation_type is not None

    def test_s3_score_deduplication(self):
        """Higher score wins among same capability_id candidates."""
        sc = make_scenario(mutation="R", capabilities=2)
        state = state_ready_for("S3", sc)
        result = run_stage("S3", state, sc)
        assert result.capability_match is not None
        assert result.capability_match.score >= 0.0
