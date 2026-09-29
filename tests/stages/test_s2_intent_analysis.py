"""
S2 Intent Analysis — tests.

Tests cover:
- Produces IntentResult
- Intent stored in PipelineState
- Workflow detection
- Mock LLM deterministic

Per R-H: uses run_through() helper, no with_stage_output in tests.
"""

from __future__ import annotations

import asyncio
import pytest

from contracts.pipeline_state import PipelineState
from engine.stages.s2_intent_analysis.handler import MockLLMProvider
from tests.fixtures.pipeline import run_through


def _s1_state(raw_input: dict) -> PipelineState:
    """Run S0+S1 and return state ready for S2."""
    return run_through("S1", request=raw_input)


class TestS2IntentAnalysis:
    def test_produces_intent_result(self):
        """S2 produces an IntentResult."""
        state = _s1_state({"text": "create a contact in GHL"})
        llm = MockLLMProvider()
        result = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )
        assert result.intent_result is not None
        assert result.intent_result.intent_type is not None

    def test_intent_stored_in_state(self):
        """Intent is stored in PipelineState.intent_result."""
        state = _s1_state({"text": "create a contact in GHL"})
        llm = MockLLMProvider()
        result = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )
        assert result.intent_result is not None
        assert result.intent_result.intent_type

    def test_workflow_detection(self):
        """Workflow intent is detected."""
        state = _s1_state({"text": "create contact then send email"})
        llm = MockLLMProvider()
        result = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(state, llm)
        )
        assert result.intent_result is not None
        assert result.intent_result.is_workflow is True

    def test_mock_llm_deterministic(self):
        """Mock LLM returns consistent results."""
        state = _s1_state({"text": "list all users"})
        llm = MockLLMProvider()

        result1 = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )
        result2 = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )

        assert result1.intent_result.intent_type == result2.intent_result.intent_type

    def test_s2_normalize_label_inconsistency(self):
        """S2 produces intent regardless of S1 normalize naming."""
        state = _s1_state({"text": "list users"})
        llm = MockLLMProvider()
        result = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )
        assert result.intent_result is not None
        assert result.intent_result.intent_type is not None

    def test_s2_is_only_llm_stage(self):
        """S2 is the only stage with LLM provider."""
        import engine.stages.s2_intent_analysis.handler as s2_mod
        import glob
        llm_stages = []
        for filepath in glob.glob("src/engine/stages/s*/handler.py", recursive=True):
            with open(filepath) as f:
                content = f.read()
            if 'MockLLMProvider' in content or 'llm_provider' in content or 'LLMProvider' in content:
                llm_stages.append(filepath)
        assert len(llm_stages) == 1, f"Expected only S2 to use LLM, found: {llm_stages}"

    def test_s2_normalize_label_inconsistency(self):
        """S2 handler should not depend on S1 'normalize' labeling."""
        state = _s1_state({"text": "list users"})
        llm = MockLLMProvider()
        result = asyncio.run(
            __import__("engine.stages.s2_intent_analysis.handler", fromlist=["handle"]).handle(
                state, llm
            )
        )
        # Just verify S2 produces output regardless of S1 naming
        assert result.intent_result is not None
        assert result.intent_result.intent_type is not None

    def test_s2_is_only_llm_stage(self):
        """S2 is the only stage that uses LLM."""
        import engine.stages.s2_intent_analysis.handler as s2_mod
        assert hasattr(s2_mod, 'MockLLMProvider'), "S2 must have MockLLMProvider for tests"
        # Verify no other stage has LLM provider
        import glob
        for filepath in glob.glob("src/engine/stages/s*/handler.py", recursive=True):
            if "s2_intent" in filepath:
                continue
            with open(filepath) as f:
                content = f.read()
                # No MockLLMProvider or LLM provider in other stages
                assert 'MockLLMProvider' not in content, f"LLM provider found in {filepath}"
