"""
FastAPI application — HTTP API for SuprAgents.

Source: FINAL_ARCHITECTURE.md §36, COMPONENTS_BLUEPRINT.md

Two ways to build it:
- create_app(pipeline=..., authenticator=...): dependencies injected (tests, embedding).
- create_app(database_url=...): production. The lifespan opens the PostgreSQL pool in the
  app's own event loop, refuses to start if the database is unreachable or unmigrated,
  builds the API-key authenticator and the S0–S11 runner over the real adapters, and closes
  the pool on shutdown. Without a DeepSeek key (or injected model) the authenticator is
  wired but the pipeline is not: /execute answers 503 instead of running half-built.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from contracts.intent_model import IntentModel

logger = logging.getLogger(__name__)

_REQUIRED_TABLE = "public.api_keys"  # created by migration 002; proves --migrate was run


class StartupError(RuntimeError):
    """The application cannot start safely."""


def _production_lifespan(database_url: str, intent_model: IntentModel | None):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from adapters.postgres.database import Database
        from bootstrap import build_authenticator, build_intent_model, build_runner
        from contracts.errors import DependencyUnavailable
        from contracts.stage_registry import validate_stage_order

        validate_stage_order()
        logger.info("Starting SuprAgents API...")
        try:
            database = await Database.connect(database_url)
        except Exception as exc:  # noqa: BLE001 — never log the URL (it holds the password)
            raise StartupError(f"cannot connect to the database: {type(exc).__name__}") from None
        try:
            async with database.transaction() as connection:
                bypass = await connection.fetchval(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
                if bypass is not False:
                    raise StartupError(
                        "refusing to start: the database role is a superuser or has BYPASSRLS, "
                        "which disables row-level tenant isolation. Use a plain application role.")
                if await connection.fetchval("SELECT to_regclass($1)", _REQUIRED_TABLE) is None:
                    raise StartupError("database is not migrated: run `python main.py --migrate`")

            settings = get_settings()
            model = intent_model
            if model is None and settings.deepseek_api_key:
                model = build_intent_model(settings)

            app.state.database = database
            app.state.authenticator = build_authenticator(database)
            app.state.pipeline = build_runner(database, model) if model is not None else None
            if app.state.pipeline is None:
                logger.warning("No intent model configured (DEEPSEEK_API_KEY): /execute answers 503")
            logger.info("SuprAgents API started")
            yield
        except DependencyUnavailable as exc:
            raise StartupError(str(exc)) from None
        finally:
            logger.info("Shutting down SuprAgents API...")
            app.state.pipeline = None
            app.state.authenticator = None
            app.state.database = None
            await database.close()
            logger.info("Shutdown complete")
    return lifespan


@asynccontextmanager
async def _static_lifespan(app: FastAPI):
    from contracts.stage_registry import validate_stage_order
    validate_stage_order()
    yield


def create_app(pipeline=None, authenticator=None, *, database_url: str | None = None,
               intent_model: IntentModel | None = None,
               cors_origins: tuple[str, ...] = ()) -> FastAPI:
    """Create the FastAPI application (see the module docstring)."""
    if database_url and (pipeline is not None or authenticator is not None):
        raise ValueError("pass either database_url or injected pipeline/authenticator, not both")

    app = FastAPI(
        title="SuprAgents API",
        description="Multi-tenant durable execution kernel for AI workers",
        version="0.1.0",
        lifespan=_production_lifespan(database_url, intent_model) if database_url else _static_lifespan,
    )
    app.state.pipeline = pipeline
    app.state.authenticator = authenticator
    app.state.database = None

    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_credentials=False,          # credentials are a bearer header, not cookies
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    @app.get("/health")
    async def health_check():
        """Liveness: the process is up."""
        return {"status": "healthy", "app": get_settings().app_name}

    @app.get("/ready")
    async def ready(request: Request):
        """Readiness: authentication and the pipeline are wired and the database answers."""
        state = request.app.state
        problems = []
        if state.authenticator is None:
            problems.append("authenticator_unavailable")
        if state.pipeline is None:
            problems.append("pipeline_unavailable")
        if state.database is not None:
            try:
                async with state.database.transaction() as connection:
                    await connection.fetchval("SELECT 1")
            except Exception:  # noqa: BLE001
                problems.append("database_unavailable")
        if problems:
            return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
        return {"status": "ready"}

    from engine.control_plane.api import router as control_plane_router
    app.include_router(control_plane_router, prefix="/api/v1", tags=["control-plane"])

    return app


def create_production_app() -> FastAPI:
    """The app for `python main.py`: real database, origins from CORS_ORIGINS."""
    settings = get_settings()
    origins = tuple(o.strip() for o in settings.cors_origins.split(",") if o.strip())
    return create_app(database_url=settings.database_url, cors_origins=origins)
