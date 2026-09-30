"""Run the production app (lifespan, pool, adapters) as a separate process for the real-server tests.

Environment: APP_DATABASE_URL (a NON-superuser role), APP_PORT, FAKE_DEEPSEEK_URL (the local
stand-in for the provider), MODEL_TIMEOUT (seconds). Test use only: the model is the REAL
DeepSeekIntentModel pointed at the local fake endpoint.
"""
from __future__ import annotations

import os

import uvicorn

from adapters.llm.deepseek import DeepSeekIntentModel
from app import create_app

if __name__ == "__main__":
    model = DeepSeekIntentModel(
        "test-key-not-real",
        endpoint=os.environ["FAKE_DEEPSEEK_URL"],
        timeout=float(os.environ.get("MODEL_TIMEOUT", "2")),
    )
    app = create_app(database_url=os.environ["APP_DATABASE_URL"], intent_model=model)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["APP_PORT"]), log_level="warning")
