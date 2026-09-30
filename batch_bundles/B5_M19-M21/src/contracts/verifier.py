"""Verifier (DATA_CONTRACTS §34) and the kernel-operation metadata it is built from (gate D1).

The verifier is built BEFORE the step runs, from the step definition and the registry's
metadata, so the adapter's self-report cannot influence it. It only describes how to observe;
running it (S13) never calls the adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Verifier:
    """Independent post-execution verifier: the fields of DATA_CONTRACTS §34."""
    verifier_id: str                 # deterministic per (execution, step, operation, binding)
    step_id: str
    execution_id: str
    kernel_op_id: str
    binding_id: str
    expected_state: dict             # what a correct read-back looks like (from the step definition)
    observation_method: str          # e.g. "get_contact" (registry)
    observation_params: dict         # static part of the observation query
    max_attempts: int
    attempt_delay_ms: int


@dataclass(frozen=True)
class KernelOpMetadata:
    """Registry facts a verifier needs about one kernel operation."""
    kernel_op_id: str
    mutation: str                            # R | W | D | IRREVERSIBLE
    observation_method: str | None           # None: the operation cannot be observed
    expects_absent: bool = False             # a delete: the resource must be gone afterwards
    identifier_field: str | None = None      # which field of the adapter result names the resource


class KernelOpMetadataReader(Protocol):
    async def read(self, kernel_op_ids: tuple[str, ...], *, capability_version: str,
                   binding_version: str) -> dict[str, KernelOpMetadata] | None:
        """Metadata of the operations at the versions the manifest pinned, or None if the registry
        no longer serves those versions. Raise DependencyUnavailable if it cannot be read."""
