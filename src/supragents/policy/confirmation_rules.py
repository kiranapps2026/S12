"""When a plan needs user confirmation (DATA_CONTRACTS §7, PIPELINE_STAGES §12).

The §7 table asks for confirmation of a D mutation only above cost 5, but §12 says
D/IRREVERSIBLE operations are NEVER executed without confirmation. The stricter rule
wins: every D and IRREVERSIBLE plan is confirmed.
"""
from __future__ import annotations

from supragents.contracts.vocabulary import Mutation

COST_THRESHOLD = 20
RISK_THRESHOLD = 0.7
PROVIDER_THRESHOLD = 3
_ALWAYS_CONFIRM = frozenset({Mutation.DELETE, Mutation.IRREVERSIBLE})


def requires_confirmation(
    mutation: Mutation, risk: float, total_cost: int, provider_count: int
) -> bool:
    return (
        mutation in _ALWAYS_CONFIRM
        or total_cost > COST_THRESHOLD
        or risk > RISK_THRESHOLD
        or provider_count >= PROVIDER_THRESHOLD
    )
