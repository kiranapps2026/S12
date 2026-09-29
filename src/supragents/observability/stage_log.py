"""One structured log line per stage, keyed for grep: stage=, status=, reason=, trace=."""
from __future__ import annotations

import logging

from supragents.contracts.events import StageEvent
from supragents.contracts.vocabulary import StageStatus

logger = logging.getLogger("supragents.pipeline")


def log_stage(event: StageEvent) -> None:
    level = logging.INFO if event.status is StageStatus.NORMAL else logging.WARNING
    logger.log(
        level,
        "stage=%s status=%s reason=%s trace=%s request=%s tenant=%s duration_ms=%.1f",
        event.stage, event.status.value, event.reason or "-", event.trace_id or "-",
        event.request_id or "-", event.tenant_id or "-", event.duration_ms,
    )
