"""S4 Graph Classification: one step per item, each depending on the previous one.

``parameters["items"]`` (a list of objects) asks for the same operation once per item;
the other parameters are shared by every step. Without items there is one step.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from supragents.contracts.frozen_json import FrozenJson
from supragents.contracts.outputs import GraphAnalysis
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import GraphType, StageStatus
from supragents.pipeline.deps import PipelineDeps

STAGE = "S4"
ITEMS_KEY = "items"
MAX_CHAIN_STEPS = 5


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    parameters = state.intent_result.parameters
    shared = {key: value for key, value in parameters.items() if key != ITEMS_KEY}
    items = parameters.get(ITEMS_KEY)
    if items is None:
        step_params = (MappingProxyType(shared),)
    elif _valid_items(items):
        step_params = tuple(MappingProxyType({**shared, **item}) for item in items)
    else:
        return state.halted(STAGE, StageStatus.CLARIFY, "invalid_items")
    return state.with_output(STAGE, graph_analysis=GraphAnalysis(
        graph_type=_graph_type(len(step_params)), step_params=step_params,
    ))


def _valid_items(items: FrozenJson) -> bool:
    return isinstance(items, tuple) and bool(items) and all(isinstance(i, Mapping) for i in items)


def _graph_type(step_count: int) -> GraphType:
    if step_count == 1:
        return GraphType.SIMPLE
    if step_count <= MAX_CHAIN_STEPS:
        return GraphType.CHAIN
    return GraphType.COMPLEX
