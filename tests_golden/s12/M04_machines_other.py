"""M4 golden — state machines II: lease, worker, dead letter, episode, confirmation, circuit breaker. Owner-pinned.

Gate v10: Appendix A.4–A.9 (A.5 = STATE_TRANSITIONS §4 exactly), C18, C21, C26, C28 (bare-literal architecture test),
C37; ruling CONF-012 (worker and confirmation list no reason codes: any non-empty reason is accepted).

Interface (extends M3): ``engine.stages.s12_execute.transitions.validate(machine, from_state, to_state, *, reason,
closed=False)`` for machines lease, worker, dead_letter, episode, confirmation, breaker; ``closed=True`` (an episode whose
``closed_at`` is set) makes every episode move illegal. ``contracts.execution_states.CircuitBreakerState`` with values
closed, open, half_open. Worker states are ``contracts.worker.WorkerStatus`` (S0–S11, unchanged).
An episode is created ``None → pending_probe`` (reason ``opened``); ``none`` is never a stored episode status.
"""
from __future__ import annotations

import itertools

import pytest

from tests_golden.fixtures.appendix_a import ANY_REASON, machines
from tests_golden.fixtures.code_scan import ROOT, s12_files, string_literals

ENUMS = {"lease": ("contracts.execution_states", "LeaseStatus"),
         "worker": ("contracts.worker", "WorkerStatus"),
         "dead_letter": ("contracts.execution_states", "DeadLetterStatus"),
         "episode": ("contracts.execution_states", "ReconciliationStatus"),
         "confirmation": ("contracts.execution_states", "ConfirmationStatus"),
         "breaker": ("contracts.execution_states", "CircuitBreakerState")}
BAD = "not_a_reason_code"
ANY = "golden_reason"

# C28 bare-literal rule: persisted state machines whose values/names may not appear as bare string literals in S12 code.
STATE_ENUMS = ("ExecutionStatus", "StepState", "ReservationState", "ReconciliationStatus", "LeaseStatus",
               "DeadLetterStatus", "ConfirmationStatus", "CircuitBreakerState")
# Not states (C28): KernelResult codes, AdapterErrorType values, VerificationResult values.
NOT_STATES = {"ok", "partial", "error", "UNKNOWN", "transient", "permanent", "rate_limit", "auth_failure", "unknown",
              "timeout", "PASS", "FAIL"}
# Machine names are identifiers of the transition log (DATABASE.md state_transitions.machine), not states. The run/step
# value "dead_letter" is spelled like the machine name, so as a lower-case literal it cannot be checked (the upper-case
# name DEAD_LETTER still is).
MACHINE_NAMES = {"run", "step", "reservation", "lease", "worker", "dead_letter", "episode", "confirmation", "breaker"}


def _enum(machine: str):
    module, name = ENUMS[machine]
    return getattr(__import__(module, fromlist=[name]), name)


def _states(machine: str) -> list[str]:
    values = sorted(s.value for s in _enum(machine))
    return [v for v in values if not (machine == "episode" and v == "none")]


def _reasons(machine: str) -> set[str]:
    out = {BAD, ANY, "created", "opened", "acquired"}
    for edge in machines()[machine].edges.values():
        if isinstance(edge.reasons, frozenset):
            out |= edge.reasons
    return out


def _validate():
    from engine.stages.s12_execute.transitions import IllegalStateTransition, validate
    return validate, IllegalStateTransition


def _legal_cases():
    for name in ENUMS:
        for (a, b), edge in sorted(machines()[name].edges.items()):
            for reason in ([ANY] if edge.reasons == ANY_REASON else sorted(edge.reasons)):
                yield name, a, b, reason


def test_breaker_enum_values():
    from contracts.execution_states import CircuitBreakerState
    assert {s.value for s in CircuitBreakerState} == {"closed", "open", "half_open"}


def test_pair_generation_is_complete():
    for name in ENUMS:
        states = set(_states(name))
        for a, b in machines()[name].edges:
            assert a in states and b in states, (name, a, b)


@pytest.mark.parametrize("machine,a,b,reason", list(_legal_cases()))
def test_legal_edge_with_an_allowed_reason(machine, a, b, reason):
    validate, _ = _validate()
    validate(machine, a, b, reason=reason)


@pytest.mark.parametrize("machine,a,b", sorted({(m, a, b) for m, a, b, _ in _legal_cases()}))
def test_legal_edge_rejects_other_reasons(machine, a, b):
    validate, illegal = _validate()
    edge = machines()[machine].edges[(a, b)]
    rejected = {""} if edge.reasons == ANY_REASON else _reasons(machine) - set(edge.reasons)
    for reason in sorted(rejected):
        with pytest.raises(illegal):
            validate(machine, a, b, reason=reason)


@pytest.mark.parametrize("machine", sorted(ENUMS))
def test_every_other_pair_is_illegal(machine):
    validate, illegal = _validate()
    legal = set(machines()[machine].edges)
    wrong = []
    for a, b in itertools.product(_states(machine), repeat=2):
        if (a, b) in legal:
            continue
        for reason in sorted(_reasons(machine)):
            try:
                validate(machine, a, b, reason=reason)
                wrong.append(f"{a} -> {b} ({reason})")
            except illegal:
                pass
    assert wrong == []


@pytest.mark.parametrize("machine", ["lease", "dead_letter", "episode", "confirmation"])
def test_creation_goes_to_the_initial_state_with_its_reason(machine):
    validate, illegal = _validate()
    initial, reason = machines()[machine].initial
    validate(machine, None, initial, reason=reason)
    with pytest.raises(illegal):
        validate(machine, None, initial, reason=BAD)
    for state in _states(machine):
        if state != initial:
            with pytest.raises(illegal):
                validate(machine, None, state, reason=reason)


def test_no_episode_move_after_closed_at():
    validate, illegal = _validate()
    for (a, b), edge in machines()["episode"].edges.items():
        for reason in sorted(edge.reasons):
            with pytest.raises(illegal):
                validate("episode", a, b, reason=reason, closed=True)


def test_exhausted_episode_is_not_a_transition():
    """An exhausted episode keeps status pending_probe and only gets closed_at (A.7): no edge represents it."""
    validate, illegal = _validate()
    for target in ("pending_probe", "confirmed_failure", "confirmed_success"):
        for reason in ("exhausted", "probe_exhausted", "EXHAUSTED"):
            with pytest.raises(illegal):
                validate("episode", "pending_probe", target, reason=reason)


def test_lease_can_only_be_renewed_while_active():
    validate, illegal = _validate()
    validate("lease", "active", "active", reason="renewed")
    for state in ("expired", "released"):
        with pytest.raises(illegal):
            validate("lease", state, "active", reason="renewed")


def test_worker_pause_is_not_a_state():
    """RD-4/RD-5: PAUSED and SCHEDULED are not worker states."""
    assert not {"PAUSED", "SCHEDULED"} & {s.value for s in _enum("worker")}


def test_no_bare_state_literals_in_s12_code():
    """C28/C18: state values and names appear only in the enum module; S12 code uses the typed enums."""
    from contracts import execution_states
    words = set()
    for name in STATE_ENUMS:
        for member in getattr(execution_states, name):
            words |= {member.value, member.name}
    words -= NOT_STATES | MACHINE_NAMES
    offenders = [f"{p.relative_to(ROOT).as_posix()}:{line}:{text}" for p in s12_files()
                 if p.relative_to(ROOT).as_posix() != "src/contracts/execution_states.py"
                 for line, text in string_literals(p) if text in words]
    assert offenders == []
