# S12 ruling pack: open records blocking M15, M19 and M20

Prepared 2026-10-01 at `s12-work` HEAD `2891cda`, for the owner. **This is not a record.** The records of truth are
still `S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md`. A ruling counts only when the owner writes it into the
row's Status and Ruling columns (see "How to apply" at the end). Every quote below was checked against the repository
at that commit. Line numbers are for that commit.

Code state assumed throughout: **M1–M9 are built. Nothing from M10 onwards is implemented on `s12-work`.** M10–M21
exist only as unpinned golden drafts (`tests_golden/s12/M10..M21`). The code under `batch_bundles/` is the drafter's
unreviewed scratch reference, not an implementation (`batch_bundles/B4_M15-M18/MANIFEST.md:7-9`).

## What blocks what (the certifier's view)

`owner_certify_s12.py` row S12-REC fails a milestone target when any of these exists up to that milestone:
- a CONF row with status `open`;
- a STOP row with status `open` or `ruled` (`tools/owner_certify_s12.py:141-154`).

DEF rows are not read by the certifier. The tracker blocks `reviewed` on an open DEF of that milestone
(`tools/s12_tracker.py:71-74`).

| Record | Milestone column | Status now | Blocks the certifier from | Recommendation in one line |
|---|---|---|---|---|
| CONF-005 | M15 | open | M15 onwards | Drop autonomy from layer selection for this phase; deferred register |
| CONF-042 | M19 | open | M19 onwards | Accept the SECURITY DEFINER discovery function, as amended by CONF-046 |
| CONF-043 | M19 | open | M19 onwards | Accept: never probe from a tampered plan; PROBE dead letter for an operator |
| CONF-044 | M19 | open | M19 onwards | Accept: checkpoint rows as a hint, plus one golden assertion that they are written |
| CONF-046 | M19 | open | M19 onwards | Accept: judge a run by its latest lease, grace of one TTL |
| CONF-047 | M19 | open | M19 onwards | Accept: NOT_EXECUTED in a RECONCILING run is cancelled `not_executed_no_retry` |
| CONF-045 | M20 | open | M20 onwards | Implement renewal **and pin it in M20** (two golden cases); do not leave it unpinned |
| CONF-008 | M6 | ruled | nothing | Keep fail-closed; write the deferred-register entry the ruling promised |
| CONF-020 | M8a | ruled | nothing | **Ruling has no implementation path.** Amend it to a DENY envelope in M18, with 2 golden cases |
| CONF-027 | M12 | ruled | nothing (M21 ★ review) | Assign the PostgreSQL sources to M21 now, while B5 is still unpinned |
| DEF-003 | S0–S11 | open | nothing mechanically | `wontfix` for this phase (RLS + role guard); fix it in the first post-S15 change-control batch |
| STOP-004 | M10 | open | **M10 onwards** | `applied` once B3 is pinned |
| STOP-005 | M10 | open | **M10 onwards** | `applied` (CONF-021..023 ruled in `150a668`) |
| *proposed CONF-048* | M19 | not recorded | — | New finding: M19 needs `StepState.UNKNOWN` outside the two allowed files; see the last page |

Only STOP-004 and STOP-005 block B3 (M10–M14). STOP-001 and STOP-002 also block it, but they are owner close-out rows.
They are covered in `S12_B3_PREFLIGHT.md`, not here.

---

## CONF-005 — no `AutonomyLevel` source for verification layer selection (blocks M15)

**Side A: the gate and specifications ask for autonomy.**
- `S12_S15_EXECUTION_GATE.md:1441-1443` (D6): "Tests use a mock LLM. If preflight item 6 shows no canonical
  AutonomyLevel source, STOP and report. Do not guess."
- `S12_S15_EXECUTION_GATE.md:1961` (suite 9): "Layer selection per mutation, risk and autonomy."
- `PIPELINE_STAGES.md:1114,1120` and `FINAL_ARCHITECTURE.md:2423,2430`:
  `def required_verification_layers(mutation, risk, autonomy)` … `if mutation == "IRREVERSIBLE" or autonomy == CONFIRM_ALL: layers.append("human")`.
- `DATA_CONTRACTS.md:2237-2241` defines the enum. Its only carrier is `IntentSpecification.autonomy_level`
  (`DATA_CONTRACTS.md:2282`; `FINAL_ARCHITECTURE.md:2192`).

**Side B: the code has no source.**
- `S12_M0_PREFLIGHT.md:57-59`: "**Not present in code.** No `AutonomyLevel` or 'autonomy' in `src/`, `tests/` or
  `tests_postgres/`."
