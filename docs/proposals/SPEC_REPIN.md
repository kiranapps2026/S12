# Spec re-pin — applied at the owner's instruction

**Status: APPLIED** on the owner's explicit instruction ("pin as per latest sources"),
byte-for-byte from `claude/peaceful-brown-9f3w18@adec209` (the branch head at the time).
The agent had first stopped when the environment refused the change, and proceeded only after
the owner authorized it. The 6 golden-test pins were not touched. Result: `owner_certify.py`
19/19 (OWN-17 and OWN-20 included).

Original analysis, kept for the record:

**Status before: not applied.** The pinned specs in `docs/implementation/` (28 files,
pinned in `docs/gates/spec_pins.sha256`, checked by OWN-20) are the OLDER copies. The latest
owner decisions (worker-management rulings RD-1…RD-18, gate v10, ADR-14, EVENT_GATEWAY lock,
FINAL_ARCHITECTURE 4.5.2, …) live in the newer copies on branch
`claude/peaceful-brown-9f3w18` (commit `adec209`).

The runbook (Part 0, rule 5) forbids the agent to edit a spec or the pin file, and an attempt
to do so in this session was refused by the environment's integrity guard. It was not retried
or worked around. Everything below was checked read-only.

## Findings (read-only)

- 28 pinned specs: **5 identical** to the newer copies, **23 differ**.
- **OWN-17** (contract field names vs `DATA_CONTRACTS.md`): dry run against the NEWER
  `DATA_CONTRACTS.md` in a throw-away directory → **PASS**. So re-pinning does not break OWN-17.
- The 6 pinned golden test files (`tests/stages/…`) are unchanged since the owner pinned them.
- The S6 amendment (every D/IRREVERSIBLE plan needs confirmation) is **not** implemented: the
  pinned golden `test_s6_task_profile.py` still encodes the old table (`delete_cost_5_boundary`
  → False). It needs the new golden S6 test from the owner first.

| pinned spec | vs newer copy |
|---|---|
| `ADAPTABILITY_PRINCIPLES.md` | identical |
| `BUILD_READINESS_MATRIX.md` | 24 changed lines |
| `COMPONENTS_BLUEPRINT.md` | identical |
| `DATABASE.md` | 292 changed lines |
| `DATA_CONTRACTS.md` | 229 changed lines |
| `EVENT_GATEWAY_AND_ROUTER.md` | 137 changed lines |
| `EXECUTION_PLAN.md` | 2 changed lines |
| `FINAL_ARCHITECTURE.md` | 199 changed lines |
| `IDENTITY_AND_TENANCY.md` | 71 changed lines |
| `LAYA_DECISION_ADAPTER.md` | identical |
| `MUTATION_SAFETY.md` | 21 changed lines |
| `PIPELINE_STAGES.md` | 25 changed lines |
| `PROVIDER_ADAPTERS.md` | 15 changed lines |
| `README.md` | 80 changed lines |
| `REFAUDIT.md` | identical |
| `RELIABILITY.md` | 14 changed lines |
| `REPAIRS_APPLIED.md` | 89 changed lines |
| `RESOLVE_LAYER.md` | 2 changed lines |
| `S12_S15_EXECUTION_GATE.md` | 216 changed lines |
| `S12_S15_IMPLEMENTATION_PLAN.md` | 94 changed lines |
| `S12_SESSION0_PREFLIGHT_PROMPT.md` | 38 changed lines |
| `SECURITY.md` | 119 changed lines |
| `STATE_TRANSITIONS.md` | 25 changed lines |
| `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` | 126 changed lines |
| `VALIDATION.md` | 49 changed lines |
| `VOCABULARY_INDEX.md` | 26 changed lines |
| `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md` | 99 changed lines |
| `XS-1_REGISTER_ENTRY.md` | identical |

## How it was done (reproducible)

For each file in `docs/implementation/`: `git show adec209:<file> > docs/implementation/<file>`
(from the peaceful-brown branch); then the 23 document lines of `docs/gates/spec_pins.sha256`
were regenerated with SHA-256 (uppercase hex) and the 6 test-file lines left as they were.

## Spec text the implementation already relies on (for the owner to confirm is in the newer copies)

- S5 records `tenant_policy_version_id`, `workspace_policy_version_id`, `policy_version_id`
  (R-E, from the run scope).
- `BindingRow` carries `kernel_op_id` and `engine_module`; `CapabilityMatch.candidate_count`.
- S2 answer vocabulary: a registry intent, `unknown` (→ CLARIFY `intent_unclear`),
  `prohibited` (→ DENY `intent_prohibited`); ruling id still to be assigned.
- R-AA S0.1 activation check: `docs/proposals/S0_1_PAUSE_CHECK.md`.
- S8 rule-not-met reasons per R-L (`capability_granted_denied`, `mutation_safety_denied`,
  `budget_available_denied`).
- Stage event log (`pipeline_events`) and suspended runs (`suspended_runs`) tables.
