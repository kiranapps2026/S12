"""Which source files are S12–S15 code, and static scans over them (owner fixture).

Frozen S0–S11 code = every file under ``src/`` at tag ``s0-s11-certified`` except the S12 prototype files listed in
PROTOTYPE (M0 preflight item 3; ruling CONF-011). Frozen files must be byte-identical to the tag.
S12 code = every ``src/**/*.py`` that is not frozen (the prototype files plus everything added after the tag).
"""
from __future__ import annotations

import ast
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAG = "s0-s11-certified"

PROTOTYPE = frozenset({
    "src/engine/stages/s12_entry/__init__.py", "src/engine/stages/s12_entry/admission.py",
    "src/engine/stages/s12_entry/checks.py", "src/engine/stages/s12_entry/verifiers.py",
    "src/engine/stages/s12_execute/__init__.py", "src/engine/stages/s12_execute/guard.py",
    "src/engine/stages/s12_execute/loop.py", "src/engine/stages/s12_execute/transitions.py",
    "src/engine/stages/s12_worker_execution/handler.py", "src/engine/stages/s13_reconciliation/handler.py",
    "src/engine/stages/s14_verification/handler.py", "src/engine/stages/s15_final_state/handler.py",
    "src/adapters/postgres/admission.py", "src/adapters/postgres/execution.py",
    "src/adapters/postgres/budget_reserver.py", "src/adapters/postgres/live_authorization.py",
    "src/adapters/runtime/circuit_breaker.py",
    "src/engine/execution/__init__.py", "src/engine/reliability/__init__.py",
})

S12_TABLES = ("execution_runs", "execution_steps", "execution_manifests", "execution_plans", "execution_ownership",
              "state_transitions", "budget_reservations", "worker_leases", "step_reconciliations", "dead_letters",
              "idempotency_ledger", "checkpoints", "operation_quotas", "workers", "pending_confirmations")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


@lru_cache(maxsize=1)
def frozen_files() -> frozenset:
    return frozenset(p for p in _git("ls-tree", "-r", "--name-only", TAG, "src").splitlines() if p not in PROTOTYPE)


def frozen_changes() -> list[str]:
    """Frozen files that differ from the tag (changed or deleted)."""
    changed = _git("diff", "--name-only", TAG, "--", "src").splitlines()
    untracked = _git("ls-files", "--others", "--exclude-standard", "src").splitlines()
    return sorted(p for p in set(changed) | set(untracked) if p in frozen_files())


def s12_files() -> list[Path]:
    frozen = frozen_files()
    return sorted(p for p in (ROOT / "src").rglob("*.py")
                  if "__pycache__" not in p.parts and p.relative_to(ROOT).as_posix() not in frozen)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _fold(node: ast.AST) -> str | None:
    """Constant strings, `a + b` of strings, and f-strings (formatted parts as {})."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def string_literals(path: Path) -> list[tuple[int, str]]:
    """Every non-docstring string literal (outermost fold only) with its line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs, seen, out = _docstring_ids(tree), set(), []
    for node in ast.walk(tree):
        if id(node) in seen or id(node) in docs:
            continue
        text = _fold(node)
        if text is not None:
            for child in ast.walk(node):
                seen.add(id(child))
            out.append((node.lineno, text))
    return out


def sql_statements(path: Path) -> list[tuple[int, str]]:
    keywords = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")
    return [(line, text) for line, text in string_literals(path)
            if any(k in text.upper() for k in keywords) and any(t in text for t in S12_TABLES)]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def attribute_uses(path: Path, owner: str, attr: str) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == attr
            and isinstance(n.value, ast.Name) and n.value.id == owner]
