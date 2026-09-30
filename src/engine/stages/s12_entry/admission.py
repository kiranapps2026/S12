"""S12 entry, start to finish: the §7.1 checks (nothing written) then durable admission (§7.2)."""
from __future__ import annotations

import logging

from contracts.activation import ActivationStateReader
from contracts.admission import DENIED, AdmissionOutcome, ExecutionAdmitter
from contracts.binding_reader import BindingVersionReader
from contracts.confirmation_record import ConsumedConfirmationReader
from contracts.errors import DependencyUnavailable
from contracts.pipeline_state import PipelineState
from contracts.verifier import KernelOpMetadataReader
from engine.stages.s12_entry.checks import check_entry

logger = logging.getLogger(__name__)

ADMISSION_UNAVAILABLE = "admission_unavailable"


async def admit_run(state: PipelineState, *, bindings: BindingVersionReader | None,
                    activation: ActivationStateReader | None, metadata: KernelOpMetadataReader | None,
                    admitter: ExecutionAdmitter | None, runtime_instance_id: str,
                    confirmations: ConsumedConfirmationReader | None = None) -> AdmissionOutcome:
    """Run the entry checks; only if they all pass, write the run durably. A refusal at any point
    leaves nothing behind. Fail closed: no admitter, or a database that cannot be used, is DENIED."""
    decision = await check_entry(state, bindings=bindings, activation=activation, metadata=metadata,
                                 confirmations=confirmations)
    if not decision.allowed:
        return AdmissionOutcome(DENIED, reason=decision.reason)
    if admitter is None or not runtime_instance_id:
        return AdmissionOutcome(DENIED, reason=ADMISSION_UNAVAILABLE)
    try:
        return await admitter.admit(state, decision.verifiers, runtime_instance_id)
    except DependencyUnavailable:
        logger.warning("S12 admission: database unavailable")
        return AdmissionOutcome(DENIED, reason=ADMISSION_UNAVAILABLE)
    except Exception:  # noqa: BLE001 — the transaction rolled back; never guess, never let it escape half done
        logger.exception("S12 admission failed; nothing was written")
        return AdmissionOutcome(DENIED, reason=ADMISSION_UNAVAILABLE)
