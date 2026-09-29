"""The S0–S11 stage sequence: the single definition the runner executes."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from supragents.contracts.state import PipelineState
from supragents.pipeline.deps import PipelineDeps
from supragents.stages import (
    s00_entry,
    s01_normalize,
    s02_intent,
    s03_capability,
    s04_graph,
    s05_binding,
    s06_task_profile,
    s07_path,
    s09_plan,
    s10_confirmation,
    s11_validation,
)
from supragents.stages.s08_safety import gate as s08_safety

StageHandler = Callable[[PipelineState, PipelineDeps], Awaitable[PipelineState]]

STAGES: tuple[tuple[str, StageHandler], ...] = (
    ("S0", s00_entry.run),
    ("S1", s01_normalize.run),
    ("S2", s02_intent.run),
    ("S3", s03_capability.run),
    ("S4", s04_graph.run),
    ("S5", s05_binding.run),
    ("S6", s06_task_profile.run),
    ("S7", s07_path.run),
    ("S8", s08_safety.run),
    ("S9", s09_plan.run),
    ("S10", s10_confirmation.run),
    ("S11", s11_validation.run),
)