- `IDENTITY_AND_TENANCY.md:394`: the per-grant `autonomy_level` "is **not** added to `CapabilityGrant`, which is a
  frozen S0–S11 contract".
- CONF-041 has already been ruled on this assumption (`S12_RECORDS.md:52`): "in this phase
  `required_verification_layers(mutation, risk)` without autonomy (the CONFIRM_ALL branch is inactive until CONF-005
  names a source)". Golden M15 pins this: `tests_golden/s12/M15_verification.py:14,23-24`.

**Options**

| | Option | Cost |
|---|---|---|
| A | Drop autonomy from layer selection for this phase. The CONFIRM_ALL → human branch is inactive. Record it in the deferred register (§21) as "autonomy source: post-S15". | Nothing to build. Golden M15 already matches it. One sentence in the certification report. |
| B | Name a source now, for example a tenant or workspace setting. That needs a new migration, an entry-time read persisted with the execution (as D1 does for verifiers) and new M06/M15 golden cases. | One new interface and a re-draft of M15. It is also **useless in this phase**: the human layer always returns UNKNOWN, which dead-letters the step (D4, `S12_S15_EXECUTION_GATE.md:1410-1412`). Every CONFIRM_ALL tenant's every step would end DEAD_LETTER. |
| C | Read `IntentSpecification.autonomy_level`. | `IntentSpecification` is a specification type only: no code builds or persists it. That makes this option B plus an S0–S11 contract change (§19.3). |

**Recommendation: A.**
- CONFIRM_ALL means "nothing without approval, every mutation" (`FINAL_ARCHITECTURE.md:2207-2214`). The certified S10
  confirmation gate already enforces that before execution.
- A post-execution human layer adds nothing while the layer has no HITL channel (D4).
- This is "do not guess" applied correctly: the owner names no source, and the branch stays off by ruling, not by a
  silent default.

Row edit: Status `ruled`. Ruling: `ruled 2026-10-01 (owner): option A — no AutonomyLevel source in this phase; layer
selection by mutation and risk (CONF-041, golden M15); deferred register entry "autonomy source"`.

---

## CONF-042 — row-level security hides other tenants' orphaned runs from the sweeper (blocks M19)

**Side A: the gate wants a cross-tenant sweep.** `S12_S15_EXECUTION_GATE.md:1740-1744` (§13): "The sweeper finds runs
in RUNNING or RECONCILING whose ownership lease is expired or absent … Select candidate runs with `FOR UPDATE SKIP
LOCKED`."

**Side B: forced RLS everywhere.**
- `001_s0_s11_schema.sql:146-153` forces RLS on `tenants` itself (`ALTER TABLE %I FORCE ROW LEVEL SECURITY`, with
  policy `tenant_id = current_setting('app.current_tenant', true)`).
- `015_s12_schema.sql:174-181` does the same for every S12 table.
- `src/app.py:56-59` refuses to start as a superuser or BYPASSRLS role.
- So a sweeper on the application role sees exactly one tenant, and cannot even list tenants.

**Options**

| | Option | Cost |
|---|---|---|
| A | Migration 017 `s12_recovery_candidates(...)`, a `SECURITY DEFINER` function. It returns `(tenant_id, execution_id)` only and writes nothing. Each claim then runs tenant-scoped under RLS through the lease compare-and-set. | One function. It is the one deliberate RLS hole: ids only, read-only, hardened by CONF-046. Golden M19 already pins it (`M19_recovery.py:42-43,729-738`). |
| B | A dedicated BYPASSRLS "sweeper" role with its own pool. | A second credential, and the most powerful role in the system, in every Worker Runtime. It contradicts the stance of `app.py:56-59`. Deployment must create and rotate it. |
| C | An RLS-free side index (`orphan_index`) maintained by triggers on lease and ownership changes. | Extra writes on the hottest path, every lease change. The same id leak as A, plus a second source of truth that can drift. |
| D | Sweep per tenant. | Needs the tenant list, which is RLS-forced too, so D still needs A or B. |

