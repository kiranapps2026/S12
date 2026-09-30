# Proposal — R-AA: S0.1 activation (pause) check

**Status: proposed id, owner ratifies.** Not a pinned document. R-A … R-Z are all used
(R-W is named only in the runbook header) and R-P is already the vocabulary ruling, so the
next free id is **R-AA**. If the owner prefers another id, replace `R-AA` in
`src/engine/stages/s0_entry/activation.py` and `docs/proposals/` (nothing else refers to it).

## Text to insert into `docs/gates/S0_S11_RUNBOOK.md`, Part 2, after R-Z (owner applies)

> R-AA. **S0.1 activation check.** Immediately after S0 creates the ExecutionContext, and
> before any other work (including S8's dependency reads and the run scope), the kernel
> reads the tenant's and the workspace's `paused_until` and `scheduled_activation_at` and
> the database clock `now`. The request is DENIED at S0 when:
>
> | condition | reason (exact) |
> |---|---|
> | tenant `paused_until` > now | `tenant_paused` |
> | workspace `paused_until` > now | `workspace_paused` |
> | tenant or workspace `scheduled_activation_at` > now | `not_yet_active` |
> | the state cannot be read (missing row, database error) | `activation_state_unavailable` |
>
> The first matching row wins; `paused_until == now` is no longer paused. Time is the
> database clock, never the caller's. Fail closed. The check also runs on every reply to a
> waiting confirmation (a paused tenant completes no pending run). No S1–S11 stage produces
> output for a denied request.

Also in the runbook header line that lists the rulings, add `R-AA (S0.1 activation check)`.

## Where it is implemented and tested

- `src/engine/stages/s0_entry/activation.py` (rule), `src/contracts/activation.py` (reader
  port), `src/adapters/postgres/activation.py` (database clock), runner call in
  `src/engine/control_plane/pipeline_state_runner.py`.
- `tests/integration/test_activation_check.py` (reason table, no output after S0, denied
  before the scope is read, reply blocked, fail closed) and `tests_postgres/` (adapter and
  HTTP flows).
