"""
S4 Graph Classification — tests.

Tests cover:
- Classifies graph complexity from real pipeline state
- Workflow detection
- Multi-step linear
"""

from __future__ import annotations

import asyncio
import pytest

from contracts.pipeline_state import PipelineState
from tests.fixtures.states import state_ready_for, make_scenario


class TestS4GraphClassification:
    def test_s4_classifies_single_step(self):
        """S4 classifies no candidates as SINGLE_STEP."""
        state = state_ready_for("S4", make_scenario(mutation="read", steps=1, graph="simple"))
        result = asyncio.run(
            __import__("engine.stages.s4_graph_classification.handler", fromlist=["handle"]).handle(state)
        )
        assert result.graph_analysis is not None
        assert result.graph_analysis.complexity == "simple"

    def test_s4_classifies_chain(self):
        """S4 classifies 1 candidate as LINEAR (chain)."""
        state = state_ready_for("S4", make_scenario(mutation="read", steps=2, graph="chain"))
        result = asyncio.run(
            __import__("engine.stages.s4_graph_classification.handler", fromlist=["handle"]).handle(state)
        )
        assert result.graph_analysis is not None
        assert result.graph_analysis.complexity == "chain"

    def test_s4_classifies_complex(self):
        """S4 classifies multiple candidates as COMPLEX."""
        state = state_ready_for("S4", make_scenario(mutation="W", steps=5, graph="chain"))
        result = asyncio.run(
            __import__("engine.stages.s4_graph_classification.handler", fromlist=["handle"]).handle(state)
        )
        assert result.graph_analysis is not None
        assert result.graph_analysis.complexity in ("complex", "chain")

    def test_workflow_detected(self):
        """Workflow intent is detected."""
        state = state_ready_for("S4", make_scenario(mutation="W", steps=3, graph="chain"))
        result = asyncio.run(
            __import__("engine.stages.s4_graph_classification.handler", fromlist=["handle"]).handle(state)
        )
        assert result.graph_analysis is not None
        assert result.graph_analysis.is_workflow is True

    def test_multi_step_linear(self):
        """Multiple steps results in appropriate complexity."""
        state = state_ready_for("S4", make_scenario(mutation="W", steps=5, graph="chain"))
        result = asyncio.run(
            __import__("engine.stages.s4_graph_classification.handler", fromlist=["handle"]).handle(state)
        )
        assert result.graph_analysis is not None
        assert result.graph_analysis.candidate_count >= 1
