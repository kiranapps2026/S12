# B5 golden review (M19–M21)

2026-09-30, drafted on the owner's instruction "draft B5". **Self-review**: the drafter will also implement B5, so this
does not replace an independent review. It records how every file was validated and what needs a ruling before
pinning. As for B3 and B4, each case was checked with one question: which wrong implementation would still pass?

## Validation (every file)

Each file was run three ways:
- red on `s12-work` (for the right reason: missing modules, not test errors);
- green on a scratch reference implementation (a detached worktree in the session scratchpad; nothing of it is in `src/`);
- under every sabotage patch (each must turn an assertion red, never a setup error).

Results on the reference:
- All 22 golden files M01–M21 pass together: 857 cases (490 for M01–M09, since M08 gained one with CONF-032; 184 for M10–M14; 135 for M15–M18; 48 for B5), 950 with `tests_agent`. The frozen `tests/` suite passes (836).
- The three B5 files passed 10 consecutive runs (48 / 48 each time, real subprocesses included).
- Every M10–M18 sabotage patch is still caught (51 / 51) after the loop gained the fault, recovery and metrics seams.

M01–M09 stay green on `s12-work` with invariant I15 added (583 with `tests_agent`).

| File | Cases | Red on `s12-work` | Reference | Sabotage caught |
|---|---|---|---|---|
| `s12/M19_recovery.py` | 21 | 20 fail, 1 passes (invariants of an unfinished schema) | 21 / 21 | 4 / 4 |
| `s12/M20_multiprocess.py` | 9 | 8 fail, 1 passes (the §21 S9 portability scan, a standing rule) | 9 / 9 | 3 / 3 |
| `s12/M21_journeys.py` | 18 | 12 fail, 6 pass | 18 / 18 | 2 / 2 |

The six M21 cases that already pass are standing rules that must hold at every milestone:
- four architecture scans: no re-resolution imports, no direct adapter call, no unfenced SQL write, and no filesystem / hosts / Laya;
- the S1 settings object (built in M2);
- the invariants of an unfinished schema.

Each architecture scan was checked against real code: it found the prototype guard's direct adapter call, a builtin `open(` versus a method named `open`, and `FOR UPDATE SKIP LOCKED` versus an UPDATE statement, so none is vacuous. The two false positives were fixed.

Mutation checks by hand on the reference, beyond the sabotage patches (each turned a case red):
- removing the no-marker branch, the episode continuation, the "all layers passed" branch, or `expire_lapsed` from the recovery rule;
- the last one survived until the two-worker case was added.

