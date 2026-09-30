"""``assert_system_invariants(schema)`` — the invariant checker entry point (owner fixture, plan §5.4).

It grows milestone by milestone. Active now:
  * I5 (M2): every row of the transition log is legal per gate Appendix A: a creation row (``from_state`` NULL, or
    ``none`` for an episode) goes to the machine's initial state with its creation reason; every other row is an
    Appendix A edge whose reason is allowed on that edge.
"""
from __future__ import annotations

from tests_golden.fixtures.appendix_a import ANY_REASON, ANY_TERMINAL_REASON, machines

TERMINAL_REASONS = frozenset({
    "user_cancelled", "admission_rejected", "admission_exhausted", "no_worker", "lease_unavailable", "budget_exhausted",
    "preflight_failed", "not_executed_no_retry", "dependency_failed", "run_dead_lettered", "authorization_revoked",
    "kill_switch_engaged", "binding_invalid", "credential_invalid"})


def transition_problems(rows) -> list[str]:
    table = machines()
    problems = []
    for r in rows:
        machine = table.get(r["machine"])
        if machine is None:
            problems.append(f"{r['machine']}: unknown machine")
            continue
        if r["from_state"] in (None, "none"):
            if machine.initial is None or (r["to_state"], r["reason"]) != machine.initial:
                problems.append(f"{r['machine']} {r['entity_id']}: creation {r['to_state']}/{r['reason']}"
                                f" (expected {machine.initial})")
            continue
        edge = machine.edges.get((r["from_state"], r["to_state"]))
        if edge is None:
            problems.append(f"{r['machine']} {r['entity_id']}: illegal {r['from_state']} -> {r['to_state']}")
        elif edge.reasons == ANY_TERMINAL_REASON:
            if r["reason"] not in TERMINAL_REASONS:
                problems.append(f"{r['machine']} {r['entity_id']}: reason {r['reason']!r} not a StepTerminalReason")
        elif edge.reasons != ANY_REASON and r["reason"] not in edge.reasons:
            problems.append(f"{r['machine']} {r['entity_id']}: reason {r['reason']!r} not allowed on "
                            f"{r['from_state']} -> {r['to_state']}")
    return problems


async def assert_system_invariants(schema) -> None:
    columns = {r["column_name"] for r in await schema.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = 'state_transitions'",
        schema.name)}
    machine = "machine" if "machine" in columns else "entity_type"
    rows = await schema.fetch(f"SELECT {machine} AS machine, entity_id, from_state, to_state, reason"
                              " FROM state_transitions ORDER BY transition_id")
    problems = transition_problems(rows)
    assert not problems, "I5 violated:\n" + "\n".join(problems)
