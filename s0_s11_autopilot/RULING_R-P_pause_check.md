### R-P — Pause and scheduled-activation check at S0.1 (owner ruling, 2026-09-29)

<!-- OWNER: append this whole section to docs/gates/S0_S11_RUNBOOK.md, fill in the
     <FILL: ...> values, bump the runbook's revision line, and re-certify S0–S11 before
     the S12–S15 phase starts (S12_S15_EXECUTION_GATE.md v10 preflight item 17). To find
     the S0 handler and the stage sequence, from the repo root in PowerShell:
       Get-ChildItem -Recurse src -Filter *.py | Select-String -Pattern 'PRE_EXECUTION_SEQUENCE|class \w*S0\w*|def handle\(' |
         ForEach-Object { "{0}:{1}  {2}" -f $_.Path.Replace("$PWD\",''), $_.LineNumber, $_.Line.Trim() }
-->

**Code this ruling changes:**
- S0 entry handler: `<FILL: file:line of the S0 stage handler>`
- Stage sequence definition: `<FILL: file:line of PRE_EXECUTION_SEQUENCE or equivalent>`
- Tenant and workspace read path used by S8's `Tenant active` check: `<FILL: file:line>`

If the code differs from these references, STOP (S-4) and quote what you found. Do not
invent a new interface.

**Why.** A tenant or workspace pause (`paused_until`) and a future activation time
(`scheduled_activation_at`) must stop new work immediately. If they are checked only at
S12 entry (gate v10 C39), a paused tenant still runs S1–S11: the S2 LLM call, capability
discovery, and possibly an S10 confirmation of an IRREVERSIBLE operation, before anything
stops. The pause would delay denial instead of pausing. One row read after S0 closes that
gap before any resource is spent.

**Rule.**
1. **Position.** A check runs immediately after S0 has built the `ExecutionContext` and
   before S1. It is part of the S0 stage handler (call it S0.1 in documents); it is **not** a
   new stage, so the stage sequence `S0 … S11` and `StageStatus` are unchanged.
2. **Reads only.** Read `tenants.paused_until`, `tenants.scheduled_activation_at`,
   `workspaces.paused_until` and `workspaces.scheduled_activation_at` for
   `ExecutionContext.tenant_id` / `workspace_id`, comparing with **database** `NOW()`
   (I-019). NULL means "not paused" / "already active". Nothing is written.
3. **Outcome.** If `paused_until > NOW()` at tenant or workspace level: `StageStatus.DENY`
   with reason `tenant_paused` or `workspace_paused`. If `scheduled_activation_at > NOW()`
   at either level: `StageStatus.DENY` with reason `not_yet_active`. The run goes straight
   to S15 through the existing DENY short-circuit. No S1–S11 work is performed.
4. **Fail closed.** If the rows cannot be read, DENY on the existing deny path (the same
   behaviour as S8's `Tenant active` check when live state is unreadable).
5. **No bypass.** Admin roles do not bypass a tenant or workspace pause at S0.1 (the admin
   bypass applies only to worker-level eligibility filters in S12, gate C39).
6. **Scope.** Worker-level pause, activation, assignment and quota are **not** checked
   here; they need a selected worker or a run row and stay in S12 (gate C39). S12 entry
   re-checks tenant/workspace pause as a safety net for runs that passed S0.1 before a
   pause was set; running steps are never cancelled by a pause (the kill switch does that).
7. The columns come from the S12–S15 migration 018 (DATABASE.md). If the S0–S11 schema is
   certified before 018 exists, this ruling adds only those four nullable columns, in an
   S0–S11 migration, and 018 skips them if present.
8. No other S0–S11 contract, stage or test changes because of this ruling.

**Required tests** (in the certifier's required list, checked by OWN-12):

| Node id | Asserts |
|---|---|
| `tests/stages/test_s0_entry.py::test_s0_denies_paused_tenant` | With `tenants.paused_until` in the future (database time), S0 returns DENY `tenant_paused`; a recording fake for S1 and the S2 LLM client records **zero** calls; nothing is written. |
| `tests/stages/test_s0_entry.py::test_s0_denies_paused_workspace` | Same for `workspaces.paused_until`, reason `workspace_paused`. |
| `tests/stages/test_s0_entry.py::test_s0_denies_not_yet_active` | `scheduled_activation_at` in the future at tenant or workspace level → DENY `not_yet_active`, zero S1/S2 calls. |
| `tests/stages/test_s0_entry.py::test_s0_passes_when_pause_elapsed` | `paused_until` in the past, or NULL → the pipeline continues to S1 unchanged. |
| `tests/stages/test_s0_entry.py::test_s0_pause_check_uses_database_time` | With the process clock skewed ahead of the database clock, the decision follows the database time. |
| `tests/stages/test_s0_entry.py::test_s0_pause_unreadable_fails_closed` | The tenant/workspace read raises → DENY, zero S1/S2 calls. |

**Sabotage.** Add `SAB-12` (AUTOPILOT Part F). The patch moves the check after S2, and
`test_s0_denies_paused_tenant` must then fail on the S2 call count.
