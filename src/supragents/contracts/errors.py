"""Exceptions shared across the pipeline."""
from __future__ import annotations


class ContractViolation(Exception):
    """A stage broke a PipelineState rule. This is a programming error, never user input."""


class DependencyUnavailable(Exception):
    """A port could not answer (store down, LLM unreachable). Callers fail closed."""
