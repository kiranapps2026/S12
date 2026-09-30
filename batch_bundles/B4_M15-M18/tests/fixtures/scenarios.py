"""
Scenario fixtures for S0-S11 pipeline tests.

A Scenario configures all inputs needed to run the real handlers S0..stage_id
through `state_ready_for()`.  It sets up:
  - CapabilityMetadata (mutation, cost, risk components)
  - Mock-LLM input text (intent type, confidence, workflow flag)
  - Binding rows for provider resolution
  - Step count for graph classification

Source: RUNBOOK R-T
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.stages.s10_confirmation.store import ConfirmationStoreImpl

from contracts.capability import BindingRow, CapabilityMetadata, CapabilityRegistry


class RecordingConfirmationStore:
    """Delegates to the production store and records every save call."""

    def __init__(self) -> None:
        self._inner = ConfirmationStoreImpl()
        self.saves: list[tuple] = []

    async def save(self, confirmation, tenant_id, execution_id):
        await self._inner.save(confirmation, tenant_id, execution_id)
        self.saves.append((confirmation, tenant_id, execution_id))

    async def consume(self, confirmation_id, *, tenant_id, user_id, plan_hash, now=None):
        return await self._inner.consume(confirmation_id, tenant_id=tenant_id, user_id=user_id,
                                         plan_hash=plan_hash, now=now)

    async def reject(self, confirmation_id, *, tenant_id, user_id):
        return await self._inner.reject(confirmation_id, tenant_id=tenant_id, user_id=user_id)


@dataclass(frozen=True)
class Scenario:
    """Immutable scenario configuration for pipeline fixture helpers."""

    mutation: str = "R"
    risk: float = 0.1
    risk_floor: float | None = None
    risk_rule: float | None = None
    risk_implied: float | None = None
    cost: int = 1
    steps: int = 1
    graph: str = "simple"
    confidence: float = 0.95
    capabilities: int = 1
    risk_deny_threshold: float = 0.95
    confirmation_store: RecordingConfirmationStore = field(
        default_factory=RecordingConfirmationStore, compare=False, repr=False)

    def effective_risk_floor(self) -> float:
        """When only risk is given, all three risk components equal risk."""
        if self.risk_floor is not None:
            return self.risk_floor
        return self.risk


# ---------------------------------------------------------------------------
# Pre-built named scenarios (R-T)
# ---------------------------------------------------------------------------

def _scenario(mutation, risk, **kw):
    return Scenario(mutation=mutation, risk=risk, **kw)


SCENARIO_READ_LOW_RISK = _scenario("R", 0.1)
SCENARIO_WRITE_CHAIN = _scenario("W", 0.2, steps=3, graph="chain")
SCENARIO_DELETE_HIGH_RISK = _scenario("D", 0.9, cost=6)
SCENARIO_IRREVERSIBLE = _scenario("IRREVERSIBLE", 0.5)
SCENARIO_LOW_CONFIDENCE = _scenario("R", 0.1, confidence=0.4)
SCENARIO_COMPLEX = _scenario("R", 0.1, steps=7)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def make_scenario(
    mutation: str = "R",
    risk: float = 0.1,
    risk_floor: float | None = None,
    risk_rule: float | None = None,
    risk_implied: float | None = None,
    cost: int = 1,
    steps: int = 1,
    graph: str = "simple",
    confidence: float = 0.95,
    capabilities: int = 1,
    risk_deny_threshold: float = 0.95,
) -> Scenario:
    """Build a Scenario that configures the fixture registry, bindings, and mock LLM.

    When only ``risk`` is given, all three risk components (risk_floor,
    risk_rule, risk_implied) default to ``risk``.
    """
    return Scenario(
        mutation=mutation,
        risk=risk,
        risk_floor=risk_floor,
        risk_rule=risk_rule,
        risk_implied=risk_implied,
        cost=cost,
        steps=steps,
        graph=graph,
        confidence=confidence,
        capabilities=capabilities,
        risk_deny_threshold=risk_deny_threshold,
    )


# ---------------------------------------------------------------------------
# Helpers consumed by states.py
# ---------------------------------------------------------------------------

def _intent_text(mutation: str) -> str:
    mapping = {
        "READ": "list users",
        "R": "list users",
        "WRITE": "create contact",
        "W": "create contact",
        "DELETE": "delete user",
        "D": "delete user",
        "IRREVERSIBLE": "irreversible action",
    }
    return mapping.get(mutation, "test request")


def _build_capability_dicts(scenario: Scenario) -> list[dict]:
    """Build candidate dicts for S3 from a Scenario."""
    rf = scenario.effective_risk_floor()
    rr = scenario.risk_rule if scenario.risk_rule is not None else 0.0
    ri = scenario.risk_implied if scenario.risk_implied is not None else 0.0
    primary = {
        "capability_id": "cap-1",
        "name": "TestCap",
        "risk_floor": rf,
        "risk_rule": rr,
        "risk_implied": ri,
        "mutation_type": scenario.mutation,
        "estimated_cost_units": scenario.cost,
        "tags": [],
    }
    extras = []
    for i in range(1, scenario.capabilities):
        extras.append({
            "capability_id": f"cap-{i + 1}",
            "name": f"AltCap{i}",
            "risk_floor": rf,
            "risk_rule": rr,
            "risk_implied": ri,
            "mutation_type": scenario.mutation,
            "estimated_cost_units": scenario.cost,
            "tags": [],
        })
    return [primary] + extras


_OP_TAG = {"R": "query", "W": "create", "D": "delete", "IRREVERSIBLE": "create"}


class ScenarioRegistry(CapabilityRegistry):
    """Fixture capability registry configured entirely by a Scenario (R-T).

    Not in src/: production registries read the database. `capabilities=0` yields an
    empty registry; extra capabilities are alternatives with the same properties.
    """

    def __init__(self, scenario: Scenario) -> None:
        self._sc = scenario

    def _caps(self) -> list[CapabilityMetadata]:
        sc = self._sc
        rf = sc.effective_risk_floor()
        rr = sc.risk_rule if sc.risk_rule is not None else 0.0
        ri = sc.risk_implied if sc.risk_implied is not None else 0.0
        return [
            CapabilityMetadata(
                capability_id=f"cap-{i + 1}",
                name="TestCap" if i == 0 else f"AltCap{i}",
                description="", namespace="test", input_schema={}, output_schema={},
                risk_floor=rf, risk_rule=rr, risk_implied=ri,
                mutation_type=sc.mutation, estimated_cost_units=sc.cost,
                tags=[_OP_TAG.get(sc.mutation, "query")],
            )
            for i in range(sc.capabilities)
        ]

    async def discover(self, intent, tenant_id):
        return self._caps()

    async def known_intents(self, tenant_id):
        return (_OP_TAG.get(self._sc.mutation, "query"),)

    async def get_capability(self, capability_id):
        return next((c for c in self._caps() if c.capability_id == capability_id), None)

    async def list_bindings(self, capability_id):
        return [
            BindingRow(
                binding_id=f"binding-{capability_id}", capability_id=capability_id,
                provider="local", adapter_class="DefaultAdapter",
                capability_version="cap-v7", binding_version="bind-v3",
                policy_version="policy-1", risk_policy_version="risk-v2",
                authorization_version="auth-v4", effective_risk=0.0,
                kernel_op_id=f"kernel-op-{capability_id}", engine_module="engines.default",
            )
        ]
