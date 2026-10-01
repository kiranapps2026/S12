"""Canonical state machines (gate Appendix A, C24): the only legal moves, each with its reason codes.

``validate(machine, from_state, to_state, *, reason, closed=False)`` is the single check every transition goes through:
a legal edge with one of its listed reasons returns None, anything else raises ``IllegalStateTransition``.
``from_state=None`` is a creation: legal only to the machine's initial state with its creation reason.
Retries are not transitions (C24): there is no RUNNING -> RUNNING edge.

Machines: run (A.1), step (A.2), reservation (A.3), lease (A.4), worker (A.5 = STATE_TRANSITIONS §4, validator only),
dead_letter (A.6), episode (A.7), confirmation (A.8), breaker (A.9). States come from contracts.execution_states and
contracts.worker.WorkerStatus; values are the stored ``.value`` strings (C28). Worker and confirmation list no reason
codes, so any non-empty reason is accepted (CONF-012). ``closed=True`` (an episode whose ``closed_at`` is set) rejects
every episode move; an exhausted episode keeps ``pending_probe`` and is closed, which is not a transition (A.7). "Not produced" edges (running -> cancelled/partial, unknown -> ...) are
legal for the validator, but no code in this phase writes them (C24).
"""
from __future__ import annotations

import types
from collections.abc import Mapping

from contracts.errors import StateTransitionError
from contracts.execution_states import CircuitBreakerState as K
from contracts.execution_states import ConfirmationStatus as C
from contracts.execution_states import DeadLetterStatus as D
from contracts.execution_states import ExecutionStatus as R
from contracts.execution_states import LeaseStatus as L
from contracts.execution_states import ReconciliationStatus as E
from contracts.execution_states import ReservationState as B
from contracts.execution_states import StepState as S
from contracts.execution_states import StepTerminalReason
from contracts.worker import WorkerStatus as W


class IllegalStateTransition(StateTransitionError):
    """A move that Appendix A does not allow (pair, reason, or creation)."""


ANY_REASON = object()            # a not-produced edge with no listed reason: any non-empty reason
ANY_TERMINAL_REASON = object()   # step pending -> cancelled: any StepTerminalReason value (C22)

_RUN_CANCEL = frozenset({"user_cancelled", "budget_exhausted", "authorization_revoked", "kill_switch_engaged",
                         "binding_invalid", "credential_invalid"})

