"""Configurable doubles for the read-only ports. ``error`` makes a port raise."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.vocabulary import CircuitState, Mutation, RecordStatus
from supragents.ports.activation import ActivationState
from supragents.ports.authorization import ConnectionState
from supragents.ports.intent import IntentCompletion
from supragents.ports.policy import KernelPolicy, PolicyVersions
from supragents.ports.usage import UsageRecord


class FakeActivation:
    def __init__(self, clock, error: bool = False, **times: float | None) -> None:
        self.clock, self.error, self.times, self.calls = clock, error, times, 0
        self.database_now: float | None = None  # set to diverge from the process clock

    async def read(self, tenant_id: str, workspace_id: str) -> ActivationState:
        self.calls += 1
        if self.error:
            raise DependencyUnavailable("activation rows unreadable")
        return ActivationState(
            database_now=self.clock.current if self.database_now is None else self.database_now,
            tenant_paused_until=self.times.get("tenant_paused_until"),
            tenant_activation_at=self.times.get("tenant_activation_at"),
            workspace_paused_until=self.times.get("workspace_paused_until"),
            workspace_activation_at=self.times.get("workspace_activation_at"),
        )


def intent_json(intent: str, confidence: float = 0.95, **parameters: object) -> str:
    return json.dumps({"intent": intent, "confidence": confidence, "parameters": parameters})


class ScriptedIntentModel:
    """Returns the scripted answers in order; records every prompt, intent list and feedback."""

    TOKENS_PER_CALL = 42

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str | None]] = []
        self.offered_intents: list[tuple[str, ...]] = []

    async def complete(self, text: str, intents: tuple[str, ...], feedback: str | None) -> IntentCompletion:
        self.calls.append((text, feedback))
        self.offered_intents.append(intents)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return IntentCompletion(text=answer, model="scripted-model", total_tokens=self.TOKENS_PER_CALL)


class RecordingUsage:
    def __init__(self, fail: bool = False) -> None:
        self.records: list[UsageRecord] = []
        self.fail = fail

    async def record(self, usage: UsageRecord) -> None:
        if self.fail:
            raise DependencyUnavailable("usage store down")
        self.records.append(usage)


@dataclass
class FakeAuthorization:
    user: RecordStatus = RecordStatus.ACTIVE
    tenant: RecordStatus = RecordStatus.ACTIVE
    connection: ConnectionState = ConnectionState(RecordStatus.ACTIVE, None)
    grant: bool = True
    scope: bool = True
    budget: bool = True
    failing: set[str] = field(default_factory=set)
    grant_calls: list[str] = field(default_factory=list)

    def _answer(self, name: str, value):
        if name in self.failing:
            raise DependencyUnavailable(name)
        return value

    async def user_status(self, tenant_id, user_id): return self._answer("user", self.user)
    async def tenant_status(self, tenant_id): return self._answer("tenant", self.tenant)
    async def connection_state(self, tenant_id, connection_id): return self._answer("connection", self.connection)

    async def has_grant(self, tenant_id, user_id, capability_id):
        self.grant_calls.append(capability_id)
        return self._answer("grant", self.grant)

    async def workspace_in_scope(self, tenant_id, user_id, workspace_id, membership_id):
        return self._answer("scope", self.scope)

    async def budget_available(self, tenant_id, amount): return self._answer("budget", self.budget)


class FakePolicy:
    def __init__(self, kill_switch: bool = False, threshold: float = 0.95, error: bool = False) -> None:
        self.policy = KernelPolicy(kill_switch_engaged=kill_switch, risk_deny_threshold=threshold)
        self.error = error

    async def current(self, tenant_id: str) -> KernelPolicy:
        if self.error:
            raise DependencyUnavailable("policy store down")
        return self.policy


class FakeCircuitBreaker:
    def __init__(self, state: CircuitState = CircuitState.CLOSED) -> None:
        self.value = state

    async def state(self, provider: str) -> CircuitState:
        return self.value


class FakeMutationPolicy:
    def __init__(self, permit: bool = True) -> None:
        self.permit = permit
        self.calls: list[tuple[Mutation, float]] = []

    async def permits(self, tenant_id: str, mutation: Mutation, risk: float) -> bool:
        self.calls.append((mutation, risk))
        return self.permit


class FakePolicyVersions:
    def __init__(self, error: bool = False, **overrides: str) -> None:
        self.error = error
        self.versions = PolicyVersions(**{"tenant_policy_version_id": "tpv-5",
                                          "workspace_policy_version_id": "wpv-2",
                                          "policy_version_id": "pv-8", **overrides})

    async def current(self, tenant_id: str, workspace_id: str) -> PolicyVersions:
        if self.error:
            raise DependencyUnavailable("policy versions unreadable")
        return self.versions