**Recommendation: A, ruled together with CONF-046's amendment** (signature `(runtime_instance_id, limit,
orphan_after_s)`, `search_path` pinned with `pg_temp` last, the only SECURITY DEFINER function in the schema).

Add one deferred-register line: "at deployment, `REVOKE EXECUTE ON FUNCTION s12_recovery_candidates FROM PUBLIC`
and grant it to the application role". The migrations do not know the role name; `tools/setup_database.py:80` does.

Row edit: `ruled 2026-10-01 (owner): option A as amended by CONF-046; EXECUTE revoke from PUBLIC is a deployment step
(deferred register)`.

---

## CONF-043 — in-flight step of a tampered plan during recovery (blocks M19)

**Side A: stop on a tampered plan.** `S12_S15_EXECUTION_GATE.md:1507-1509` (§7.3): "On mismatch during recovery, move
the run to DEAD_LETTER with reason `plan_integrity` and alert. Do not execute any new step."

**Side B: recovery resolves the in-flight step first.**
- `S12_S15_EXECUTION_GATE.md:1747-1749` (§13 steps 2–3): "Reload the plan … verify the digest" then "Handle the
  in-flight step first. It is never blindly re-executed."
- Its branches lead to a provider probe or verification (`:1751-1784`), and both rebuild the call from the plan that
  just failed its digest.
- Appendix A.2 has exactly one exit from `pending_probe` that is neither verification nor probe: `pending_probe →
  dead_letter` with `probe_exhausted` (`:2381`).

**Options**

| | Option | Cost |
|---|---|---|
| A | Proposal. The in-flight step is never probed, verified or re-run. RUNNING/TIMEOUT → `pending_probe` → `dead_letter` (`probe_exhausted`); budget stays LOCKED (D4). A dead letter `unknown_unresolved` with retry_mode PROBE and evidence `plan_integrity` goes to an operator. The remaining PENDING steps become `cancelled (run_dead_lettered)`; consolidation gives DEAD_LETTER. | Pinned already (B5 second pass, `S12_B5_REVIEW.md`, case "the in-flight step of a tampered plan is dead-lettered, never probed"). The probe is not lost: it is deferred. A PROBE-mode dead letter is resolved by an operator-triggered probe (D5, `:1426-1427`). The reason `probe_exhausted` is a slight misnomer: no probe ran. |
| B | Probe using only the admitted `execution_steps` row (`kernel_op_id`) and the idempotency key, which does not depend on the plan's params. | The automated path gets a definitive answer. But it trusts rows written in the same admission transaction as the plan that was tampered with. Plan tampering implies write access to the database, so those rows are equally suspect. Golden M19 must be re-drafted. |
| C | Add a dedicated Appendix A.2 reason (`plan_integrity`) for `pending_probe → dead_letter`. | A gate (Appendix A) change: re-pin of the gate and of B1 (`M03` enumerates every pair and reason). The audit trail is more honest, at the highest change-control cost. |

**Recommendation: A.**
- It is the only option that holds §7.3's "do not execute" literally without touching Appendix A.
- The operator path is exactly D5's PROBE retry.
- Record the misnomer in the ruling text so an auditor reading `probe_exhausted` with evidence `plan_integrity`
  understands it.

Row edit: `ruled 2026-10-01 (owner): accepted as proposed; reason probe_exhausted with evidence plan_integrity is the
recorded meaning (no probe ran); the operator resolves through the PROBE-mode retry (D5)`.

---

## CONF-044 — checkpoints are written but never read (blocks M19)

**Side A: the gate requires checkpoint writes.**
- `S12_S15_EXECUTION_GATE.md:1600` (§8 step 7): "Step PENDING → RUNNING. Budget RESERVED → LOCKED. Write the checkpoint."
- `:1639` (§8 step 11): "Write the checkpoint and release the lease."
- `:435-436` (C10): "checkpoints are rows in `checkpoints`, written with `fenced_write()`".
- `:1861` (§15.2) names the fault point `after_commit_before_checkpoint`.

**Side B: nothing reads them.** `:1788` (§13): "The DB state is the source of truth. The checkpoint is a hint." No
recovery branch (`:1751-1784`) reads a checkpoint.

**Options**

| | Option | Cost |
|---|---|---|
| A | Proposal. Write a `checkpoints` row (sequence; completed / failed / pending step ids) through `fenced_write` at steps 7 and 11. It is a hint only; no golden pins its content. | Two more fenced writes per step. A write path no golden checks is exactly where an unfenced or wrong write could hide (the M21 "no write outside `fenced_write`" scan would still catch an unfenced one). |
| A+ | A, plus one assertion in M19: after a completed run, `checkpoints` has increasing sequence numbers and the last row lists every step id. Recovery still never reads it. | One assertion. It also makes M20's tenant-isolation check on `checkpoints` (`M20_multiprocess.py:302`) non-vacuous; today it would pass even if no row were ever written. |
| B | Write no checkpoints in this phase; record the deviation from §8 steps 7/11 and C10. | Saves two writes per step. It is a written deviation from a normative section, and the M20 isolation check on checkpoints becomes permanently vacuous. |

**Recommendation: A+.** It is cheap, keeps §8 and C10 literal, and turns an unpinned write into a pinned one. Amend
M19 before pinning B5, so no re-pin is needed later.

Row edit: `ruled 2026-10-01 (owner): accepted as proposed, plus one M19 assertion on the rows' sequence and content;
recovery never reads checkpoints`.

---

## CONF-045 — lease renewal during a step (blocks M20)

**Side A: the gate requires background renewal.**
- `S12_S15_EXECUTION_GATE.md:1624` (§8 step 8): "Renew the lease in the background at TTL/3."
- `:1226` (C37): "`lease_ttl >= 3 × lease_renewal_interval`". This is enforced in
  `src/engine/stages/s12_execute/settings.py:55-56`.

**Side B: no card or golden exercises it.**
- No golden runs a step longer than the TTL.
- The renewal primitive exists (`src/adapters/postgres/leases.py:121-133`, M07), but it issues a **new, larger token**
  and moves `execution_ownership.fencing_token` (C5, `:330-335`).
- So a step that renews while running must carry the new token into its own later fenced writes. Otherwise it fences
  itself out.
- Golden M21 pins defaults `step_timeout_s == lease_ttl_s == 30.0` (`M21_journeys.py:344`). With retries, probes and
  verification, a step can outlive its lease with no renewal, and another runtime's sweeper takes it over mid-call.

**Options**

| | Option | Cost |
|---|---|---|
| A | Proposal, and **pin it in M20**. While a step runs, the loop renews every `lease_renewal_interval_s` through `PostgresLeaseManager.renew`. The holder's token is updated under the same lock the loop's fenced writes take. `LeaseLost` stops the step like `FencedOut`. Add two M20 cases: (1) a step longer than the TTL completes with no takeover, its tokens strictly increasing; (2) a renewal refused with `LeaseLost` writes nothing further and the result is discarded. | New concurrency code (token hand-off between the renewal task and the step) in a "very high" milestone that already runs on Opus. Two golden cases. Recovery latency stays about one short TTL. |
| B | No renewal in this phase. Add a settings rule that the lease outlives the worst-case step budget (attempts × step timeout + backoff + probe and verification budgets). Amend M21's defaults (for example TTL 240 s). | No concurrency code. Recovery after a crash then waits for that long TTL, plus one more TTL for a released lease (CONF-046), so minutes, not seconds. It is also a written deviation from §8 step 8. |
| C | The proposal as recorded: renew, but "pinned when an owner assigns it". | Concurrency code that no golden checks, in the module that decides who may write. The worst of both. |

**Recommendation: A, assigned to M20, with the two cases drafted into `M20_multiprocess.py` before B5 is pinned.**
Reject C explicitly. Take B only if the owner prefers slow recovery to concurrency code in this phase. Say so in the
ruling, because it changes the M21 defaults.

Row edit: `ruled 2026-10-01 (owner): option A, assigned to M20; golden M20 gains the long-step and LeaseLost cases
before pinning; the renewal hands the new token to the step's fenced writes under one lock`.

