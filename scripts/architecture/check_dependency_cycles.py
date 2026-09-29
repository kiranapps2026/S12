"""
Architecture Drift Detection — Dependency Cycle Check.

Verifies that the module dependency graph has no cycles.
CI gate: unauthorized_dependency, dependency cycle detection

Canonical dependency direction:
    Contracts → Domain → Control Plane → Execution → Adapters → External
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Canonical layer ordering (lower = higher level)
LAYER_ORDER = {
    "contracts": 0,
    "constants": 0,  # leaf module: importable from every layer
    "memory": 2,
    "engine/registry": 3,
    "engine/stages": 3,
    "engine/control_plane": 4,
    "engine/execution": 5,
    "engine/reliability": 6,
    "engine/providers": 7,
    "adapters": 9,  # outermost: depends on everything above, nothing depends on it
}


def get_layer(rel_path: str) -> int:
    """Get the layer number for a module path."""
    # Normalize path
    rel_path = rel_path.replace("\\", "/")
    for layer, order in LAYER_ORDER.items():
        if rel_path.startswith(layer):
            return order
    return 99  # Unknown layer


def extract_imports(file_path: Path, root: Path) -> list[str]:
    """Extract internal imports from a Python file."""
    imports: list[str] = []

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if _is_internal(module):
                    imports.append(module)
        elif isinstance(node, ast.ImportFrom):
            if node.module and _is_internal(node.module):
                imports.append(node.module)
            # relative imports stay inside the importer's own package: no layer crossing

    return imports


def _is_internal(module: str) -> bool:
    """A module is internal iff its top-level name is a package or module under src/.
    (Anything else — standard library, third party — is external.)"""
    top = module.split(".")[0]
    return (SRC / top).is_dir() or (SRC / f"{top}.py").is_file()


def build_dependency_graph() -> dict[str, set[str]]:
    """Build the internal dependency graph."""
    graph: dict[str, set[str]] = defaultdict(set)

    for py_file in SRC.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue

        rel_path = str(py_file.relative_to(SRC)).replace("\\", "/").replace(".py", "")
        # Normalize: src/contracts/stage_registry → contracts.stage_registry
        if rel_path.startswith("src/"):
            rel_path = rel_path[4:]

        imports = extract_imports(py_file, SRC)
        for imp in imports:
            imp_path = imp.replace(".", "/")
            graph[rel_path].add(imp_path)

    return dict(graph)


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Detect cycles in the dependency graph using DFS."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
                return True

        path.pop()
        rec_stack.remove(node)
        return False

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles


def check_layer_violations() -> list[str]:
    """Check for imports that violate the layer dependency direction."""
    violations: list[str] = []
    graph = build_dependency_graph()

    for src, deps in graph.items():
        src_layer = get_layer(src)
        for dep in deps:
            dep_layer = get_layer(dep)
            if dep_layer > src_layer:
                violations.append(
                    f"  {src} (layer {src_layer}) → {dep} (layer {dep_layer})"
                )

    return violations


def main() -> int:
    print("=" * 60)
    print("Dependency Cycle Check")
    print("=" * 60)

    # Check for cycles
    graph = build_dependency_graph()
    cycles = detect_cycles(graph)

    if cycles:
        print(f"\n❌ Dependency cycles detected ({len(cycles)}):")
        for cycle in cycles:
            print(f"   {' → '.join(cycle)}")
    else:
        print("\n✅ No dependency cycles detected")

    # Check for layer violations
    violations = check_layer_violations()
    if violations:
        print(f"\n⚠️  Layer dependency violations ({len(violations)}):")
        for v in violations[:10]:  # Limit output
            print(v)
        if len(violations) > 10:
            print(f"   ... and {len(violations) - 10} more")
    else:
        print("✅ No layer dependency violations")

    if cycles:
        print(f"\n🔴 FAIL: {len(cycles)} dependency cycle(s) detected")
        return 1

    if violations:
        print(f"\n🟡 WARNING: {len(violations)} layer violation(s)")
        return 0

    print("\n🟢 PASS: Dependency graph is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
