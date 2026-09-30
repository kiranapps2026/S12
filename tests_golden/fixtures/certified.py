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


@lru_cache(maxsize=4)
def _certified(chain: bool):
    from engine.control_plane.pipeline_state_runner import build_pipeline
    from tests.fixtures.multi import ChainModel, chain_deps
    from tests.fixtures.pipeline import make_entry, make_pipeline_deps
    from tests.fixtures.scenarios import make_scenario
    deps = chain_deps(ChainModel(CHAIN)) if chain else make_pipeline_deps(make_scenario())
    result = asyncio.run(build_pipeline(deps).run(make_entry(ENTRY)))
    assert result.status.value == "NORMAL" and result.final_stage == "S11", result.reason
    return result.final_state


def certified_state(*, tenant_id: str | None = None, chain: bool = False, **context):
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
