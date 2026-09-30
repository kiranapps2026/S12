"""Propose observation-method SQL for the registry (Phase D1d). READ-ONLY: it prints SQL for the owner to review and
run; it never writes to the database.

    DATABASE_URL=postgresql://... python tools/propose_observation.py > observation_proposal.sql

For every production-enabled W/D/IRREVERSIBLE operation without an observation method it proposes, from the operation id
`<domain>.<noun>_<verb>`:
  * create / add / update / edit / set / tag / assign / move  ->  observe with `get_<noun>` (identifier field `id`);
  * delete / remove                                           ->  the same read, `observation_expects_absent = true`;
  * an inverse (`inverse`) is proposed only for create -> delete when the delete operation exists and none is set;
  * anything else (send, charge, publish, ...) is NOT proposed: an effect that has no read-back cannot be verified, so the
    owner names the read (or leaves the operation blocked). Those appear as `-- NEEDS OWNER`.
The proposal is a starting point: `get_<noun>` must be a read the provider adapter really implements (S12 M10).
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from adapters.postgres.database import normalize_url  # noqa: E402

PRESENT = {"create", "add", "update", "edit", "set", "tag", "assign", "move", "rename", "archive", "restore"}
ABSENT = {"delete", "remove"}


def split_op(kernel_op_id: str) -> tuple[str, str] | None:
    """`crm.contact_create` -> (`contact`, `create`); None if it does not follow `<domain>.<noun>_<verb>`."""
    _, _, rest = kernel_op_id.partition(".")
    noun, sep, verb = rest.rpartition("_")
    return (noun, verb) if sep and noun and verb else None


def propose(ops: list[dict], all_ids: set[str]) -> list[str]:
    lines: list[str] = []
    for op in ops:
        op_id, parts = op["kernel_op_id"], split_op(op["kernel_op_id"])
        if parts is None or parts[1] not in PRESENT | ABSENT:
            lines.append(f"-- NEEDS OWNER: {op_id} ({op['mutation']}): name a read that shows its effect, or leave it blocked")
            continue
        noun, verb = parts
        method = f"get_{noun}"
        absent = ", observation_expects_absent = true" if verb in ABSENT else ""
        lines.append(f"UPDATE kernel_ops SET observation_method = '{method}', observation_identifier_field = 'id'{absent}"
                     f" WHERE kernel_op_id = '{op_id}';")
        domain = op_id.partition(".")[0]
        inverse = f"{domain}.{noun}_delete"
        if verb == "create" and inverse in all_ids and not op["inverse"]:
            lines.append(f"UPDATE kernel_ops SET inverse = '{inverse}' WHERE kernel_op_id = '{op_id}';")
    return lines


def database_url() -> str | None:
    """DATABASE_URL from the environment, else from the repo's .env (never printed)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8-sig"):
            key, _, value = line.strip().removeprefix("export ").partition("=")
            if key.strip() == "DATABASE_URL" and value.strip():
                return value.strip().strip("\"'")
    return None


async def main(url: str) -> int:
    connection = await asyncpg.connect(normalize_url(url))
    try:
        rows = await connection.fetch(
            "SELECT kernel_op_id, mutation, inverse FROM kernel_ops WHERE truth_state = 'PRODUCTION_ENABLED'"
            " AND mutation <> 'R' AND (observation_method IS NULL OR observation_method = '') ORDER BY kernel_op_id")
        all_ids = await connection.fetch("SELECT kernel_op_id FROM kernel_ops WHERE truth_state = 'PRODUCTION_ENABLED'")
    finally:
        await connection.close()
    ops = [dict(r) for r in rows]
    print("-- Proposed by tools/propose_observation.py: REVIEW, then run in a transaction. Nothing has been applied.")
    print(f"-- {len(ops)} operation(s) without an observation method")
    print("BEGIN;")
    for line in propose(ops, {r["kernel_op_id"] for r in all_ids}):
        print(line)
    print("COMMIT;")
    print("-- then: python tools/registry_readiness.py")
    return 0


if __name__ == "__main__":
    url = database_url()
    if not url:
        sys.exit("DATABASE_URL is not set in the environment or in .env")
    sys.exit(asyncio.run(main(url)))
