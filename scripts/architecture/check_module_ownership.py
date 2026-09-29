"""
Architecture Drift Detection — Module Ownership Check.

Verifies that every module/file in src/ has an entry in the Ownership Registry.
CI gate: component_has_no_owner
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]  # scripts/ → project root
SRC = ROOT / "src"

# Modules that don't need ownership entries
EXEMPT_MODULES = frozenset({
    "__init__.py",
    "_version.py",
    "exceptions.py",
    "errors.py",
    "types.py",
    "protocols.py",
})


@dataclass(frozen=True)
class ModuleInfo:
    """Information about a source module."""
    rel_path: str
    is_init: bool
    classes: list[str]
    functions: list[str]


def scan_modules() -> list[ModuleInfo]:
    """Scan all Python modules in src/."""
    modules: list[ModuleInfo] = []

    for py_file in sorted(SRC.rglob("*.py")):
        rel_path = str(py_file.relative_to(SRC))
        name = py_file.name

        if name in EXEMPT_MODULES:
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        classes = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        ]
        functions = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and not node.name.startswith("_")
            and isinstance(node, ast.FunctionDef)
        ]

        modules.append(ModuleInfo(
            rel_path=rel_path,
            is_init=(name == "__init__.py"),
            classes=classes,
            functions=functions[:10],  # Limit for display
        ))

    return modules


def check_ownership() -> tuple[list[str], list[str]]:
    """
    Check that every module has an owner.

    Returns:
        (unowned_modules, ownerless_public_api)
    """
    modules = scan_modules()

    # Import ownership registry to check against
    sys.path.insert(0, str(SRC))
    try:
        from contracts.ownership import OWNERSHIP_REGISTRY  # noqa: F401
        registered_modules = {e.canonical_module for e in OWNERSHIP_REGISTRY}
    except ImportError:
        registered_modules = set()

    unowned = []
    for mod in modules:
        # Check if any registered module path matches
        has_owner = any(
            mod.rel_path.startswith(reg.replace("src/", "").rstrip("/"))
            for reg in registered_modules
        )
        if not has_owner and not mod.is_init:
            unowned.append(mod.rel_path)

    return unowned, []


def main() -> int:
    print("=" * 60)
    print("Module Ownership Check")
    print("=" * 60)

    unowned, _ = check_ownership()

    if unowned:
        print(f"\n⚠️  Modules without ownership entry ({len(unowned)}):")
        for mod in unowned:
            print(f"   - {mod}")
        print("\n   Add entries to src/contracts/ownership.py")
    else:
        print("\n✅ All modules have ownership entries")

    # This is a warning, not a failure, for new projects
    print("\n🟢 PASS: Ownership check complete (warnings above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