---

## CONF-046 — when is a run "orphaned"? (blocks M19)

**Side A: §13's literal rule.** `S12_S15_EXECUTION_GATE.md:1740-1741`: the sweeper takes runs "whose ownership lease
is expired or absent".

**Side B: two live states have no lease.**
- §7.2 commits the RUNNING run and `execution_ownership` "(this Worker Runtime, no lease yet)" before the first lease
  (`:1496-1498`).
- §8 step 11 releases the lease after every step (`:1639`).
- Read literally, a second runtime's sweeper takes a live run at either moment. Fencing keeps that safe (C25), but it
  is a needless takeover. The B5 review saw it make M20's "claimed exactly once" flaky: 1 failure in 660 case runs
  (`S12_B5_REVIEW.md`, second pass).
- Separately, `SECURITY DEFINER` with an unpinned `search_path` resolves the caller's `pg_temp` tables first (same
  review).

**Options**

| | Option | Cost |
|---|---|---|
| A | Proposal. Judge a run by its latest lease: active and unexpired → never; lapsed or expired → at once; released → one TTL after release; never leased → one TTL after the ownership row. Signature `(runtime_instance_id, limit, orphan_after_s)`. `search_path` pinned with `pg_temp` last. | Already pinned by the B5 second pass. Worst-case recovery latency for a run between steps or never leased is one TTL. |
| B | A runtime heartbeat table, so a run is orphaned when its owner's heartbeat lapses. | Another fenced write stream and another table. It is the fleet-phase design (ADR-5), not single-node. |
| C | The literal rule plus fencing only. | Needless takeovers of live runs, and the M20 flake comes back. |

