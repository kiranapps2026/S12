"""M3 golden — state machines I: run, step, budget reservation (gate commit C part 3). Owner-pinned.

Gate v10: Appendix A.1–A.3 (read here from the pinned gate text by tests_golden/fixtures/appendix_a.py), C6, C7, C13,
C22, C24, C27; rulings CONF-006 (contracts/state_validators.py is non-canonical) and CONF-012 (machines without listed
reason codes accept any non-empty reason).

Interface this file fixes (``engine.stages.s12_execute.transitions``):
  * ``validate(machine, from_state, to_state, *, reason, closed=False)`` returns None for a legal move and raises
    ``IllegalStateTransition`` otherwise. ``from_state=None`` is a creation: legal only to the machine's initial state
    with its creation reason (C24). Machine names: run, step, reservation (M3); lease, worker, dead_letter, episode,
    confirmation, breaker (M4).
  * ``IllegalStateTransition`` is an Exception subclass defined (or re-exported) there.
Pairs are generated over the enum values of ``contracts.execution_states`` (M1). "Not produced" edges with no listed
reason (``running → partial``, ``unknown → …``) are neither asserted legal nor illegal here.
"""
from __future__ import annotations

import itertools

import pytest

from tests_golden.fixtures.appendix_a import ANY_REASON, ANY_TERMINAL_REASON, machines
from tests_golden.fixtures.code_scan import ROOT, attribute_uses, imports, s12_files
from tests_golden.fixtures.invariants import TERMINAL_REASONS

MACHINES = {"run": "ExecutionStatus", "step": "StepState", "reservation": "ReservationState"}
BAD = "not_a_reason_code"


def _states(machine: str) -> list[str]:
    from contracts import execution_states
    return sorted(s.value for s in getattr(execution_states, MACHINES[machine]))


def _all_reasons(machine: str) -> set[str]:
    out = set(TERMINAL_REASONS) | {BAD, "created", "step_attempt"}
    for edge in machines()[machine].edges.values():
        if isinstance(edge.reasons, frozenset):
            out |= edge.reasons
    return out


def _legal_cases():
    for name in MACHINES:
        for (a, b), edge in sorted(machines()[name].edges.items()):
            if edge.reasons == ANY_REASON:
                continue
            reasons = TERMINAL_REASONS if edge.reasons == ANY_TERMINAL_REASON else edge.reasons
            for reason in sorted(reasons):
                yield name, a, b, reason


def _neutral(name: str) -> set[tuple[str, str]]:
    return {pair for pair, edge in machines()[name].edges.items() if edge.reasons == ANY_REASON}


def _illegal_pairs():
    for name in MACHINES:
        legal = set(machines()[name].edges)
        for a, b in itertools.product(_states(name), repeat=2):
            if (a, b) not in legal:
                yield name, a, b


def _validate():
    from engine.stages.s12_execute.transitions import IllegalStateTransition, validate
    return validate, IllegalStateTransition


@pytest.mark.parametrize("machine,a,b,reason", list(_legal_cases()))
def test_legal_edge_with_an_allowed_reason(machine, a, b, reason):
    validate, _ = _validate()
    validate(machine, a, b, reason=reason)


@pytest.mark.parametrize("machine,a,b", sorted({(m, a, b) for m, a, b, _ in _legal_cases()}))
def test_legal_edge_rejects_any_other_reason(machine, a, b):
    validate, illegal = _validate()
    edge = machines()[machine].edges[(a, b)]
    allowed = TERMINAL_REASONS if edge.reasons == ANY_TERMINAL_REASON else edge.reasons
    for reason in sorted(_all_reasons(machine) - set(allowed)):
        with pytest.raises(illegal):
            validate(machine, a, b, reason=reason)


def test_pair_generation_is_complete():
    """Guard for the generator itself: every Appendix A state is an enum value, so no edge is silently dropped."""
    for name in MACHINES:
        states = set(_states(name))
        for a, b in machines()[name].edges:
            assert a in states and b in states, (name, a, b)


@pytest.mark.parametrize("machine", sorted(MACHINES))
def test_every_other_pair_is_illegal(machine):
    validate, illegal = _validate()
    reasons = sorted(_all_reasons(machine))
    wrong = []
    for name, a, b in _illegal_pairs():
        if name != machine or (a, b) in _neutral(name):
            continue
        for reason in reasons:
            try:
                validate(machine, a, b, reason=reason)
                wrong.append(f"{a} -> {b} ({reason})")
            except illegal:
                pass
    assert wrong == []


@pytest.mark.parametrize("machine", sorted(MACHINES))
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


@pytest.mark.parametrize("pair", [("timeout", "dead_letter"), ("timeout", "unknown"), ("unknown", "failed"),
                                  ("pending", "pending_probe"), ("partial", "dead_letter"), ("running", "running"),
                                  ("running", "unknown"), ("pending", "failed"), ("failed", "dead_letter")])
def test_step_edges_the_gate_names_illegal(pair):
    """v9 explicitly illegal (Appendix A.2), retries are not transitions (C24), and the old DATA_CONTRACTS /
    state_validators edges (CONF-006)."""
    validate, illegal = _validate()
    for reason in sorted(_all_reasons("step")):
        with pytest.raises(illegal):
            validate("step", *pair, reason=reason)


def test_reservation_never_commits_from_reserved():
    validate, illegal = _validate()
    for reason in sorted(_all_reasons("reservation")):
        with pytest.raises(illegal):
            validate("reservation", "reserved", "committed", reason=reason)


def test_terminal_states_have_no_outgoing_edge():
    validate, illegal = _validate()
    for name in MACHINES:
        for state in machines()[name].terminal:
            for target in _states(name):
                for reason in sorted(_all_reasons(name)):
                    with pytest.raises(illegal):
                        validate(name, state, target, reason=reason)


def test_unknown_machine_is_rejected():
    validate, illegal = _validate()
    with pytest.raises(illegal):
        validate("not_a_machine", "pending", "running", reason="admitted")


# --- Architecture ----------------------------------------------------------------------------------------------

def test_no_code_writes_step_state_unknown():
    """C24: UNKNOWN is never written in this phase; only the enum and the transition tables may name it."""
    allowed = {"src/contracts/execution_states.py", "src/engine/stages/s12_execute/transitions.py"}
    uses = [f"{p.relative_to(ROOT).as_posix()}:{line}" for p in s12_files()
            if p.relative_to(ROOT).as_posix() not in allowed for line in attribute_uses(p, "StepState", "UNKNOWN")]
    assert uses == []


def test_s12_code_does_not_use_the_non_canonical_validator():
    """CONF-006: contracts.state_validators contradicts Appendix A; S12–S15 code must not import it."""
    offenders = [p.relative_to(ROOT).as_posix() for p in s12_files()
                 if any(m == "contracts.state_validators" or m.endswith(".state_validators") for m in imports(p))]
    assert offenders == []
