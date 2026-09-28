#!/usr/bin/env python3
"""
OWNER CERTIFIER for S0-S11 (1SuperAgents).

Owned by the project owner. The coding agent must NOT modify this file.
Its SHA-256 is recorded in docs/gates/owner_certify.sha256 and is verified
before every certification. Certification = this script exits 0.

Usage (from the repository root):
    python tools/owner_certify.py            # run all checks
    python tools/owner_certify.py --static   # static checks only (no pytest)
    python tools/owner_certify.py --selftest # prove every static check can fail

Static checks read files with ast/regex only (no imports of project code), so they
cannot be fooled by import-time side effects.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXCLUDED_PKG = re.compile(r"[\\/](s1[2-5]_[^\\/]*)[\\/]")   # pre-existing S12-S15 handlers (R-I/R-J)
SEQUENCE = tuple(f"S{i}" for i in range(12))

CONTRACTS = {  # class -> approved extensions (runbook R-O)
    "ExecutionContext": set(),
    "Plan": set(),
    "Step": set(),
    "FrozenBindingIdentity": {"capability_version", "binding_version",
                              "risk_policy_version", "authorization_version"},
    "TaskProfile": set(),
    "SafetyResult": set(),
    "ValidationResult": set(),
    "Confirmation": set(),
    "ExecutionManifest": {"auth_result_id"},
    "StageStatus": set(),
    "PathDecision": set(),
}
ENUMS = {"StageStatus", "PathDecision"}

NON_CANONICAL = ["READ", "WRITE", "DELETE", "IDEMPOTENT_WRITE", "STANDARD",
                 "SINGLE_STEP", "WORKFLOW", "sequential", "approved"]

REQUIRED_TESTS = [
    ('tests/stages/test_s8_safety_gate.py::test_kill_switch_engaged_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_kill_switch_policy_missing_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_kill_switch_policy_raises_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_kill_switch_evaluated_first', 1),
    ('tests/stages/test_s8_safety_gate.py::test_status_denials', 6),
    ('tests/stages/test_s8_safety_gate.py::test_all_checks_pass_allows', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_write_once_guard', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_matrix', 40),
    ('tests/stages/test_s8_safety_gate.py::test_all_unknown_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_missing_identity_denies', 4),
    ('tests/stages/test_s8_safety_gate.py::test_missing_dependency_denies', 4),
    ('tests/stages/test_s8_safety_gate.py::test_llm_injection_does_not_change_decision', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_missing_task_profile_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_providers_receive_frozen_values', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_allow_sets_auth_passed', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_deny_leaves_context_unchanged', 1),
    ('tests/stages/test_s8_safety_gate.py::test_s8_writes_only_safety_result_and_context', 1),
    ('tests/stages/test_s8_safety_gate.py::test_connection_expired_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_kill_switch_invalid_value_denies', 1),
    ('tests/stages/test_s8_safety_gate.py::test_first_failure_stops_evaluation', 1),
    ('tests/stages/test_s7_path_routing.py::test_s7_unmatched_combination_clarifies', 1),
    ('tests/integration/test_s0_to_s11_journey.py::test_every_executable_path_runs_s8', 1),
    ('tests/stages/test_s7_to_s11.py::test_s9_requires_safety_passed', 1),
    ('tests/stages/test_s7_to_s11.py::test_s10_requires_safety_passed', 1),
    ('tests/stages/test_s7_to_s11.py::test_s11_requires_safety_passed', 1),
    ('tests/stages/test_s7_to_s11.py::test_manifest_records_auth_result_id', 1),
    ('tests/contracts/test_pipeline_state.py::test_write_order_enforced', 1),
    ('tests/stages/test_s7_path_routing.py::test_s7_routing_table', 10),
    ('tests/stages/test_s7_path_routing.py::test_s7_never_emits_agentic', 1),
    ('tests/stages/test_s6_task_profile.py::test_s6_copies_risk_and_mutations_from_frozen_binding', 1),
    ('tests/stages/test_s6_task_profile.py::test_s6_confirmation_table', 9),
    ('tests/stages/test_s7_path_routing.py::test_s7_threshold_unavailable_denies', 1),
    ('tests/stages/test_s9_plan_creation.py::test_s9_plan_shape', 1),
    ('tests/stages/test_s9_plan_creation.py::test_s9_uses_frozen_risk_when_task_profile_tampered', 1),
    ('tests/stages/test_s9_plan_creation.py::test_s9_plan_hash_changes_with_execution_inputs', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_not_required_writes_outcome', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_required_creates_pending_confirmation', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_expired_denies', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_wrong_user_denies', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_wrong_hash_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_kernel_op_mismatch_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_risk_mismatch_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_empty_plan_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_negative_budget_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_cycle_denies', 1),
    ('tests/stages/test_s11_plan_validation.py::test_s11_unconsumed_confirmation_denies', 1),
    ('tests/architecture/test_pipeline_runner.py::test_stage_sequence_is_s0_to_s11', 1),
    ('tests/architecture/test_pipeline_runner.py::test_uncaught_exception_becomes_error_and_stops', 1),
    ('tests/contracts/test_execution_context_protection.py::test_no_binding_fields_on_context', 1),
    ('tests/contracts/test_execution_context_protection.py::test_s5_writes_only_policy_version_fields', 1),
    ('tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_wrong_type', 1),
    ('tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_non_owner', 1),
    ('tests/contracts/test_pipeline_state.py::test_with_stage_output_rejects_second_write', 1),
    ('tests/contracts/test_pipeline_state.py::test_s11_writes_two_owned_fields', 1),
    ('tests/architecture/test_runtime_no_reresolve.py::test_s6_to_s11_no_resolver_calls', 1),
    ('tests/architecture/test_runtime_no_reresolve.py::test_frozen_binding_identity_preserved', 1),
    ('tests/integration/test_s0_to_s11_journey.py::test_full_journey_real_handlers', 1),
    ('tests/integration/test_short_circuit_journeys.py::test_s2_deny', 1),
    ('tests/integration/test_short_circuit_journeys.py::test_s2_clarify', 1),
    ('tests/integration/test_short_circuit_journeys.py::test_s8_deny', 1),
    ('tests/integration/test_short_circuit_journeys.py::test_s10_expired_deny', 1),
    ('tests/integration/test_short_circuit_journeys.py::test_s11_plan_mutation_deny', 1),
    # runbook R-Z: confirmation store carries tenant_id and execution_id (owner ruling)
    ('tests/stages/test_s10_confirmation.py::test_s10_store_receives_tenant_and_execution_id', 1),
    ('tests/stages/test_s10_confirmation.py::test_s10_wrong_tenant_denies', 1),
    ('tests/contracts/test_confirmation_store.py::test_store_save_requires_tenant_and_execution_id', 1),
]

# ----------------------------------------------------------------- helpers
def py_files(root: Path, sub: str, exclude_s12: bool = True):
    base = root / sub
    if not base.exists():
        return []
    out = []
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if exclude_s12 and EXCLUDED_PKG.search(str(p)):
            continue
        out.append(p)
    return out


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")


def code_lines(text: str):
    """Yield (lineno, line) excluding pure comment lines."""
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        yield i, line


def grep(files, pattern: str, root: Path):
    rx = re.compile(pattern)
    hits = []
    for f in files:
        for i, line in code_lines(read(f)):
            if rx.search(line):
                hits.append(f"{f.relative_to(root)}:{i}")
    return hits


def find_class(root: Path, name: str):
    """Return ast.ClassDef for `name`, preferring src/contracts/. Excludes S12-S15."""
    candidates = []
    for f in py_files(root, "src"):
        try:
            tree = ast.parse(read(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                candidates.append((0 if "contracts" in f.parts else 1, f, node))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][2], candidates[0][1]


def class_fields(node: ast.ClassDef, enum: bool):
    names = set()
    for stmt in node.body:
        if enum and isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_"):
                    names.add(t.id)
        if not enum and isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            ann = ast.unparse(stmt.annotation)
            if "ClassVar" not in ann and not stmt.target.id.startswith("_"):
                names.add(stmt.target.id)
    return names


def annassign(node: ast.ClassDef, field: str):
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == field:
            return stmt
    return None


def spec_fields(spec_text: str):
    """Parse ```python blocks of DATA_CONTRACTS.md -> {class: set(field names)}."""
    result = {}
    for block in re.findall(r"```python\n(.*?)```", spec_text, flags=re.S):
        lines = block.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"^class (\w+)(\(([^)]*)\))?\s*:", lines[i])
            if not m:
                i += 1
                continue
            name, bases = m.group(1), (m.group(3) or "")
            enum = "Enum" in bases
            fields = set()
            i += 1
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                ln = lines[i]
                if re.match(r"^    (def |@)", ln):
                    break
                if enum:
                    fm = re.match(r"^    ([A-Z][A-Z0-9_]*)\s*=", ln)
                else:
                    fm = re.match(r"^    ([a-z_][a-z0-9_]*)\s*:", ln)
                if fm:
                    fields.add(fm.group(1))
                i += 1
            if name not in result and fields:
                result[name] = fields
    return result


# ----------------------------------------------------------------- static checks
def chk01(root):
    hits = grep(py_files(root, "src") + py_files(root, "tests", False),
                r"\bStageResult\b|_StageHandlerAdapter|stage_result_to_pipeline_update|_replace_fields", root)
    return not hits, hits


def chk02(root):
    node, _ = find_class(root, "ExecutionContext")
    if node is None:
        return False, ["class ExecutionContext not found"]
    bad = class_fields(node, False) & {"provider", "binding_id", "capability_id", "kernel_op_id", "metadata"}
    return not bad, sorted(bad)


def chk03(root):
    node, _ = find_class(root, "PipelineState")
    if node is None:
        return False, ["class PipelineState not found"]
    bad = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            ann = ast.unparse(stmt.annotation)
            if re.search(r"\b(dict|Dict|Any|Mapping|MutableMapping|object)\b", ann):
                bad.append(f"{stmt.target.id}: {ann}")
    return not bad, bad


def chk05(root):
    for f in py_files(root, "src"):
        try:
            tree = ast.parse(read(f))
        except SyntaxError:
            continue
        for stmt in tree.body:
            targets = []
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
                value = stmt.value
            if "PRE_EXECUTION_SEQUENCE" in targets:
                try:
                    got = tuple(ast.literal_eval(value))
                except Exception:
                    return False, [f"{f.relative_to(root)}: PRE_EXECUTION_SEQUENCE is not a literal"]
                return got == SEQUENCE, [f"{f.relative_to(root)}: {got}"]
    return False, ["PRE_EXECUTION_SEQUENCE not defined at module level in src/"]


def chk06(root):
    node, f = find_class(root, "KernelPolicy")
    if node is None:
        return False, ["class KernelPolicy not found"]
    problems = []
    for field in ("kill_switch_engaged", "risk_deny_threshold"):
        a = annassign(node, field)
        if a is None:
            problems.append(f"{field}: missing")
        elif a.value is not None:
            problems.append(f"{field}: has a default ({ast.unparse(a.value)})")
    return not problems, problems


def chk07(root):
    hits = grep(py_files(root, "src"), r"kill_switch_engaged\s*=\s*False|enable_kill_switch", root)
    return not hits, hits


ALLOWED_MODULE_NAMES = {"logger", "log", "__all__", "__version__"}


def chk08(root):
    hits = []
    for f in py_files(root, "src"):
        try:
            tree = ast.parse(read(f))
        except SyntaxError:
            continue
        rel = f.relative_to(root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                hits.append(f"{rel}:{node.lineno} global statement")
        for stmt in tree.body:  # module level only
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("set_"):
                hits.append(f"{rel}:{stmt.lineno} module-level setter {stmt.name}()")
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                value = stmt.value
                for t in targets:
                    if not isinstance(t, ast.Name) or t.id in ALLOWED_MODULE_NAMES:
                        continue
                    if t.id == "__all__" or value is None:
                        continue
                    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
                        hits.append(f"{rel}:{stmt.lineno} module-level mutable {t.id}")
                    elif isinstance(value, ast.Call):
                        fn = ast.unparse(value.func)
                        if fn in {"logging.getLogger", "getLogger", "TypeVar", "frozenset", "tuple",
                                  "MappingProxyType", "types.MappingProxyType", "re.compile",
                                  "NewType", "field", "dataclasses.field"}:
                            continue
                        if t.id.isupper():
                            continue
                        hits.append(f"{rel}:{stmt.lineno} module-level instance {t.id} = {fn}(...)")
    return not hits, hits


def chk09(root):
    hits = grep(py_files(root, "src"), r"InMemoryAuthorizationStateProvider|AllowAllMutationPolicy|ConfigurableAuthState", root)
    return not hits, hits


def chk10(root):
    hits = grep(py_files(root, "src"), r"default\s*=\s*str\b", root)
    return not hits, hits


def chk11(root):
    hits = grep(py_files(root, "tests", False), r"pytest\.skip|\bxfail\b|mark\.skip", root)
    return not hits, hits


def chk16(root):
    hits = grep(py_files(root, "src") + py_files(root, "tests", False), r"^\s*(from|import)\s+src\.", root)
    return not hits, hits


def chk17(root):
    spec_path = root / "docs" / "implementation" / "DATA_CONTRACTS.md"
    if not spec_path.exists():
        return False, [f"{spec_path} not found"]
    spec = spec_fields(read(spec_path))
    problems = []
    for cls, ext in CONTRACTS.items():
        if cls not in spec:
            problems.append(f"{cls}: not found in DATA_CONTRACTS.md")
            continue
        node, f = find_class(root, cls)
        if node is None:
            problems.append(f"{cls}: no implementation class with this exact name in src/")
            continue
        impl = class_fields(node, cls in ENUMS)
        missing = spec[cls] - impl
        extra = impl - spec[cls] - ext
        if missing or extra:
            problems.append(f"{cls} ({f.relative_to(root)}): missing={sorted(missing)} extra={sorted(extra)}")
    return not problems, problems


def chk18(root):
    alt = "|".join(re.escape(w) for w in NON_CANONICAL)
    hits = grep(py_files(root, "src"), rf"""["']({alt})["']""", root)
    return not hits, hits


def chk19(root):
    files = [f for f in py_files(root, "tests", False)
             if f.name != "test_pipeline_state.py" and "fixtures" not in f.parts]
    hits = grep(files, r"with_stage_output\(", root)
    return not hits, hits


PIN_FILE = Path("docs") / "gates" / "spec_pins.sha256"


def chk20(root):
    """Spec documents are owner-controlled: their SHA-256 must match the owner's pins."""
    import hashlib
    pin_path = root / PIN_FILE
    if not pin_path.exists():
        return False, [f"{PIN_FILE} missing (owner must create it)"]
    problems, count = [], 0
    for line in read(pin_path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            problems.append(f"bad pin line: {line}")
            continue
        expected, rel = parts[0].upper(), parts[1].strip()
        target = root / rel
        count += 1
        if not target.exists():
            problems.append(f"{rel}: missing")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest().upper()
        if actual != expected:
            problems.append(f"{rel}: changed (expected {expected[:12]}…, got {actual[:12]}…)")
    if count == 0:
        problems.append("no pins listed")
    return not problems, problems


STATIC = [
    ("OWN-01", "legacy symbols gone (src + tests)", chk01),
    ("OWN-02", "ExecutionContext has no binding fields / metadata", chk02),
    ("OWN-03", "PipelineState fields not dict/Any/Mapping", chk03),
    ("OWN-05", "PRE_EXECUTION_SEQUENCE == S0..S11 exactly", chk05),
    ("OWN-06", "KernelPolicy kill_switch_engaged / risk_deny_threshold required", chk06),
    ("OWN-07", "no kill-switch fallback in src", chk07),
    ("OWN-08", "no globals, setters, module-level mutable state", chk08),
    ("OWN-09", "test doubles not in src", chk09),
    ("OWN-10", "no default=str in src", chk10),
    ("OWN-11", "no skip/xfail in tests", chk11),
    ("OWN-16", "no 'src.' import paths", chk16),
    ("OWN-17", "contract field names match DATA_CONTRACTS (R-O)", chk17),
    ("OWN-18", "no non-canonical vocabulary literals in src", chk18),
    ("OWN-19", "no with_stage_output in tests outside allowed files", chk19),
    ("OWN-20", "spec documents unchanged since owner pinned them", chk20),
]


# ----------------------------------------------------------------- pytest checks
# pytest's text output depends on verbosity and on the project's own addopts (e.g. an
# "addopts = -v" cancels "-q" and switches --collect-only to tree format). To be
# independent of all that, results are captured by a tiny plugin that writes JSON.
_PLUGIN = """
import json, os
_ids = []
_counts = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "error": 0}
def pytest_collection_finish(session):
    _ids.extend(item.nodeid for item in session.items)
def pytest_collectreport(report):
    if report.failed:
        _counts["error"] += 1
def pytest_runtest_logreport(report):
    if hasattr(report, "wasxfail"):
        if report.skipped:
            _counts["xfailed"] += 1
        elif report.passed and report.when == "call":
            _counts["xpassed"] += 1
        return
    if report.when == "call":
        if report.passed:
            _counts["passed"] += 1
        elif report.failed:
            _counts["failed"] += 1
        elif report.skipped:
            _counts["skipped"] += 1
    elif report.failed:
        _counts["error"] += 1
    elif report.skipped:
        _counts["skipped"] += 1
def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["OWNER_CERT_OUT"], "w", encoding="utf-8") as fh:
        json.dump({"ids": _ids, "counts": _counts, "exit": int(exitstatus)}, fh)
"""


def run_pytest(root, args):
    import json
    import os
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "_owner_cert_plugin.py").write_text(_PLUGIN, encoding="utf-8")
        out_file = Path(tmp) / "result.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["OWNER_CERT_OUT"] = str(out_file)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "_owner_cert_plugin", *args],
            cwd=root, capture_output=True, text=True, env=env)
        if not out_file.exists():
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
            return None, tail
        return json.loads(out_file.read_text(encoding="utf-8")), None


def pytest_checks(root):
    results = []
    collected, err = run_pytest(root, ["--collect-only"])
    if collected is None:
        for cid, desc in (("OWN-12", "required test IDs collected"), ("OWN-13", "full suite green, nothing skipped"),
                          ("OWN-14", "collected tests >= 185")):
            results.append((cid, desc, False, ["pytest did not run:"] + err))
    else:
        ids = collected["ids"]

        def norm(node_id: str) -> str:
            # accept tests inside classes: file::Class::name[param] -> file::name[param]
            parts = node_id.replace("\\", "/").split("::")
            return parts[0] + "::" + parts[-1] if len(parts) > 2 else "::".join(parts)

        normed = [norm(i) for i in ids]
        missing = []
        for req, minimum in REQUIRED_TESTS:
            n = sum(1 for i in normed if i == req or i.startswith(req + "["))
            if n < minimum:
                missing.append(f"{req} (found {n}, need >= {minimum})")
        if collected["counts"]["error"]:
            missing.insert(0, f"{collected['counts']['error']} collection error(s)")
        results.append(("OWN-12", "required test IDs collected", not missing, missing))

        run, err = run_pytest(root, [])
        if run is None:
            results.append(("OWN-13", "full suite green, nothing skipped", False, ["pytest did not run:"] + err))
        else:
            c = run["counts"]
            ok = (run["exit"] == 0 and c["passed"] > 0 and not any(
                c[k] for k in ("failed", "error", "skipped", "xfailed", "xpassed")))
            results.append(("OWN-13", "full suite green, nothing skipped", ok,
                            [f"exit={run['exit']} " + " ".join(f"{k}={v}" for k, v in c.items())]))
        results.append(("OWN-14", "collected tests >= 185", len(ids) >= 185, [f"collected {len(ids)}"]))

    gates = root / "docs" / "gates"
    need = ["test_manifest_baseline.txt", "test_manifest_final.txt", "test_reconciliation.md"]
    miss = [n for n in need if not (gates / n).exists()]
    results.append(("OWN-15", "manifests and reconciliation present", not miss, miss))
    return results


# ----------------------------------------------------------------- self-test
BAD_FILES = {
    "src/contracts/legacy.py": "class StageResult:\n    pass\n",
    "src/contracts/execution_context.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass ExecutionContext:\n    trace_id: str\n    provider: str\n",
    "src/contracts/pipeline_state.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass PipelineState:\n    plan: dict | None = None\n",
    "src/engine/runner.py": "PRE_EXECUTION_SEQUENCE = ('S0','S1','S2','S3','S4','S5','S6','S7','S8','S9','S10','S11','S12')\n",
    "src/contracts/kernel_policy.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass KernelPolicy:\n    kill_switch_engaged: bool = False\n    risk_deny_threshold: float = 0.9\n",
    "src/engine/s8.py": "policy = KernelPolicy(kill_switch_engaged=False)\n",
    "src/engine/globals.py": "_breaker = Breaker()\ndef set_breaker(b):\n    global _breaker\n    _breaker = b\n",
    "src/engine/fakes.py": "class InMemoryAuthorizationStateProvider:\n    pass\n",
    "src/engine/hashing.py": "import json\nx = json.dumps({}, default=str)\n",
    "tests/test_skip.py": "import pytest\npytest.skip('x')\n",
    "tests/test_imports.py": "from src.contracts import x\n",
    "src/contracts/contracts.py": "from dataclasses import dataclass\n@dataclass\nclass SafetyResult:\n    allowed: bool\n    kill_switch_active: bool = False\n",
    "src/engine/vocab.py": "MODE = 'READ'\n",
    "tests/stages/test_handbuilt.py": "def test_x(s):\n    s.with_stage_output('S5', 1)\n",
    "docs/gates/spec_pins.sha256": "0000000000000000000000000000000000000000000000000000000000000000  docs/implementation/DATA_CONTRACTS.md\n",
    "docs/implementation/DATA_CONTRACTS.md": "```python\r\nclass SafetyResult:\r\n    allowed: bool\r\n    reason: str | None = None\r\n    failed_check: str | None = None\r\n```\r\n",
}
CLEAN_FILES = {
    "src/contracts/execution_context.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass ExecutionContext:\n    trace_id: str\n",
    "src/contracts/pipeline_state.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass PipelineState:\n    plan: 'PlanCreationResult | None' = None\n",
    "src/engine/runner.py": "import logging\nlogger = logging.getLogger(__name__)\nPRE_EXECUTION_SEQUENCE = ('S0','S1','S2','S3','S4','S5','S6','S7','S8','S9','S10','S11')\n",
    "src/contracts/kernel_policy.py": "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass KernelPolicy:\n    kill_switch_engaged: bool\n    risk_deny_threshold: float\n",
    "src/contracts/contracts.py": "from dataclasses import dataclass\n@dataclass\nclass SafetyResult:\n    allowed: bool\n    reason: str | None = None\n    failed_check: str | None = None\n",
    "src/engine/vocab.py": "MODE = 'R'\n",
    "src/engine/s14_old/handler.py": "import json\nx = json.dumps({}, default=str)\n",  # excluded package
    "tests/stages/test_ok.py": "def test_x():\n    assert True\n",
    "tests/contracts/test_pipeline_state.py": "def test_x(s):\n    s.with_stage_output('S5', 1)\n",
    "docs/implementation/DATA_CONTRACTS.md": "```python\nclass SafetyResult:\n    allowed: bool\n    reason: str | None = None\n    failed_check: str | None = None\n```\n",
}


def build(tmp: Path, files):
    import hashlib
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
    if "docs/gates/spec_pins.sha256" not in files:
        spec = tmp / "docs" / "implementation" / "DATA_CONTRACTS.md"
        digest = hashlib.sha256(spec.read_bytes()).hexdigest().upper()
        pin = tmp / "docs" / "gates" / "spec_pins.sha256"
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text(f"{digest}  docs/implementation/DATA_CONTRACTS.md\n", encoding="utf-8")


def selftest():
    global CONTRACTS
    saved = CONTRACTS
    CONTRACTS = {"SafetyResult": set()}   # only this class exists in the fixture spec
    ok_all = True
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        bad, clean = Path(a), Path(b)
        build(bad, BAD_FILES)
        build(clean, CLEAN_FILES)
        for cid, desc, fn in STATIC:
            det = not fn(bad)[0]
            passed = fn(clean)[0]
            ok = det and passed
            ok_all &= ok
            print(f"{cid:7} detects violation: {'yes' if det else 'NO '}   passes clean tree: "
                  f"{'yes' if passed else 'NO '}   {'OK' if ok else 'BROKEN'}")
            if not passed:
                print("         clean-tree detail:", fn(clean)[1][:3])
    CONTRACTS = saved

    # pytest-based checks: must work even when the project sets "addopts = -v".
    global REQUIRED_TESTS
    saved_req = REQUIRED_TESTS
    REQUIRED_TESTS = [("tests/test_t.py::test_needed", 2)]
    base = ("import pytest\n@pytest.mark.parametrize('x', [1, 2])\n"
            "def test_needed(x):\n    assert True\n")
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        bad, clean = Path(a), Path(b)
        for d in (bad, clean):
            (d / "tests").mkdir()
            (d / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
            (d / "tests" / "test_t.py").write_text(base, encoding="utf-8")
        (bad / "tests" / "test_skip.py").write_text(
            "import pytest\ndef test_s():\n    pytest.skip('x')\n", encoding="utf-8")
        (bad / "tests" / "test_t.py").write_text(base.replace("[1, 2]", "[1]"), encoding="utf-8")
        bad_r = {r[0]: r[2] for r in pytest_checks(bad)}
        clean_r = {r[0]: r[2] for r in pytest_checks(clean)}
        for cid in ("OWN-12", "OWN-13"):
            det, passed = not bad_r[cid], clean_r[cid]
            ok = det and passed
            ok_all &= ok
            print(f"{cid:7} detects violation: {'yes' if det else 'NO '}   passes clean tree: "
                  f"{'yes' if passed else 'NO '}   {'OK' if ok else 'BROKEN'}")
    REQUIRED_TESTS = saved_req
    return ok_all


# ----------------------------------------------------------------- main
def main():
    root = Path.cwd()
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    rows = []
    for cid, desc, fn in STATIC:
        try:
            ok, detail = fn(root)
        except Exception as exc:          # a crash is never a PASS
            ok, detail = False, [f"CHECKER ERROR: {exc!r}"]
        rows.append((cid, desc, ok, detail))
    if "--static" not in sys.argv:
        rows += pytest_checks(root)
    width = max(len(r[1]) for r in rows)
    for cid, desc, ok, detail in rows:
        print(f"{cid:7} {desc:<{width}}  {'PASS' if ok else 'FAIL'}")
        if not ok:
            for d in detail[:15]:
                print(f"          - {d}")
            if len(detail) > 15:
                print(f"          ... {len(detail) - 15} more")
    failed = sum(1 for r in rows if not r[2])
    print(f"\n{len(rows) - failed}/{len(rows)} PASS")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
