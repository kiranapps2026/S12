"""Verification layers and verdicts (gate S8 step 9, C12, C19, D6; FINAL_ARCHITECTURE S43)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class VerificationLayer(StrEnum):
    SCHEMA = "schema"
    DETERMINISTIC = "deterministic"
    PROVIDER_STATE = "provider_state"
    SEMANTIC = "semantic"
    HUMAN = "human"


LAYER_ORDER = tuple(VerificationLayer)


@dataclass(frozen=True)
class LayerResult:
    layer: str
    verdict: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationOutcome:
    verdict: str
    layers: tuple[LayerResult, ...] = ()

    def pending(self) -> tuple[str, ...]:
        """The layers not yet PASS, in run order."""
        return tuple(r.layer for r in self.layers if r.verdict != Verdict.PASS)


def aggregate(layers: tuple[LayerResult, ...]) -> str:
    verdicts = {r.verdict for r in layers}
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.UNKNOWN in verdicts:
        return Verdict.UNKNOWN
    return Verdict.PASS
