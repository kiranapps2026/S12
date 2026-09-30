"""Create a tenant with its first workspace, owner and API key (Phase B: onboarding).

    python tools/create_tenant.py --slug acme --name "Acme Inc" --owner "Ada Owner" [--budget 10000] [--max-mutation W]

Uses ADMIN_DATABASE_URL (a database owner/superuser URL, environment or .env) and the database given by --db (default: the
one in DATABASE_URL). The owner's API key is printed ONCE; store it now. Nothing else in the repo can create the first owner,
because the administration API needs an existing owner.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapters.postgres.database import Database, normalize_url  # noqa: E402
from adapters.postgres.tenant_setup import TenantSetupError, create_tenant  # noqa: E402
from setup_database import env_value, with_database  # noqa: E402


async def main(args) -> int:
    admin = env_value("ADMIN_DATABASE_URL")
    if not admin:
        sys.exit("ADMIN_DATABASE_URL is not set (environment or .env)")
    db_name = args.db or urlparse(normalize_url(env_value("DATABASE_URL") or "")).path.lstrip("/") or "suprpg"
    database = await Database.connect(with_database(admin, db_name))
    try:
        result = await create_tenant(database, slug=args.slug, name=args.name, owner_name=args.owner,
                                     budget_pool=args.budget, max_mutation=args.max_mutation)
    except TenantSetupError as error:
        sys.exit(f"not created: {error}")
    finally:
        await database.close()
    print(f"tenant {result['tenant_id']} created in database {db_name}")
    for field in ("workspace_id", "user_id", "membership_id", "connection_id"):
        print(f"{field}: {result[field]}")
    print(f"\nowner API key (shown once, store it now):\n{result['api_key']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--owner", required=True, help="display name of the first owner")
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--max-mutation", default="W", choices=["R", "W", "D", "IRREVERSIBLE"])
    parser.add_argument("--db", default=None)
    sys.exit(asyncio.run(main(parser.parse_args())))
