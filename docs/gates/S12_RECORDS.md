# S12 records

Append-only. Each record documents a specification conflict, a code deviation, or a STOP outcome that needs owner attention.

## Format
- ID: S12-REC-XXX
- Documents: ...
- Conflict: ...
- Ruling applied: ...
- Open question: ...

---

## S12-REC-001: DEF-003 — confirmations.py missing tenant_id predicate

- ID: S12-REC-001
- Documents: gate v10 §19.3, C20, C34; docs/gates/S12_DEFECTS.md DEF-003
- Conflict: `src/adapters/postgres/confirmations.py` UPDATE/SELECT queries lacked `tenant_id` predicate. C20 ruled `AND tenant_id = :t` required. DEF-003 fixed this by adding the predicate.
- Ruling applied: Owner must decide: (a) approve the predicate addition and re-pin S0-S11 baseline via change-control, or (b) accept RLS as the only guard and record the deviation (revert the change).
- Open question: Owner ruling needed. Until ruled, M02 test `test_s0_s11_code_unchanged_since_the_tag` will fail.

---

## S12-REC-002: STOP-004 — M10 golden test file exists but guard module missing

- ID: S12-REC-002
- Documents: gate v10 Appendix B, plan M10; STOP-004 in docs/gates/S12_STOPS.md
- Conflict: `tests_golden/s12/M10_guard.py` exists (55 tests, 54 failing). The implementation files (`contracts/adapter_interface.py`, `engine/providers/guard.py`, `adapters/runtime/`) do not exist in `src/`.
- Ruling applied: None yet. M10 cannot be built until the missing modules are implemented or the golden test is replaced.
- Open question: Owner must approve M10 scope: implement the 5 guard components per gate §15.3, or defer M10 to a later milestone.

---

## S12-REC-003: STOP-002 — M5 golden test exists but may not be pinned

- ID: S12-REC-003
- Documents: STOP-002 in docs/gates/S12_STOPS.md
- Conflict: `tests_golden/s12/M05_confirmation_store.py` exists (30 tests, all passing). STOP-002 says "no golden file" — this appears resolved.
- Ruling applied: STOP-002 appears stale. Owner should verify `M05_confirmation_store.py` is owner-pinned and update STOP-002 to "applied".
- Open question: Owner confirmation that M05 is pinned.

---

## S12-REC-004: Forensic audit S12_FORENSIC_AUDIT_M0-M10.md contains stale findings

- ID: S12-REC-004
- Documents: S12_FORENSIC_AUDIT_M0-M10.md (audit dated 2026-09-30)
- Conflict: The audit lists 6 "critical blockers" but 3 of 4 M4/M9/M7 findings are incorrect against current code:
  - Blocker 2 (BudgetReserver missing): FALSE — `src/adapters/postgres/budget_reserver.py` exists with full `PostgresBudgetReserver` class (reserve/lock/commit/release).
  - Blocker 3 (M4 validators missing): FALSE — `src/engine/stages/s12_execute/transitions.py` contains validators for all 6 machines (run/step/reservation/lease/worker/dead_letter/episode/confirmation/breaker).
  - Blocker 5 (lease acquisition missing): FALSE — `src/engine/stages/s12_execute/selection.py` implements `lease_for_step()` with selection and bounded retry.
  - Blocker 1 (adapter interface conflict) and Blocker 4 (SafeAdapterWrapper missing): TRUE — M10 not built per gate.
- Ruling applied: Only M10-related blockers are genuine. M4, M9, M7 are complete. The audit appears to have been written against an earlier code state.
- Open question: Owner should re-pin the forensic audit after verifying current code, or supersede it.
