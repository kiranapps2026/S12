"""Composition root: the one place where real adapters are wired to the pipeline.

``build_runner`` is the "master switch": give it a database and an intent model and it
returns a PipelineRunner connected to every production adapter. ``build_intent_model``
builds the DeepSeek model from settings.
"""
from __future__ import annotations

from supragents.adapters.llm.deepseek import DeepSeekIntentModel
from supragents.adapters.postgres.clock import DatabaseClock
from supragents.adapters.postgres.confirmations import PostgresConfirmationStore
from supragents.adapters.postgres.database import Database
from supragents.adapters.postgres.identity import PostgresActivationReader, PostgresAuthorizationState
from supragents.adapters.postgres.ledger import PostgresEventSink
from supragents.adapters.postgres.policy import (
    PostgresKernelPolicy,
    PostgresMutationPolicy,
    PostgresPolicyVersions,
)
from supragents.adapters.postgres.registry import PostgresCapabilityRegistry
from supragents.adapters.postgres.usage import PostgresUsageRecorder
from supragents.adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from supragents.pipeline.deps import PipelineDeps
from supragents.pipeline.runner import PipelineRunner
from supragents.ports.intent import IntentModel
from supragents.ports.policy import CircuitBreaker
from supragents.settings import Settings


def build_deps(database: Database, intent_model: IntentModel,
               circuit_breaker: CircuitBreaker | None = None) -> PipelineDeps:
    return PipelineDeps(
        activation=PostgresActivationReader(database),
        intent_model=intent_model,
        registry=PostgresCapabilityRegistry(database),
        authorization=PostgresAuthorizationState(database),
        policy=PostgresKernelPolicy(database),
        policy_versions=PostgresPolicyVersions(database),
        circuit_breaker=circuit_breaker or InProcessCircuitBreaker(),
        mutation_policy=PostgresMutationPolicy(database),
        confirmations=PostgresConfirmationStore(database),
        clock=DatabaseClock(database),
        usage=PostgresUsageRecorder(database),
    )


def build_intent_model(settings: Settings) -> IntentModel:
    return DeepSeekIntentModel(settings.require("deepseek_api_key").deepseek_api_key)


def build_runner(database: Database, intent_model: IntentModel,
                 circuit_breaker: CircuitBreaker | None = None) -> PipelineRunner:
    return PipelineRunner(build_deps(database, intent_model, circuit_breaker),
                          PostgresEventSink(database))