**Recommendation: A.** It is the smallest rule that makes "orphaned" mean "nobody is driving it". It is
deterministic in the goldens and fixes the `search_path` hijack. The latency cost is one TTL, and CONF-045 option A
keeps that TTL short.

Row edit: `ruled 2026-10-01 (owner): accepted as proposed (amends CONF-042)`.

---

## CONF-047 — NOT_EXECUTED found while the run is RECONCILING (blocks M19)

**Side A: the run must go terminal.** `S12_S15_EXECUTION_GATE.md:474-478` (C13): "The run enters RECONCILING only when
every non-UNKNOWN step is terminal … From RECONCILING the run must go to a terminal state". Appendix A.1 has no
`reconciling → running` edge (`:2353-2355`).

**Side B: §9 wants a retry.** `:1663-1665` (§9): "NOT_EXECUTED: step → PENDING, budget → RELEASED. The step may be
retried within its retry ceiling." A retry needs a RUNNING run.

**Options**

| | Option | Cost |
|---|---|---|
| A | Proposal. In a RECONCILING run, a step the probe finds NOT_EXECUTED goes `pending_probe → pending` (`probe_not_executed`) → `cancelled (not_executed_no_retry)`, both legal A.2 edges (`:2378`, "otherwise the step goes on to `cancelled` with `not_executed_no_retry`"). An executed step completes. The run is consolidated in the same recovery pass. | Pinned (`M19_recovery.py:476`). A step that never ran is cancelled rather than retried. In practice the cost is nil: nothing in this phase moves a run into RECONCILING (CONF-029; `S12_B5_REVIEW.md` "no golden produces one"). Only a seeded or legacy row reaches it. |
| B | Add `reconciling → running` to Appendix A.1 so the retry can happen. | A gate change, a re-pin of the gate and of B1 (`M03` asserts every other pair illegal), and a change to the C13 ruling. All for a state nothing produces. |
| C | Never let recovery leave a run in RECONCILING: resolve with the run in RUNNING, as CONF-029 does in-line. | Contradicts §13, which explicitly sweeps RECONCILING runs. It still leaves a pre-existing RECONCILING row unhandled. |

**Recommendation: A.** It is legal under Appendix A as written and costs nothing reachable.

Row edit: `ruled 2026-10-01 (owner): accepted as proposed`.

---

## CONF-008 — kernel-op metadata is not versioned (ruled; one action outstanding)

**Side A: the gate reads at pinned versions.** `S12_S15_EXECUTION_GATE.md:1379-1382` (D1): "The metadata is read at the
versions pinned in the manifest (`capability_version`, `binding_version`) … If pinned metadata is unavailable, deny at
S12 entry with reason `verifier_metadata_unavailable`."

**Side B: one global version.**
- `001_s0_s11_schema.sql:104-108`: `registry_versions` is a singleton (`singleton BOOLEAN PRIMARY KEY … CHECK
  (singleton)`). `kernel_ops` has no version column.
- `src/adapters/postgres/registry.py:132-133`: if the versions moved, the reader returns None. Entry also denies
  earlier with `binding_version_mismatch` (`src/engine/stages/s12_entry/checks.py:149-153`).

**The current ruling** (`S12_RECORDS.md:19`) reads "accepted for this phase (fail closed); goes into the deferred
register". **The register entry was never written**: `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` has no CONF-008 or
`registry_versions` line.

**Who is hurt:** only plans certified at S11 but not yet admitted at S12 when the catalog is reloaded with new
versions. In practice these are plans waiting on a user's S10 confirmation. They are denied when the user confirms.
Admitted runs are unaffected: verifiers are persisted with the execution (§7.3) and recovery reloads them.

| | Option | Cost |
|---|---|---|
| A | Keep fail-closed. Write the register entry now, plus an operator rule: "a catalog version bump denies every plan awaiting confirmation (`binding_version_mismatch`); bump when none are pending, or accept the denials". | One register line and one runbook line. |
| B | Version the metadata: migration 018 adds a history table filled by a trigger on `kernel_ops`/`bindings`, with new S12 readers. `registry.py` is frozen, so this means new files. | A new milestone item, amended M06 goldens and a schema change. It belongs to the fleet/catalog phase. |

