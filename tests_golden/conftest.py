"""Golden tests for the S12–S15 milestones (owner-pinned; Fable never edits anything under tests_golden/).

Run one milestone:   TEST_DATABASE_URL=postgresql://.../suprpg_test pytest tests_golden/s12/M01_schema.py
Run all golden:      pytest tests_golden -p no:cacheprovider

These files live outside ``tests/`` on purpose: they are red until their milestone is built, and the S0–S11
certifier (OWN-13) runs ``pytest tests`` and must stay 19/19 throughout S12–S15. Without TEST_DATABASE_URL the run
fails loudly; golden tests are never skipped.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tests_golden.fixtures.db import GoldenSchema, new_schema_name, golden_database_url


def pytest_collect_file(file_path, parent):
    # Golden files are named Mxx_*.py (plan §4), which pytest's default pattern does not collect.
    # A file named on the command line is collected by pytest itself; collecting it here too would run it twice.
    if parent.session.isinitpath(file_path):
        return None
    if file_path.suffix == ".py" and file_path.name[:1] == "M" and file_path.name[1:3].isdigit():
        return pytest.Module.from_parent(parent, path=file_path)
    return None


@pytest.fixture(scope="module")
def db_schema(request):
    """A fresh schema with every migration applied, dropped after the module."""
    url = golden_database_url()
    schema = GoldenSchema(url, new_schema_name(request.module.__name__))
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(schema.create())
        schema.applied_first = loop.run_until_complete(schema.migrate())
        sabotage = os.environ.get("GOLDEN_SABOTAGE")   # owner verify only: a tests_golden/sabotage/*.sql file
        if sabotage and sabotage.endswith(".sql"):
            loop.run_until_complete(schema.execute(Path(sabotage).read_text(encoding="utf-8")))
        schema.loop = loop
        yield schema
    finally:
        loop.run_until_complete(schema.drop())
        loop.close()


@pytest.fixture(scope="session", autouse=True)
def code_sabotage():
    """Owner verify only: GOLDEN_SABOTAGE=<tests_golden/sabotage/*.py> monkeypatches the interface under test
    (its ``apply()`` runs once, before any test); every such patch must turn some case of its milestone FAIL."""
    path = os.environ.get("GOLDEN_SABOTAGE", "")
    if path.endswith(".py"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("golden_sabotage", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.apply()
    yield


@pytest.fixture
def run(db_schema):
    """``run(coro)``: run a coroutine on the module schema's loop."""
    return db_schema.loop.run_until_complete
