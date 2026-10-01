"""
Pipeline journey helpers — the REAL runner, real handlers, fixture dependencies.

Source: R-H (runbook): journeys use real handlers, not hand-built state.

  make_pipeline_deps(scenario, *, model=None, s8=None) -> PipelineDependencies
  run_pipeline(request, scenario=None, *, stop_after=None, ...) -> PipelineRunResult
  run_through(stage_id, request, deps) -> PipelineState   (must end NORMAL)
"""
from __future__ import annotations

import asyncio

from contracts.kernel_policy import KernelPolicy
from engine.control_plane.scope import RunScope
from contracts.pipeline_state import PipelineState
from engine.control_plane.pipeline_state_runner import (
    PipelineDependencies, PipelineRunResult, build_pipeline,
)
from engine.stages.s0_entry.handler import EntryRequest
from tests.fixtures.deps import make_s8_deps
from tests.fixtures.scenarios import ScenarioRegistry, make_scenario
from tests.fixtures.states import POLICY_VERSIONS, ScenarioIntentModel


class InMemorySuspendedRuns:
    """Fixture SuspendedRunStore. Stores the JSON text, so every save/load goes through the
    real codec exactly as the database adapter does. Tenant-scoped like RLS."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], str] = {}
        self.fail_saves = False

    async def save(self, state, *, tenant_id, execution_id, confirmation_id):
        import json
        from contracts.codec import encode_state
        if self.fail_saves:
            raise RuntimeError("store down")
        self.rows[(tenant_id, confirmation_id)] = json.dumps(encode_state(state))

    async def load(self, *, tenant_id, confirmation_id):
        import json
        from contracts.codec import decode_state
        raw = self.rows.get((tenant_id, confirmation_id))
        return None if raw is None else decode_state(json.loads(raw))


class StaticActivation:
    """Fixture ActivationStateReader: never paused unless a test sets a field."""

    def __init__(self) -> None:
        self.tenant_paused_until = self.tenant_activation_at = None
        self.workspace_paused_until = self.workspace_activation_at = None
        self.now = None
        self.error: Exception | None = None

    async def read(self, tenant_id, workspace_id):
        import time
        from contracts.activation import ActivationState
        if self.error:
            raise self.error
        return ActivationState(
            database_now=self.now if self.now is not None else time.time(),
            tenant_paused_until=self.tenant_paused_until, tenant_activation_at=self.tenant_activation_at,
            workspace_paused_until=self.workspace_paused_until,
            workspace_activation_at=self.workspace_activation_at)


class InMemoryEvents:
    """Fixture EventSink: records every stage event; `fail` makes emit raise."""

    def __init__(self) -> None:
        self.events: list = []
        self.fail = False
        self.fail_on_stage: str | None = None

    async def emit(self, event):
        if self.fail or event.stage == self.fail_on_stage:
            raise RuntimeError("ledger down")
        self.events.append(event)


class StaticReferences:
    """Fixture ReferenceSource: dictionaries per tenant/user/workspace; records every call."""

    def __init__(self) -> None:
        self.results: dict[tuple, list[str]] = {}         # (tenant, user, conversation) -> newest first
        self.files: dict[tuple, object] = {}               # (tenant, workspace, name) -> FileInfo
        self.variables: dict[tuple, str] = {}              # (tenant, workspace, name) -> value
        self.time = 1_772_668_800.0                        # 2026-03-05T00:00:00Z
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def previous_result(self, *, tenant_id, user_id, conversation_id, index):
        self.calls.append(("result", tenant_id, user_id, conversation_id, index))
        if self.error:
            raise self.error
        items = self.results.get((tenant_id, user_id, conversation_id), [])
        return items[index - 1] if 0 < index <= len(items) else None

    async def file(self, *, tenant_id, workspace_id, name):
        self.calls.append(("file", tenant_id, workspace_id, name))
        if self.error:
            raise self.error
        return self.files.get((tenant_id, workspace_id, name))

    async def variable(self, *, tenant_id, workspace_id, name):
        self.calls.append(("variable", tenant_id, workspace_id, name))
        if self.error:
            raise self.error
        return self.variables.get((tenant_id, workspace_id, name))

    async def now(self):
        if self.error:
            raise self.error
        return self.time


class StaticScopes:
    """Fixture RunScopeFactory: the same scope for every tenant."""

    def __init__(self, scenario, s8=None) -> None:
        self._scope = RunScope(
            policy=KernelPolicy(kill_switch_engaged=False,
                                risk_deny_threshold=scenario.risk_deny_threshold),
            s8=s8 or make_s8_deps(kill_switch=False),
            policy_versions=POLICY_VERSIONS,
        )

    async def for_run(self, tenant_id, workspace_id):
        return self._scope


def make_pipeline_deps(scenario, *, model=None, s8=None) -> PipelineDependencies:
    return PipelineDependencies(
        intent_model=model or ScenarioIntentModel(scenario),
        registry=ScenarioRegistry(scenario),
        scopes=StaticScopes(scenario, s8),
        confirmation_store=scenario.confirmation_store,
        suspended=InMemorySuspendedRuns(),
        activation=StaticActivation(),
        events=InMemoryEvents(),
        references=StaticReferences(),
    )


def make_entry(request: dict | None = None) -> EntryRequest:
    request = request or {"message": "test", "entry_channel": "api"}
    return EntryRequest(
        raw_payload=request,
        entry_channel=request.get("entry_channel", "api"),
        tenant_id=request.get("tenant_id", "tenant-1"),
        workspace_id=request.get("workspace_id", "ws-1"),
        user_id=request.get("user_id", "user-1"),
        conversation_id=request.get("conversation_id"),
        connection_id=request.get("connection_id"),
    )


def run_pipeline(request: dict | None = None, scenario=None, *, stop_after: str | None = None,
                 model=None, s8=None, deps: PipelineDependencies | None = None) -> PipelineRunResult:
    """Run the real S0..S11 runner over the request."""
    scenario = scenario or make_scenario()
    deps = deps or make_pipeline_deps(scenario, model=model, s8=s8)
    return asyncio.run(build_pipeline(deps).run(make_entry(request), stop_after=stop_after))


def run_through(stage_id: str, request: dict | None = None, deps=None,
                scenario=None) -> PipelineState:
    """Run real handlers S0..stage_id and return the PipelineState as stage_id leaves it.

    `deps` is an optional S8Dependencies override. The run must end NORMAL; a stage that
    stops it is reported with its stage and reason.
    """
    result = run_pipeline(request, scenario, stop_after=stage_id, s8=deps)
    if result.final_stage != stage_id or result.status.value != "NORMAL":
        raise AssertionError(
            f"run_through({stage_id}): stopped at {result.final_stage}: "
            f"{result.status} / {result.reason}")
    return result.final_state
