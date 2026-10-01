"""Worker eligibility (gate §8 step 2, C39; WORKER_LIFECYCLE §13 "Worker-Eligibility Filters"; invariant I18).

``filter_workers`` is a pure function of the live candidates and the step's ``SelectionContext``; it runs before
locality scoring. Each worker is checked in the order 4b, 12b, 13b, 14, 17a–c, 17d and removed with the first reason
that applies. The admin bypass (the run's original principal is a live owner/admin of the run's workspace) lets a
worker through 12b, 13b and 14 only, never 4b or 17. Every comparison uses database time (``now``, I-019).

Malformed worker data fails closed: ``settings`` that is not a mapping, a ``restricted_capabilities`` that is not a
list of ids, or a ``max_mutation`` / step mutation outside ``R < W < D < IRREVERSIBLE`` removes the worker.
``runtime_type`` only ever filters workers; the adapter comes from the binding frozen at S5 (RD-9).
"""
from __future__ import annotations

import types
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from contracts.execution_states import StepTerminalReason
from contracts.step_admission import DecisionLedger

WORKSPACE_MISMATCH = "workspace_mismatch"          # 4b, no bypass
WORKER_PAUSED = "worker_paused"                    # 12b, bypassable
WORKER_NOT_YET_ACTIVE = "worker_not_yet_active"    # 13b, bypassable
NOT_ASSIGNED = "not_assigned"                      # 14, bypassable
CAPABILITY_MISMATCH = "capability_mismatch"        # 17a–c, no bypass
MUTATION_CEILING = "mutation_ceiling"              # 17d, no bypass

BYPASS_EVENT = "eligibility_bypass"               # one ledger event per admin bypass (C39)

_MUTATION_RANK = types.MappingProxyType({"R": 0, "W": 1, "D": 2, "IRREVERSIBLE": 3})


@dataclass(frozen=True)
class WorkerCandidate:
    worker_id: str
    workspace_id: str | None                 # NULL only on legacy rows (never eligible, filter 4b)
    capacity: int
    current_load: int
    paused_until: float | None               # filter 12b (database epoch seconds)
    scheduled_activation_at: float | None    # filter 13b (database epoch seconds)
    assigned_user_id: str | None             # filter 14; None = any user
    capability_profile: frozenset[str]       # capability ids (filter 17a)
    settings: Mapping[str, Any]              # restricted_capabilities (17b), execution_policy.max_mutation (17d)
    runtime_type: str                        # RuntimeType (filter 17c)


@dataclass(frozen=True)
class SelectionContext:
    """What one step's selection is judged against; S12 derives it from the run (ruling CONF-016)."""
    workspace_id: str
    capability_id: str
    effective_mutation: str                  # the step's frozen effective mutation
    required_runtime_types: tuple[str, ...]  # from the binding row; empty = any runtime
    original_principal_id: str | None
    principal_is_human: bool
    event_driven: bool
    admin: bool                              # live owner/admin membership of the original principal in the workspace
    now: float                               # database epoch seconds


@dataclass(frozen=True)
class FilterResult:
    eligible: tuple[WorkerCandidate, ...]         # in input order
    removed: Mapping[str, str]                    # worker_id -> the reason that removed it
    bypassed: tuple[tuple[str, str], ...]         # (worker_id, reason) the admin bypass let through


def filter_workers(candidates: Iterable[WorkerCandidate], ctx: SelectionContext) -> FilterResult:
    eligible, removed, bypassed = [], {}, []
    for worker in candidates:
        reason, let_through = _judge(worker, ctx)
        if reason is None:
            eligible.append(worker)
            bypassed.extend((worker.worker_id, r) for r in let_through)
        else:
            removed[worker.worker_id] = reason
    return FilterResult(tuple(eligible), types.MappingProxyType(removed), tuple(bypassed))


