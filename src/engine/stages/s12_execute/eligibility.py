"""Worker eligibility (gate §8 step 2, C39; WORKER_LIFECYCLE §13 "Worker-Eligibility Filters").

``WorkerCandidate`` is one ACTIVE worker of the tenant as read live for selection; times are database epoch seconds
(I-019: every comparison uses database ``NOW()``). The eligibility filters that run before scoring are M8a.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkerCandidate:
    worker_id: str
    workspace_id: str | None                 # NULL only on legacy rows (never eligible, filter 4b)
    capacity: int
    current_load: int
    paused_until: float | None               # filter 12b
    scheduled_activation_at: float | None    # filter 13b
    assigned_user_id: str | None             # filter 14; None = any user
    capability_profile: frozenset[str]       # capability ids (filter 17a)
    settings: Mapping[str, Any]              # restricted_capabilities (17b), execution_policy.max_mutation (17d)
    runtime_type: str                        # RuntimeType (filter 17c)
