"""``assert_system_invariants(schema)`` — the invariant checker entry point (owner fixture, plan §5.4).

It grows milestone by milestone. Active now:
  * I5 (M2): every row of the transition log is legal per gate Appendix A: a creation row (``from_state`` NULL, or
    ``none`` for an episode) goes to the machine's initial state with its creation reason; every other row is an
    Appendix A edge whose reason is allowed on that edge.
  * I9 (M6): every persisted plan's canonical digest equals its ``plan_hash``.
  * I7 (M7): no ``active`` lease for a terminal run; no lease left ``expired`` and later became ``active`` (log).
  * I8 (M7): fence tokens strictly increase per worker and per execution, in issue order (the lease log rows that issue
    a token carry it in ``fence_token``); usable leases per
    worker (``active`` and ``expires_at > now()``) never exceed ``capacity`` and equal ``current_load`` once stale leases
    have been expired (checked on the stored rows: ``active`` leases per worker equal ``current_load`` and <= capacity).
  * I1 (M9): per tenant and budget period, the cost of its reserved + locked + committed reservations never exceeds
    ``budget_pool``.
  * I2 (M9): no reservation is ``reserved`` for a terminal run; a ``locked`` one for a terminal run only on a
    ``dead_letter`` step (D4).
  * I12 (M9, non-dead-letter parts): a non-terminal step has at most one live reservation (reserved, locked,
    committed); a ``completed`` step exactly one, ``committed``; a ``failed``, ``cancelled`` or ``skipped`` step none.
  * I10 (M6): every step's ``resolved_binding_id``, ``effective_risk`` and ``effective_mutation`` equal that step's binding
    in the persisted ``frozen_bindings`` (through ``step_binding_index``).
  * I16 (M12): every ``ProviderCalled`` ledger event follows the ``step_attempt`` event of the same attempt.
  * I6 (M13): a step with an episode passed through ``pending_probe``; every ``timeout`` is followed by
    ``pending_probe``. C13 (M13): when a run moved to ``reconciling``, every other step was terminal.
  * I14 (M14): no ``ProviderCalled`` event after the run's ``authorization_revoked`` event; a terminal run with that
    event ended ``cancelled`` or ``dead_letter``.
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


async def plan_problems(schema) -> list[str]:
    import json

    from contracts import codec
    from contracts.frozen_binding import FrozenBindingIdentity
    from contracts.plan_hash import canonical_plan_digest
    from contracts.stage_outputs import Plan
    problems = []
    for p in await schema.fetch("SELECT execution_id, plan_hash, canonical_plan, frozen_bindings, step_binding_index"
                                " FROM execution_plans"):
        plan = codec.decode(Plan, json.loads(p["canonical_plan"]))
        if canonical_plan_digest(plan) != p["plan_hash"]:
            problems.append(f"I9 {p['execution_id']}: stored plan digest differs from plan_hash")
        bindings = codec.decode(tuple[FrozenBindingIdentity, ...], json.loads(p["frozen_bindings"]))
        index = json.loads(p["step_binding_index"])
        for s in await schema.fetch("SELECT plan_step_id, resolved_binding_id, effective_risk, effective_mutation"
                                    " FROM execution_steps WHERE execution_id = $1", p["execution_id"]):
            if s["plan_step_id"] not in index:
                problems.append(f"I10 {p['execution_id']}/{s['plan_step_id']}: step not in step_binding_index")
                continue
            b = bindings[index[s["plan_step_id"]]]
            if (s["resolved_binding_id"], s["effective_risk"], s["effective_mutation"]) != \
                    (b.binding_id, b.effective_risk, b.effective_mutation):
                problems.append(f"I10 {p['execution_id']}/{s['plan_step_id']}: step differs from its frozen binding")
    return problems


async def lease_problems(schema) -> list[str]:
    tables = {r["t"] for r in await schema.fetch(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = $1", schema.name)}
    if "worker_leases" not in tables:
        return []
    problems = []
    for r in await schema.fetch(
            "SELECT l.lease_id FROM worker_leases l JOIN execution_runs e ON e.execution_id = l.execution_id"
            " WHERE l.status = 'active' AND e.status IN ('completed','partial','failed','cancelled','dead_letter')"):
        problems.append(f"I7 lease {r['lease_id']}: active for a terminal run")
    for r in await schema.fetch(
            "SELECT a.entity_id FROM state_transitions a JOIN state_transitions b ON b.entity_id = a.entity_id"
            " AND b.entity_type = 'lease' AND b.transition_id > a.transition_id AND b.to_state = 'active'"
            " WHERE a.entity_type = 'lease' AND a.to_state = 'expired'"):
        problems.append(f"I7 lease {r['entity_id']}: reactivated after expiry")
    # I8 tokens: the lease log rows that issue a token (None -> active, active -> active) carry it in fence_token and
    # are numbered (transition_id) inside the locked acquisition, so their order is the issue order.
    issued = await schema.fetch(
        "SELECT t.transition_id, t.fence_token, l.worker_id, l.execution_id, l.lease_id FROM state_transitions t"
        " JOIN worker_leases l ON l.lease_id = t.entity_id WHERE t.entity_type = 'lease' AND t.to_state = 'active'"
        " ORDER BY t.transition_id")
    for r in issued:
        if r["fence_token"] is None:
            problems.append(f"I8 lease {r['lease_id']}: token-issuing log row without fence_token")
    for key in ("worker_id", "execution_id"):
        last: dict = {}
        for r in issued:
            k = r[key]
            if k is None or r["fence_token"] is None:
                continue
            if k in last and r["fence_token"] <= last[k]:
                problems.append(f"I8 {key} {k}: fence token {r['fence_token']} not above {last[k]}")
            last[k] = r["fence_token"]
    for r in await schema.fetch(
            "SELECT w.worker_id, w.capacity, w.current_load,"
            "       (SELECT count(*) FROM worker_leases l WHERE l.worker_id = w.worker_id AND l.status = 'active') AS n"
            "  FROM workers w"):
        if r["n"] > r["capacity"] or r["n"] != r["current_load"]:
            problems.append(f"I8 worker {r['worker_id']}: {r['n']} active leases, current_load {r['current_load']},"
                            f" capacity {r['capacity']}")
    return problems


async def budget_problems(schema) -> list[str]:
    from adapters.postgres.budget import PERIOD_START_SQL
    problems = []
    for r in await schema.fetch(
            "SELECT t.tenant_id, t.budget_pool, COALESCE((SELECT SUM(r.cost) FROM budget_reservations r"
            " WHERE r.tenant_id = t.tenant_id AND r.status IN ('reserved','locked','committed')"
            f" AND r.created_at >= {PERIOD_START_SQL}), 0) AS used FROM tenants t"):
        if r["used"] > r["budget_pool"]:
            problems.append(f"I1 tenant {r['tenant_id']}: {r['used']} reserved/locked/committed > pool {r['budget_pool']}")
    terminal = "('completed','partial','failed','cancelled','dead_letter')"
    for r in await schema.fetch(
            "SELECT b.reservation_id, b.status, s.status AS step FROM budget_reservations b"
            " JOIN execution_runs e ON e.execution_id = b.execution_id"
            " LEFT JOIN execution_steps s ON s.step_id = b.step_id"
            f" WHERE e.status IN {terminal} AND b.status IN ('reserved','locked')"):
        if r["status"] == "reserved" or r["step"] != "dead_letter":
            problems.append(f"I2 reservation {r['reservation_id']}: {r['status']} for a terminal run (step {r['step']})")
    for r in await schema.fetch(
            "SELECT s.step_id, s.status, count(b.reservation_id) FILTER (WHERE b.status IN ('reserved','locked','committed'))"
            " AS live, count(b.reservation_id) FILTER (WHERE b.status = 'committed') AS committed"
            " FROM execution_steps s LEFT JOIN budget_reservations b ON b.step_id = s.step_id GROUP BY s.step_id, s.status"):
        status, live, committed = r["status"], r["live"], r["committed"]
        if status == "completed" and not (live == 1 and committed == 1):
            problems.append(f"I12 step {r['step_id']}: completed with {live} live / {committed} committed reservations")
        elif status in ("failed", "cancelled", "skipped") and live:
            problems.append(f"I12 step {r['step_id']}: {status} with {live} live reservation(s)")
        elif status in ("pending", "running", "timeout", "pending_probe") and live > 1:
            problems.append(f"I12 step {r['step_id']}: {status} with {live} live reservations")
    return problems


async def revocation_problems(schema) -> list[str]:
    tables = {r["t"] for r in await schema.fetch(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = $1", schema.name)}
    if "execution_events" not in tables:
        return []
    problems = [f"I14 {r['execution_id']}: ProviderCalled after authorization_revoked" for r in await schema.fetch(
        "SELECT DISTINCT c.execution_id FROM execution_events c JOIN execution_events r ON r.execution_id ="
        " c.execution_id AND r.event_type = 'authorization_revoked' AND r.seq < c.seq WHERE c.event_type ="
        " 'ProviderCalled'")]
    problems += [f"I14 {r['execution_id']}: revoked run ended {r['status']}" for r in await schema.fetch(
        "SELECT DISTINCT e.execution_id, e.status FROM execution_runs e JOIN execution_events r ON r.execution_id ="
        " e.execution_id AND r.event_type = 'authorization_revoked' WHERE e.status IN ('completed', 'partial',"
        " 'failed')")]
    return problems


async def dispatch_problems(schema) -> list[str]:
    """I16 (M12): every ``ProviderCalled`` event of an attempt follows a ``step_attempt`` event of that attempt, which
    is written only after the attempt's dispatch marker committed (C24, C35)."""
    tables = {r["t"] for r in await schema.fetch(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = $1", schema.name)}
    if "execution_events" not in tables:
        return []
    return [f"I16 {r['execution_id']} {r['attempt_id']}: ProviderCalled without an earlier step_attempt"
            for r in await schema.fetch(
                "SELECT c.execution_id, c.attempt_id FROM execution_events c WHERE c.event_type = 'ProviderCalled'"
                " AND NOT EXISTS (SELECT 1 FROM execution_events a WHERE a.event_type = 'step_attempt'"
                " AND a.execution_id = c.execution_id AND a.step_id = c.step_id AND a.attempt_id = c.attempt_id"
                " AND a.seq < c.seq)")]


TERMINAL_STEP = ("completed", "failed", "cancelled", "skipped", "dead_letter", "partial")


async def uncertainty_problems(schema) -> list[str]:
    problems = []
    rows = await schema.fetch("SELECT transition_id, entity_type, entity_id, execution_id, to_state FROM"
                              " state_transitions ORDER BY transition_id")
    history: dict = {}
    for r in rows:
        if r["entity_type"] == "step":
            history.setdefault(r["entity_id"], []).append(r["to_state"])
    for step_id, states in history.items():
        for i, state in enumerate(states):
            if state == "timeout" and i + 1 < len(states) and states[i + 1] != "pending_probe":
                problems.append(f"I6 step {step_id}: timeout not followed by pending_probe")
    tables = {r["t"] for r in await schema.fetch(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = $1", schema.name)}
    if "step_reconciliations" in tables:
        for r in await schema.fetch("SELECT DISTINCT step_id FROM step_reconciliations"):
            if "pending_probe" not in history.get(r["step_id"], []):
                problems.append(f"I6 step {r['step_id']}: an episode without pending_probe")
    step_state: dict = {}
    step_run = {r["step_id"]: r["execution_id"] for r in await schema.fetch(
        "SELECT step_id, execution_id FROM execution_steps")}
    for r in rows:
        if r["entity_type"] == "step":
            step_state[r["entity_id"]] = r["to_state"]
        elif r["entity_type"] == "run" and r["to_state"] == "reconciling":
            open_steps = [s for s, st in step_state.items() if step_run.get(s) == r["entity_id"]
                          and st not in TERMINAL_STEP and st != "pending_probe"]
            if open_steps:
                problems.append(f"C13 run {r['entity_id']}: reconciling while {open_steps} not terminal")
    return problems


async def assert_system_invariants(schema) -> None:
    columns = {r["column_name"] for r in await schema.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = 'state_transitions'",
        schema.name)}
    machine = "machine" if "machine" in columns else "entity_type"
    rows = await schema.fetch(f"SELECT {machine} AS machine, entity_id, from_state, to_state, reason"
                              " FROM state_transitions ORDER BY transition_id")
    problems = ([f"I5 {p}" for p in transition_problems(rows)] + await plan_problems(schema)
                + await lease_problems(schema) + await budget_problems(schema) + await dispatch_problems(schema)
                + await uncertainty_problems(schema) + await revocation_problems(schema))
    assert not problems, "invariants violated:\n" + "\n".join(problems)
