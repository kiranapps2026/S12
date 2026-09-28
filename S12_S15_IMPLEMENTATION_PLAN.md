# S12–S15 IMPLEMENTATION PLAN (after S0–S11 is certified)

Status: PLAN — owner approval required before M0 starts
Governing rules: `docs/implementation/S12_S15_EXECUTION_GATE.md` (v8)
Precondition: tag `s0-s11-certified` exists and `tools\owner_verify.ps1` passed.

---

## 1. What S0–S11 taught us, and the control that answers each lesson

| What went wrong in S0–S11 | Control for S12 |
|---|---|
| The agent edited its own checker until it passed | The certifier is owner-written and hash-pinned (already in place) |
| The agent edited the spec to match its code | Spec documents are pinned (OWN-20 pattern), including the gate |
| Tests were changed to assert the bug ("enforced at S12") | **Golden tests**: owner-written acceptance tests, pinned by hash; the agent may never edit them |
| Tests built impossible states by hand | Golden tests use owner-written fixtures that run real code; hand-built state is detected |
| Context loss: instructions "remembered" wrongly | Every rule lives in pinned files; the agent re-reads them each iteration |
| Owner copy-pasting every step | Autopilot loop per milestone; the owner acts only at milestone boundaries (one script) |
| Scope creep and step skipping | One milestone at a time; the certifier for milestone N fails while any earlier milestone's golden tests fail |

The single most important change: **for S12 the agent does not write the acceptance
tests.** The owner (with Claude) writes them before each milestone starts. The agent's
freedom is limited to making pinned tests pass in `src/`.

---

## 2. Artifacts and who owns them

| Artifact | Owner | Agent may edit? |
|---|---|---|
| `docs/implementation/*` incl. the S12–S15 gate v8 | Owner | No (pinned) |
| `tests/golden/s12/Mx_*.py` golden tests per milestone | Owner | No (pinned) |
| `tests/golden/fixtures/*` (mock adapter, fault injection, DB harness contracts) | Owner | No (pinned) |
| `tools/owner_certify_s12.py` | Owner | No (pinned) |
| `docs/gates/S12_AUTOPILOT.md` | Owner | No |
| `src/**` | Agent | Yes |
| `tests/agent/**` (extra tests the agent wants) | Agent | Yes, but they never count for certification |
| `docs/gates/s12_autopilot_log.md` | Agent | Append only |

The fixtures the golden tests need (mock provider adapter with the gate's behavior
table, fault-injection hooks, PostgreSQL test harness, clock control) are specified as
**interfaces** in the golden fixture files. The agent implements the production side
(`src/`) behind those interfaces; the golden side is fixed.

---

## 3. Milestones

Each milestone = a gate commit range, a golden test file, certifier checks, and exit
criteria. The agent runs the autopilot loop inside the milestone and stops at its end.

### M0 — Preflight (gate commit A)
- **Golden:** none. **Certifier:** preflight checks only (PostgreSQL 16+, `suprpg_test`,
  repo clean, S0–S11 tag present, gate v8 pinned).
- **Exit:** preflight report with items 3–15 answered from code (`file:line`).
- **Owner action:** read the report's "Conflicts found" line; Claude rules on each.

### M1 — Durable foundation (gate commits B–C)
- **Scope:** doc repairs C1–C23 as proposed text (owner applies and re-pins); additive
  migrations (Section 7.3); repositories; `fenced_write()`; one transition function per
  state machine.
- **Golden `M1_state_machines.py`:** exhaustive legal/illegal transition pairs for run,
  step, budget, lease, worker, dead letter, reconciliation episode (generated from the
  corrected tables); `fenced_write` rejects a stale token; migrations apply to an empty
  `suprpg_test` and are idempotent.
- **Certifier:** golden M1 green; AST: no `UPDATE`/`INSERT` on execution tables outside
  the repository module; no direct status assignment outside transition functions.
- **Risk:** migration type mismatches (UUID vs TEXT). Ruling already in gate 7.3.

### M2 — Entry and durable admission (gate commit D)
- **Scope:** PostgreSQL confirmation store (C20), S12 entry checks (7.1), durable
  admission transaction (7.2), `execution_plans` with digest verification.
- **Golden `M2_entry.py`:** each 7.1 check denies with its reason and writes nothing;
  duplicate `request_id` returns the existing run; tampered plan denied; confirmation
  consume with 20 concurrent consumers → exactly one winner (real transactions).

### M3 — Workers, leases, fencing (gate commit E)
- **Scope:** worker selection, capacity-bounded leases (C5), renewal, expiry,
  `execution_ownership`, admission controller.
- **Golden `M3_leases.py`:** capacity 1 and 3 never exceeded under concurrency; fence
  tokens strictly increasing; stale Runner's writes affect 0 rows; lease lost during a
  slow call → result discarded.

### M4 — Budget (gate commit F)
- **Scope:** BudgetReserver per C3, C14, D4.
- **Golden `M4_budget.py`:** 20 concurrent reservations against a small pool never
  over-reserve; full lifecycle; I1, I2, I12 after every test.