_EDGES: Mapping[str, Mapping[tuple[str, str], object]] = types.MappingProxyType({
    "run": types.MappingProxyType({
        (R.PENDING.value, R.RUNNING.value): frozenset({"admitted"}),
        (R.PENDING.value, R.CANCELLED.value): _RUN_CANCEL - {"budget_exhausted"},
        **{(R.RUNNING.value, to.value): frozenset({"consolidated"})
           for to in (R.COMPLETED, R.PARTIAL, R.FAILED, R.DEAD_LETTER)},
        (R.RUNNING.value, R.CANCELLED.value): _RUN_CANCEL,
        (R.RUNNING.value, R.RECONCILING.value): frozenset({"awaiting_resolution"}),
        **{(R.RECONCILING.value, to.value): frozenset({"consolidated"})
           for to in (R.COMPLETED, R.PARTIAL, R.FAILED, R.DEAD_LETTER)},
        (R.RECONCILING.value, R.CANCELLED.value): _RUN_CANCEL,
    }),
    "step": types.MappingProxyType({
        (S.PENDING.value, S.RUNNING.value): frozenset({"started"}),
        (S.PENDING.value, S.SKIPPED.value): frozenset({"dependency_failed"}),
        (S.PENDING.value, S.CANCELLED.value): ANY_TERMINAL_REASON,
        (S.RUNNING.value, S.COMPLETED.value): frozenset({"verified", "ledger_hit_verified"}),
        (S.RUNNING.value, S.FAILED.value): frozenset({"non_retryable_error", "retries_exhausted",
                                                      "verification_failed", "ledger_hit_failure"}),
        (S.RUNNING.value, S.TIMEOUT.value): frozenset({"step_timeout"}),
        (S.RUNNING.value, S.PENDING_PROBE.value): frozenset({"execution_uncertain", "verification_uncertain",
                                                             "recovery"}),
        (S.RUNNING.value, S.CANCELLED.value): frozenset({"user_cancelled"}),     # not produced (C16, C23)
        (S.RUNNING.value, S.PARTIAL.value): ANY_REASON,                          # not produced (C6)
        (S.TIMEOUT.value, S.PENDING_PROBE.value): frozenset({"step_timeout_probe"}),
        (S.UNKNOWN.value, S.PENDING_PROBE.value): ANY_REASON,                    # UNKNOWN is never written (C24)
        (S.UNKNOWN.value, S.DEAD_LETTER.value): ANY_REASON,
        (S.PENDING_PROBE.value, S.COMPLETED.value): frozenset({"probe_executed_success", "verification_passed",
                                                               "ledger_hit_success"}),
        (S.PENDING_PROBE.value, S.FAILED.value): frozenset({"probe_executed_failure", "ledger_hit_failure",
                                                            "verification_failed"}),
        (S.PENDING_PROBE.value, S.PENDING.value): frozenset({"probe_not_executed", "no_dispatch_marker",
                                                             "read_reexecution_safe"}),
        (S.PENDING_PROBE.value, S.DEAD_LETTER.value): frozenset({"probe_exhausted", "verification_exhausted",
                                                                 "human_verification_pending"}),
    }),
    "reservation": types.MappingProxyType({
        (B.RESERVED.value, B.LOCKED.value): frozenset({"step_started"}),
        (B.RESERVED.value, B.RELEASED.value): frozenset({"preflight_failed", "budget_released_before_start",
                                                         "run_cancelled"}),
        (B.LOCKED.value, B.COMMITTED.value): frozenset({"step_completed", "dead_letter_resolved_executed",
                                                        "dead_letter_resolved_undetermined", "dead_letter_abandoned"}),
        (B.LOCKED.value, B.RELEASED.value): frozenset({"step_failed", "probe_not_executed", "no_dispatch_marker",
                                                       "dead_letter_resolved_not_executed"}),
    }),
    "lease": types.MappingProxyType({
        (L.ACTIVE.value, L.ACTIVE.value): frozenset({"renewed"}),       # only while usable; new fence token (C26)
        (L.ACTIVE.value, L.EXPIRED.value): frozenset({"ttl_elapsed"}),
        (L.ACTIVE.value, L.RELEASED.value): frozenset({"work_complete", "fenced_out", "run_terminal"}),
    }),
    "worker": types.MappingProxyType({
        (W.REGISTERED.value, W.ACTIVE.value): ANY_REASON,
        (W.REGISTERED.value, W.TERMINATED.value): ANY_REASON,
        (W.ACTIVE.value, W.DRAINING.value): ANY_REASON,
        (W.ACTIVE.value, W.TERMINATED.value): ANY_REASON,
        (W.DRAINING.value, W.DRAINED.value): ANY_REASON,
        (W.DRAINING.value, W.ACTIVE.value): ANY_REASON,
        (W.DRAINED.value, W.TERMINATED.value): ANY_REASON,
        (W.DRAINED.value, W.ACTIVE.value): ANY_REASON,
    }),
    "dead_letter": types.MappingProxyType({
        (D.PENDING.value, D.RETRYING.value): frozenset({"retry_started"}),
        (D.PENDING.value, D.RESOLVED.value): frozenset({"human_resolved"}),
        (D.RETRYING.value, D.RESOLVED.value): frozenset({"retry_resolved"}),
        (D.RETRYING.value, D.PENDING.value): frozenset({"retry_inconclusive"}),
        (D.RETRYING.value, D.ABANDONED.value): frozenset({"abandoned_after_retries"}),
    }),
    "episode": types.MappingProxyType({
        (E.PENDING_PROBE.value, E.RECONCILING.value): frozenset({"attempt_started"}),
        (E.RECONCILING.value, E.CONFIRMED_SUCCESS.value): frozenset({"executed_success", "verified_pass", "ledger_hit"}),
        (E.RECONCILING.value, E.CONFIRMED_FAILURE.value): frozenset({"executed_failure", "verified_fail", "not_executed",
                                                                    "ledger_hit_failure"}),
        (E.RECONCILING.value, E.PENDING_PROBE.value): frozenset({"inconclusive"}),
    }),
    "confirmation": types.MappingProxyType({
        (C.PENDING.value, C.CONSUMED.value): ANY_REASON,
        (C.PENDING.value, C.REJECTED.value): ANY_REASON,
        (C.PENDING.value, C.EXPIRED.value): ANY_REASON,
    }),
    "breaker": types.MappingProxyType({
        (K.CLOSED.value, K.OPEN.value): frozenset({"failure_threshold"}),
        (K.OPEN.value, K.HALF_OPEN.value): frozenset({"recovery_timeout"}),
        (K.HALF_OPEN.value, K.CLOSED.value): frozenset({"trial_success"}),
        (K.HALF_OPEN.value, K.OPEN.value): frozenset({"trial_failure", "trial_inconclusive"}),
    }),
})

