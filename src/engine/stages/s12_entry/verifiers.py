"""Build the step verifiers at S12 entry (gate D1, §7.1 item 6).

`build_verifier` is pure and deterministic: its output depends only on the step, the ids passed
in and the operation's registry metadata (a test proves it reads nothing else). The verifier id is
a UUIDv5 of (execution, step, operation, binding), so rebuilding on recovery yields the same id.

Which steps get a verifier (WORKER_LIFECYCLE §6): reads are self-verifying and get none; every
W, D and IRREVERSIBLE step gets one, and its operation MUST have a registered observation method,
otherwise the plan is refused (`verifier_metadata_unavailable`) rather than run unverifiable.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import Step
from contracts.verifier import KernelOpMetadata, KernelOpMetadataReader, Verifier
from engine.stages.plan_steps import plan_step_bindings

VERIFIER_METADATA_UNAVAILABLE = "verifier_metadata_unavailable"
MAX_ATTEMPTS = 3
ATTEMPT_DELAY_MS = 1000
_NAMESPACE = uuid.UUID("6f0c7b1e-3a52-4d0e-9c1a-5d8f2b7e4a10")
_VERIFIED = frozenset({"W", "D", "IRREVERSIBLE"})


@dataclass(frozen=True)
class VerifierBuild:
    verifiers: tuple[Verifier, ...] = ()
    reason: str | None = None


def build_verifier(step: Step, *, execution_id: str, binding_id: str,
                   metadata: KernelOpMetadata | None) -> Verifier | None:
    """The verifier for one step; None for a read. Raises ValueError if a mutating step's
    operation has no usable metadata (the caller turns that into a denial)."""
    if step.mutation not in _VERIFIED:
        return None
    if (metadata is None or metadata.kernel_op_id != step.kernel_op_id
            or metadata.mutation != step.mutation or not metadata.observation_method):
        raise ValueError("no observation method for " + step.kernel_op_id)
    if metadata.expects_absent:
        expected: dict = {"exists": False}
    else:
        expected = {"exists": True, "properties": dict(step.params)}
    return Verifier(
        verifier_id=str(uuid.uuid5(_NAMESPACE, f"{execution_id}|{step.id}|{step.kernel_op_id}|{binding_id}")),
        step_id=step.id,
        execution_id=execution_id,
        kernel_op_id=step.kernel_op_id,
        binding_id=binding_id,
        expected_state=expected,
        observation_method=metadata.observation_method,
        # the identifier of the resource is read from the adapter result at run time (S13); it is
        # the only thing taken from that result
        observation_params={"identifier_from_result": metadata.identifier_field},
        max_attempts=MAX_ATTEMPTS,
        attempt_delay_ms=ATTEMPT_DELAY_MS,
    )


def _binding_ids(state: PipelineState) -> tuple[str, ...] | None:
    """The binding id of every plan step, in order (None if it cannot be determined)."""
    single = state.frozen_binding_identity
    if single is not None:
        return (single.binding_id,) * len(state.plan.plan.steps)
    mapped = plan_step_bindings(state)
    if mapped is None or len(mapped) != len(state.plan.plan.steps):
        return None
    return tuple(item.binding.binding_id for item in mapped)


async def build_verifiers(state: PipelineState, reader: KernelOpMetadataReader | None) -> VerifierBuild:
    """One verifier per W/D/IRREVERSIBLE step, in plan order. Fail closed on anything missing."""
    plan_result, manifest = state.plan, state.execution_manifest
    binding_ids = _binding_ids(state)
    if plan_result is None or manifest is None or binding_ids is None:
        return VerifierBuild(reason=VERIFIER_METADATA_UNAVAILABLE)
    steps = plan_result.plan.steps
    needing = tuple(dict.fromkeys(s.kernel_op_id for s in steps if s.mutation in _VERIFIED))
    if not needing:
        return VerifierBuild()                      # reads only: nothing to observe
    if reader is None:
        return VerifierBuild(reason=VERIFIER_METADATA_UNAVAILABLE)
    try:
        found = await reader.read(needing, capability_version=manifest.capability_version,
                                  binding_version=manifest.binding_version)
    except Exception:  # noqa: BLE001 — fail closed
        return VerifierBuild(reason=VERIFIER_METADATA_UNAVAILABLE)
    if found is None:
        return VerifierBuild(reason=VERIFIER_METADATA_UNAVAILABLE)
    built = []
    for step, binding_id in zip(steps, binding_ids):
        try:
            verifier = build_verifier(step, execution_id=plan_result.execution_id, binding_id=binding_id,
                                      metadata=found.get(step.kernel_op_id))
        except ValueError:
            return VerifierBuild(reason=VERIFIER_METADATA_UNAVAILABLE)
        if verifier is not None:
            built.append(verifier)
    return VerifierBuild(verifiers=tuple(built))
