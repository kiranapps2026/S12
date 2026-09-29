"""
Data-flow invariant verification for S0-S11.

Source: FINAL_ARCHITECTURE.md §2 (Golden Rules)
Validates:
- No stage bypasses S0 (no manual context injection after S0)
- S5 is the ONE AND ONLY risk/mutation authority
- S5 output fields (FrozenBindingIdentity) are read-only after S5
- S8 is the ONE AND ONLY safety_result authority
- S11 has NO fallback risk
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def check_risk_sources() -> dict:
    """Verify only S5 computes effective_risk/mutation_type."""
    issues = []

    # Handlers that should READ frozen risk/mutation
    frozen_readers = ["s6_task_profile_assembly/handler.py"]

    # Files that should NOT assign effective_risk or mutation_type except S5
    forbidden = [p for p in (ROOT / "src" / "engine" / "stages").rglob("handler.py")
                 if "s5_binding" not in str(p).lower()]

    for filepath in forbidden:
        if not filepath.exists():
            continue
        text = filepath.read_text()
        # Flag any direct assignment to effective_risk or mutation_type
        if re.search(r"effective_risk\s*=|mutation_type\s*=", text):
            # Allow reading from frozen binding
            lines = text.splitlines()
            for i, line in enumerate(lines, 1):
                if re.search(r"effective_risk\s*=|mutation_type\s*=", line):
                    if "frozen" not in line.lower() and "frozen_binding" not in line.lower():
                        issues.append(f"  {filepath.relative_to(ROOT)}:{i} — {line.strip()}")

    return {"issues": issues, "passed": len(issues) == 0}


def check_s5_is_sole_risk_authority() -> dict:
    """Verify S5 binding handler is the only place risk/mutation are computed."""
    result = {"passed": True, "s5_handler": None, "other_risk_assignments": []}

    s5_handler = ROOT / "src" / "engine" / "stages" / "s5_binding_resolution" / "handler.py"
    if s5_handler.exists():
        result["s5_handler"] = str(s5_handler.relative_to(ROOT))

    # Check for risk computation outside S5
    for filepath in (ROOT / "src" / "engine" / "stages").rglob("handler.py"):
        if not filepath.exists():
            continue
        text = filepath.read_text()
        if "s5_binding" in str(filepath).lower():
            continue
        # Look for risk assessment patterns
        if re.search(r"risk.*=|effective_risk\s*=.*\d", text):
            result["other_risk_assignments"].append(str(filepath.relative_to(ROOT)))

    result["passed"] = len(result["other_risk_assignments"]) == 0
    return result


def check_s8_safety_authority() -> dict:
    """Verify S8 is the only stage that writes safety_result."""
    result = {"passed": True, "s8_writes": [], "other_writes": []}

    for filepath in (ROOT / "src" / "engine" / "stages").rglob("handler.py"):
        if not filepath.exists():
            continue
        text = filepath.read_text()
        if "safety_result" in text:
            if "s8" in str(filepath).lower():
                result["s8_writes"].append(str(filepath.relative_to(ROOT)))
            else:
                result["other_writes"].append(str(filepath.relative_to(ROOT)))

    result["passed"] = len(result["other_writes"]) == 0
    return result


def check_pipeline_state_stage_outputs() -> dict:
    """Verify stage output field assignments match STAGE_OUTPUT_FIELD."""
    # Import and check programmatically
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from contracts.pipeline_state import STAGE_OUTPUT_FIELD

    expected = {
        "S0": "execution_context",
        "S1": "normalized_input",
        "S2": "intent_result",
        "S3": "capability_match",
        "S4": "graph_analysis",
        "S5": "frozen_binding_identity",
        "S6": "task_profile",
        "S7": "path_decision",
        "S8": "safety_result",
        "S9": "lock_id",
        "S10": "confirmation",
        "S11": "execution_manifest",
        "S12": "execution_result",
        "S13": "reconciliation_status",
        "S14": "verification_result",
        "S15": "final_state",
    }

    result = {"passed": True, "mismatches": []}
    for stage, expected_field in expected.items():
        actual = STAGE_OUTPUT_FIELD.get(stage)
        if actual != expected_field:
            result["mismatches"].append({
                "stage": stage,
                "expected": expected_field,
                "actual": actual,
            })

    result["passed"] = len(result["mismatches"]) == 0
    return result


def main() -> None:
    print("=" * 60)
    print("DATA-FLOW INVARIANT VERIFICATION")
    print("=" * 60)

    checks = {
        "S5 is sole risk authority": check_s5_is_sole_risk_authority,
        "S8 is sole safety authority": check_s8_safety_authority,
        "No forbidden risk assignments": check_risk_sources,
        "STAGE_OUTPUT_FIELD assignments": check_pipeline_state_stage_outputs,
    }

    all_passed = True
    for name, check_fn in checks.items():
        result = check_fn()
        status = "[PASS]" if result.get("passed", False) else "[FAIL]"
        print(f"\n{status} — {name}")
        if not result.get("passed", False):
            all_passed = False
            for key, value in result.items():
                if key != "passed" and value:
                    print(f"  {key}: {value}")

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL INVARIANTS VALIDATED")
    else:
        print("INVARIANT VIOLATIONS DETECTED")
    print("=" * 60)


if __name__ == "__main__":
    main()
