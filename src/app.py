"""
FastAPI application — HTTP API for SuprAgents.

Source: FINAL_ARCHITECTURE.md §36, COMPONENTS_BLUEPRINT.md
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from db.session import DatabaseSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    # Startup
    logger.info("Starting SuprAgents API...")
    db = DatabaseSession()
    await db.initialize()
    app.state.db = db

    # Validate contracts at startup
    from contracts.stage_registry import validate_stage_order
    validate_stage_order()

    logger.info("SuprAgents API started")

    yield

    # Shutdown
    logger.info("Shutting down SuprAgents API...")
    await db.close()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="SuprAgents API",
        description="Multi-tenant durable execution kernel for AI workers",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "app": settings.app_name}

    # Include routers
    from engine.control_plane.api import router as control_plane_router
    app.include_router(control_plane_router, prefix="/api/v1", tags=["control-plane"])

    return app
