"""
Golden architecture guard — no vector code before MR-1 (S12-S15 gate v10 §1, §14, suite 2).

Owned by the project owner. The coding agent must NOT modify this file (plan v3 §3).
Standing guard: it runs at every milestone exit, not only at one milestone, so the
plan's "red first" rule does not apply to it. It is validated by its own sabotage
self-tests below instead (plan v3 §5).

Rule (blocker register Section 20, ADR-14): no vector-store dependency, import, or
migration may exist until MR-1 (memory scope contract and physical layout) is
DECIDED and propagated.

DELETION CONTRACT: when MR-1 is decided, delete this file and the gate §1 entry
("Write any vector code ...") in the same change, together with the other references
listed in s12_s15_golden/README.md "Deletion contract". Neither may outlive the other.

Static checks only: files are read with ast/regex, and no project code is imported,
so import-time side effects cannot hide a violation. Every file in the repository is
scanned except the EXCLUDED_DIRS (virtual environments, caches, .git), so imports in
scripts/, top-level files and nested packages are caught too (audit round 2 C7).

Repository root: the S12_REPO_ROOT environment variable, or four levels above this
file (tests/golden/s12/<this file> -> repository root).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

FORBIDDEN_MODULES = frozenset({"lancedb", "lance", "pgvector"})
FORBIDDEN_PACKAGES = ("lancedb", "pylance", "pgvector")

EXCLUDED_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "site-packages", ".mypy_cache", ".pytest_cache", ".ruff_cache",
})
MIGRATION_DIRS = ("migrations", "alembic", "src/migrations", "src/db/migrations")
MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock",
    "poetry.lock", "uv.lock", "environment.yml", "environment.yaml",
})
MANIFEST_PREFIXES = ("requirements", "constraints")  # requirements*.txt, constraints*.txt, requirements/*.txt

_PACKAGE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(" + "|".join(FORBIDDEN_PACKAGES) + r")(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_CREATE_EXTENSION_RE = re.compile(
    r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?vector\b", re.IGNORECASE
)
_VECTOR_COLUMN_RE = re.compile(r"\bvector\s*\(\s*\d+\s*\)", re.IGNORECASE)
_DYNAMIC_IMPORT_FUNCS = frozenset({"import_module", "__import__", "find_spec"})


def repo_root() -> Path:
    env = os.environ.get("S12_REPO_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[3]


SELF_RELPATH = Path("tests/golden/s12") / Path(__file__).name


def _is_self(path: Path, base: Path) -> bool:
    """This guard file: its sabotage data contains the very strings it forbids."""
    try:
        if path.resolve() == Path(__file__).resolve():
            return True
    except OSError:
        pass
    return path.relative_to(base) == SELF_RELPATH


def _walk(base: Path, suffixes: tuple[str, ...] | None = None):
    """Every file under `base` (optionally filtered by suffix), skipping EXCLUDED_DIRS and this file."""
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        if path.is_file() and (suffixes is None or path.suffix in suffixes) and not (
            EXCLUDED_DIRS & set(path.relative_to(base).parts)
        ) and not _is_self(path, base):
            yield path


def _is_manifest(path: Path) -> bool:
    if path.name in MANIFEST_NAMES:
        return True
    return path.suffix == ".txt" and (
        path.name.startswith(MANIFEST_PREFIXES) or path.parent.name == "requirements"
    )


def _top(module: str | None) -> str:
    return (module or "").split(".")[0]


def _import_violations(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{rel}: cannot be parsed, so it cannot be checked ({exc.__class__.__name__})"]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _top(alias.name) in FORBIDDEN_MODULES:
                    found.append(f"{rel}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _top(node.module) in FORBIDDEN_MODULES:
                found.append(f"{rel}:{node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if (
                name in _DYNAMIC_IMPORT_FUNCS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _top(node.args[0].value) in FORBIDDEN_MODULES
            ):
                found.append(f"{rel}:{node.lineno}: dynamic import of {node.args[0].value!r}")
    return found


def _manifest_violations(root: Path) -> list[str]:
    found = []
    for path in _walk(root):
        if not _is_manifest(path):
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            match = _PACKAGE_RE.search(line)
            if match:
                found.append(
                    f"{path.relative_to(root)}:{lineno}: dependency {match.group(1)!r}"
                )
    return found


def _migration_violations(root: Path) -> list[str]:
    found = []
    migration_files = {p for d in MIGRATION_DIRS for p in _walk(root / d, (".py", ".sql"))}
    for path in _walk(root, (".py", ".sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _CREATE_EXTENSION_RE.search(line):
                found.append(f"{rel}:{lineno}: CREATE EXTENSION vector")
            elif (path.suffix == ".sql" or path in migration_files) and _VECTOR_COLUMN_RE.search(line):
                found.append(f"{rel}:{lineno}: vector(n) column type")
    return found


def scan(root: Path) -> list[str]:
    """Every violation of the no-vector-code rule under `root`, as 'file:line: what'."""
    violations: list[str] = []
    for path in _walk(root, (".py",)):  # every Python file in the repository (audit C7)
        violations.extend(_import_violations(path, root))
    violations.extend(_manifest_violations(root))
    violations.extend(_migration_violations(root))
    return violations


# ── The guard ────────────────────────────────────────────────────────────────

def test_no_vector_code_in_repository() -> None:
    root = repo_root()
    assert (root / "src").is_dir(), (
        f"{root} has no src/ directory: set S12_REPO_ROOT to the repository root"
    )
    violations = scan(root)
    assert not violations, (
        "Vector code is blocked until MR-1 is decided (blocker register Section 20, "
        "ADR-14, gate v10 §14):\n  " + "\n  ".join(violations)
    )


# ── Self-tests: every sabotage must be caught; clean code must pass ─────────

SABOTAGE = {
    "import": ("src/memory/vec.py", "import lancedb\n"),
    "import_submodule": ("src/memory/vec.py", "import lancedb.table as t\n"),
    "from_import": ("src/memory/vec.py", "from pgvector.sqlalchemy import Vector\n"),
    "pylance_import": ("src/memory/vec.py", "import lance\n"),
    "nested_import": ("src/memory/vec.py", "def f():\n    import lancedb\n"),
    "dynamic_import": ("src/memory/vec.py", "import importlib\nimportlib.import_module('lancedb')\n"),
    "dunder_import": ("src/memory/vec.py", "__import__('pgvector')\n"),
    "test_import": ("tests/agent/test_x.py", "import lancedb\n"),
    "requirements": ("requirements.txt", "psycopg==3.2\nlancedb==0.13.0\n"),
    "requirements_dir": ("requirements/prod.txt", "pgvector>=0.3\n"),
    "pyproject": ("pyproject.toml", '[project]\ndependencies = ["pgvector>=0.3"]\n'),
    "pyproject_pylance": ("pyproject.toml", '[project]\ndependencies = ["pylance"]\n'),
    "poetry_lock": ("poetry.lock", '[[package]]\nname = "lancedb"\n'),
    "migration_sql": ("migrations/019_vec.sql", "CREATE EXTENSION IF NOT EXISTS vector;\n"),
    "migration_column": ("migrations/019_vec.sql", "ALTER TABLE m ADD COLUMN e vector(1536);\n"),
    "alembic_py": ("alembic/versions/019_vec.py", 'op.execute("CREATE EXTENSION vector")\n'),
    "alembic_column": ("alembic/versions/019_vec.py", 'op.execute("ALTER TABLE m ADD e VECTOR(768)")\n'),
    "unparseable": ("src/memory/vec.py", "import lancedb as\n"),
    "scripts_dir": ("scripts/seed_vectors.py", "import lancedb\n"),
    "root_file": ("manage.py", "from pgvector.psycopg import register_vector\n"),
    "nested_pyproject": ("packages/memory/pyproject.toml", '[project]\ndependencies = ["lancedb"]\n'),
    "root_sql": ("db/019_vec.sql", "CREATE EXTENSION vector;\n"),
}

CLEAN = {
    "src/memory/vector_math.py": "def vector(n):\n    return [0.0] * n\nv = vector(3)\n",
    "src/memory/notes.py": '"""Mentions lancedb and pgvector in a docstring only."""\nX = "lancedb"\n',
    "src/memory/lancedb_notes.py": "import json\n",
    "src/pkg/__init__.py": "from . import lance\n",
    "src/pkg/lance.py": "NAME = 'local module named lance, relative import'\n",
    "requirements.txt": "psycopg==3.2\nasyncpg==0.30\n",
    "migrations/018_worker_management.sql": "CREATE TABLE operation_quotas (quota_id TEXT);\n",
}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("case", sorted(SABOTAGE))
def test_selftest_sabotage_is_caught(tmp_path: Path, case: str) -> None:
    (tmp_path / "src").mkdir()
    rel, text = SABOTAGE[case]
    _write(tmp_path, rel, text)
    assert scan(tmp_path), f"sabotage {case!r} was not detected"


def test_selftest_clean_repository_passes(tmp_path: Path) -> None:
    for rel, text in CLEAN.items():
        _write(tmp_path, rel, text)
    assert scan(tmp_path) == []


def test_selftest_guard_does_not_flag_itself(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    _write(tmp_path, str(SELF_RELPATH), Path(__file__).read_text(encoding="utf-8"))
    assert scan(tmp_path) == []


def test_selftest_excluded_dirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    _write(tmp_path, ".venv/lib/site-packages/lancedb/__init__.py", "import lancedb\n")
    _write(tmp_path, "src/.venv/x.py", "import lancedb\n")
    assert scan(tmp_path) == []
