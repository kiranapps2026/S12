"""A real Worker Runtime process for golden M20 (gate §15.2 subprocess kills, suite 17). Owner fixture.

Run as ``python -m tests_golden.fixtures.runtime_process --url ... --schema ... --runtime ... --effects FILE
(--run TENANT EXECUTION | --sweep SECONDS) [--hang POINT]``. It builds the same Worker Runtime the in-process goldens
use (M17's dependencies: guard, verification, consolidation, dead letters), connected as the non-superuser role
``golden_app`` to one golden schema, and either runs one execution or sweeps for orphaned runs until the time is up.

The provider is ``FileProvider``: a ``BaseAdapter`` whose side-effect ledger is an append-only file shared by every
process, so a side effect survives the process that caused it (a real provider's state survives a crashed client), and
"no step executes twice" can be checked across processes. ``--hang POINT`` freezes the whole process (a blocking
sleep: no asyncio deadline can end it, as with a hung process) the first time it reaches ``call`` (before the side effect), ``after_call`` (after it, before returning) or ``observe`` (inside the
first verification observation), after printing ``HANG <point> <key>`` — the moment the test kills it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

HANG_S = 3600.0


def executions(path: Path) -> list[str]:
    """The idempotency keys the provider executed, one per real side effect."""
    if not path.exists():
        return []
    return [json.loads(line)["key"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _provider(effects: Path, hang: str | None):
    from contracts.adapter_interface import BaseAdapter, Observation, ProbeOutcome
    from contracts.step_execution import AdapterResult

    class FileProvider(BaseAdapter):
        def __init__(self):
            self.hung = False

        async def _maybe_hang(self, point, key):
            if hang == point and not self.hung:
                self.hung = True
                print(f"HANG {point} {key}", flush=True)
                time.sleep(HANG_S)          # blocks the whole process: no deadline can end it, only the kill

        def _record(self, key):
            with effects.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "pid": os.getpid()}) + "\n")
                f.flush()
                os.fsync(f.fileno())

        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            key = call_meta.idempotency_key
            await self._maybe_hang("call", key)
            if key not in executions(effects):              # the provider deduplicates a repeated key
                self._record(key)
            await self._maybe_hang("after_call", key)
            return AdapterResult("ok", data={"id": f"res-{key}", "key": key})

        async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
            done = call_meta.idempotency_key in executions(effects)
            return ProbeOutcome.EXECUTED_SUCCESS if done else ProbeOutcome.NOT_EXECUTED

        async def observe(self, kernel_op_id, observation_spec, binding, context):
            key = observation_spec.get("idempotency_key", "")
            await self._maybe_hang("observe", key)
            exists = key in executions(effects)
            return Observation(1, time.time(), 200, {"exists": exists}, exists, None)

    return FileProvider()


class _Schema:
    """What the golden dependency builders need of a GoldenSchema: the code-under-test database."""
    def __init__(self, database):
        self._database = database

    def database(self):
        return self._database


def _apply_sabotage() -> None:
    """Owner verify only: a code sabotage patch of the parent test run applies in this process too (GOLDEN_SABOTAGE)."""
    path = os.environ.get("GOLDEN_SABOTAGE", "")
    if path.endswith(".py"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("golden_sabotage", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.apply()


async def _main(args) -> int:
    import asyncpg
    _apply_sabotage()

    from adapters.postgres.database import Database
    from tests_golden.s12.M17_dead_letter import _dl_deps
    pool = await asyncpg.create_pool(args.url, min_size=1, max_size=4,
                                     server_settings={"search_path": args.schema, "role": "golden_app"})
    try:
        database = Database(pool)
        deps = _dl_deps(_Schema(database), _provider(Path(args.effects), args.hang), lease_ttl_s=args.ttl)
        import dataclasses
        deps = dataclasses.replace(deps, runtime_instance_id=args.runtime)
        print("STARTED", flush=True)
        if args.run:
            from engine.stages.s12_execute.loop import run_execution
            result = await run_execution(deps, args.run[0], args.run[1])
            print(f"RESULT {result.run_status} {result.reason}", flush=True)
            return 0
        from engine.stages.s12_execute.recovery import RecoverySweeper
        sweeper, deadline = RecoverySweeper(database, deps), time.monotonic() + args.sweep
        while time.monotonic() < deadline:
            for _tenant_id, execution_id, result in await sweeper.sweep():
                print(f"SWEPT {execution_id} {result.run_status} {result.reason}", flush=True)
            await asyncio.sleep(0.2)
        return 0
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--effects", required=True)
    parser.add_argument("--ttl", type=float, default=1.0)
    parser.add_argument("--hang", choices=["call", "after_call", "observe"])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", nargs=2, metavar=("TENANT", "EXECUTION"))
    group.add_argument("--sweep", type=float)
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
