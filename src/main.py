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


async def run_kernel() -> None:
    """Run the main execution kernel."""
    if not validate_contracts():
        logger.error("Contract validation failed — aborting startup")
        sys.exit(1)

    logger.info("SuprAgents kernel starting...")
    logger.info("Pipeline: %s", " → ".join(PIPELINE_SEQUENCE))

    # Import here to avoid circular imports and allow contract validation first
    from db.session import DatabaseSession
    from engine.control_plane.pipeline import PipelineEngine
    from engine.observability.ledger import EventLedger

    db = DatabaseSession()
    ledger = EventLedger(db)
    pipeline = PipelineEngine(db, ledger)

    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(signum: int, _frame: Any) -> None:
        logger.info("Received signal %d, shutting down...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        await pipeline.start()
        logger.info("Pipeline engine started — waiting for requests")
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down pipeline engine...")
        await pipeline.stop()
        await db.close()
        logger.info("Shutdown complete")


async def run_migrations() -> None:
    """Run database migrations."""
    logger.info("Running database migrations...")

    from db.session import DatabaseSession
    from db.migrations.runner import MigrationRunner

    db = DatabaseSession()
    runner = MigrationRunner(db)
    await runner.run_migrations()
    await db.close()

    logger.info("Migrations complete")


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
    parser.add_argument("--check-architecture", action="store_true", help="Run architecture drift checks")
    parser.add_argument("--validate-contracts", action="store_true", help="Validate contracts only")

    args = parser.parse_args()

    setup_logging()

    if args.validate_contracts:
        success = validate_contracts()
        return 0 if success else 1

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
        asyncio.run(run_kernel())

    return 0


if __name__ == "__main__":
    sys.exit(main())