**Recommendation: A.** Close the dangling action. B goes on the post-S15 list.

Row edit: none to the status. Append to the Ruling column: `deferred-register entry written <commit>`.

---

## CONF-020 — soft-quota upgrade text (ruled, but the ruling cannot be implemented as written)

**Side A: the gate wants upgrade text.** `S12_S15_EXECUTION_GATE.md:1324-1326` (C39): "Soft → retry … then DENY
`quota_exhausted` with `retry_after_ms` and upgrade text in `detail`. Nothing is written on a DENY." Repeated in
`DATA_CONTRACTS.md:2778`: "with `retry_after_ms` and upgrade guidance".

**Side B: the frozen outcome has no detail field.** `src/contracts/admission.py:17-23`: `AdmissionOutcome(status,
execution_id, run_status, reason, retry_after_ms)` has no `detail`.

**The current ruling** (`S12_RECORDS.md:31`; STOP-003): "S12 entry returns `quota_exhausted` with `retry_after_ms`
only; the S15 response (M18) adds the upgrade text for `reason = quota_exhausted`".

**Why it has no path:**
1. A DENY writes nothing (`:1326`, and `:1488`, "zero rows at any level rolls the transaction back"). There is no
   run, so M18's `build_envelope(summary)`, which takes a **run summary**, never sees a `quota_exhausted` entry
   denial.
2. Golden M18 has **no** `quota_exhausted` case. `grep quota_exhausted tests_golden/s12/M18_response.py` is empty; the
   only upgrade text pinned is `budget_exhausted` (`M18_response.py:73`).

So the ruling would pass certification without ever being implemented.

| | Option | Cost |
|---|---|---|
| A | Amend the ruling. M18 adds `entry_denial_envelope(outcome: AdmissionOutcome)` in `s15_final_state/response.py`, the S15 mapping for entry denials. `quota_exhausted` maps to Envelope error type `budget_exceeded` (the closest existing type, `DATA_CONTRACTS.md:116`, "Increase budget…"; the type list has no quota or rate-limit type). Soft gives the upgrade text plus `retry_after_ms`; hard gives the upgrade text and no retry. Draft 2–3 M18 cases before pinning B4. | One small function and three cases. It is the natural seam for the API layer, which does not call S12 yet (`docs/proposals/SESSION_HANDOFF.md:15`). |
| B | Drop the upgrade text in this phase; record a deviation from C39. | Nothing to build. A user-visible requirement silently disappears. |
| C | Add `detail` to `AdmissionOutcome`. | Frozen S0–S11 contract: §19.3 change control and re-certification. Not worth it for a string. |

**Recommendation: A.** Amend M18 before B4 is pinned. Name the error type (`budget_exceeded`) and the exact upgrade
sentence in the amended ruling, as CONF-039 did for cancellations, so the drafter does not guess.

Row edit: append `amended 2026-10-01 (owner): entry denials are mapped by S15 entry_denial_envelope (M18), pinned by
M18 quota cases; the run-summary path never sees a DENY`.

---

## CONF-027 — no milestone builds the live admission snapshot or pre-flight (ruled; assignment outstanding)

**Side A: the gate's step loop needs both sources.**
- `S12_S15_EXECUTION_GATE.md:1573-1580` (§8 step 1): "Call the admission controller …" (a snapshot of kill switch,
  tenant, quota, mode, provider, capacity, circuit, pool pressure, budget, load).
- `:1597-1599` (§8 step 6): "Validate params against the kernel input schema and check resource scope."

**Side B: both are injected.**
- `S12_RECORDS.md:38`: "both are injected `LoopDeps` callables in M12–M14; the PostgreSQL sources are assigned to a
  milestone by the owner (M21 journeys at the latest)".
- **No milestone was assigned.** Every golden injects them: `M12_loop.py:191-217` (`AdmissionSnapshot(**PASSING)`,
  `no_preflight_problem`). Even the M21 journeys do the same (`M21_journeys.py:200-215`).

**Consequence if left:** S12–S15 can be tagged certified with a loop that, in production, has no real per-step
admission and no pre-flight. Every gate of WORKER_LIFECYCLE §10 would be decided by a stub.

