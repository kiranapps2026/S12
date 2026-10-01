# B5 agent guide: M19–M21 (crash recovery, real processes, journeys and architecture)

Read `../README.md` first: precedence, the ten rules, the module map and the names the tests patch. This file
covers what is specific to B5. Each milestone has its own file in `milestones/`.

## Entry conditions (all must hold before the first B5 commit)

- [ ] `docs/gates/s12_milestones.json`: M0–M18 are `green` or `reviewed`.
- [ ] `python tools/owner_certify_s12.py --milestone M18` exits 0 on the current head (B4 complete: 135/135, 12/12
      sabotage).
- [ ] `--selftest` all OK; `git diff origin/s12-work -- tests_golden docs/gates/*.sha256` empty; S12-FRZ PASS.
- [ ] **Open rulings.** CONF-042, 043, 044, 046 and 047 (M19) and CONF-045 (M20) are `open` in `S12_RECORDS.md`.
      S12-REC fails for M19/M20 until the owner rules them. Implement their proposal text only after the ruling.
      Before that, build and test, but report the milestone as blocked, never as reached.
- [ ] Red first: the B5 files fail on the current head for the right reason. Six M21 cases and one M20 case are
      standing rules that already pass (see M21 and M20 files). That is expected, not a reason to stop.

## What B5 builds on

Everything in B3 and B4. B5 adds **seams** to the existing loop (`faults`, `metrics`) and a **second entry point**
(`recover_execution`). It does not add a new loop. If recovery seems to need a different loop, STOP: §13 step 4 says
the loop continues from the first PENDING step.

## Order and targets

| Milestone | Golden file | Sabotage | New modules | Changed modules (additive) | Target |
|---|---|---|---|---|---|
| [M19](milestones/M19_recovery.md) | `M19_recovery.py` | 4 | `s12_execute/fault_injection.py`, `s12_execute/recovery.py`, migration `017_recovery_candidates.sql` | `loop.py` (+`faults`, `recover_execution`, resume at the next attempt), `leases.py` (+`skip_locked`, `expire_lapsed`), `reconciliation.py` (+`find_open`), `execution_events.py` (+`layer_verdicts`), `attempts.py` (+`faults`), `probe.py` (+`faults=`, `metrics=`), `settings.py` (+`recovery_sweep_interval_s`) | all pass, 4/4 caught, the full invariant checker I1–I16 green |
| [M20](milestones/M20_multiprocess.md) | `M20_multiprocess.py` | 4 (2 code, 2 SQL) | none expected | fixes only, where a real-process case proves a defect | all pass, 4/4, **5 consecutive runs** (M20 is in the certifier's CONCURRENCY set) |
| [M21](milestones/M21_journeys.md) ★ | `M21_journeys.py` | 2 | `contracts/metrics.py` | `loop.py` (+`metrics`), `probe.py` (counts probes) | all pass, 2/2, then the owner's final review |

Batch target: **68/68 B5 cases** (the MANIFEST count, after the second review pass; confirm with
`pytest --collect-only -q`), **10/10 sabotage**, every M01–M18 golden case and every M10–M18 sabotage still green and
caught (51/51 in the B5 review).

## Files B5 may create or change

```text
src/engine/stages/s12_execute/fault_injection.py         M19  new
src/engine/stages/s12_execute/recovery.py                M19  new
src/adapters/postgres/migrations/017_recovery_candidates.sql  M19  new (never edit 001–016)
src/engine/stages/s12_execute/loop.py                    M19, M21  additive
src/engine/stages/s12_execute/attempts.py                M19  faults seam
src/engine/stages/s12_execute/settings.py                M19  recovery_sweep_interval_s
src/engine/stages/s13_reconciliation/probe.py            M19, M21  faults=, metrics=
src/adapters/postgres/leases.py                          M19  skip_locked, expire_lapsed
src/adapters/postgres/reconciliation.py                  M19  find_open
src/adapters/postgres/execution_events.py                M19  layer_verdicts
src/contracts/metrics.py                                 M21  new
any earlier S12 (non-frozen) file                         M20  only for a defect a real-process case proves
tests_agent/**                                            any
```

**Never touch** `tests_golden/fixtures/runtime_process.py`. It is the owner's real Worker Runtime process and the
M20 cases depend on it exactly.

## Conflict avoidance (B5-specific)

| Risk | Rule |
|---|---|
| Two owners of one run | Takeover only through `PostgresLeaseManager.acquire(..., skip_locked=True)` with the ownership compare-and-set and a **larger** token. Never expire a live lease (sabotage `M19_takeover_steals`) |
| Sweeper takes its own run | Skip executions whose `runtime_instance_id` is the sweeper's own (CONF-033; sabotage `M19_sweeper_takes_its_own`) |
| Recovery re-executes | The ledger first, then the dispatch marker, then the probe. Never a blind call (sabotages `M19_ledger_blind_recovery`, `M19_marker_never_written`, `M20_probe_blind`) |
| Cross-tenant discovery | Only through `s12_recovery_candidates` (SECURITY DEFINER, ids only, writes nothing). Every claim then runs tenant-scoped under RLS. Never disable or reset RLS |
| `SimulatedCrash` swallowed | It is a `BaseException`. No `except BaseException` / bare `except:` on the loop path may catch it, except to release resources and re-raise. `RecoverySweeper.sweep` isolates `Exception` per run and never catches `SimulatedCrash` |
| Fault injection switch | No `os.environ` / `getenv` in `fault_injection.py`. It is inert unless a test injects a `FaultInjector` through `LoopDeps.faults` |
| Portability (§21 S9) | `subprocess` + `Popen.kill()`, `pathlib`, `sys.executable`. No `os.fork`, `signal.SIGKILL`, `/tmp/...` or other fixed paths in the engine |
| Hosts and filesystem (M21 scan) | No `localhost`, `127.0.0.1`, `postgres://`, `http(s)://`, `:5432`, builtin `open(`, `.write_text(`, `pickle`, `shelve`, or the word `laya` (any case) in any S12 source, **comments and docstrings included** |
| Metrics name collision | The timing method is `timing`, never `observe` (`.observe(` is reserved for verification, M15 scan) |

## Milestone end

As in `S12_AUTOPILOT.md`:

1. Full certifier for the milestone.
2. Scope check with `git diff --name-only`.
3. Log line, then push `origin s12-work`.

M19 and M20 are ⚙: send the report and continue, unless S12-REC is red on open CONFs. In that case STOP with the ids.
**M21 is ★:** STOP with the milestone report and wait for the owner. The certification report (§20), the deferred
register and the tag `s12-s15-certified` are owner work. Never create a tag.
