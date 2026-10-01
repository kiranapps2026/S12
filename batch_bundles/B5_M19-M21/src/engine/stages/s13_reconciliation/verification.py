"""Per-step verification (gate §8 step 9, C12, C19, D4, D6; WORKER_LIFECYCLE §6–§9; FINAL_ARCHITECTURE §43).

The code lives in the S13 package and is called from the S12 loop (C12). A worker's self-report is not evidence: the
provider-state layer observes the provider independently (``guard.observe``, read-only, no breaker, no budget), and the
semantic layer sees only the verifier's expected state and that observation, never the adapter's result data, so text
in a provider response can never reach the language model. Every required layer must PASS on its own (D6).

Schema and deterministic layers are local checks: PASS or FAIL, never UNKNOWN (C19). An observation that fails is
UNKNOWN, never FAIL; only a successful observation that contradicts the expected state is FAIL (WORKER_LIFECYCLE §9).
The human layer has no channel in this phase: UNKNOWN at once, never retried (D4). After a probe confirmed an execution
there is no adapter result: the schema and deterministic layers (checks of that result) do not apply, the others do.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from contracts.step_execution import AdapterResult
from contracts.verification import (
    LAYER_ORDER,
    LayerResult,
    Verdict,
    VerificationLayer,
    VerificationOutcome,
    aggregate,
)

L = VerificationLayer
_MUTATING = frozenset({"W", "D", "IRREVERSIBLE"})
SEMANTIC_RISK = 0.7


def required_verification_layers(mutation: str, risk: float) -> tuple[str, ...]:
    """FINAL_ARCHITECTURE §43 without the autonomy argument: no AutonomyLevel source exists (CONF-005)."""
    layers = [L.SCHEMA, L.DETERMINISTIC]
    if mutation in _MUTATING:
        layers.append(L.PROVIDER_STATE)
    if risk >= SEMANTIC_RISK or mutation == "IRREVERSIBLE":
        layers.append(L.SEMANTIC)
    if mutation == "IRREVERSIBLE":
        layers.append(L.HUMAN)
    return tuple(str(layer) for layer in layers)


def parse_semantic(raw: object) -> str:
    """The strict enum or UNKNOWN (D6): anything but exactly PASS, FAIL or UNKNOWN is malformed."""
    if isinstance(raw, str) and raw.strip() in {v.value for v in Verdict}:
        return Verdict(raw.strip())
    return Verdict.UNKNOWN


class SemanticAssessor(Protocol):
    async def assess(self, *, expected_state: dict, observed_state: dict | None) -> str: ...


def _identifier(result: AdapterResult | None, verifier) -> object:
    field = (verifier.observation_params or {}).get("identifier_from_result") if verifier is not None else None
    return None if field is None or result is None else (result.data or {}).get(field)


def _schema(result: Any) -> LayerResult:
    ok = isinstance(result, AdapterResult) and result.status == "ok" and isinstance(result.data, dict)
    if ok:
        try:
            json.dumps(result.data)
        except (TypeError, ValueError):
            ok = False
    return LayerResult(L.SCHEMA, Verdict.PASS if ok else Verdict.FAIL, {"structure_valid": ok})


def _deterministic(result: AdapterResult, verifier) -> LayerResult:
    needs = verifier is not None and (verifier.observation_params or {}).get("identifier_from_result") is not None
    value = _identifier(result, verifier)
    ok = (not needs) or (isinstance(value, (str, int)) and not isinstance(value, bool) and value != "")
    return LayerResult(L.DETERMINISTIC, Verdict.PASS if ok else Verdict.FAIL, {"identifier_present": ok})


class StepVerifier:
    """Runs a step's required layers. ``verify`` never raises for a provider or model problem: that is UNKNOWN."""

    def __init__(self, guard, *, semantic: SemanticAssessor | None = None,
                 sleep: Callable[[float], Awaitable[object]]) -> None:
        self._guard, self._semantic, self._sleep = guard, semantic, sleep

    async def verify(self, step, binding, result: AdapterResult | None, *, verifier, context, idempotency_key: str,
                     layers: tuple[str, ...] | None = None) -> VerificationOutcome:
        required = required_verification_layers(step.mutation, binding.effective_risk)
        if result is None:                              # a probe confirmed the execution: there is no adapter result
            required = tuple(x for x in required if x not in (L.SCHEMA, L.DETERMINISTIC))
        wanted = required if layers is None else tuple(x for x in required if x in set(layers))
        results: list[LayerResult] = []
        for layer in (x for x in LAYER_ORDER if x in wanted):
            found = await self._run(layer, step, binding, result, verifier, context, idempotency_key)
            results.append(found)
            if found.verdict == Verdict.FAIL:
                break                                   # a FAIL is final: later layers cannot change it (D6)
        return VerificationOutcome(aggregate(tuple(results)), tuple(results))

    async def _run(self, layer, step, binding, result, verifier, context, key) -> LayerResult:
        if layer == L.SCHEMA:
            return _schema(result)
        if layer == L.DETERMINISTIC:
            return _deterministic(result, verifier)
        if layer == L.PROVIDER_STATE:
            return await self._provider_state(step, binding, result, verifier, context, key)
        if layer == L.SEMANTIC:
            return await self._semantic_layer(step, binding, result, verifier, context, key)
        return LayerResult(L.HUMAN, Verdict.UNKNOWN, {"reason": "no_human_channel"})

    def _spec(self, result, verifier, key) -> dict:
        return {"method": verifier.observation_method, "identifier": _identifier(result, verifier),
                "expected": verifier.expected_state, "idempotency_key": key}

    async def _provider_state(self, step, binding, result, verifier, context, key) -> LayerResult:
        if verifier is None:
            return LayerResult(L.PROVIDER_STATE, Verdict.UNKNOWN, {"reason": "no_verifier"})
        attempts, code = max(1, int(verifier.max_attempts)), 0
        for n in range(1, attempts + 1):
            seen = await self._guard.observe(step.kernel_op_id, self._spec(result, verifier, key), binding, context)
            code = seen.provider_response_code
            if seen.error is None and seen.matches_expected is True:
                return LayerResult(L.PROVIDER_STATE, Verdict.PASS, {"observations": n, "response_code": code})
            if seen.error is None and seen.matches_expected is False:
                return LayerResult(L.PROVIDER_STATE, Verdict.FAIL, {"observations": n, "response_code": code})
            if n < attempts:
                await self._sleep(verifier.attempt_delay_ms / 1000)
        return LayerResult(L.PROVIDER_STATE, Verdict.UNKNOWN, {"observations": attempts, "response_code": code})

    async def _semantic_layer(self, step, binding, result, verifier, context, key) -> LayerResult:
        if self._semantic is None:
            return LayerResult(L.SEMANTIC, Verdict.UNKNOWN, {"reason": "no_assessor"})
        observed = None
        if verifier is not None:
            seen = await self._guard.observe(step.kernel_op_id, self._spec(result, verifier, key), binding, context)
            observed = seen.observed_state if seen.error is None else None
        try:
            raw = await self._semantic.assess(expected_state=dict(verifier.expected_state) if verifier else {},
                                              observed_state=observed)
        except Exception:  # noqa: BLE001 — a model problem is UNKNOWN, never a pass
            raw = None
        verdict = parse_semantic(raw)
        return LayerResult(L.SEMANTIC, verdict, {"parsed": str(verdict)})
