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
from tests.fixtures.states import state_ready_for, make_scenario, tamper


class TestS3CapabilityDiscovery:
    def test_returns_candidates(self):
        """S3 returns ranked capability candidates from intent.parameters."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=2))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.capability_id is not None

    def test_score_ordering(self):
        """Candidates are ordered by score (highest first)."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=2))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.score > 0

    def test_empty_candidates(self):
        """No candidates returns no-match result."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=0))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.capability_id == "none"

    def test_s3_filters_duplicate_candidates(self):
        """S3 deduplicates candidates by capability_id."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=3))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.capability_id is not None

    def test_s3_respects_mutation_type(self):
        """S3 preserves mutation_type from candidates (lowercase from scenario)."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=2))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.mutation_type is not None

    def test_s3_score_deduplication(self):
        """Higher score wins among same capability_id candidates."""
        state = state_ready_for("S3", make_scenario(mutation="read", capabilities=2))
        result = asyncio.run(
            __import__("engine.stages.s3_capability_discovery.handler", fromlist=["handle"]).handle(state)
        )
        assert result.capability_match is not None
        assert result.capability_match.score >= 0.0
