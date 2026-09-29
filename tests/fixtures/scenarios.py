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

from contracts.capability import CapabilityMetadata


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
