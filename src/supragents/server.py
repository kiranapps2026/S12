"""Start the HTTP service: database + DeepSeek + runner + API keys, on one event loop."""
from __future__ import annotations

import logging

import uvicorn

from supragents.adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from supragents.adapters.postgres.database import Database
from supragents.api.app import create_app
from supragents.bootstrap import build_intent_model, build_runner
from supragents.settings import Settings


async def serve(settings: Settings, host: str, port: int) -> None:
    settings.require("database_url", "deepseek_api_key")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    database = await Database.connect(settings.database_url)
    try:
        runner = build_runner(database, build_intent_model(settings))
        app = create_app(runner, PostgresApiKeyAuthenticator(database))
        await uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info")).serve()
    finally:
        await database.close()
