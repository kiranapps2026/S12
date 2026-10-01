"""
S12 entry checks — gate §7.1 items 1–5b and 7, in the gate's order, then the C20 confirmation check. First failure decides.

A pure decision: nothing is written, nothing is re-authorised, nothing is re-resolved. The caller
(the S12 admission step, when it exists) writes only after `allowed` is True.

Item 6 (build the verifiers, D1) is in verifiers.py and runs here between items 5b and 7; on
success the decision carries the verifiers, to be persisted with the execution (gate §7.3).

Multi-step plans (M2a) follow docs/proposals/S12_MULTI_STEP.md G1/G2/G7: one frozen binding per
plan step; each DISTINCT binding row is read once and its version must equal the manifest's.
Until the gate owner accepts that amendment this is a proposal in code, marked by these notes.

Fail closed: an unreadable registry or activation state is a denial, never a pass.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass

from contracts.activation import ActivationStateReader
from contracts.binding_reader import BindingVersionReader
from contracts.pipeline_state import PipelineState
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import StepOutputReference, StepParameterBinding
from contracts.confirmation_record import ConsumedConfirmationReader
from contracts.verifier import KernelOpMetadataReader, Verifier
from engine.stages.plan_steps import plan_step_bindings
from engine.stages.s12_entry.verifiers import build_verifiers
from engine.stages.s12_entry.confirmation import confirmation_denial
from engine.stages.s0_entry.activation import UNAVAILABLE as ACTIVATION_UNAVAILABLE, inactive_reason

logger = logging.getLogger(__name__)

PLAN_NOT_VALIDATED = "plan_not_validated"
CONTEXT_INCOMPLETE = "context_incomplete"
AUTHORIZATION_MISSING = "authorization_missing"
BINDING_MISSING = "binding_missing"
JOIN_MODE_UNSUPPORTED = "join_mode_unsupported"
PLAN_INTEGRITY = "plan_integrity"
DATA_FLOW_UNSUPPORTED = "data_flow_unsupported"
BINDING_VERSION_MISMATCH = "binding_version_mismatch"
BINDING_UNAVAILABLE = "binding_unavailable"

_REQUIRED_CONTEXT = ("task_id", "workspace_id", "conversation_id", "user_id", "tenant_id",
                     "trace_id", "request_id")
_REFERENCE_TEXT = re.compile(
    r"(?i)(?:\$\{?|\{\{)\s*steps?\s*[.\[:]|\bstep[-_]?\d+\s*\.\s*(?:output|result|data)\b")
_MAX_DEPTH = 20


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    reason: str | None = None
    verifiers: tuple[Verifier, ...] = ()     # item 6: one per W/D/IRREVERSIBLE step, in plan order


def _deny(reason: str) -> EntryDecision:
    logger.warning("S12 entry: DENY %s", reason)
    return EntryDecision(False, reason)


def references_another_step(value, depth: int = 0) -> bool:
    """True if a step parameter looks like a reference to another step's output (C36). The
    contracts have no reference form yet, so this is deliberately broad: the reference
    dataclasses, a {step_id, output_field} mapping, or text such as `${steps.1.id}`,
    `{{steps.1.id}}` or `step-1.output`. Anything too deep to inspect counts as a reference."""
    if depth > _MAX_DEPTH:
        return True
    if isinstance(value, (StepOutputReference, StepParameterBinding)):
        return True
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(references_another_step(getattr(value, f.name), depth + 1)
                   for f in dataclasses.fields(value))
    if isinstance(value, dict):
        if "step_id" in value and "output_field" in value:
            return True
        return any(references_another_step(k, depth + 1) or references_another_step(v, depth + 1)
                   for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(references_another_step(v, depth + 1) for v in value)
    if isinstance(value, str):
        return _REFERENCE_TEXT.search(value) is not None
    return False


def _binding_ids(state: PipelineState) -> tuple[str, ...] | None:
    """The distinct binding ids this plan runs, or None if the bindings are missing or the plan
    does not map onto them (G1: exactly one of the singular field and the per-step tuple)."""
    single, many = state.frozen_binding_identity, state.frozen_bindings
    if (single is None) == (many is None):
        return None
    if single is not None:
        return (single.binding_id,)
    if plan_step_bindings(state) is None:
        return None
    return tuple(dict.fromkeys(b.binding_id for b in many))


async def check_entry(state: PipelineState, *, bindings: BindingVersionReader | None,
                      activation: ActivationStateReader | None,
                      metadata: KernelOpMetadataReader | None = None,
                      confirmations: ConsumedConfirmationReader | None = None) -> EntryDecision:
    ctx, manifest, plan_result = state.execution_context, state.execution_manifest, state.plan

    # 1. S11 succeeded and issued the manifest.
    vr = state.validation_result
    if vr is None or vr.is_valid is not True or manifest is None or plan_result is None:
        return _deny(PLAN_NOT_VALIDATED)

    # 1a. Every NOT NULL value of execution_runs exists (C33).
    if ctx is None or any(not getattr(ctx, name, None) for name in _REQUIRED_CONTEXT):
        return _deny(CONTEXT_INCOMPLETE)

    # 2. S8 authorised it and recorded that on the context. Never re-authorise here.
    if ctx.auth_passed is not True or not ctx.auth_result_id or manifest.auth_result_id != ctx.auth_result_id:
        return _deny(AUTHORIZATION_MISSING)

    # 3. The frozen binding(s) are present.
    binding_ids = _binding_ids(state)
    if binding_ids is None:
        return _deny(BINDING_MISSING)

    # 4. Only join_mode "all" runs (D3).
    plan = plan_result.plan
    if plan.join_mode != "all":
        return _deny(JOIN_MODE_UNSUPPORTED)

    # 5. The plan is the one S9 hashed and S11 froze.
    try:
        digest = canonical_plan_digest(plan)
    except (TypeError, ValueError):
        return _deny(PLAN_INTEGRITY)
    if digest != manifest.plan_hash or digest != plan_result.plan_hash:
        return _deny(PLAN_INTEGRITY)

    # 5a. No step consumes another step's output (C36).
    if any(references_another_step(step.params) for step in plan.steps):
        return _deny(DATA_FLOW_UNSUPPORTED)

    # 5b. Each distinct binding row, read once, still has the version the manifest froze (C32).
    if bindings is None:
        return _deny(BINDING_UNAVAILABLE)
    for binding_id in binding_ids:
        try:
            version = await bindings.binding_version(binding_id)
        except Exception:  # noqa: BLE001 — fail closed
            logger.exception("S12 entry: binding registry unavailable")
            return _deny(BINDING_UNAVAILABLE)
        if version is None or version != manifest.binding_version:
            return _deny(BINDING_VERSION_MISMATCH)

    # 6. Verifiers (D1): built from the step and the registry metadata at the manifest's versions.
    built = await build_verifiers(state, metadata)
    if built.reason is not None:
        return _deny(built.reason)

    # 7. Pause safety net (C39): the S0.1 check, again, at the database's current time.
    if activation is None:
        return _deny(ACTIVATION_UNAVAILABLE)
    try:
        state_now = await activation.read(ctx.tenant_id, ctx.workspace_id)
    except Exception:  # noqa: BLE001 — fail closed
        logger.exception("S12 entry: activation state unavailable")
        return _deny(ACTIVATION_UNAVAILABLE)
    reason = inactive_reason(state_now)
    if reason is not None:
        return _deny(reason)

    # C20. A plan that needed a confirmation runs only if the store row shows it consumed for THIS run (same
    # tenant, execution_id and plan_hash). Not a numbered §7.1 item, so it comes after them; it reads the store only
    # when every other check passed.
    denied = await confirmation_denial(state, confirmations)
    if denied is not None:
        return _deny(denied)
    return EntryDecision(True, verifiers=built.verifiers)
