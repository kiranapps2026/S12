"""Named fault-injection points (gate §15.2, suite 14).

The engine calls ``faults.hit(point)`` at each of the ten points; the default ``NoFaults`` checks the name and does
nothing, so the points are inert unless a test injects its own ``FaultInjector``. Nothing in the product ever raises
``SimulatedCrash``: only a test's injector does. It is a BaseException, so no ``except Exception`` in the engine (a
guard, a probe, an observation) can swallow a simulated crash: it ends the Worker Runtime's work exactly where a
process death would.
"""
from __future__ import annotations

from typing import Protocol

POINTS = (
    "after_lease_acquire",
    "after_budget_reserve",
    "after_budget_lock",
    "after_dispatch_marker_before_call",
    "after_adapter_call_before_ledger",
    "after_ledger_before_verification",
    "during_verification",
    "after_verification_before_step_commit",
    "after_commit_before_checkpoint",
    "during_probe",
)
_KNOWN = frozenset(POINTS)


class SimulatedCrash(BaseException):  # noqa: N818 - named by gate §15.2
    """A test-mode process death at a named point."""


class FaultInjector(Protocol):
    def hit(self, point: str) -> None: ...


class NoFaults:
    """The product's injector: every point is inert."""
    def hit(self, point: str) -> None:
        if point not in _KNOWN:
            raise ValueError(f"unknown fault-injection point {point!r}")
