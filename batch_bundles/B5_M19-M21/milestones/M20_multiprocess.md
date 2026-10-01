# M20: real Worker Runtime processes, two runtimes, tenant isolation (gate commit L, part 2) ⚙

| | |
|---|---|
| Gate | §15.2 (at least 3 real subprocess kills), suite 14, suite 17 (two runtimes on one database), suite 18 (tenant isolation, C34), §21 S4 (`FOR UPDATE SKIP LOCKED`), §21 S9 (portability) |
| Rulings | CONF-033, CONF-042/046 (M19). **Open:** CONF-045 (lease renewal during a step) |
| Golden | `tests_golden/s12/M20_multiprocess.py` (8 functions). It runs **5 consecutive times** (the certifier's CONCURRENCY set) |
| Sabotage | `M20_probe_blind` (code; also reaches the subprocesses), `M20_skip_locked_ignored` (code), `M20_rls_not_forced.sql`, `M20_rls_write_unchecked.sql` |
| Process fixture | `tests_golden/fixtures/runtime_process.py` (owner fixture, **never edit**) |

## What M20 is

M20 adds **no new module** in the reference. It proves that M19's recovery works across real processes and that the
schema isolates tenants. Expect to fix defects that only real processes reveal, in files you already own. Do not
build new structure.

**The fixture's contract with `src/`:**

- It builds the runtime with M17's golden helper `_dl_deps` (guard, verification, consolidation, dead letters), then
  `dataclasses.replace(deps, runtime_instance_id=...)`. So `LoopDeps` must stay a dataclass with that field name.
- It calls `run_execution(deps, tenant, execution)`, or `RecoverySweeper(database, deps).run(stop, interval_s=0.2)`.
- It connects as the non-superuser role `golden_app`, so RLS applies exactly as in production.
- `--hang` freezes the whole process with a **blocking** sleep, at `call`, `after_call` or `observe`. The test then
  kills it with `Popen.kill()`.
- It applies `GOLDEN_SABOTAGE` itself, so code sabotage reaches the killed and restarted processes.

## Cases and what each needs from the code

| Case | Needs |
|---|---|
| kill a runtime mid-step, recover in a new process (3 kills: before the side effect, after it, while verifying) | M19's in-flight rule. Before → NOT_EXECUTED, then a retry. After → EXECUTED_SUCCESS, no second call. While verifying → a VERIFICATION episode. Each side effect exactly once in the shared file |
| two runtimes share four runs; one is killed holding a run, the other takes it over | one owner per run at a time (the lease log never shows two leases at once); the sweeper of the survivor takes over after the TTL |
| two sweeping processes claim six orphaned runs exactly once each | `acquire(..., skip_locked=True)` under `FOR UPDATE SKIP LOCKED`; candidates from migration 017 |
| a sweeper skips an execution another sweeper holds, then takes it when free | SKIP LOCKED, never waiting on the row (sabotage `M20_skip_locked_ignored`) |
| tenant A can neither read nor change tenant B's rows | runs, steps, reservations, leases, dead letters, events, episodes, ownership, plans: 0 rows, `UPDATE 0`, `FencedOut`, `get`/`load` → `None` |
| tenant A can neither forge rows for B nor claim B's runs | RLS policies with `WITH CHECK` on writes (sabotage `M20_rls_write_unchecked.sql`) |
| every S12 table forces RLS on its tenant | for `S12_TABLES` plus `execution_events` and `idempotency_ledger`: `ENABLE` and `FORCE ROW LEVEL SECURITY`, a policy, and a `NOT NULL tenant_id` (sabotage `M20_rls_not_forced.sql`) |
| the engine uses no POSIX-only process APIs or fixed paths (a standing rule that already passes) | none of `os.fork(`, `signal.SIGTERM`, `signal.SIGKILL`, `signal.signal(`, `os.kill(`, `'/tmp`, `"/tmp`, `os.setsid`, `preexec_fn` in any S12 file |

## Conditions to keep

- A new process means a new `runtime_instance_id` (§13). The first process runs as the **admitting** runtime. The
  loop correctly refuses to take over a run another runtime owns (CONF-033).
- No step executes twice across processes: the ledger, the dispatch marker and the probe decide, never a blind
  re-call (sabotage `M20_probe_blind`: a probe that always answers NOT_EXECUTED must turn the case red).
- Never add an "admin" connection, `SET ROLE`, `row_security = off`, or a reset of `app.current_tenant` to make an
  isolation case pass. If a cross-tenant read seems needed, it goes through `s12_recovery_candidates` (ids only) or
  it is a STOP.
- Lease renewal during a long step (CONF-045) is **not pinned**. Do not build it in M20 unless the owner rules
  CONF-045 and assigns it.

## Traps

- A "hang" written with `asyncio.sleep` ends at the step deadline, so the process finishes before the kill and the
  case measures nothing. The fixture uses a blocking sleep. Do not "fix" the engine to work around a deadline.
- Flaky passes: M20 must pass 5 runs in a row. A race that passes 4 of 5 is a defect (usually a missing row lock or
  a non-SKIP-LOCKED select). It is never a flake to retry.

## Done when

- [ ] Every case of `M20_multiprocess.py` passes, 5 consecutive runs (`owner_certify_s12.py --milestone M20` runs
      the C-row).
- [ ] M01–M19 green; sabotage 4/4 caught (the SQL ones as assertions, not errors).
- [ ] CONF-045 ruled, or listed as the blocker in the report.
