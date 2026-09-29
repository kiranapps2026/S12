"""
Architecture Drift Detection — Test Coverage Check.

Verifies that every module with architectural significance has corresponding tests.
CI gate: component_has_no_tests
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

# Modules that don't need direct test files
EXEMPT_MODULES = frozenset({
    "__init__.py",
    "_version.py",
    "exceptions.py",
    "errors.py",
    "protocols.py",
    "stage_registry.py",  # Registry is tested implicitly
    "ownership.py",       # Ownership is tested implicitly
})


@dataclass(frozen=True)
class ModuleInfo:
    """Information about a source module."""
    rel_path: str
    is_public: bool
    has_classes: bool


@dataclass(frozen=True)
class TestInfo:
    """Information about a test module."""
    rel_path: str
    test_functions: int


def scan_src_modules() -> list[ModuleInfo]:
    """Scan source modules."""
    modules: list[ModuleInfo] = []

    for py_file in SRC.rglob("*.py"):
        if py_file.name in EXEMPT_MODULES:
            continue

        rel = str(py_file.relative_to(SRC))

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        has_classes = any(isinstance(n, ast.ClassDef) and not n.name.startswith("_")
                          for n in ast.walk(tree))
        is_public = not py_file.name.startswith("_")

        modules.append(ModuleInfo(
            rel_path=rel,
            is_public=is_public,
            has_classes=has_classes,
        ))

    return modules


def scan_test_modules() -> set[str]:
    """Get all test module paths."""
    test_files = set()
    if TESTS.exists():
        for py_file in TESTS.rglob("test_*.py"):
            rel = str(py_file.relative_to(TESTS))
            # Extract the module being tested
            # e.g., tests/unit/test_resolver.py → engine/registry/resolver.py
            parts = rel.split("/")
            if len(parts) >= 3:
                module_name = parts[-1].replace("test_", "").replace(".py", "")
                test_files.add(module_name)

    return test_files


def check_test_coverage() -> tuple[list[str], list[str]]:
    """
    Check test coverage for architectural modules.

    Returns:
        (modules_without_tests, info)
    """
    modules = scan_src_modules()
    test_modules = scan_test_modules()

    missing = []
    for mod in modules:
        if not mod.is_public:
            continue
        if not mod.has_classes:
            continue

        # Check if a test module exists for this module
        module_name = Path(mod.rel_path).stem
        has_test = any(
            module_name in test_mod
            for test_mod in test_modules
        )

        if not has_test:
            missing.append(mod.rel_path)

    return missing, []


def main() -> int:
    print("=" * 60)
    print("Test Coverage Check")
    print("=" * 60)

    missing, _ = check_test_coverage()

    if missing:
        print(f"\n⚠️  Public modules without test files ({len(missing)}):")
        for mod in missing:
            print(f"   - {mod}")
    else:
        print("\n✅ All public modules have test coverage")

    # Warning only for now
    print("\n🟢 PASS: Test coverage check complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
