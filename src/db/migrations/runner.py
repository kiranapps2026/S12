"""
Database migration runner — Alembic-based migration management.

Source: DATABASE.md, FINAL_ARCHITECTURE.md §37
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.session import DatabaseSession

logger = logging.getLogger(__name__)

# Alembic directory
ALEMBIC_DIR = Path(__file__).parent.parent.parent / "src" / "db" / "migrations"
VERSIONS_DIR = ALEMBIC_DIR / "versions"


class MigrationRunner:
    """
    Manages database migrations using Alembic.

    Handles:
    - Running pending migrations
    - Creating new migration files
    - Verifying migration state
    """

    def __init__(self, db: "DatabaseSession") -> None:
        self.db = db

    async def run_migrations(self) -> None:
        """Run all pending migrations."""
        logger.info("Running database migrations...")

        # Ensure alembic directory exists
        self._ensure_alembic_setup()

        # Set database URL for Alembic
        from config import settings
        os.environ["DATABASE_URL"] = settings.database_url

        # Run Alembic upgrade
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(ALEMBIC_DIR.parent.parent.parent),  # Project root
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("Migration failed: %s", result.stderr)
            raise RuntimeError(f"Migration failed: {result.stderr}")

        logger.info("Migrations applied successfully")
        if result.stdout:
            print(result.stdout)

    async def create_migration(self, message: str) -> str:
        """
        Create a new migration file.

        Args:
            message: Description of the migration

        Returns:
            Path to the created migration file
        """
        logger.info("Creating migration: %s", message)
        self._ensure_alembic_setup()

        result = subprocess.run(
            [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message],
            cwd=str(ALEMBIC_DIR.parent.parent.parent),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("Migration creation failed: %s", result.stderr)
            raise RuntimeError(f"Migration creation failed: {result.stderr}")

        logger.info("Migration created: %s", message)
        return result.stdout.strip()

    async def get_current_revision(self) -> str | None:
        """Get the current database revision."""
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=str(ALEMBIC_DIR.parent.parent.parent),
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip()
        return output if output else None

    def _ensure_alembic_setup(self) -> None:
        """Ensure Alembic configuration exists."""
        if not ALEMBIC_DIR.exists():
            ALEMBIC_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Created migrations directory: %s", ALEMBIC_DIR)

        if not VERSIONS_DIR.exists():
            VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Created versions directory: %s", VERSIONS_DIR)

        # Create alembic.ini if it doesn't exist
        ini_path = ALEMBIC_DIR.parent.parent.parent / "alembic.ini"
        if not ini_path.exists():
            self._create_alembic_ini(ini_path)

        # Create env.py if it doesn't exist
        env_path = ALEMBIC_DIR / "env.py"
        if not env_path.exists():
            self._create_env_py(env_path)

    def _create_alembic_ini(self, path: Path) -> None:
        """Create alembic.ini configuration file."""
        content = """[alembic]
script_location = src/db/migrations
sqlalchemy.url = driver://user:pass@localhost/dbname

[post_write_hooks]
# format using "black" - use the console_scripts runner, against the source code
hooks = black
;black.type = console_scripts
;black.entrypoint = black
;options = -l 100 src/db/migrations/versions

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""
        path.write_text(content)
        logger.info("Created alembic.ini at %s", path)

    def _create_env_py(self, path: Path) -> None:
        """Create env.py for Alembic migrations."""
        content = '''"""
Alembic environment configuration.

Source: DATABASE.md migration strategy
"""
from logging.config import fileConfig
import sys
from pathlib import Path

from alembic import context

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from config import settings
from db.models import Base
from db.session import get_engine

config = context.config

# Set database URL from settings
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''
        path.write_text(content)
        logger.info("Created env.py at %s", path)
