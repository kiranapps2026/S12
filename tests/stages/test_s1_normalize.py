"""
S1 Normalize — tests.

Tests cover:
- Safe input continues
- Injection detection
- Sanitized input stored in PipelineState.normalized_input
- Nested dict sanitization

Per R-H: uses run_through() helper, no hand-built state.
"""

from __future__ import annotations

import asyncio
import pytest

from tests.fixtures.pipeline import run_through


class TestS1Normalize:
    def test_safe_input_continues(self):
        """Safe input passes through with CONTINUE outcome."""
        state = run_through("S1", request={"message": "hello world"})
        assert state.normalized_input is not None
        assert state.normalized_input.has_critical_injection is False
        assert state.normalized_input.was_modified is False

    def test_injection_detected(self):
        """Injection patterns are detected."""
        state = run_through("S1", request={"message": "<script>alert('xss')</script>"})
        assert state.normalized_input is not None
        assert len(state.normalized_input.patterns_detected) > 0

    def test_sanitized_input_set(self):
        """Sanitized input is stored in NormalizedInput."""
        state = run_through("S1", request={"message": "hello world"})
        assert state.normalized_input is not None
        assert "message" in state.normalized_input.sanitized_input

    def test_nested_dict_sanitized(self):
        """Nested dicts are sanitized recursively."""
        state = run_through("S1", request={
            "message": {"user": {"name": "test", "email": "test@example.com"}}
        })
        assert state.normalized_input is not None
        assert state.normalized_input.sanitized_input is not None
        assert "message" in state.normalized_input.sanitized_input
        assert "user" in state.normalized_input.sanitized_input["message"]