async def record_filtering(ledger: DecisionLedger, result: FilterResult) -> None:
    """The ledger events of one filtering (C39): each admin bypass, and when no candidate is left, ``no_worker`` with
    every filter reason (the step's terminal reason stays ``no_worker``)."""
    for worker_id, reason in result.bypassed:
        await ledger.record(BYPASS_EVENT, {"worker_id": worker_id, "reason": reason})
    if not result.eligible:
        await ledger.record(StepTerminalReason.NO_WORKER, {"reasons": dict(result.removed)})


def _judge(worker: WorkerCandidate, ctx: SelectionContext) -> tuple[str | None, list[str]]:
    """(the reason that removes the worker or None, the bypassable reasons the admin bypass let through)."""
    if worker.workspace_id is None or worker.workspace_id != ctx.workspace_id:
        return WORKSPACE_MISMATCH, []
    let_through = []
    for reason in _bypassable_failures(worker, ctx):
        if not ctx.admin:
            return reason, []
        let_through.append(reason)
    if not _capability_matches(worker, ctx):
        return CAPABILITY_MISMATCH, []
    if not _within_mutation_ceiling(worker, ctx):
        return MUTATION_CEILING, []
    return None, let_through


def _bypassable_failures(worker: WorkerCandidate, ctx: SelectionContext) -> list[str]:
    failures = []
    if worker.paused_until is not None and worker.paused_until > ctx.now:
        failures.append(WORKER_PAUSED)
    if worker.scheduled_activation_at is not None and worker.scheduled_activation_at > ctx.now:
        failures.append(WORKER_NOT_YET_ACTIVE)
    # 14: only a human principal outside an event-driven run carries an assignment (system runs skip it; a
    # worker-delegated run carries the human's id as its original principal).
    if ctx.principal_is_human and not ctx.event_driven and worker.assigned_user_id is not None \
            and worker.assigned_user_id != ctx.original_principal_id:
        failures.append(NOT_ASSIGNED)
    return failures


def _capability_matches(worker: WorkerCandidate, ctx: SelectionContext) -> bool:
    if not isinstance(worker.settings, Mapping):
        return False                                                                        # malformed: fail closed
    if ctx.capability_id not in worker.capability_profile:                                  # 17a
        return False
    restricted = worker.settings.get("restricted_capabilities") or []
    if not isinstance(restricted, list | tuple) or not all(isinstance(c, str) for c in restricted):
        return False                                                                        # malformed: fail closed
    if ctx.capability_id in restricted:                                                     # 17b
        return False
    return not ctx.required_runtime_types or worker.runtime_type in ctx.required_runtime_types   # 17c


def _within_mutation_ceiling(worker: WorkerCandidate, ctx: SelectionContext) -> bool:     # 17d
    if not isinstance(worker.settings, Mapping):
        return False
    policy = worker.settings.get("execution_policy") or {}
    if not isinstance(policy, Mapping):
        return False
    ceiling = policy.get("max_mutation")
    if ceiling is None:
        return True
    if not isinstance(ceiling, str) or ceiling not in _MUTATION_RANK or ctx.effective_mutation not in _MUTATION_RANK:
        return False
    return _MUTATION_RANK[ctx.effective_mutation] <= _MUTATION_RANK[ceiling]


async def binding_requirements(reader, binding_ids) -> dict:
    """The runtime list of each distinct binding, read once per run (ruling CONF-019)."""
    return {binding_id: await reader.required_runtime_types(binding_id) for binding_id in binding_ids}


def step_context(*, workspace_id, binding, requirements, principal_id, principal_is_human, event_driven, admin,
                 now) -> SelectionContext:
    return SelectionContext(workspace_id=workspace_id, capability_id=binding.capability_id,
                            effective_mutation=binding.effective_mutation,
                            required_runtime_types=requirements[binding.binding_id],
                            original_principal_id=principal_id, principal_is_human=principal_is_human,
                            event_driven=event_driven, admin=admin, now=now)