| | Option | Cost |
|---|---|---|
| A | Assign to M21 and amend the M21 golden **before B5 is pinned**. Define `PostgresAdmissionSnapshot`: kill switch, tenant status, budget headroom, provider allowed and circuit state from the breaker (CONF-022 keying), and worker capacity from `workers`. Pool pressure and system load come from the runtime's own pool statistics and settings. Define `PostgresPreflight`: kernel input JSON schema from `kernel_ops`, resource scope from the frozen binding. At least one journey runs with the real sources, plus one case per DB-backed gate flipping its source. | About 6–10 cases and two adapters. M21 is a Sonnet "high" milestone; this raises it. |
| B | A new milestone M21b between M21 and the tag. | The same work, in a cleaner card. `ORDER` in `owner_certify_s12.py:51-52` is hard-coded, so a new id needs a certifier change and a new pinned hash (owner work). |
| C | Defer past S15. Certify with injected sources, and state in the certification report that the loop is not production-wired. | Nothing now. The tag then means less than its name. |

**Recommendation: A**, because amending an unpinned draft is the cheapest moment this work will ever have. Choose C
only with the report caveat written out, never silently.

Row edit: append `assigned 2026-10-01 (owner): M21; golden M21 amended before pinning`.

---

## DEF-003 — frozen confirmation store updates without a `tenant_id` predicate

**Side A: the rules require the predicate.**
- C20 ruling: `S12_S15_EXECUTION_GATE.md:658`, "`… AND tenant_id = :t`. Exactly one row updated means success".
- C34: `:1119-1130`, "every table … carries `tenant_id`", and every repository query filters on it.

**Side B: the frozen code omits it.**
- `src/adapters/postgres/confirmations.py:36-38` (expire), `:40-42` (consume) and `:47-48` (status read) filter only on
  `confirmation_id`, `user_id` and `plan_hash`. `reject` (`:55`) does the same.
- Reproduced as a superuser: a cross-tenant `consume` returned `consumed` (`S12_DEFECTS.md:14`).

**Mitigations in place:**
- Forced RLS on `pending_confirmations` (`001_s0_s11_schema.sql:146-153`).
- `src/app.py:56-59` refuses to start as a superuser or BYPASSRLS role.
- `tools/setup_database.py:80` creates the role `NOSUPERUSER NOBYPASSRLS`.
- Gap: the guard lives only in the API process. The future Worker Runtime entry point (M20's process) has no such
  check.

| | Option | Cost |
|---|---|---|
| A | §19.3 change control now: add `AND tenant_id = $n` to the four statements and re-certify S0–S11. | The tag `s0-s11-certified` moves. `TAG` is hard-coded in the pinned `code_scan.py` and the certifier, S12-FRZ's baseline moves under every built milestone, and the owner re-verifies M1–M9. Highest cost, mid-batch. |
| B | `wontfix` for this phase: RLS plus the role guard are the control. Require the same superuser/BYPASSRLS refusal in every Worker Runtime entry point (M20/M21 seam). Fix it in the first post-S15 change-control batch together with CONF-006's `state_validators.py` deletion, so there is one re-certification for both. | One deferred-register line and one small check in the runtime entry point. The defense-in-depth gap stays open until after S15, guarded against misconfiguration only by the role checks. |
| C | Move `confirmations.py` into the CONF-011 prototype list (`code_scan.py:17`), so it becomes S12 code. The C34 static rule (`pending_confirmations` is in the S12 table list, `code_scan.py:32`) then **forces** the fix, inside M5. | An edit to a pinned file and a re-pin. It stretches CONF-011, which covered prototype S12 files, to genuine S0–S11 code, a precedent for reclassifying any frozen file the S12 work finds inconvenient. |

**Recommendation: B**, with the runtime-entry role check made a pinned requirement (an M21 settings/architecture case).
Severity is `major`, not `blocker`: exploiting it needs a misconfigured role that two independent checks refuse.

Row edit: Status `wontfix`. Fix column: `owner 2026-10-01: RLS + NOSUPERUSER/NOBYPASSRLS role guard are the control in
this phase; Worker Runtime entry must refuse superuser/BYPASSRLS (M21); predicate added in the first post-S15 S0–S11
change-control batch with CONF-006`.

---

## STOP-004 — no B3 golden file for M10 (blocks M10)

**Side A: the stop condition.** `S12_STOPS.md:16`: "G-M10: no golden file `tests_golden/s12/M10_*.py` (batch B3 =
M10–M14 not drafted)". Its proposal: "draft B3 goldens (M10–M14) as owner proxy … owner reviews and pins them".

**Side B: the cause is resolved.**
- B3 was drafted (`4a2bdec`, `33434f4`, `ceafe41`, `d1da7d4`, `7abdaa9`) and hardened by a second pass (`71532d9`:
  +25 cases, +7 sabotage).
