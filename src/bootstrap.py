"""Composition root: the one place where production adapters are wired to the pipeline."""
from __future__ import annotations

from adapters.postgres.activation import PostgresActivationReader
from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.confirmations import PostgresConfirmationStore
from adapters.postgres.database import Database
from adapters.postgres.admin import AdminService
from adapters.postgres.event_log import PostgresEventLog
from adapters.postgres.events import PostgresEventSink
from adapters.postgres.references import PostgresReferenceSource
from adapters.postgres.registry import PostgresCapabilityRegistry
from adapters.postgres.scope import PostgresRunScopes
from adapters.postgres.suspended_runs import PostgresSuspendedRunStore
from adapters.postgres.webhook_credentials import Kek, PostgresWebhookCredentials
from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from engine.control_plane.pipeline_state_runner import (
    PipelineDependencies, PipelineRunner, build_pipeline,
)
from adapters.llm.deepseek import DeepSeekIntentModel
from config import Settings
from adapters.postgres.event_schemas import PostgresEventSchemas
from adapters.postgres.schedules import PostgresScheduleStore
from engine.gateway.run import run_received_event
from engine.gateway.scheduler import EventScheduler
from engine.gateway.webhook import EventGateway
from contracts.intent_model import IntentModel


def build_authenticator(database: Database) -> PostgresApiKeyAuthenticator:
    return PostgresApiKeyAuthenticator(database)


def build_webhook_gateway(database: Database, settings: Settings) -> EventGateway:
    """The event gateway for every source. Signed sources (webhook, mcp) need WEBHOOK_KEK; without it
    they answer 503, while API events and schedules still work. Event types must be registered."""
    credentials = None
    if settings.webhook_kek:
        credentials = PostgresWebhookCredentials(
            database, Kek.from_base64(settings.webhook_kek, settings.webhook_kek_version))
    return EventGateway(credentials, PostgresEventLog(database), PostgresEventSchemas(database))


def build_admin(database: Database, settings: Settings) -> AdminService:
    """The administration service. Endpoint (webhook/MCP) operations need WEBHOOK_KEK and answer 503 without it."""
    credentials = None
    if settings.webhook_kek:
        credentials = PostgresWebhookCredentials(
            database, Kek.from_base64(settings.webhook_kek, settings.webhook_kek_version))
    return AdminService(database, credentials)


def build_scheduler(database: Database, gateway: EventGateway, pipeline, meter=None) -> EventScheduler:
    """Scheduled events run through the same pipeline; with a `meter` their model calls are billed to their tenant."""
    async def run(received):
        if meter is None:
            return await run_received_event(pipeline, gateway, received)
        with meter.scope(received.principal.tenant_id, received.principal.user_id, received.envelope.event_id):
            return await run_received_event(pipeline, gateway, received)
    return EventScheduler(PostgresScheduleStore(database), gateway, run)


def build_intent_model(settings: Settings) -> IntentModel:
    """The DeepSeek model. The key comes from DEEPSEEK_API_KEY; nothing else is configurable."""
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set (put it in .env)")
    return DeepSeekIntentModel(settings.deepseek_api_key)


def build_runner(database: Database, intent_model: IntentModel) -> PipelineRunner:
    """The S0–S11 runner over the real adapters. `intent_model` is required: S2 has no default."""
    return build_pipeline(PipelineDependencies(
        intent_model=intent_model,
        registry=PostgresCapabilityRegistry(database),
        scopes=PostgresRunScopes(database, InProcessCircuitBreaker()),
        confirmation_store=PostgresConfirmationStore(database),
        suspended=PostgresSuspendedRunStore(database),
        activation=PostgresActivationReader(database),
        events=PostgresEventSink(database),
        references=PostgresReferenceSource(database),
    ))
