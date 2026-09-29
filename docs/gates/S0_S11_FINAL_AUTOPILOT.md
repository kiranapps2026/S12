# S0–S11 FINAL AUTOPILOT — FIX, THEN VERIFY, THEN STOP

Repository: `C:\Users\Administrator\Documents\1SuperAgents` (branch `s8-rewrite`)
Save as `docs\gates\S0_S11_FINAL_AUTOPILOT.md`. It replaces `docs\gates\AUTOPILOT.md`.
Trigger: the owner says **"run S0_S11_FINAL_AUTOPILOT"**. Run all phases in order
without messaging the owner until the end or a STOP.

Rulings: `docs\gates\S0_S11_RUNBOOK.md` (R-A … R-Z, Part 6 test code).

---

## Guardrails (always)

1. Never edit: `tools/owner_certify.py`, `docs/gates/*.sha256`, anything in
   `docs/implementation/`, the runbook, this file, or the required-test list. The owner
   verifies with an external copy of the certifier; edits to the repo copy change nothing.
2. Fix only in `src/` and `tests/`. Never change an expected value in runbook Part 6 code.
3. Every commit: under 800 changed lines, full suite green (`python -m pytest -q`).
   Never set `AR_DISABLE_SIMPLIFY_GATE`.
4. Pre-existing S12–S15 handler packages (`s12_*` … `s15_*`): comment header only
   (item F12); no logic changes.
5. A ruling or check you believe is wrong, or two rulings that contradict → STOP.
6. Your own checklists are not evidence. Evidence = the certifier output and `git grep`.

After every commit append one line to `docs/gates/autopilot_log.md`:
`<commit> | <item> | <OWN pass count>/19 | <summary>`

---

## PHASE 1 — Fix queue (do in this order; one commit per item unless it exceeds 800 lines)

Before F1: commit any uncommitted work (suite green), and add to
`docs/gates/test_reconciliation.md` the name of the test removed when the count went
282 → 281, with reason and replacement.

