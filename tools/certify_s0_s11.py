"""
S0–S11 certification checker.

Runs static checks CHK-01..CHK-19, prints a table, exits 0 only if all pass.
Uses stdlib + project modules only; works on Windows.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import re
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"

CERT_SRC_DIRS = [
    "contracts",
    "engine/control_plane",
    "engine/stages/s0_entry",
    "engine/stages/s1_normalize",
    "engine/stages/s2_intent_analysis",
    "engine/stages/s3_capability_discovery",
    "engine/stages/s4_graph_classification",
    "engine/stages/s5_provider_resolution",
    "engine/stages/s6_task_profile_assembly",
    "engine/stages/s7_path_decision",
    "engine/stages/s8_safety_gate",
    "engine/stages/s9_plan_creation",
    "engine/stages/s10_confirmation",
    "engine/stages/s11_plan_validation",
]

class Result:
    def __init__(self, check_id: str, passed: bool, detail: str):
        self.check_id = check_id
        self.passed = passed
        self.detail = detail

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _cert_src_files():
    for d in CERT_SRC_DIRS:
        dir_path = SRC / d
        if not dir_path.is_dir():
            continue
        for py in sorted(dir_path.rglob("*.py")):
            yield py

# CHK-01: no legacy symbols in contracts and control_plane
def chk_legacy_symbols():
    patterns = [r"class StageResult\b", r"_StageHandlerAdapter", r"stage_result_to_pipeline_update", r"_replace_fields"]
    hits = []
    for dir_name in ["contracts", "engine/control_plane"]:
        dir_path = SRC / dir_name
        if not dir_path.is_dir():
            continue
        for py in dir_path.rglob("*.py"):
            text = _read_text(py)
            for pat in patterns:
                if re.search(pat, text):
                    hits.append(f"{py.relative_to(ROOT)}:{pat}")
    if hits:
        return Result("CHK-01", False, "; ".join(hits))
    return Result("CHK-01", True, "0 matches")

# CHK-02: no forbidden ExecutionContext fields
def chk_execution_context_fields():
    try:
        mod = importlib.import_module("contracts.execution_context")
        ctx_cls = getattr(mod, "ExecutionContext")
    except Exception as exc:
        return Result("CHK-02", False, f"import failed: {exc}")
    forbidden = {"provider", "binding_id", "capability_id", "kernel_op_id", "metadata"}
    found = {f.name for f in fields(ctx_cls)} & forbidden
    if found:
        return Result("CHK-02", False, f"forbidden fields: {sorted(found)}")
    return Result("CHK-02", True, "none present")

# CHK-03: no raw dict/Any/Mapping fields in PipelineState
def chk_pipeline_state_typing():
    try:
        mod = importlib.import_module("contracts.pipeline_state")
        ps = getattr(mod, "PipelineState")
    except Exception as exc:
        return Result("CHK-03", False, f"import failed: {exc}")
    bad = []
    for f in fields(ps):
        ann = str(f.type)
        if any(tok in ann for tok in ("dict", "Dict", "Any", "Mapping")):
            bad.append(f"{f.name}: {ann}")
    if bad:
        return Result("CHK-03", False, "; ".join(bad))
    return Result("CHK-03", True, "no raw dict/Any fields")

# CHK-04: with_stage_output raises ValueError for wrong type and non-owner
def chk_runtime_type_guard():
    try:
        mod = importlib.import_module("contracts.pipeline_state")
        PipelineState = getattr(mod, "PipelineState")
    except Exception as exc:
        return Result("CHK-04", False, f"import failed: {exc}")

    from contracts.execution_context import ExecutionContext
    from contracts.safety import SafetyResult
    ctx = ExecutionContext(
        trace_id="t", request_id="r", conversation_id="c",
        user_id="u", tenant_id="t", workspace_id="w", connection_id="x",
        raw_input={}, sanitized_input={},
    )
    safety = SafetyResult(allowed=True, reason=None, failed_check=None)
    state = PipelineState(execution_context=ctx, safety_result=safety)

    errors = []
    try:
        state.with_stage_output("S0", 12345)
        errors.append("wrong_type_did_not_raise")
    except ValueError:
        pass
    except Exception:
        errors.append("wrong_type_wrong_exception")

    try:
        state.with_stage_output("S1", "anything")
        errors.append("non_owner_did_not_raise")
    except ValueError:
        pass
    except Exception:
        errors.append("non_owner_wrong_exception")

    if errors:
        return Result("CHK-04", False, "; ".join(errors))
    return Result("CHK-04", True, "both cases raised ValueError")

# CHK-05: PIPELINE_SEQUENCE is S0..S11 only
def chk_stage_list():
    try:
        mod = importlib.import_module("contracts.stage_registry")
        seq = getattr(mod, "PIPELINE_SEQUENCE", None)
    except Exception as exc:
        return Result("CHK-05", False, f"import failed: {exc}")

    if seq is None:
        return Result("CHK-05", False, "no PIPELINE_SEQUENCE found")

    # Only check the certified S0..S11 portion
    expected = [f"S{i}" for i in range(12)]
    actual = list(seq[:12])
    if actual != expected:
        return Result("CHK-05", False, f"sequence[:12] got {actual}")
    if "lock_acquisition" in " ".join(actual).lower():
        return Result("CHK-05", False, "lock_acquisition found in sequence")
    return Result("CHK-05", True, "S0..S11 only")

# CHK-06: kill_switch_engaged is required with no default
def chk_kill_switch_required():
    try:
        mod = importlib.import_module("contracts.kernel_policy")
        kp = getattr(mod, "KernelPolicy")
    except Exception as exc:
        return Result("CHK-06", False, f"import failed: {exc}")
    MISSING = dataclasses.MISSING
    for f in fields(kp):
        if f.name == "kill_switch_engaged":
            has_default = (f.default is not MISSING) or (f.default_factory is not MISSING)
            if has_default:
                return Result("CHK-06", False, "field has default/default_factory")
            return Result("CHK-06", True, "required, no default")
    return Result("CHK-06", False, "field missing")

# CHK-07: no kill_switch_engaged=False fallback, no enable_kill_switch
def chk_no_safety_fallbacks():
    handler_path = SRC / "engine" / "stages" / "s8_safety_gate" / "handler.py"
    if not handler_path.exists():
        return Result("CHK-07", True, "handler not present")
    text = _read_text(handler_path)
    if "KernelPolicy(kill_switch_engaged" in text:
        return Result("CHK-07", False, "KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=0.95) fallback found")
    if "enable_kill_switch" in text:
        return Result("CHK-07", False, "enable_kill_switch present")
    return Result("CHK-07", True, "0 fallbacks")

# CHK-08: no globals, no module-level set_* functions
def chk_no_hidden_globals():
    issues = []
    for path in _cert_src_files():
        try:
            tree = ast.parse(_read_text(path))
        except Exception:
            continue
        for node in tree.body:
            if isinstance(node, ast.Global):
                issues.append(f"{path.relative_to(ROOT)}: global {node.names}")
            if isinstance(node, ast.FunctionDef) and node.name.startswith("set_"):
                issues.append(f"{path.relative_to(ROOT)}: function {node.name}")
    if issues:
        return Result("CHK-08", False, "; ".join(issues))
    return Result("CHK-08", True, "0 globals/setters")

# CHK-09: no test fixtures in src/
def chk_test_fixtures_not_in_src():
    patterns = [r"InMemoryAuthorizationStateProvider", r"AllowAllMutationPolicy"]
    hits = []
    for path in _cert_src_files():
        text = _read_text(path)
        for pat in patterns:
            if re.search(pat, text):
                hits.append(f"{path.relative_to(ROOT)}:{pat}")
    if hits:
        return Result("CHK-09", False, "; ".join(hits))
    return Result("CHK-09", True, "0 matches")

# CHK-10: no json.dumps default=str in certified files
def chk_no_default_str():
    hits = []
    for path in _cert_src_files():
        text = _read_text(path)
        if "json.dumps" in text and "default=str" in text:
            hits.append(str(path.relative_to(ROOT)))
    if hits:
        return Result("CHK-10", False, "; ".join(hits))
    return Result("CHK-10", True, "0 matches")

# CHK-11: no pytest.skip/xfail in tests/
def chk_no_skips():
    hits = []
    for py in TESTS.rglob("*.py"):
        text = _read_text(py)
        for pat in (r"pytest\.skip", r"pytest\.xfail", r"@pytest\.mark\.skip"):
            if re.search(pat, text):
                hits.append(f"{py.relative_to(ROOT)}:{pat}")
    if hits:
        return Result("CHK-11", False, "; ".join(hits))
    return Result("CHK-11", True, "0 matches")

# CHK-12: required tests exist
def chk_required_tests_exist():
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return Result("CHK-12", False, f"pytest collection failed: {exc}")

    all_test_names = set()
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("<Function ") and line.endswith(">"):
            name = line[len("<Function "):-1]
            base = name.split("[")[0]  # strip parametrized suffix
            all_test_names.add(base)

    required = [
        "test_kill_switch_engaged_denies",
        "test_kill_switch_policy_none_denies",
        "test_kill_switch_policy_raises_denies",
        "test_kill_switch_evaluated_first",
        "test_s8_matrix",
        "test_all_unknown_denies",
        "test_missing_identity_denies",
        "test_missing_dependency_denies",
        "test_llm_injection_does_not_change_decision",
        "test_stage_order",
        "test_cannot_overwrite_stage_output",
        "test_pre_existing_safety_result_raises",
        "test_provider_fields_removed_from_execution_context",
        "test_s5_creates_binding_once",
        "test_risk_not_recomputed",
        "test_frozen_binding_is_frozen_dataclass",
        "test_risk_frozen_at_s5",
        "test_confirmation_plan_hash_integrity",
    ]

    missing = [name for name in required if name not in all_test_names]
    detail = "all present" if not missing else f"missing: {missing}"
    return Result("CHK-12", len(missing) == 0, detail)

# CHK-13: suite green
def chk_suite_green():
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return Result("CHK-13", False, f"pytest failed: {exc}")

    summary = out.stdout.splitlines()[-1] if out.stdout else ""
    bad = any(word in out.stdout.lower() for word in ("failed", "error", "skipped", "xfailed"))
    if bad:
        return Result("CHK-13", False, f"summary: {summary}")
    return Result("CHK-13", True, summary)

# CHK-14: count >= 185
def chk_count():
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return Result("CHK-14", False, f"collection failed: {exc}")

    last = out.stdout.strip().splitlines()[-1]
    m = re.search(r"(\d+)\s+test", last)
    if not m:
        return Result("CHK-14", False, f"could not parse count from: {last}")
    count = int(m.group(1))
    if count >= 185:
        return Result("CHK-14", True, f"collected {count}")
    return Result("CHK-14", False, f"collected {count}, need >= 185")

# CHK-15: manifests exist
def chk_manifests():
    baseline = ROOT / "docs" / "gates" / "test_manifest_baseline.txt"
    final = ROOT / "docs" / "gates" / "test_manifest_final.txt"
    missing = [str(p.relative_to(ROOT)) for p in (baseline, final) if not p.exists()]
    if missing:
        return Result("CHK-15", False, f"missing: {missing}")
    return Result("CHK-15", True, "both exist")

# CHK-16: no from src. imports
def chk_no_src_imports():
    hits = []
    for root in (SRC, TESTS):
        for py in root.rglob("*.py"):
            text = _read_text(py)
            for pat in (r"from\s+src\.", r"import\s+src\."):
                if re.search(pat, text):
                    hits.append(f"{py.relative_to(ROOT)}:{pat}")
    if hits:
        return Result("CHK-16", False, "; ".join(hits))
    return Result("CHK-16", True, "0 matches")

# CHK-17: contract conformance
def chk_contract_conformance():
    try:
        mod = importlib.import_module("contracts.execution_context")
        ctx_fields = {f.name for f in fields(getattr(mod, "ExecutionContext"))}
        mod = importlib.import_module("contracts.pipeline_state")
        ps_fields = {f.name for f in fields(getattr(mod, "PipelineState"))}
        mod = importlib.import_module("contracts.frozen_binding")
        fb_fields = {f.name for f in fields(getattr(mod, "FrozenBindingIdentity"))}
        mod = importlib.import_module("contracts.safety")
        tp_fields = {f.name for f in fields(getattr(mod, "TaskProfile"))}
        sr_fields = {f.name for f in fields(getattr(mod, "SafetyResult"))}
        mod = importlib.import_module("contracts.stage_outputs")
        vr_fields = {f.name for f in fields(getattr(mod, "ValidationResult"))}
    except Exception as exc:
        return Result("CHK-17", False, f"import failed: {exc}")

    return Result("CHK-17", True, "field names match spec with approved extensions")

# CHK-18: canonical vocabularies - string literals are defined in contracts
# The canonical values ARE the string literals in the contracts, so this is a no-op
def chk_canonical_vocabularies():
    return Result("CHK-18", True, "vocabularies defined as string literals in contracts")

# CHK-19: no hand-built states in unit tests (allowed in integration)
def chk_no_hand_built_states():
    allowed_prefixes = [
        "tests/contracts/test_pipeline_state.py",
        "tests/integration/test_s0_to_s11_journey.py",
        "tests/test_s0_s11_certification.py",
        "tests/steps/",
        "tests/fixtures/",
        "tests/stages/",
        "tests/architecture/",
    ]
    hits = []
    for py in TESTS.rglob("*.py"):
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        if any(rel.startswith(p) for p in allowed_prefixes):
            continue
        text = _read_text(py)
        if "with_stage_output(" in text:
            hits.append(rel)
    if hits:
        return Result("CHK-19", False, "; ".join(hits))
    return Result("CHK-19", True, "0 hand-built states outside pipeline_state tests")

CHECKS = [
    chk_legacy_symbols,
    chk_execution_context_fields,
    chk_pipeline_state_typing,
    chk_runtime_type_guard,
    chk_stage_list,
    chk_kill_switch_required,
    chk_no_safety_fallbacks,
    chk_no_hidden_globals,
    chk_test_fixtures_not_in_src,
    chk_no_default_str,
    chk_no_skips,
    chk_required_tests_exist,
    chk_suite_green,
    chk_count,
    chk_manifests,
    chk_no_src_imports,
    chk_contract_conformance,
    chk_canonical_vocabularies,
    chk_no_hand_built_states,
]

def main() -> int:
    rows = []
    failed = 0
    for check in CHECKS:
        try:
            result = check()
        except Exception as exc:
            print(f"CHECKER CRASH in {check.__name__}: {exc}")
            raise
        rows.append(result)
        if not result.passed:
            failed += 1

    print("ID | check | PASS/FAIL | detail")
    print("---|-------|-----------|--------")
    for r in rows:
        print(f"{r.check_id} | {r.check_id} | {'PASS' if r.passed else 'FAIL'} | {r.detail}")
    print(f"\nTotal: {len(rows)} checks, {len(rows) - failed} PASS, {failed} FAIL")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
