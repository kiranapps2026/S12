"""Fixtures for multi-capability plans (M2a): a registry with one capability per intent and a
model that answers with a canned list of steps."""
from __future__ import annotations

import asyncio
import dataclasses
import json
from dataclasses import dataclass

from contracts.capability import BindingRow, CapabilityMetadata, CapabilityRegistry
from contracts.intent_model import IntentCompletion
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario


@dataclass(frozen=True)
class Cap:
    mutation: str = "W"
    risk: float = 0.2
    cost: int = 3
    provider: str = "crm"
    inverse: str | None = None
    alternatives: int = 1          # >1: the registry offers several capabilities for the intent


DEFAULT_CAPS = {
    "contact.create": Cap("W", 0.2, 3, "crm", inverse="op.contact.delete"),
    "email.send": Cap("W", 0.3, 2, "mail"),
    "contact.list": Cap("R", 0.1, 1, "crm"),
    "contact.delete": Cap("D", 0.5, 5, "crm"),
    "invoice.void": Cap("IRREVERSIBLE", 0.6, 4, "billing"),
    "report.run": Cap("R", 0.1, 1, "analytics"),
}


class ChainRegistry(CapabilityRegistry):
    def __init__(self, caps: dict[str, Cap] | None = None) -> None:
        self.caps = dict(DEFAULT_CAPS if caps is None else caps)

    def _cap_id(self, intent: str, n: int = 0) -> str:
        return f"cap.{intent}" + (f".alt{n}" if n else "")

    async def discover(self, intent, tenant_id):
        cap = self.caps.get(intent["intent_type"])
        if cap is None:
            return []
        return [
            CapabilityMetadata(
                capability_id=self._cap_id(intent["intent_type"], n), name=intent["intent_type"],
                description="", namespace="test", input_schema={}, output_schema={},
                risk_floor=cap.risk, risk_rule=0.0, risk_implied=0.0, mutation_type=cap.mutation,
                estimated_cost_units=cap.cost, tags=[intent["intent_type"]])
            for n in range(cap.alternatives)
        ]

    async def known_intents(self, tenant_id):
        return tuple(self.caps)

    async def get_capability(self, capability_id):
        return None

    async def list_bindings(self, capability_id):
        intent = capability_id.removeprefix("cap.").split(".alt")[0]
        cap = self.caps[intent]
        return [BindingRow(
            binding_id=f"bind.{capability_id}", capability_id=capability_id, provider=cap.provider,
            adapter_class="Adapter", capability_version="cap-v7", binding_version="bind-v3",
            policy_version="p", risk_policy_version="risk-v2", authorization_version="auth-v4",
            effective_risk=0.0, kernel_op_id=f"op.{intent}", engine_module="engines.x",
            inverse_kernel_op_id=cap.inverse)]


class ChainModel:
    """Answers `{"steps": [...]}` (or a raw body) whatever the text is."""

    def __init__(self, steps=None, confidence=0.95, raw: str | None = None) -> None:
        self.steps, self.confidence, self.raw = steps, confidence, raw
        self.calls: list[tuple] = []

    async def complete(self, text, intents, feedback):
        self.calls.append((text, intents, feedback))
        body = self.raw if self.raw is not None else json.dumps(
            {"steps": [{"intent": i, "parameters": p} for i, p in self.steps], "confidence": self.confidence})
        return IntentCompletion(text=body, model="m", total_tokens=1)


def chain_deps(model: ChainModel, caps: dict[str, Cap] | None = None, *, s8=None):
    deps = make_pipeline_deps(make_scenario(), s8=s8)
    return dataclasses.replace(deps, registry=ChainRegistry(caps), intent_model=model)


def run_chain(steps, *, confidence=0.95, caps=None, s8=None, raw=None, deps=None):
    """Run S0-S11 for a canned multi-step answer. Returns (result, deps)."""
    model = ChainModel(steps, confidence, raw)
    deps = deps or chain_deps(model, caps, s8=s8)
    runner = build_pipeline(deps)
    return asyncio.run(runner.run(make_entry({"message": "do the things", "connection_id": "c"}))), deps
