"""Programmable mock provider adapter with a side-effect ledger per idempotency key (gate §15.3, C32).

``program(kernel_op_id, call, ...)`` fixes how one operation behaves. The side-effect ledger counts real executions per
idempotency key, and a key that already executed successfully is not executed again (the provider deduplicates), so a
test can assert "at most one side effect per key" (I4). Probes and observations answer from that ledger. Every call,
probe and observation asks the CredentialProvider (S6); a credential never appears in a result, only in an exception
text of ``raise_exception`` (the redaction tests need one to leak).
"""
from __future__ import annotations

import asyncio
import time
import types
from dataclasses import dataclass, field

from contracts.adapter_interface import BaseAdapter, CallMeta, ErrorClass, Observation, ProbeOutcome
from contracts.step_execution import AdapterResult

_HANG_S = 3600.0
_DEFAULT = "default"          # probe/observe mode: the BaseAdapter default
_RETRYABLE_EARLY = types.MappingProxyType({"fail_500_then_success": ErrorClass.SERVER_ERROR,
                                           "rate_limit_429": ErrorClass.RATE_LIMITED,
                                           "connect_refused": ErrorClass.NOT_DISPATCHED})
_CLIENT = frozenset({"auth_401", "validation_422"})


@dataclass
class _Program:
    call: str = "success"
    n: int = 0
    ms: int = 0
    probe: str = "ledger"
    observe: str = "ledger"
    observe_unknown: int = 0
    body: dict | None = None
    calls: int = 0
    observations: int = 0


@dataclass
class _Effect:
    executions: int = 0
    succeeded: bool = False
    mismatch: bool = False


@dataclass
class MockAdapter(BaseAdapter):
    credentials: object
    _programs: dict = field(default_factory=dict)
    _effects: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)
    probes: list = field(default_factory=list)
    observations: list = field(default_factory=list)

    def program(self, kernel_op_id: str, call: str = "success", *, n: int = 0, ms: int = 0, probe: str = "ledger",
                observe: str = "ledger", observe_unknown: int = 0, body: dict | None = None) -> None:
        self._programs[kernel_op_id] = _Program(call, n, ms, probe, observe, observe_unknown, body)

    def side_effects(self, idempotency_key: str) -> int:
        return self._effects.get(idempotency_key, _Effect()).executions

    def _execute(self, key: str, *, ok: bool = True, mismatch: bool = False) -> None:
        effect = self._effects.setdefault(key, _Effect())
        if effect.succeeded:
            return                                    # the provider deduplicates a repeated key
        effect.executions += 1
        effect.succeeded, effect.mismatch = ok, mismatch

    @staticmethod
    def _ok(key: str) -> AdapterResult:
        return AdapterResult("ok", data={"id": f"res-{key}", "key": key})

    async def _hang(self) -> None:
        await asyncio.sleep(_HANG_S)                  # only a deadline (TimeoutManager) ends this
        raise AssertionError("mock hang ended without a deadline")

    async def call(self, kernel_op_id, params, binding, context, *, call_meta: CallMeta | None = None):
        await self.credentials.credential(context.tenant_id, context.connection_id)
        self.calls.append(call_meta)
        p = self._programs.setdefault(kernel_op_id, _Program())
        p.calls += 1
        key = call_meta.idempotency_key if call_meta else f"no-key-{len(self.calls)}"
        early, kind = p.calls <= p.n, p.call
        if kind == "success":
            self._execute(key)
            return self._ok(key)
        if kind == "slow":
            await asyncio.sleep(p.ms / 1000)
            self._execute(key)
            return self._ok(key)
        if kind in _RETRYABLE_EARLY:
            if early:
                return AdapterResult("error", True, _RETRYABLE_EARLY[kind], dict(p.body or {}))
            self._execute(key)
            return self._ok(key)
        if kind in _CLIENT:
            return AdapterResult("error", False, ErrorClass.CLIENT_ERROR, dict(p.body or {}))
        if kind == "verify_mismatch":
            self._execute(key, mismatch=True)
            return self._ok(key)
        if kind == "timeout_executed":
            self._execute(key)
            await self._hang()
        if kind == "timeout_failed":
            self._execute(key, ok=False)
            await self._hang()
        if kind == "timeout_not_executed":
            if p.n == 0 or early:
                await self._hang()
            self._execute(key)
            return self._ok(key)
        if kind == "raise_exception":
            secret = await self.credentials.credential(context.tenant_id, context.connection_id)
            raise RuntimeError(f"provider exploded with credential {secret}\nTraceback (most recent call last):\n"
                               f'  File "provider.py", line 1, in call')
        raise ValueError(f"unknown mock behaviour {kind}")

    async def probe(self, kernel_op_id, params, binding, context, *, call_meta: CallMeta) -> ProbeOutcome:
        await self.credentials.credential(context.tenant_id, context.connection_id)
        self.probes.append(call_meta)
        mode = self._programs.get(kernel_op_id, _Program()).probe
        if mode == _DEFAULT:
            return await super().probe(kernel_op_id, params, binding, context, call_meta=call_meta)
        if mode == "inconclusive":
            return ProbeOutcome.INCONCLUSIVE
        effect = self._effects.get(call_meta.idempotency_key)
        if effect is None or effect.executions == 0:
            return ProbeOutcome.NOT_EXECUTED
        return ProbeOutcome.EXECUTED_SUCCESS if effect.succeeded else ProbeOutcome.EXECUTED_FAILURE

    async def observe(self, kernel_op_id, observation_spec, binding, context) -> Observation:
        await self.credentials.credential(context.tenant_id, context.connection_id)
        self.observations.append(dict(observation_spec))
        p = self._programs.setdefault(kernel_op_id, _Program())
        p.observations += 1
        if p.observe == _DEFAULT:
            return await super().observe(kernel_op_id, observation_spec, binding, context)
        if p.observe == "inconclusive" or p.observations <= p.observe_unknown:
            return Observation(p.observations, time.time(), 503, None, None, "provider_unavailable")
        effect = self._effects.get(observation_spec.get("idempotency_key", ""))
        exists = effect is not None and effect.succeeded
        return Observation(p.observations, time.time(), 200, {"exists": exists}, exists and not effect.mismatch, None)