# Initial state and creation reason per machine (C24); the reservation's creation reason is its state name.
_INITIAL: Mapping[str, tuple[str, str]] = types.MappingProxyType({
    "run": (R.PENDING.value, "created"),
    "step": (S.PENDING.value, "created"),
    "reservation": (B.RESERVED.value, B.RESERVED.value),
    "lease": (L.ACTIVE.value, "acquired"),
    "dead_letter": (D.PENDING.value, "created"),
    "episode": (E.PENDING_PROBE.value, "opened"),           # logged none -> pending_probe (C18)
    "confirmation": (C.PENDING.value, "created"),
})

_TERMINAL_REASONS = frozenset(r.value for r in StepTerminalReason)


def validate(machine: str, from_state: str | None, to_state: str, *, reason: str, closed: bool = False) -> None:
    edges = _EDGES.get(machine)
    if edges is None:
        raise IllegalStateTransition(f"unknown state machine {machine!r}")
    if not reason:
        raise IllegalStateTransition(f"{machine}: a transition needs a reason code (C24)")
    if closed and machine == "episode":
        raise IllegalStateTransition("episode: no transition after closed_at (A.7)")
    if from_state is None:
        if machine not in _INITIAL:
            raise IllegalStateTransition(f"{machine}: rows are not created through the transition log")
        if _INITIAL[machine] != (to_state, reason):
            raise IllegalStateTransition(f"{machine}: creation must be {_INITIAL[machine]}, got ({to_state}, {reason})")
        return
    allowed = edges.get((from_state, to_state))
    if allowed is None:
        raise IllegalStateTransition(f"illegal {machine} transition {from_state} -> {to_state}")
    if allowed is ANY_REASON:
        return
    if allowed is ANY_TERMINAL_REASON:
        allowed = _TERMINAL_REASONS
    if reason not in allowed:
        raise IllegalStateTransition(f"reason {reason!r} not allowed on {machine} {from_state} -> {to_state}")


# --- pair-only checks for the prototype loop and its unit tests (reason checked by validate) ---------------------

def _targets(machine: str) -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = {}
    for a, b in _EDGES[machine]:
        out.setdefault(a, set()).add(b)
    return {a: frozenset(b) for a, b in out.items()}


RUN = types.MappingProxyType(_targets("run"))
STEP = types.MappingProxyType(_targets("step"))
# budget includes the in-memory PENDING state of C3, never stored and not a ReservationState member; it is spelled
# like every other "pending" state value, so the run enum supplies the spelling (no bare state literal, C28).
_IN_MEMORY_PENDING = R.PENDING.value
BUDGET = types.MappingProxyType({**_targets("reservation"),
                                 _IN_MEMORY_PENDING: frozenset({B.RESERVED.value, B.RELEASED.value})})
TERMINAL_STEP = frozenset(s.value for s in S) - frozenset(STEP)

# Step states that represent an in-flight (not yet terminal) step (CONF-048, §13 step 3).
# Recovery imports this tuple instead of constructing its own, keeping M03's C24 invariant
# (UNKNOWN is never written outside this file and loop.py) intact.
IN_FLIGHT_STEP_STATES = (S.RUNNING, S.TIMEOUT, S.UNKNOWN, S.PENDING_PROBE)


def _check(table, kind: str, current: str, new: str) -> None:
    if new not in table.get(current, frozenset()):
        raise IllegalStateTransition(f"illegal {kind} transition {current} -> {new}")


def check_run(current: str, new: str) -> None:
    _check(RUN, "run", current, new)


def check_step(current: str, new: str) -> None:
    _check(STEP, "step", current, new)


def check_budget(current: str, new: str) -> None:
    _check(BUDGET, "budget", current, new)
