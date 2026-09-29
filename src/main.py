"""
SuprAgents Application — Multi-tenant durable execution kernel for AI workers.

Usage:
    python -m src.main                    # Start the kernel
    python -m src.main --worker            # Start as worker
    python -m src.main --migrate           # Run database migrations
    python -m src.main --check-architecture # Run architecture drift checks
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent))

from contracts.stage_registry import PIPELINE_SEQUENCE, validate_stage_order
from contracts.ownership import validate_ownership
from contracts.state_validators import STATE_VALIDATOR

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def validate_contracts() -> bool:
    """Validate all contracts at startup."""
    logger.info("Validating contracts...")

    try:
        validate_stage_order()
        validate_ownership()
        logger.info("Stage registry: %d stages validated", len(PIPELINE_SEQUENCE))
        logger.info("Ownership registry: validated")
        logger.info("State validators: %d state machines loaded", len(STATE_VALIDATOR.get_all_machines()))
        return True
    except AssertionError as e:
        logger.error("Contract validation failed: %s", e)
        return False


def run_kernel() -> None:
    """Serve the HTTP API over the PostgreSQL adapters."""
    if not validate_contracts():
        logger.error("Contract validation failed — aborting startup")
        sys.exit(1)

    logger.info("SuprAgents kernel starting...")
    logger.info("Pipeline: %s", " → ".join(PIPELINE_SEQUENCE))

    import uvicorn
    from app import create_app

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)


async def run_migrations() -> None:
    """Apply the SQL migrations (adapters/postgres/migrations), once each, in order."""
    from adapters.postgres.database import Database
    from adapters.postgres.migrate import apply_migrations
    from config import get_settings

    database = await Database.connect(get_settings().database_url)
    try:
        applied = await apply_migrations(database)
    finally:
        await database.close()
    logger.info("Migrations applied: %s", applied or "none (up to date)")


async def issue_api_key(values: list[str]) -> None:
    """Create an API key for an existing tenant/workspace/user/membership/connection."""
    from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
    from adapters.postgres.database import Database
    from config import get_settings
    from contracts.principal import Principal

    tenant, workspace, user, membership, connection, scope = values
    database = await Database.connect(get_settings().database_url)
    try:
        key = await PostgresApiKeyAuthenticator(database).issue(
            Principal(tenant, workspace, user, membership, connection, scope))
    finally:
        await database.close()
    print(key)  # shown once; only its SHA-256 is stored


def run_architecture_checks() -> int:
    """Run all architecture drift checks."""
    import subprocess
    import sys

    scripts_dir = Path(__file__).parent.parent / "scripts" / "architecture"
    checks = [
        "check_stage_registry.py",
        "check_ownership.py",
        "check_contract_sync.py",
        "check_dependency_cycles.py",
        "check_test_coverage.py",
    ]

    results: list[tuple[str, int]] = []
    for script in checks:
        script_path = scripts_dir / script
        if not script_path.exists():
            logger.warning("Script not found: %s", script_path)
            continue

        logger.info("Running: %s", script)
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
        )
        results.append((script, result.returncode))
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

    failed = [name for name, code in results if code != 0]
    if failed:
        logger.error("Failed checks: %s", failed)
        return 1

    logger.info("All architecture checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SuprAgents — Multi-tenant durable execution kernel")
    parser.add_argument("--worker", action="store_true", help="Start as worker node")
    parser.add_argument("--migrate", action="store_true", help="Run database migrations")
    parser.add_argument("--issue-api-key", nargs=6, metavar=("TENANT", "WORKSPACE", "USER", "MEMBERSHIP", "CONNECTION", "SCOPE"),
                        help="Create an API key (printed once)")
    parser.add_argument("--check-architecture", action="store_true", help="Run architecture drift checks")
    parser.add_argument("--validate-contracts", action="store_true", help="Validate contracts only")

    args = parser.parse_args()

    setup_logging()

    if args.validate_contracts:
        success = validate_contracts()
        return 0 if success else 1

    if args.issue_api_key:
        asyncio.run(issue_api_key(args.issue_api_key))
        return 0

    if args.migrate:
        asyncio.run(run_migrations())
        return 0

    if args.check_architecture:
        return run_architecture_checks()

    # Default: run kernel
    if args.worker:
        logger.info("Starting as worker node")
        # Worker startup — handled by worker module
        pass
    else:
        run_kernel()

    return 0


if __name__ == "__main__":
    sys.exit(main())
