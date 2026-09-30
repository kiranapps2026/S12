"""Validate and load the registry catalog (capabilities, operations, bindings, versions).

    python tools/load_catalog.py docs/catalog/catalog.yaml            # dry run: validate and show what would change
    python tools/load_catalog.py docs/catalog/catalog.yaml --apply    # write it in one transaction

Uses ADMIN_DATABASE_URL (environment or .env) and the database in DATABASE_URL, or --db. Nothing is ever deleted: rows in
the database but not in the file are reported and kept (retire an operation with `truth_state: DEPRECATED`). If anything
changed, `versions` must change too. Afterwards run `python tools/registry_readiness.py`.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapters.postgres import catalog  # noqa: E402
from adapters.postgres.database import Database, normalize_url  # noqa: E402
from setup_database import env_value, with_database  # noqa: E402


async def main(args) -> int:
    with open(args.file, encoding="utf-8-sig") as handle:
        doc = yaml.safe_load(handle)
    errors = catalog.validate(doc)
    if errors:
        print(f"{len(errors)} problem(s) in {args.file}:")
        for error in errors:
            print(f"  - {error}")
        return 1
    admin = env_value("ADMIN_DATABASE_URL")
    if not admin:
        sys.exit("ADMIN_DATABASE_URL is not set (environment or .env)")
    db_name = args.db or urlparse(normalize_url(env_value("DATABASE_URL") or "")).path.lstrip("/") or "suprpg"
    database = await Database.connect(with_database(admin, db_name))
    try:
        if args.apply:
            try:
                result = await catalog.apply(database, doc)
            except ValueError as error:
                print(f"NOT APPLIED: {error}")
                return 1
        else:
            result = await catalog.plan(database, doc)
    finally:
        await database.close()
    for table in ("kernel_ops", "capabilities", "bindings"):
        print(f"{table}: {len(result.add[table])} new, {len(result.change[table])} changed"
              + (f", {len(result.missing_from_file[table])} in the database but not in the file (kept)" if result.missing_from_file[table] else ""))
    print(f"versions {'CHANGED' if result.versions_change else 'unchanged'}")
    if result.content_changes and not result.versions_change and not args.apply:
        print("WARNING: content changes but versions do not: --apply will refuse until `versions` is bumped")
    print("applied." if args.apply else "dry run: nothing was written (add --apply).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=None)
    sys.exit(asyncio.run(main(parser.parse_args())))
