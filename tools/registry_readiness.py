"""Registry readiness (Phase D1d): lists every production-enabled write/delete operation that S12 would refuse to run
because it has no observation method. Exit 0 when the list is empty, 1 otherwise.

    DATABASE_URL=postgresql://... python tools/registry_readiness.py

Rules for filling the registry (owner may overrule):
  * every W, D and IRREVERSIBLE kernel operation needs `observation_method`: the name of the read that shows its effect;
  * operations that create or address one resource also need `observation_identifier_field`, the field of the adapter's
    result that names it (usually `id`);
  * a delete sets `observation_expects_absent = true` and is verified by the resource being gone;
  * an operation with no read that could show its effect stays without a method and therefore cannot run: do not invent one.
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

QUERY = ("SELECT kernel_op_id, mutation FROM kernel_ops WHERE truth_state = 'PRODUCTION_ENABLED' AND mutation <> 'R'"
         " AND (observation_method IS NULL OR observation_method = '') ORDER BY kernel_op_id")
INCOMPLETE = ("SELECT kernel_op_id FROM kernel_ops WHERE truth_state = 'PRODUCTION_ENABLED' AND mutation <> 'R'"
              " AND observation_method <> '' AND observation_method IS NOT NULL"
              " AND (observation_identifier_field IS NULL OR observation_identifier_field = '') ORDER BY kernel_op_id")


async def main(url: str) -> int:
    connection = await asyncpg.connect(url)
    try:
        blocked = await connection.fetch(QUERY)
        no_identifier = await connection.fetch(INCOMPLETE)
    finally:
        await connection.close()
    for row in blocked:
        print(f"BLOCKED  {row['kernel_op_id']} ({row['mutation']}): no observation_method")
    for row in no_identifier:
        print(f"WARNING  {row['kernel_op_id']}: observation_identifier_field is empty (fine only if it addresses no resource)")
    print(f"{len(blocked)} operation(s) blocked at S12 entry")
    return 1 if blocked else 0


if __name__ == "__main__":
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("set DATABASE_URL")
    sys.exit(asyncio.run(main(database_url)))
