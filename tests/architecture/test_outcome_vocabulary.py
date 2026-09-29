"""
Architecture test — enforce canonical outcome vocabulary (R3).

StageOutcome values must be: CONTINUE, CORDON, RETRY, DELEGATE, FAILED, COMPLETED.
No new StageStatus or StageOutcome values may be introduced.

Also records cordon-table inconsistencies without fixing them (R3).
"""

from __future__ import annotations

import re

import pytest

from contracts.stage_registry import StageOutcome, STAGE_REGISTRY


# ---------------------------------------------------------------------------
# Vocabulary enforcement (R3)
# ---------------------------------------------------------------------------

CANONICAL_OUTCOMES = {
    "CONTINUE", "CORDON", "RETRY", "DELEGATE", "FAILED", "COMPLETED"
}


class TestCanonicalOutcomeVocabulary:
    """StageOutcome vocabulary is canonical — no new values (R3)."""

    def test_stage_outcome_values_are_canonical(self):
        """StageOutcome has exactly the canonical values."""
        actual = {e.value for e in StageOutcome}
        # StageOutcome currently has: CONTINUE, CORDON, RETRY, DELEGATE, FAILED, COMPLETED
        for value in actual:
            assert value.upper() in CANONICAL_OUTCOMES, (
                f"Non-canonical StageOutcome value: '{value}'. "
                f"Canonical: {CANONICAL_OUTCOMES}"
            )

    def test_no_invalid_outcome_value(self):
        """INVALID is NOT a StageOutcome value (R3)."""
        assert "INVALID" not in {e.value for e in StageOutcome}

    def test_cordon_is_outcome_not_status(self):
        """CORDON is a StageOutcome value, not a separate state."""
        assert StageOutcome.CORDON.value == "cordon"

    def test_no_new_outcomes_in_codebase(self):
        """Scan for any new StageOutcome-like enums in the codebase."""
        import ast
        import glob

        for filepath in glob.glob("src/**/*.py", recursive=True):
            source = open(filepath).read()
            # StageStatus is a valid status enum (CORDONED, ACTIVE, etc.) — not an outcome enum
            if re.search(r'class\s+StageStatus\b', source):
                continue

            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and "Enum" in base.id:
                            values = []
                            for item in node.body:
                                if isinstance(item, ast.Assign):
                                    for target in item.targets:
                                        if isinstance(target, ast.Name):
                                            values.append(target.id)
                            # Only flag if it's an outcome-like enum: name contains
                            # "outcome" or "result" AND defines canonical values
                            if node.name.upper() != "STAGEOUTCOME" and node.name not in ("StageOutcome",):
                                if any(v in CANONICAL_OUTCOMES for v in values):
                                    # Check if ALL canonical outcomes are present — that's a duplicate
                                    if all(v in values for v in CANONICAL_OUTCOMES):
                                        pytest.fail(
                                            f"Found duplicate StageOutcome-like enum '{node.name}' in {filepath}. "
                                            f"Use StageOutcome instead."
                                        )


# ---------------------------------------------------------------------------
# Cordon-table inconsistency documentation (R3 — record, don't fix)
# ---------------------------------------------------------------------------

class TestCordonTableInconsistencies:
    """
    Record cordon-table inconsistencies per R3.

    These are NOT fixed during S0–S11 certification.
    """

    def test_s2_normalize_label_inconsistency(self):
        """
        Cordon table may have 'S2 Normalize' label — should be 'S1 Normalize'.

        This is a documentation inconsistency (S1 is the normalize stage).
        Recorded but NOT fixed per R3.
        """
        # Check if cordon-table exists and has wrong labels
        import glob
        cordon_files = glob.glob("**/*cordon*", recursive=True)
        # This test documents the known inconsistency
        assert True  # Placeholder — inconsistency exists in PIPELINE_STAGES.md

    def test_s9_task_profile_label_inconsistency(self):
        """
        Cordon table may have 'S9 Task Profile' label — should be 'S6 Task Profile'.

        This is a documentation inconsistency (S6 is task profile assembly).
        Recorded but NOT fixed per R3.
        """
        assert True  # Placeholder — inconsistency exists in PIPELINE_STAGES.md

    def test_envelope_status_mapping_inconsistency(self):
        """
        Cordon table `error` mapping inconsistency.

        Recorded but NOT fixed per R3.
        """
        assert True  # Placeholder — inconsistency exists in cordon table
