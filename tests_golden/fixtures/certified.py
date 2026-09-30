"""A PipelineState that S11 certified, produced by running the real S0–S11 pipeline (owner fixture).

``certified_state(tenant_id=..., chain=False)`` runs the S0–S11 pipeline with the certified test fixtures
(tests/fixtures: scenario registry, fake model) and returns the final state. ``tenant_id`` replaces the tenant on the
execution context (the plan digest does not cover the tenant). ``entry_readers()`` returns S12 entry readers that
accept that state: every binding at the manifest's version, observation metadata for every operation, no pause.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
from functools import lru_cache

from contracts.activation import ActivationState
from contracts.verifier import KernelOpMetadata

ENTRY = {"message": "x", "conversation_id": "conv-1", "connection_id": "conn-1"}
CHAIN = [("contact.create", {"name": "Ana"}), ("email.send", {"to": "a@x.com"})]


@lru_cache(maxsize=8)
def _certified(chain):
    """``chain``: False (the one-step scenario), True (``CHAIN``) or a JSON list of [intent, params] pairs (added
    with B3: a linear chain of any of the ``tests.fixtures.multi.DEFAULT_CAPS`` intents)."""
    import json
    from engine.control_plane.pipeline_state_runner import build_pipeline
    from tests.fixtures.multi import ChainModel, chain_deps
    from tests.fixtures.pipeline import make_entry, make_pipeline_deps
    from tests.fixtures.scenarios import make_scenario
    if chain is False:
        deps = make_pipeline_deps(make_scenario())
    else:
        steps = CHAIN if chain is True else [tuple(pair) for pair in json.loads(chain)]
        deps = chain_deps(ChainModel(steps))
    result = asyncio.run(build_pipeline(deps).run(make_entry(ENTRY)))
    assert result.status.value == "NORMAL" and result.final_stage == "S11", result.reason
    return result.final_state


def certified_state(*, tenant_id: str | None = None, chain=False, **context):
    """``chain``: False, True, or a sequence of (intent, params) pairs for a linear chain."""
    if chain is not False and chain is not True:
        import json
        chain = json.dumps([[intent, params] for intent, params in chain], sort_keys=True)
    state = _certified(chain)
    changes = dict(context)
    if tenant_id is not None:
        changes["tenant_id"] = tenant_id
    if changes:
        state = dataclasses.replace(state, execution_context=dataclasses.replace(state.execution_context, **changes))
    return state


class ManifestBindings:
    """BindingVersionReader: every binding is at ``version`` (default: the certified manifest's)."""
    def __init__(self, version: str | None = None) -> None:
        self.version, self.calls = version, []

    async def binding_version(self, binding_id):
        self.calls.append(binding_id)
        return self.version if self.version is not None else _certified(False).execution_manifest.binding_version


class AllMetadata:
    """KernelOpMetadataReader: a W operation observed by ``get_resource`` for every requested operation."""
    async def read(self, kernel_op_ids, *, capability_version, binding_version):
        return {op: KernelOpMetadata(op, "W", "get_resource", False, "id") for op in kernel_op_ids}


class NoPause:
    async def read(self, tenant_id, workspace_id):
        return ActivationState(time.time(), None, None, None, None)


def entry_readers() -> dict:
    return {"bindings": ManifestBindings(), "activation": NoPause(), "metadata": AllMetadata()}


def fresh(state, suffix: str):
    """The same certified plan as a new request: own request_id, trace_id and execution_id (the digest covers only the
    plan, so the state stays certified)."""
    execution_id = f"golden-exec-{suffix}"
    ctx = dataclasses.replace(state.execution_context, request_id=f"golden-req-{suffix}", trace_id=f"golden-tr-{suffix}")
    plan = dataclasses.replace(state.plan, execution_id=execution_id)
    manifest = dataclasses.replace(state.execution_manifest, execution_id=execution_id, trace_id=ctx.trace_id)
    return dataclasses.replace(state, execution_context=ctx, plan=plan, execution_manifest=manifest)


async def seed_identity(schema, state, *, budget_pool: int = 1000) -> None:
    """Tenant, workspace and user rows the run's foreign keys need (as the connecting role, tenant set for RLS)."""
    ctx = state.execution_context
    await schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id)"
        " VALUES ($1, 'golden', 'active', $2, false, 'IRREVERSIBLE', 'p1') ON CONFLICT DO NOTHING",
        ctx.tenant_id, budget_pool, tenant=ctx.tenant_id)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'w')"
                         " ON CONFLICT DO NOTHING", ctx.workspace_id, ctx.tenant_id, tenant=ctx.tenant_id)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ($1, $2, 'active')"
                         " ON CONFLICT DO NOTHING", ctx.user_id, ctx.tenant_id, tenant=ctx.tenant_id)
