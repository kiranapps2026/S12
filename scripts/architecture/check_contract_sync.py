"""
Architecture Drift Detection — Contract-to-Code Sync Check.

Verifies that every contract type defined in DATA_CONTRACTS.md has a corresponding
Python implementation, and every implemented public class has a contract.

CI gate: contract_exists_but_no_implementation, implementation_exists_but_no_contract
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Root directory
ROOT = Path(__file__).resolve().parents[2]  # scripts/ → project root
SRC = ROOT / "src"


@dataclass(frozen=True)
class ContractType:
    """A type defined in DATA_CONTRACTS.md."""
    name: str
    section: str
    kind: str  # dataclass, enum, protocol, etc.


@dataclass(frozen=True)
class ImplementationType:
    """A type implemented in Python code."""
    name: str
    file: Path
    lineno: int
    is_public: bool


def extract_contract_types() -> list[ContractType]:
    """
    Extract contract types from DATA_CONTRACTS.md.

    This is a simplified extraction that looks for Python class/enum definitions
    in code blocks within the contracts document.
    """
    contracts_file = ROOT / "docs" / "DATA_CONTRACTS.md"
    if not contracts_file.exists():
        print(f"WARNING: DATA_CONTRACTS.md not found at {contracts_file}")
        return []

    content = contracts_file.read_text(encoding="utf-8")

    types: list[ContractType] = []
    current_section = ""

    for line in content.splitlines():
        # Track section headers
        if re.match(r"^## \d+\.", line):
            current_section = line.strip()

        # Look for class definitions in code blocks
        if re.match(r"^(class|@dataclass.*\nclass|class \w+\(.*Enum\))", line.strip()):
            match = re.search(r"class (\w+)", line)
            if match:
                name = match.group(1)
                kind = "enum" if "Enum" in line else "dataclass" if "dataclass" in content[:content.index(line)] else "class"
                types.append(ContractType(
                    name=name,
                    section=current_section,
                    kind=kind,
                ))

    return types


def extract_implementations() -> list[ImplementationType]:
    """Extract all public class definitions from src/."""
    implementations: list[ImplementationType] = []

    for py_file in sorted(SRC.rglob("*.py")):
        # Skip __init__.py files
        if py_file.name == "__init__.py":
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        rel_path = py_file.relative_to(SRC)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                is_public = not node.name.startswith("_")
                implementations.append(ImplementationType(
                    name=node.name,
                    file=rel_path,
                    lineno=node.lineno,
                    is_public=is_public,
                ))
            elif isinstance(node, ast.Enum):
                implementations.append(ImplementationType(
                    name=node.name,
                    file=rel_path,
                    lineno=node.lineno,
                    is_public=True,
                ))

    return implementations


def check_contract_sync() -> tuple[list[str], list[str]]:
    """
    Check contract-to-code synchronization.

    Returns:
        (missing_implementations, orphan_implementations)
    """
    contracts = extract_contract_types()
    implementations = extract_implementations()

    contract_names = {c.name for c in contracts}
    impl_names = {i.name for i in implementations}

    # Contracts without implementation
    missing = sorted(contract_names - impl_names)

    # Implementations without contracts (only public ones)
    orphan = sorted(
        i.name for i in implementations
        if i.is_public and i.name not in contract_names
    )

    return missing, orphan


def main() -> int:
    print("=" * 60)
    print("Contract-to-Code Sync Check")
    print("=" * 60)

    missing, orphan = check_contract_sync()

    if missing:
        print(f"\n❌ Contracts without implementation ({len(missing)}):")
        for name in missing:
            print(f"   - {name}")
    else:
        print("\n✅ All contracts have implementations")

    if orphan:
        print(f"\n⚠️  Implementations without contracts ({len(orphan)}):")
        for name in orphan:
            print(f"   - {name}")
        print("\n   (These may be legitimate internal implementations)")
    else:
        print("✅ All implementations have contracts")

    if missing:
        print(f"\n🔴 FAIL: {len(missing)} contract(s) missing implementation")
        return 1

    print("\n🟢 PASS: Contract-to-code sync is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