| Item | Change | Done when (check it yourself) |
|---|---|---|
| **F1** R-X | Remove `raw_input` and `trace` from ExecutionContext (removal, not rename). PipelineState gets `entry_request` owned by S0 (S0 writes `execution_context` and `entry_request` in one call). `pipeline_state_runner.py`, S1 and S2 read `state.entry_request` / `state.normalized_input`. S1 always returns `PipelineState`. | `git grep -n "raw_input\|\.trace\b" -- src/contracts/execution_context.py` prints nothing; suite green |
| **F2** R-P | Canonical values everywhere in `src/` (excluding `s12_*`–`s15_*`): mutation `R/W/D/IRREVERSIBLE`; graph `SINGLE_STEP→simple`, `LINEAR→chain`, `BRANCH/DAG→complex`; `join_mode="all"`; includes `constants.py`, `contracts/capability.py`, S3, S4, S5, S7, S9, `stage_outputs.py`, `execution_manifest.py`, DB model default. Keep `"rejected"` (canonical confirmation status). | OWN-18 PASS |
| **F3** R-O / R-Z | Remove `Step.output_refs` (C36), `ValidationResult.check_results`/`failed_check`/`reason` (only `is_valid`, `errors`), `Confirmation.tenant_id`/`execution_id`. S10 passes `tenant_id` (ExecutionContext) and `execution_id` (PlanCreationResult) to the confirmation store's save method. FrozenBindingIdentity has `capability_version`, `binding_version`, `risk_policy_version`, `authorization_version`. ExecutionManifest gains `auth_result_id`, keeps `policy_version` (value from `ExecutionContext.policy_version_id`). Add `tests/stages/test_s10_confirmation.py::test_s10_store_receives_tenant_and_execution_id` with a recording fake store asserting the exact values. | OWN-17 PASS; the new test passes |
| **F4** R-U | S9: every `Step.kernel_op_id`, `risk`, `mutation` from `state.frozen_binding_identity`, never from TaskProfile. | runbook Part 6.3 tests pass (incl. the tamper test) |
| **F5** R-V | S6 formula exactly as R-V (IRREVERSIBLE; D and capability.cost > 5; total cost > 20; risk > 0.7; strict `>`). | runbook Part 6.1 tests pass |
| **F6** R-Q | S7 rewritten to the 9-row table; `PathRoutingResult(decision: PathDecision, reason)`; `risk_deny_threshold` from KernelPolicy. | runbook Part 6.2 tests pass |
| **F7** R-M | Controlled ExecutionContext replacement (whitelist: S2 `task_id`; S5 policy-version fields; S8 `auth_passed`, `auth_result_id`). S8 sets both on ALLOW; unchanged on DENY. | `test_s8_allow_sets_auth_passed`, `test_s8_deny_leaves_context_unchanged` pass |
| **F8** R-N | S9, S10, S11 first check `safety_result.allowed and execution_context.auth_passed`; otherwise DENY `safety_not_passed`, no output written. | `test_s9/s10/s11_requires_safety_passed` pass |
| **F9** R-R / R-S | S10 writes `ConfirmationOutcome(required, confirmation)`. S11 denial → `ValidationResult(is_valid=False, errors=(code,))`, manifest None; manifest records `auth_result_id`. | Part 5 S10/S11 tests pass |
| **F10** R-Y / OWN-08 | `app = create_app()` removed (start with `uvicorn app:create_app --factory`; update scripts/config); `OUTCOME_TO_STATUS`, `_STAGE_REGISTRY`/`STAGE_REGISTRY` → `MappingProxyType`; every `Base = declarative_base()` → `class Base(DeclarativeBase): pass`; `src/db/session.py` globals → an injected engine/session factory. | OWN-08 PASS |
| **F11** OWN-01 | Delete tests/assertions that mention legacy names only to assert absence (`tests/steps/step_f_dead_code_removed.py`, `test_s0_s11_certification.py` lines 94/99, `test_frozen_binding_invariants.py` line 198). Record them in `test_reconciliation.md` as "covered by OWN-01". Never disguise names. | OWN-01 PASS |
| **F12** R-I / R-J | Add the header "Pre-existing. Not certified. Superseded by the S12–S15 execution gate." to the S12–S15 handlers. Record `default=str` in `s14_verification` in `docs/gates/s12_s15_findings.md` (do not fix). | headers present; findings file lists it |
| **F13** OWN-19 | Convert every listed test to `state_ready_for` / `make_scenario` / `tamper` (R-T). | OWN-19 PASS |
| **F14** OWN-12 | Add every missing required test under its exact required name (runbook Part 5/Part 6). Fix `src/` until they pass. | OWN-12 PASS |

If an item's "done when" check still fails after 3 attempts → STOP.

---

## PHASE 2 — Verify loop (until the certifier is clean)

1. `python tools/owner_certify.py --selftest` — every row OK, else STOP.
2. `python tools/owner_certify.py` — if every row PASS, go to Phase 3.
3. Take the first FAIL, fix it in `src/`/`tests/` per its ruling, suite green, commit,
   log line. Go to 1.
4. The PASS count must never go down between commits; if it does and you cannot restore
   it in one iteration → STOP.

---

## PHASE 3 — Finish

1. Regenerate `docs/gates/test_manifest_final.txt` (`pytest --collect-only -q`) and
   complete `docs/gates/test_reconciliation.md`: baseline 185 (commit `d972516`)
   + added − removed = final, every removed test named with reason and replacement.
2. `python tools/owner_certify.py > docs/gates/owner_certify_final.txt`
3. Write `docs/gates/S0_S11_CERTIFICATION_REPORT.md` (runbook Step 11 format).
4. Commit. Do **not** create any tag.
5. Send exactly:

```text
S0-S11 FINAL AUTOPILOT COMPLETE — owner certifier 19/19 PASS at commit <hash>
Owner: powershell -ExecutionPolicy Bypass -File .\tools\owner_verify.ps1
```

---

## STOP report (the only other message allowed)

```text
AUTOPILOT STOPPED — <item or OWN id> — <condition>
Detail: <certifier lines or failing test output, max 15 lines>
Tried: <1–3 lines>
Proposal: <1–3 lines>
Commit: <hash>
```
