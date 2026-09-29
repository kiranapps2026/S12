# Proposal — S0.1 activation (pause) check — ruling id: PENDING (owner to assign)

Not a pinned document. Text for the owner to number, replacing the "R-P" placeholder
(R-P is already the vocabulary ruling).

**R-?? S0.1 activation check.** Immediately after S0 creates the ExecutionContext, and
before any other work (including S8's dependency reads), the kernel reads the tenant's
and the workspace's `paused_until` and `scheduled_activation_at` and the database clock
`now`. The request is DENIED at S0 when:

| condition | reason (exact) |
|---|---|
| tenant `paused_until` > now | `tenant_paused` |
| workspace `paused_until` > now | `workspace_paused` |
| tenant or workspace `scheduled_activation_at` > now | `not_yet_active` |
| the state cannot be read (missing row, database error) | `activation_state_unavailable` |

The first matching row wins. Time is the database clock, never the caller's. Fail
closed. The check also runs on every reply to a waiting confirmation (a paused tenant
completes no pending run). No S1–S11 stage produces output for a denied request.

Implemented in `src/engine/stages/s0_entry/activation.py`; reader port
`src/contracts/activation.py`; PostgreSQL adapter `src/adapters/postgres/activation.py`.
