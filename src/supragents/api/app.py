"""FastAPI routes. Identity comes only from the API key; the body carries text and choices."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from supragents.api.envelope import Envelope, failure, from_result
from supragents.contracts.entry import EntryRequest
from supragents.contracts.errors import UnknownConfirmation
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.vocabulary import ActivationMode, ActorType
from supragents.pipeline.runner import PipelineRunner
from supragents.ports.authentication import Authenticator, Principal

logger = logging.getLogger("supragents.api")


class RunRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    conversation_id: str = Field(min_length=1, max_length=200)


class ReplyRequest(BaseModel):
    approved: bool


def create_app(runner: PipelineRunner, authenticator: Authenticator) -> FastAPI:
    app = FastAPI(title="SuprAgents S0–S11", version="0.1.0")

    async def principal_for(authorization: str | None) -> Principal | None:
        scheme, _, credential = (authorization or "").partition(" ")
        return await authenticator.authenticate(credential) if scheme == "Bearer" else None

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs")
    async def start_run(body: RunRequest, authorization: str | None = Header(default=None)):
        principal = await principal_for(authorization)
        if principal is None:
            return _respond(failure("unauthorized", "Missing or invalid API key."), 401)
        return _respond(from_result(await runner.run(_entry(principal, body))))

    @app.post("/v1/confirmations/{confirmation_id}")
    async def reply(confirmation_id: str, body: ReplyRequest,
                    authorization: str | None = Header(default=None)):
        principal = await principal_for(authorization)
        if principal is None:
            return _respond(failure("unauthorized", "Missing or invalid API key."), 401)
        answer = ConfirmationReply(confirmation_id, principal.user_id, body.approved)
        try:
            return _respond(from_result(await runner.resume(principal.tenant_id, answer)))
        except UnknownConfirmation:
            return _respond(failure("confirmation_not_found", "No request is waiting on that confirmation."), 404)

    @app.exception_handler(Exception)
    async def unavailable(request, error: Exception) -> JSONResponse:
        logger.exception("request failed: %s", type(error).__name__)
        return _respond(failure("service_unavailable", "The service is temporarily unavailable."), 503)

    return app


def _entry(principal: Principal, body: RunRequest) -> EntryRequest:
    return EntryRequest(
        text=body.text, activation_mode=ActivationMode.API, tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id, user_id=principal.user_id,
        membership_id=principal.membership_id, actor_type=ActorType.USER,
        connection_id=principal.connection_id, conversation_id=body.conversation_id,
        resource_scope=principal.resource_scope,
    )


def _respond(envelope: Envelope, status_code: int = 200) -> JSONResponse:
    return JSONResponse(envelope.as_json(), status_code=status_code)
