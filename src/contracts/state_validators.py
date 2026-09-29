"""
State Machine Validators — canonical validators for all 16 state machines.

Each state machine has:
- Valid states
- Valid transitions
- Illegal transitions (explicitly listed)
- Initial state
- Terminal states
- Cross-state invariants

Source: STATE_TRANSITIONS.md
CI enforcement: No state transition may occur without passing its validator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import FrozenSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base State Machine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StateMachineDefinition:
    """Definition of a state machine."""
    name: str
    states: FrozenSet[str]
    valid_transitions: dict[str, FrozenSet[str]]
    initial_state: str
    terminal_states: FrozenSet[str]
    illegal_transitions: dict[str, FrozenSet[str]] = field(default_factory=dict)


class StateTransitionValidator:
    """
    Validates state transitions for all state machines.

    This is the CANONICAL OWNER of all state transitions.
    No other module may update state without going through this validator.
    """

    def __init__(self) -> None:
        self._machines: dict[str, StateMachineDefinition] = {}
        self._register_default_machines()

    def _register_default_machines(self) -> None:
        """Register all 16 state machines from STATE_TRANSITIONS.md."""
        self._register_execution_run()
        self._register_execution_step()
        self._register_budget_reservation()
        self._register_worker_identity()
        self._register_worker_version()
        self._register_worker_deployment()
        self._register_lease()
        self._register_capability()
        self._register_binding()
        self._register_confirmation()
        self._register_dead_letter()
        self._register_reconciliation()
        self._register_circuit_breaker()
        self._register_verification()
        self._register_admission_decision()
        self._register_worker_subscription()

    def _register_execution_run(self) -> None:
        """ExecutionRun state machine (§1 of STATE_TRANSITIONS.md)."""
        self._machines["execution_run"] = StateMachineDefinition(
            name="execution_run",
            states=frozenset({
                "PENDING", "RESERVED", "COMMITTED", "RELEASED",
                "LOCKED", "CANCELLED", "FAILED", "COMPLETED",
            }),
            valid_transitions={
                "PENDING": frozenset({"RESERVED", "CANCELLED", "FAILED"}),
                "RESERVED": frozenset({"COMMITTED", "RELEASED", "LOCKED", "CANCELLED", "FAILED"}),
                "COMMITTED": frozenset({"COMPLETED", "FAILED"}),
                "RELEASED": frozenset({"PENDING"}),  # Can be re-queued
                "LOCKED": frozenset({"RESERVED", "COMMITTED", "RELEASED", "FAILED"}),
                "COMPLETED": frozenset(),  # Terminal
                "FAILED": frozenset({"PENDING"}),  # Can be retried
                "CANCELLED": frozenset(),  # Terminal
            },
            initial_state="PENDING",
            terminal_states=frozenset({"COMPLETED", "CANCELLED"}),
        )

    def _register_execution_step(self) -> None:
        """ExecutionStep state machine (§2 of STATE_TRANSITIONS.md)."""
        self._machines["execution_step"] = StateMachineDefinition(
            name="execution_step",
            states=frozenset({
                "PENDING", "RUNNING", "UNKNOWN", "PENDING_PROBE",
                "PROBE_FAILED", "PARTIAL", "SUCCESS", "FAILED",
                "DEAD_LETTER", "CANCELLED", "TIME_OUT",
            }),
            valid_transitions={
                "PENDING": frozenset({"RUNNING", "CANCELLED", "FAILED"}),
                "RUNNING": frozenset({"SUCCESS", "FAILED", "UNKNOWN", "TIME_OUT"}),
                "UNKNOWN": frozenset({"PENDING_PROBE", "FAILED", "DEAD_LETTER"}),
                "PENDING_PROBE": frozenset({"SUCCESS", "FAILED", "DEAD_LETTER"}),
                "PROBE_FAILED": frozenset({"DEAD_LETTER"}),
                "SUCCESS": frozenset(),  # Terminal
                "PARTIAL": frozenset({"DEAD_LETTER"}),
                "FAILED": frozenset({"DEAD_LETTER"}),
                "DEAD_LETTER": frozenset(),  # Terminal
                "CANCELLED": frozenset(),  # Terminal
                "TIME_OUT": frozenset({"FAILED", "DEAD_LETTER"}),
            },
            initial_state="PENDING",
            terminal_states=frozenset({"SUCCESS", "DEAD_LETTER", "CANCELLED"}),
        )

    def _register_budget_reservation(self) -> None:
        """BudgetReservation state machine (§3 of STATE_TRANSITIONS.md)."""
        self._machines["budget_reservation"] = StateMachineDefinition(
            name="budget_reservation",
            states=frozenset({
                "RESERVED", "LOCKED", "COMMITTED", "RELEASED",
            }),
            valid_transitions={
                "RESERVED": frozenset({"LOCKED", "RELEASED"}),
                "LOCKED": frozenset({"RESERVED", "COMMITTED", "RELEASED"}),
                "COMMITTED": frozenset(),  # Terminal
                "RELEASED": frozenset(),  # Terminal
            },
            initial_state="RESERVED",
            terminal_states=frozenset({"COMMITTED", "RELEASED"}),
        )

    def _register_worker_identity(self) -> None:
        """WorkerIdentity state machine (§4 of STATE_TRANSITIONS.md)."""
        self._machines["worker_identity"] = StateMachineDefinition(
            name="worker_identity",
            states=frozenset({
                "REGISTERED", "ACTIVE", "DRAINING", "DRAINED", "TERMINATED",
            }),
            valid_transitions={
                "REGISTERED": frozenset({"ACTIVE", "TERMINATED"}),
                "ACTIVE": frozenset({"DRAINING", "TERMINATED"}),
                "DRAINING": frozenset({"DRAINED", "ACTIVE", "TERMINATED"}),
                "DRAINED": frozenset({"TERMINATED"}),
                "TERMINATED": frozenset(),  # Terminal
            },
            initial_state="REGISTERED",
            terminal_states=frozenset({"TERMINATED"}),
        )

    def _register_worker_version(self) -> None:
        """WorkerVersion state machine (§5 of STATE_TRANSITIONS.md)."""
        self._machines["worker_version"] = StateMachineDefinition(
            name="worker_version",
            states=frozenset({
                "REGISTERED", "INACTIVE", "CANARY", "RAMPING",
                "CURRENT", "DEPRECATED", "DRAINING", "DRAINED", "RETIRED",
            }),
            valid_transitions={
                "REGISTERED": frozenset({"INACTIVE"}),
                "INACTIVE": frozenset({"CANARY", "RETIRED"}),
                "CANARY": frozenset({"RAMPING", "DEPRECATED", "RETIRED"}),
                "RAMPING": frozenset({"CURRENT", "DEPRECATED"}),
                "CURRENT": frozenset({"DEPRECATED"}),
                "DEPRECATED": frozenset({"DRAINING"}),
                "DRAINING": frozenset({"DRAINED"}),
                "DRAINED": frozenset({"RETIRED"}),
                "RETIRED": frozenset(),  # Terminal
            },
            initial_state="REGISTERED",
            terminal_states=frozenset({"RETIRED"}),
        )

    def _register_worker_deployment(self) -> None:
        """WorkerDeployment state machine (§6 of STATE_TRANSITIONS.md)."""
        self._machines["worker_deployment"] = StateMachineDefinition(
            name="worker_deployment",
            states=frozenset({
                "PENDING", "DEPLOYING", "ACTIVE", "FAILED", "ROLLED_BACK",
            }),
            valid_transitions={
                "PENDING": frozenset({"DEPLOYING", "FAILED"}),
                "DEPLOYING": frozenset({"ACTIVE", "FAILED"}),
                "ACTIVE": frozenset({"FAILED"}),
                "FAILED": frozenset({"ROLLED_BACK", "PENDING"}),
                "ROLLED_BACK": frozenset({"PENDING"}),
            },
            initial_state="PENDING",
            terminal_states=frozenset(),
        )

    def _register_lease(self) -> None:
        """Lease state machine (§7 of STATE_TRANSITIONS.md)."""
        self._machines["lease"] = StateMachineDefinition(
            name="lease",
            states=frozenset({
                "PENDING", "ACQUIRED", "EXPIRED", "RELEASED", "FENCED",
            }),
            valid_transitions={
                "PENDING": frozenset({"ACQUIRED", "EXPIRED"}),
                "ACQUIRED": frozenset({"RELEASED", "EXPIRED", "FENCED"}),
                "EXPIRED": frozenset({"PENDING"}),  # Can be re-acquired
                "RELEASED": frozenset(),  # Terminal
                "FENCED": frozenset({"RELEASED"}),
            },
            initial_state="PENDING",
            terminal_states=frozenset({"RELEASED"}),
        )

    def _register_capability(self) -> None:
        """Capability state machine (§8 of STATE_TRANSITIONS.md)."""
        self._machines["capability"] = StateMachineDefinition(
            name="capability",
            states=frozenset({
                "DESIGNED", "BUILT", "CONTRACT_VALIDATED", "TESTED",
                "FAILURE_TESTED", "CERTIFIED", "PRODUCTION_ENABLED",
                "SUSPENDED", "REVOKED",
            }),
            valid_transitions={
                "DESIGNED": frozenset({"BUILT"}),
                "BUILT": frozenset({"CONTRACT_VALIDATED"}),
                "CONTRACT_VALIDATED": frozenset({"TESTED"}),
                "TESTED": frozenset({"FAILURE_TESTED"}),
                "FAILURE_TESTED": frozenset({"CERTIFIED"}),
                "CERTIFIED": frozenset({"PRODUCTION_ENABLED", "SUSPENDED"}),
                "PRODUCTION_ENABLED": frozenset({"SUSPENDED", "REVOKED"}),
                "SUSPENDED": frozenset({"PRODUCTION_ENABLED", "REVOKED"}),
                "REVOKED": frozenset(),  # Terminal
            },
            initial_state="DESIGNED",
            terminal_states=frozenset({"REVOKED"}),
        )

    def _register_binding(self) -> None:
        """Binding state machine (§9 of STATE_TRANSITIONS.md)."""
        self._machines["binding"] = StateMachineDefinition(
            name="binding",
            states=frozenset({
                "ACTIVE", "DEPRECATED", "SUSPENDED",
            }),
            valid_transitions={
                "ACTIVE": frozenset({"DEPRECATED", "SUSPENDED"}),
                "DEPRECATED": frozenset({"SUSPENDED"}),
                "SUSPENDED": frozenset({"ACTIVE"}),
            },
            initial_state="ACTIVE",
            terminal_states=frozenset(),
        )

    def _register_confirmation(self) -> None:
        """Confirmation state machine (§10 of STATE_TRANSITIONS.md)."""
        self._machines["confirmation"] = StateMachineDefinition(
            name="confirmation",
            states=frozenset({
                "PENDING", "APPROVED", "DENIED", "EXPIRED",
            }),
            valid_transitions={
                "PENDING": frozenset({"APPROVED", "DENIED", "EXPIRED"}),
                "APPROVED": frozenset(),  # Terminal (consumed at S12)
                "DENIED": frozenset(),  # Terminal
                "EXPIRED": frozenset(),  # Terminal
            },
            initial_state="PENDING",
            terminal_states=frozenset({"APPROVED", "DENIED", "EXPIRED"}),
        )

    def _register_dead_letter(self) -> None:
        """DeadLetter state machine (§11 of STATE_TRANSITIONS.md)."""
        self._machines["dead_letter"] = StateMachineDefinition(
            name="dead_letter",
            states=frozenset({
                "PENDING_RETRY", "RETRYING", "RESOLVED", "ABANDONED",
            }),
            valid_transitions={
                "PENDING_RETRY": frozenset({"RETRYING", "ABANDONED"}),
                "RETRYING": frozenset({"RESOLVED", "PENDING_RETRY", "ABANDONED"}),
                "RESOLVED": frozenset(),  # Terminal
                "ABANDONED": frozenset(),  # Terminal
            },
            initial_state="PENDING_RETRY",
            terminal_states=frozenset({"RESOLVED", "ABANDONED"}),
        )

    def _register_reconciliation(self) -> None:
        """Reconciliation state machine (§12 of STATE_TRANSITIONS.md)."""
        self._machines["reconciliation"] = StateMachineDefinition(
            name="reconciliation",
            states=frozenset({
                "PENDING", "IN_PROGRESS", "CONSISTENT", "INCONSISTENT",
            }),
            valid_transitions={
                "PENDING": frozenset({"IN_PROGRESS"}),
                "IN_PROGRESS": frozenset({"CONSISTENT", "INCONSISTENT"}),
                "CONSISTENT": frozenset(),  # Terminal
                "INCONSISTENT": frozenset({"IN_PROGRESS"}),
            },
            initial_state="PENDING",
            terminal_states=frozenset({"CONSISTENT"}),
        )

    def _register_circuit_breaker(self) -> None:
        """CircuitBreaker state machine (§13 of STATE_TRANSITIONS.md)."""
        self._machines["circuit_breaker"] = StateMachineDefinition(
            name="circuit_breaker",
            states=frozenset({
                "CLOSED", "OPEN", "HALF_OPEN", "DEGRADED",
            }),
            valid_transitions={
                "CLOSED": frozenset({"OPEN", "DEGRADED"}),
                "OPEN": frozenset({"HALF_OPEN"}),
                "HALF_OPEN": frozenset({"CLOSED", "OPEN"}),
                "DEGRADED": frozenset({"CLOSED", "OPEN"}),
            },
            initial_state="CLOSED",
            terminal_states=frozenset(),
        )

    def _register_verification(self) -> None:
        """Verification state machine (§14 of STATE_TRANSITIONS.md)."""
        self._machines["verification"] = StateMachineDefinition(
            name="verification",
            states=frozenset({
                "PENDING", "SCHEMA_CHECK", "DETERMINISTIC_CHECK",
                "PROVIDER_STATE_CHECK", "SEMANTIC_CHECK",
                "BUSINESS_RULE_CHECK", "HUMAN_REVIEW",
                "PASSED", "FAILED", "UNKNOWN",
            }),
            valid_transitions={
                "PENDING": frozenset({"SCHEMA_CHECK"}),
                "SCHEMA_CHECK": frozenset({"DETERMINISTIC_CHECK", "FAILED"}),
                "DETERMINISTIC_CHECK": frozenset({"PROVIDER_STATE_CHECK", "FAILED"}),
                "PROVIDER_STATE_CHECK": frozenset({"SEMANTIC_CHECK", "FAILED"}),
                "SEMANTIC_CHECK": frozenset({"BUSINESS_RULE_CHECK", "FAILED"}),
                "BUSINESS_RULE_CHECK": frozenset({"HUMAN_REVIEW", "PASSED"}),
                "HUMAN_REVIEW": frozenset({"PASSED", "FAILED"}),
                "PASSED": frozenset(),  # Terminal
                "FAILED": frozenset(),  # Terminal
                "UNKNOWN": frozenset({"SCHEMA_CHECK"}),  # Retry verification
            },
            initial_state="PENDING",
            terminal_states=frozenset({"PASSED", "FAILED"}),
        )

    def _register_admission_decision(self) -> None:
        """AdmissionDecision state machine (§15 of STATE_TRANSITIONS.md)."""
        self._machines["admission_decision"] = StateMachineDefinition(
            name="admission_decision",
            states=frozenset({
                "PENDING", "ADMITTED", "DELAYED", "REJECTED",
            }),
            valid_transitions={
                "PENDING": frozenset({"ADMITTED", "DELAYED", "REJECTED"}),
                "ADMITTED": frozenset(),  # Terminal (proceeds to S12)
                "DELAYED": frozenset({"PENDING"}),  # Can retry admission
                "REJECTED": frozenset(),  # Terminal (→ DEAD_LETTER)
            },
            initial_state="PENDING",
            terminal_states=frozenset({"ADMITTED", "REJECTED"}),
        )

    def _register_worker_subscription(self) -> None:
        """WorkerSubscription state machine (§16 of STATE_TRANSITIONS.md)."""
        self._machines["worker_subscription"] = StateMachineDefinition(
            name="worker_subscription",
            states=frozenset({
                "IDLE", "POLLING", "EXECUTING", "VERIFYING", "ERROR",
            }),
            valid_transitions={
                "IDLE": frozenset({"POLLING"}),
                "POLLING": frozenset({"EXECUTING", "IDLE"}),
                "EXECUTING": frozenset({"VERIFYING", "ERROR"}),
                "VERIFYING": frozenset({"IDLE", "ERROR"}),
                "ERROR": frozenset({"IDLE"}),
            },
            initial_state="IDLE",
            terminal_states=frozenset(),
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def validate_transition(self, machine_name: str, from_state: str, to_state: str) -> bool:
        """
        Validate that a state transition is legal.

        Args:
            machine_name: Name of the state machine
            from_state: Current state
            to_state: Desired next state

        Returns:
            True if transition is valid, False otherwise
        """
        if machine_name not in self._machines:
            logger.error(f"Unknown state machine: {machine_name}")
            return False

        machine = self._machines[machine_name]

        if from_state not in machine.states:
            logger.error(f"Invalid state '{from_state}' for machine '{machine_name}'")
            return False

        if to_state not in machine.states:
            logger.error(f"Invalid target state '{to_state}' for machine '{machine_name}'")
            return False

        valid = to_state in machine.valid_transitions.get(from_state, frozenset())

        if not valid:
            logger.warning(
                "Illegal transition in '%s': %s → %s",
                machine_name, from_state, to_state,
            )
            return False

        return True

    def is_terminal(self, machine_name: str, state: str) -> bool:
        """Check if a state is terminal."""
        if machine_name not in self._machines:
            return False
        return state in self._machines[machine_name].terminal_states

    def get_valid_transitions(self, machine_name: str, state: str) -> FrozenSet[str]:
        """Get valid next states for a given state."""
        if machine_name not in self._machines:
            return frozenset()
        return self._machines[machine_name].valid_transitions.get(state, frozenset())

    def get_initial_state(self, machine_name: str) -> str | None:
        """Get the initial state for a state machine."""
        if machine_name not in self._machines:
            return None
        return self._machines[machine_name].initial_state

    def get_all_machines(self) -> dict[str, StateMachineDefinition]:
        """Get all registered state machines."""
        return dict(self._machines)

    def assert_valid_transition(
        self,
        machine_name: str,
        from_state: str,
        to_state: str,
    ) -> None:
        """
        Assert a transition is valid. Raises ValueError if not.

        Use this at the boundary where state changes occur.
        """
        if not self.validate_transition(machine_name, from_state, to_state):
            machine = self._machines.get(machine_name)
            valid = machine.valid_transitions.get(from_state, frozenset()) if machine else frozenset()
            raise ValueError(
                f"Illegal state transition in '{machine_name}': "
                f"{from_state} → {to_state}. "
                f"Valid next states: {sorted(valid)}"
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

# The canonical state transition validator — single instance for the entire process.
# CI enforcement: All state changes MUST go through this instance.
STATE_VALIDATOR = StateTransitionValidator()
