"""Shared builders: a request, a full set of fakes, and a runner wired to them."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from supragents.contracts.entry import EntryRequest
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import ActivationMode, ActorType
from supragents.pipeline.deps import PipelineDeps
from supragents.pipeline.runner import PipelineRunner
from supragents.pipeline.stages import STAGES
from tests.fakes.confirmations import InMemoryConfirmationStore
from tests.fakes.ports import (
    FakeActivation,
    FakeAuthorization,
    FakeCircuitBreaker,
    FakeMutationPolicy,
    FakePolicy,
    FakePolicyVersions,
    RecordingUsage,
    ScriptedIntentModel,
    intent_json,
)
from tests.fakes.registry import FakeRegistry, standard_registry
from tests.fakes.runtime import FakeClock, RecordingEvents


def entry(text: str = "list my contacts", **overrides) -> EntryRequest:
    base = EntryRequest(
        text=text, activation_mode=ActivationMode.HUMAN, tenant_id="tenant-a",
        workspace_id="workspace-1", user_id="user-1", membership_id="member-1",
        actor_type=ActorType.USER, connection_id="conn-1", conversation_id="conv-1",
        resource_scope="workspace-1/*",
    )
    return replace(base, **overrides)


@dataclass
class Harness:
    """Every port as a fake, plus the runner. Tweak a fake before calling ``run``."""

    clock: FakeClock = field(default_factory=FakeClock)
    intent_model: ScriptedIntentModel = field(
        default_factory=lambda: ScriptedIntentModel(intent_json("contact.list")))
    registry: FakeRegistry = field(default_factory=standard_registry)
    authorization: FakeAuthorization = field(default_factory=FakeAuthorization)
    policy: FakePolicy = field(default_factory=FakePolicy)
    policy_versions: FakePolicyVersions = field(default_factory=FakePolicyVersions)
    circuit_breaker: FakeCircuitBreaker = field(default_factory=FakeCircuitBreaker)
    mutation_policy: FakeMutationPolicy = field(default_factory=FakeMutationPolicy)
    events: RecordingEvents = field(default_factory=RecordingEvents)
    usage: RecordingUsage = field(default_factory=RecordingUsage)
    activation: FakeActivation | None = None
    confirmations: InMemoryConfirmationStore | None = None

    def __post_init__(self) -> None:
        self.activation = self.activation or FakeActivation(self.clock)
        self.confirmations = self.confirmations or InMemoryConfirmationStore(self.clock)

    @property
    def deps(self) -> PipelineDeps:
        return PipelineDeps(
            activation=self.activation, intent_model=self.intent_model, registry=self.registry,
            authorization=self.authorization, policy=self.policy,
            policy_versions=self.policy_versions,
            circuit_breaker=self.circuit_breaker, mutation_policy=self.mutation_policy,
            confirmations=self.confirmations, clock=self.clock, usage=self.usage,
        )

    def say(self, *answers) -> None:
        self.intent_model = ScriptedIntentModel(*answers)

    def run(self, request: EntryRequest | None = None):
        return asyncio.run(PipelineRunner(self.deps, self.events).run(request or entry()))

    def resume(self, suspended, reply):
        return asyncio.run(PipelineRunner(self.deps, self.events).resume(suspended, reply))

    def state_before(self, stage_id: str, request: EntryRequest | None = None) -> PipelineState:
        """Run the real stages up to (not including) ``stage_id`` — no hand-built state."""
        state = PipelineState(entry_request=request or entry())
        for current, handler in STAGES:
            if current == stage_id:
                return state
            state = asyncio.run(handler(state, self.deps))
            assert state.halt is None, f"{current} halted early: {state.halt}"
        raise ValueError(stage_id)

    def run_stage(self, stage_id: str, state: PipelineState) -> PipelineState:
        handler = dict(STAGES)[stage_id]
        return asyncio.run(handler(state, self.deps))
