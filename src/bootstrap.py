"""Composition root: the one place where production adapters are wired to the pipeline."""
from __future__ import annotations

from adapters.postgres.activation import PostgresActivationReader
from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.confirmations import PostgresConfirmationStore
from adapters.postgres.database import Database
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
from engine.gateway.webhook import WebhookGateway
from contracts.intent_model import IntentModel


def build_authenticator(database: Database) -> PostgresApiKeyAuthenticator:
    return PostgresApiKeyAuthenticator(database)


def build_webhook_gateway(database: Database, settings: Settings) -> WebhookGateway | None:
    """The webhook gateway, or None when WEBHOOK_KEK is not set (webhooks then answer 503)."""
    if not settings.webhook_kek:
        return None
    kek = Kek.from_base64(settings.webhook_kek, settings.webhook_kek_version)
    return WebhookGateway(PostgresWebhookCredentials(database, kek), PostgresEventLog(database))


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