- CONF-033..035 were ruled (`4ba83bf`). Golden M14 was amended for CONF-032 (`150a668`).
- What remains is the pin. Today `docs/gates/s12_pins.sha256` covers B1 only.

| | Option | Cost |
|---|---|---|
| A | Pin B3, then mark it `applied` citing the pin commit. | The owner's pin run (`S12_B3_PREFLIGHT.md` step O3). |
| B | `withdrawn`. | Wrong: the stop was real and is resolved by an action. `applied` is the honest status. |

**Recommendation: A.** Ruling column: `owner 2026-10-01: B3 drafted and reviewed as proposed; pinned`. Applied column:
the pin commit.

---

## STOP-005 — CONF-021..023 unruled before M10 code (blocks M10)

**Side A: the stop condition.** `S12_STOPS.md:17`: "Three document-vs-code conflicts the golden M10 draft resolves by
proposal only … one ruling pass on CONF-021..032 avoids four more stops."

**Side B: they are ruled.**
- `S12_RECORDS.md:32-43`: CONF-021..032 are all `ruled 2026-09-30 (owner): accepted` (`150a668`).
- CONF-032 was also applied to golden M08 (gate 8 is a DELAY), and `src/engine/stages/s12_execute/admission_control.py`
  changed with it.
- No M10 code was written (`s12_autopilot_log.md:29`).

| | Option | Cost |
|---|---|---|
| A | Mark it `applied`: the rulings were recorded and the goldens follow them. | None beyond the pin. Note that `150a668` changed M8 code and the M08 golden **after** M8 was reached. The owner's M8 checkpoint (preflight O4) is the first certifier run to re-prove M8 under the amended golden (40 cases). |

**Recommendation: A.** Ruling column: `owner 2026-09-30: CONF-021..032 accepted (150a668)`. Applied column: `150a668`
plus the pin commit.

---

## Proposed CONF-048 (new finding) — M19 requires naming `StepState.UNKNOWN` outside the allowed files

Found while preparing this pack. Not yet recorded. The owner or the next agent session should append it to
`S12_RECORDS.md` before M19.

**Side A: the standing rule.** `tests_golden/s12/M03_machines_run_step_budget.py:161-166` (pinned, B1): "C24: UNKNOWN
is never written in this phase; only the enum and the transition tables may name it". Allowed files:
`contracts/execution_states.py`, `s12_execute/transitions.py`.

**Side B: what M19 requires.**
- `tests_golden/s12/M19_recovery.py:453-469` requires recovery to treat a step in `unknown` as in flight and move it
  `unknown → pending_probe (recovery)`. That follows §13 step 3, which lists UNKNOWN (`S12_S15_EXECUTION_GATE.md:1752`).
- So recovery code must name UNKNOWN.
- The B5 reference does so in `loop.py` as `S.UNKNOWN` (`batch_bundles/B5_M19-M21/src/engine/stages/s12_execute/loop.py:607,715`).
- It passes M03 only because `attribute_uses` matches the literal name `StepState`
  (`tests_golden/fixtures/code_scan.py:114-117`). An alias evades the scan.

**Options:**
- **A.** Rule that the in-flight set lives in `transitions.py`, which is allowed (for example
  `IN_FLIGHT_STEP_STATES`), and recovery imports it. Evading a scan by aliasing is forbidden in the autopilot sense.
  Cost: none to the goldens.
- **B.** Widen the M03 allow-list. Cost: an edit to a pinned B1 file and a re-pin.

**Recommendation: A.** Record it with the M19 rulings.

---

## How to apply (owner)

1. Edit the rows in `docs/gates/S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md`.
   - The certifier reads only the third column (Status), so `open` → `ruled` (CONF), and `open` → `applied` (STOP).
   - Write the ruling text into the last columns as worded above, or as changed.
2. Golden amendments these rulings call for. All are on unpinned B4/B5 drafts, so make them **before** the pin that
   covers B4/B5:
   - M18: CONF-020, `quota_exhausted` cases.
   - M19: CONF-044, one checkpoint assertion.
   - M20: CONF-045, two renewal cases.
   - M21: CONF-027 real sources; DEF-003 runtime-entry role check.
3. Register lines (deferred register, §21): CONF-005, CONF-008, CONF-042 (EXECUTE revoke), DEF-003 (post-S15
   predicate), and CONF-027 if option C is chosen.
4. None of this blocks B3. B3 needs only STOP-001/002/004/005 → `applied`, the re-pin and the tracker backfill. See
   `S12_B3_PREFLIGHT.md`.