Fixture changes with B5:
- `invariants.py` gains I15 (every S12 row names its run's tenant);
- `fixtures/runtime_process.py` is a real Worker Runtime process with a `FileProvider`: a side-effect ledger in an append-only file shared by all processes;
- the runtime process applies `GOLDEN_SABOTAGE` too, so a code sabotage reaches the processes it kills and restarts. Without it, `M20_probe_blind` survived.

## What each file pins

| File | Cases |
|---|---|
| M19 | The ten points of §15.2, by name and in order:<br>• inert by default; an unknown name is refused<br>• `SimulatedCrash` is a BaseException that no `except Exception` swallows<br>• every point is wired, and nothing in the product raises a crash<br>A crash at each of the ten points (parametrized) recovers in a fresh runtime to COMPLETED with one side effect per key:<br>• before any reservation: fresh<br>• after reserve: the RESERVED reservation is reused<br>• after lock: NOT_EXECUTED with no probe; a new reservation only after it<br>• after the marker: probe, then attempt 2<br>• Crash A: the probe finds the execution, and it is never called again<br>• Crash B / C: a VERIFICATION episode, no probe<br>• all layers passed: a LEDGER_HIT episode<br>• after the commit: continue with the next step<br>• during the probe: the same episode is continued (inconclusive, then resolved)<br>Other recovery cases:<br>• the lapsed lease is expired and the new token is larger<br>• a takeover on another worker still expires the crashed lease (C26)<br>• a cached failure: FAILED, no probe, no call<br>• an expired record: probed, never blindly called<br>• a plan tampered after admission: DEAD_LETTER `plan_integrity`, no new step<br>• recovery after a revocation: the in-flight step is resolved by the probe, then everything is cancelled `kill_switch_engaged`, never resumed<br>• the sweeper takes only orphaned runs of other runtimes (never a usable lease, never its own, never a terminal run; discovery writes nothing)<br>• a run whose owner is alive is not recovered and nothing is written |
| M20 | Three real subprocess kills (`Popen.kill()`), each recovered by a new process:<br>• before the side effect: NOT_EXECUTED, then a retry<br>• after it: EXECUTED_SUCCESS, no second call<br>• while verifying: a VERIFICATION episode<br>Two runtime processes share four runs; one is killed holding a run, and the other takes it over. In both cases every step's side effect happens exactly once and the lease log never shows two leases at once. Two sweeping processes claim six orphaned runs exactly once each. In process, a sweeper skips an ownership row another sweeper holds (SKIP LOCKED), then takes it when free. Tenant A cannot read or change tenant B's runs, steps, reservations, leases, dead letters, events, episodes, ownership or plans (0 rows, `UPDATE 0`, FencedOut, `get` / `load` → None). Every S12 table forces RLS with a policy and a NOT NULL `tenant_id`. No POSIX-only process API or fixed path in the engine. |
| M21 | The eight S0→S15 journeys: happy path (dependency order), retry then success, timeout resolved by the probe, timeout not executed then retry, verification mismatch leading to PARTIAL (with a data dead letter), budget exhaustion mid-plan (with the envelope's completed step), inconclusive probe leading to DEAD_LETTER (with metrics), and crash mid-plan then resume. Each starts from a state the real S0–S11 pipeline certified, runs under an armed trap that fails if S5 resolves again after S11, ends in the S15 envelope, and checks the invariants. Metrics: fenced-out and the no-op default. The per-step baseline is recorded over 210 steps. The architecture suite (suite 2 + card), fault injection without an environment switch, and settings validation. |

## Performance baseline (record only, gate §21)

Reference implementation, zero-delay mock, Linux 6.18, Python 3.11, PostgreSQL 16 on the same host:
- p50 17.9 ms, p95 23.8 ms per step over 210 steps (admission through settlement, including verification).

The certification run on `s12-work` replaces these numbers; the certifier OS goes into the report (§21 S9).

## Defects caught while drafting

| Where | Finding | Fix |
|---|---|---|
| M20 fixture | a "hang" awaited `asyncio.sleep`, so the step deadline (0.1 s) ended it: the process continued and finished its runs before the kill, and the two-runtime case measured nothing | a blocking sleep freezes the whole process, as a hung one; found from the transition log, not guessed |
| M20 fixture | code sabotage patches did not reach the subprocesses, so `M20_probe_blind` survived | the runtime process applies `GOLDEN_SABOTAGE` |
| M20 draft | the first process ran under another runtime id, and the loop correctly refused to take over (CONF-033) | it runs as the admitting runtime |
| M19 draft | removing the sweeper's lease expiry survived: with one worker the acquisition itself expires the crashed lease | two-worker case (C26: the sweeper observes it first) |
| M21 draft | the re-resolution trap was armed before the fixture certified S0–S11 (which runs S5) | armed after certification |
| M21 draft | the trap's teardown assertion turned a sabotage into ERRORs, which the certifier refuses | the trap fails the journey where the call happens |
| M21 draft | scans matched `episodes.open(` as a builtin `open(`, and the prototype guard as a direct adapter call | the regex excludes methods and definitions; the prototype guard (CONF-011) is a guard |
| reference | the in-flight rule read verification events through a private database handle | `PostgresExecutionEvents.layer_verdicts` |
| reference | the metrics method `observe` collided with M15's scan for provider observations | renamed `timing` |

## Rulings needed (recorded in S12_RECORDS.md)

| ID | Question | Proposal |
|---|---|---|
| CONF-042 | RLS (forced even on `tenants`) hides other tenants' orphaned runs from a sweeper | `s12_recovery_candidates`: `SECURITY DEFINER`, ids only, writes nothing; claims stay under RLS |
| CONF-043 | the in-flight step of a tampered plan: the probe would rebuild its call from an untrusted plan | never probed or re-run: DEAD_LETTER (budget LOCKED) with a PROBE dead letter for an operator |
| CONF-044 | checkpoints are required (§8 steps 7, 11) but nothing reads them (§13: the database is the truth) | written as a hint; not pinned; recovery never depends on them |
| CONF-045 | lease renewal at TTL/3 during a step has no card or golden | renew every `lease_renewal_interval_s`; `LeaseLost` stops the step; pinned when assigned |

## Coverage of the gate's suites across the golden files

| Suite (§16) | Golden cases |
|---|---|
| 1 State machines | M03, M04 |
| 2 Architecture | M04 (bare literals), M10 (§21 S3), M12 (dispatch, logs), M13 / M15 (S13 package), M19 (fault points), M21 (resolver, S8, adapter calls, fenced writes, filesystem, hosts, Laya) |
| 3 S12 entry | M06, M08a |
| 4 Budget | M09, M12 (I-3), M13 (D4) |
| 5 Leases and fencing | M07, M12 (takeover, fenced out), M19 (expiry, larger token) |
| 6 Idempotency (non-crash / crash) | M11 / M19 (Crash A, B, C; cached failure; expired record) |
| 7 Retry | M11 |
| 8 UNKNOWN and probe | M13 |
| 9 Verification | M15 |
| 10 Consolidation | M16 |
| 11 Dead letter | M17 |
| 12 S15 | M18 |
| 13 Confirmation store | M05 |
| 14 Crash recovery | M19 (every point), M20 (3 subprocess kills) |
| 15 Journeys | M21 |
| 16, 16a, 16b Terminal reasons, cancellation, revalidation | M12, M14, M16, M19 (recovery after revocation) |
| 17 Two runtimes | M20 |
| 18 Tenant isolation | M20, I15 |
| 19 v9 rulings | M03–M04 (C24–C28), M08 (C30), M10 (C31, C32, C37), M11 / M19 (C35), M06 (C36) |
| 20 Worker management | M08a |

## Known gaps, left as they are (reasons)

| Gap | Why it stays |
|---|---|
| Checkpoint rows (CONF-044), lease renewal during a step (CONF-045) | pending rulings; recovery is proven without them |
| RECONCILING runs in recovery | the in-line loop never enters RECONCILING (CONF-029); the sweeper selects them, but no golden produces one |
| Performance threshold | the gate asks for a recorded baseline only |
| The certification report (§20), the deferred register (§21) and the owner's tag | M21's exit is owner work (`owner_certify_s12.py`, `owner_verify_s12.ps1`), not a golden case |
| Linux only | §21 S9: the certifier records its OS; the tests use only portable APIs (`Popen.kill()`, `pathlib`, `sys.executable`) |

## Sabotage patches added

- M19: `M19_marker_never_written`, `M19_ledger_blind_recovery`, `M19_takeover_steals`, `M19_sweeper_takes_its_own`.
- M20: `M20_skip_locked_ignored`, `M20_rls_not_forced.sql`, `M20_probe_blind` (reaches the subprocesses).
- M21: `M21_resolver_after_s11`, `M21_probe_uncounted`.

## Interfaces B5 adds to earlier modules

- `LoopDeps.faults`, `LoopDeps.metrics`.
- `AttemptDeps.faults`.
- `probe.resolve_execution(..., faults=, metrics=)`.
- `PostgresLeaseManager.acquire(..., skip_locked=)` and `expire_lapsed`.
- `PostgresEpisodes.find_open`.
- `PostgresExecutionEvents.layer_verdicts`.
- The loop's steps resume at the attempt after their last dispatched one.
- Migration 017.

All are additive: M01–M18 pass unchanged on the reference.
