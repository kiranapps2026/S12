"""Composition root: the one place where production adapters are wired to the pipeline."""
from __future__ import annotations

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.confirmations import PostgresConfirmationStore
from adapters.postgres.database import Database
from adapters.postgres.registry import PostgresCapabilityRegistry
from adapters.postgres.scope import PostgresRunScopes
from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from engine.control_plane.pipeline_state_runner import (
    PipelineDependencies, PipelineRunner, build_pipeline,
)
from engine.stages.s2_intent_analysis.handler import LLMProvider


def build_authenticator(database: Database) -> PostgresApiKeyAuthenticator:
    return PostgresApiKeyAuthenticator(database)


def build_runner(database: Database, llm: LLMProvider) -> PipelineRunner:
    """The S0–S11 runner over the real adapters. `llm` is required: S2 has no default."""
    return build_pipeline(PipelineDependencies(
        llm=llm,
        registry=PostgresCapabilityRegistry(database),
        scopes=PostgresRunScopes(database, InProcessCircuitBreaker()),
        confirmation_store=PostgresConfirmationStore(database),
    ))
