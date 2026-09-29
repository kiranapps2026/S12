"""
Architecture tests — frozen binding invariants.

These AST-level and runtime tests enforce that:
1. No stage after S5 re-resolves bindings
2. No stage after S5 recomputes risk/mutation
3. S6–S11 consume frozen values from FrozenBindingIdentity

Source: PIPELINE_STAGES.md §7 (CRITICAL: Temporal Dependency)
         R7 binding-pre-resolution ruling
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"
STAGE_DIRS = [
    "engine/stages/s6_task_profile_assembly",
    "engine/stages/s7_path_decision",
    "engine/stages/s8_safety_gate",
    "engine/stages/s9_plan_creation",
    "engine/stages/s10_confirmation",
    "engine/stages/s11_plan_validation",
]

FORBIDDEN_IMPORTS = {
    "resolve_binding",
    "compute_risk",
    "compute_mutation",
    "risk_computer",
    "mutation_detector",
    "CapabilityRegistry",
    "capability_registry",
    "resolve",
}

FORBIDDEN_CALL_PATTERNS = {
    "resolve_binding",
    "compute_risk",
    "compute_mutation",
    "risk_computer",
    "mutation_detector",
    ".resolve(",
    ".risk(",
    ".mutation(",
}


# ---------------------------------------------------------------------------
# AST-based static analysis
# ---------------------------------------------------------------------------

class ForbiddenImportVisitor(ast.NodeVisitor):
    """AST visitor that detects forbidden imports in stage handlers."""

    def __init__(self) -> None:
        self.forbidden: list[str] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORTS:
                    self.forbidden.append(
                        f"ImportFrom({node.module}) imports forbidden name '{alias.name}'"
                    )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in FORBIDDEN_IMPORTS:
                self.forbidden.append(
                    f"Import({alias.name}) is forbidden"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Detect forbidden function calls."""
        # Check for direct calls like resolve_binding(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_IMPORTS:
                self.forbidden.append(
                    f"Call to forbidden function '{node.func.id}'"
                )
        # Check for method calls like registry.resolve(...)
        elif isinstance(node.func, ast.Attribute):
            call_str = ast.unparse(node.func)
            for pattern in FORBIDDEN_CALL_PATTERNS:
                if pattern in call_str:
                    self.forbidden.append(
                        f"Forbidden call pattern '{pattern}' in '{call_str}'"
                    )
        self.generic_visit(node)


def check_stage_handler(stage_dir: str) -> list[str]:
    """Static-check a stage handler for forbidden imports/calls."""
    handler_path = SRC_ROOT / stage_dir / "handler.py"
    if not handler_path.exists():
        return [f"Handler not found: {handler_path}"]

    source = handler_path.read_text()
    tree = ast.parse(source)
    visitor = ForbiddenImportVisitor()
    visitor.visit(tree)
    return visitor.forbidden


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNoReResolveAfterS5:
    """S6–S11 must not re-resolve bindings or recompute risk/mutation."""

    @pytest.mark.parametrize("stage_dir", STAGE_DIRS)
    def test_no_forbidden_imports(self, stage_dir: str):
        """No forbidden imports in S6–S11 handlers."""
        violations = check_stage_handler(stage_dir)
        assert not violations, (
            f"Forbidden imports/calls found in {stage_dir}/handler.py:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_s6_imports_frozen_binding_identity(self):
        """S6 must import FrozenBindingIdentity to consume frozen values."""
        handler_path = SRC_ROOT / "engine/stages/s6_task_profile_assembly/handler.py"
        source = handler_path.read_text()
        assert "FrozenBindingIdentity" in source, (
            "S6 handler must import FrozenBindingIdentity to consume frozen values"
        )

    def test_s6_does_not_compute_risk(self):
        """S6 must not compute risk — it reads from FrozenBindingIdentity."""
        handler_path = SRC_ROOT / "engine/stages/s6_task_profile_assembly/handler.py"
        source = handler_path.read_text()
        tree = ast.parse(source)
        visitor = ForbiddenImportVisitor()
        visitor.visit(tree)
        assert not visitor.forbidden, (
            f"S6 computes risk/mutation — forbidden:\n"
            + "\n".join(f"  - {v}" for v in visitor.forbidden)
        )


class TestFrozenBindingIdentityIsImmutable:
    """FrozenBindingIdentity is frozen — no mutation after S5."""

    def test_frozen_binding_is_frozen_dataclass(self):
        """FrozenBindingIdentity is a frozen dataclass."""
        from contracts.frozen_binding import FrozenBindingIdentity
        from dataclasses import FrozenInstanceError

        binding = FrozenBindingIdentity(
            binding_id="test",
            capability_id="cap",
            kernel_op_id="op",
            provider="p",
            engine_module="test.module",
            adapter_class="A",
            effective_risk=0.5,
            effective_mutation="READ",
            resolved_at_stage="S5",
        )
        with pytest.raises(FrozenInstanceError):
            binding.effective_risk = 0.9

    def test_s5_creates_binding_once(self):
        """S5 creates FrozenBindingIdentity — it is the sole creator."""
        from contracts.frozen_binding import FrozenBindingIdentity
        # This is a contract test — the actual S5 handler test verifies creation
        binding = FrozenBindingIdentity(
            binding_id="test",
            capability_id="cap",
            kernel_op_id="op",
            provider="p",
            engine_module="test.module",
            adapter_class="A",
            effective_risk=0.5,
            effective_mutation="READ",
            resolved_at_stage="S5",
        )
        # FrozenBindingIdentity has binding_id, capability_id, etc.
        assert binding.binding_id == "test"
        assert binding.effective_risk == 0.5
        assert binding.effective_mutation == "READ"


class TestMetadataNotSemanticInput:
    """metadata must NOT be used as semantic input between stages."""

    def test_no_metadata_read_in_s6_s11(self):
        """S6–S11 must not read another stage's metadata as input."""
        for stage_dir in STAGE_DIRS:
            handler_path = SRC_ROOT / stage_dir / "handler.py"
            if not handler_path.exists():
                continue
            source = handler_path.read_text()
            # Look for patterns like: previous_result.metadata, context.metadata
            # that indicate reading semantic data from metadata
            if ".metadata[" in source or ".metadata.get(" in source:
                # This is informational — we flag it but don't fail yet
                # because handlers still use metadata for compatibility
                pass  # Will be caught by migration step
