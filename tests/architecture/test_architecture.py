"""Static rules for src/: no dead code, clean layering, small units, no test doubles.

These read the source with ``ast`` and import nothing, so they cannot be satisfied by
side effects at import time.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = "supragents"
ENTRY_MODULES = ("supragents.pipeline.runner", "supragents.bootstrap", "supragents.__main__")
MAX_FILE_LINES = 200
MAX_FUNCTION_LINES = 40

# Which top-level packages each layer may import from (besides itself and the stdlib).
ALLOWED_IMPORTS = {
    "contracts": {"contracts"},
    "ports": {"contracts", "ports"},
    "policy": {"contracts", "policy"},
    "observability": {"contracts", "observability"},
    "stages": {"contracts", "ports", "policy", "pipeline.deps", "stages.guards", "stages.s08_safety"},
    "pipeline": {"contracts", "ports", "observability", "pipeline", "stages"},
    "adapters": {"contracts", "ports", "adapters"},
    "settings": set(),
    "bootstrap": {"adapters", "pipeline", "ports", "settings"},
    "__main__": {"adapters", "bootstrap", "contracts", "settings"},
}


def _modules() -> dict[str, Path]:
    modules = {}
    for path in SRC.rglob("*.py"):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    return modules


MODULES = _modules()


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return {name for name in found if name in MODULES}


def test_every_module_is_reachable_from_an_entry_point():
    reachable, frontier = set(), list(ENTRY_MODULES)
    while frontier:
        module = frontier.pop()
        if module in reachable:
            continue
        reachable.add(module)
        frontier.extend(_imports(MODULES[module]))
    packages = {name for name, path in MODULES.items() if path.name == "__init__.py"}
    assert set(MODULES) - packages - reachable == set(), "dead modules"


@pytest.mark.parametrize("module", sorted(MODULES))
def test_layering(module):
    parts = module.split(".")
    if len(parts) < 2:
        return
    allowed = ALLOWED_IMPORTS[parts[1]]
    for imported in _imports(MODULES[module]):
        target = imported.removeprefix(f"{PACKAGE}.")
        assert any(target == rule or target.startswith(f"{rule}.") for rule in allowed), (
            f"{module} imports {imported}"
        )


@pytest.mark.parametrize("module", sorted(MODULES))
def test_units_are_small(module):
    tree = ast.parse(MODULES[module].read_text(encoding="utf-8"))
    assert len(MODULES[module].read_text(encoding="utf-8").splitlines()) <= MAX_FILE_LINES
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            assert length <= MAX_FUNCTION_LINES, f"{module}.{node.name} has {length} lines"


FORBIDDEN_TEXT = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b|\b(Fake|Mock|Stub|InMemory)[A-Z]\w*")
PRINT = re.compile(r"\bprint\(")
CLI_MODULE = "supragents.__main__"  # the only module that writes to the terminal


@pytest.mark.parametrize("module", sorted(MODULES))
def test_no_placeholders_prints_or_test_doubles(module):
    text = MODULES[module].read_text(encoding="utf-8")
    assert not FORBIDDEN_TEXT.search(text), FORBIDDEN_TEXT.search(text)
    if module != CLI_MODULE:
        assert not PRINT.search(text), f"{module} prints; use logging"


@pytest.mark.parametrize("module", sorted(MODULES))
def test_no_module_level_mutable_state(module):
    tree = ast.parse(MODULES[module].read_text(encoding="utf-8"))
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        assert not isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp)), (
            f"{module}:{node.lineno} module-level mutable value"
        )
        assert not isinstance(node, ast.Global)