### M5 — Reliability guard and idempotency (gate commit G)
- **Scope:** guard components by name (C4), mock adapter wiring, idempotency ledger
  (C9, C17, S7 tenant scoping), retry inside RUNNING (C6).
- **Golden `M5_guard.py`:** retry matrix per mutation class; IRREVERSIBLE never
  retried; side-effect count 1 per key; ledger conflict raises; expired ledger never
  authorizes a call.

### M6 — Execution loop, UNKNOWN and revalidation (gate commit H) — **checkpoint**
- **Scope:** Section 8 loop; EXECUTION and VERIFICATION episodes (C18, C19); live
  revalidation (C23); cancellation (C15, C16); terminal reasons (C22).
- **Golden `M6_loop.py`:** every Section 9 probe outcome; ledger-before-probe;
  verification UNKNOWN never calls the probe; revocation mid-run cancels without new
  adapter calls; I5, I6, I13, I14.
- **Owner checkpoint:** Claude reviews the milestone summary before M7 (this is the
  riskiest milestone).

### M7 — Verification, dead letter, response (gate commits I–K)
- **Scope:** S13 layers and consolidation, S14 with C21 storage and retry modes, S15
  mapping and redaction.
- **Golden `M7_outcomes.py`:** every consolidation row; dead-letter retry per
  `retry_mode`; resolution never changes run/step state; secrets absent from envelope,
  logs and persisted rows.

### M8 — Crash recovery and certification (gate commits L–M)
- **Scope:** recovery sweeper with the single decision tree (Section 13), fault
  injection, two-Runner test, journeys S0→S15, scale seams (Section 21), performance
  baseline.
- **Golden `M8_recovery.py`:** Crash A/B/C at every injection point; 3 real subprocess
  kills; two Runners on one database with takeover; all invariants I1–I14 after each.
- **Exit:** `owner_certify_s12.py` N/N PASS; owner runs `owner_verify_s12.ps1`; tag
  `s12-s15-certified`.

---

## 4. How golden tests are produced (the part that prevents detours)

1. Before a milestone starts, Claude drafts `Mx_*.py` directly from the gate rulings,
   with exact expected values, and a short fixture interface spec.
2. The owner saves the files, runs `owner_pin_s12.ps1` (adds them to the pin list),
   commits.
3. The agent's autopilot for that milestone: run the certifier → first failing golden
   test → fix `src/` → suite green → commit → repeat. It may not edit golden files; if
   it believes a golden test is wrong, it STOPs with the test name and its reasoning,
   and Claude rules.
4. At milestone end the agent sends one line; the owner runs one verify script.

This keeps the agent's freedom where it is useful (implementation) and removes it
where it caused the S0–S11 detours (deciding what "correct" means).

---

## 5. Owner effort per milestone

| Moment | Owner does | Time |
|---|---|---|
| Milestone start | Save golden files from Claude, run `owner_pin_s12.ps1`, send "start Mx per S12_AUTOPILOT" | ~5 min |
| During | Nothing, unless an `AUTOPILOT STOPPED` message arrives (forward it to Claude) | — |
| Milestone end | Run `owner_verify_s12.ps1`; paste its last 10 lines to Claude only if it fails | ~2 min |

Nine milestones, so roughly nine short owner interactions plus any STOPs.

---

## 6. S12-specific risks and mitigations

| Risk | Mitigation |
|---|---|
| Flaky concurrency tests | Real PostgreSQL only; each golden module gets its own schema; no sleeps longer than lease TTL (1–2 s); retries are forbidden in test code |
| Windows specifics (event loop, process kill) | Preflight item 10 decides the loop; subprocess kills use `Popen.kill()`; paths via `pathlib` |
| Time-dependent behavior | Lease expiry uses database time with short TTLs; unit tests use an injected clock |
| Agent special-cases tests (for example checks a test-only flag) | Certifier AST check: no reference to `pytest`, `golden` or test module names in `src/`; golden tests randomize identifiers |
| Schema drift from DATABASE.md | Migrations only additive; certifier compares migrated schema to the gate's table list |
| Context loss in long runs | Autopilot re-reads the gate and this plan each iteration; the log file is the memory |
| Large milestones overwhelming the agent | M6 has an owner checkpoint; any milestone may be split if the same check fails 3 iterations |

---

## 7. What is needed from the owner before M0

1. S0–S11 certified and tagged (via `owner_verify.ps1`).
2. PostgreSQL restricted to localhost (`listen_addresses = 'localhost'`) and
   `TEST_DATABASE_URL` set to `suprpg_test`.
3. Confirmation that gate decisions D1–D6 stand as written.
4. Approval of this plan. Claude then produces, in one delivery:
   `owner_certify_s12.py`, `S12_AUTOPILOT.md`, `owner_pin_s12.ps1`,
   `owner_verify_s12.ps1`, and the M0 and M1 golden files. Later milestones' golden
   files are delivered at each milestone start, so they reflect what M1–M(n−1) built.
