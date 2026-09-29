"""Usage recording for internal LLM consumption (PIPELINE_STAGES §4 [BILLING])."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UsageRecord:
    tenant_id: str
    user_id: str
    trace_id: str
    resource_type: str      # "llm.token"
    quantity: int
    unit: str               # "token"
    kernel_op_ref: str      # "llm.intent_analysis"
    model: str


class UsageRecorder(Protocol):
    async def record(self, usage: UsageRecord) -> None:
        """Persist one usage record. Raise DependencyUnavailable on failure."""
