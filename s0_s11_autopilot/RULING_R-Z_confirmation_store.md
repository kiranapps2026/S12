### R-Z — Confirmation store carries `tenant_id` and `execution_id` (owner ruling)

<!-- OWNER: append this whole section to docs/gates/S0_S11_RUNBOOK.md, fill in the
     three <FILL: ...> values, and bump the runbook's revision line. To find them, from
     the repo root in PowerShell:
       Get-ChildItem -Recurse src -Filter *.py | Select-String -Pattern 'class \w*Confirmation\w*(Store|Repository)\b|def (save|store|put|create|consume|verify)\w*\(' |
         Where-Object { $_.Path -match 'confirm' } | ForEach-Object { "{0}:{1}  {2}" -f $_.Path.Replace("$PWD\",''), $_.LineNumber, $_.Line.Trim() }
-->

**Interface this ruling changes (in code):**
- Store interface: `<FILL: file:line of the confirmation-store interface/protocol class>`
- Method that stores a new confirmation: `<FILL: file:line and method name>`
- Method that consumes/verifies a confirmation: `<FILL: file:line and method name>`

If the code differs from these references, STOP (S-4) and quote what you found. Do not
invent a new interface.

**Why.** The S12–S15 gate (ruling C20) stores confirmations in `pending_confirmations`.
Each row needs `tenant_id` and `execution_id`, and consuming a confirmation must filter
by tenant. The frozen `Confirmation` contract (DATA_CONTRACTS.md, `class Confirmation`)
has neither field and must not change (OWN-17). Adding them to the store now, before
S0–S11 is certified, avoids a §19.3 change request later.

**Rule.**
1. `Confirmation` stays exactly as in DATA_CONTRACTS.md. Do not add fields to it.
2. In every implementation of the interface above (in-memory included):
   - The store method takes two **required, keyword-only** arguments:
     `tenant_id: str` and `execution_id: str`. No defaults. An empty string raises
     `ValueError`. The store keeps both values with the record.
   - The consume/verify method takes a **required, keyword-only** `tenant_id: str`.
     A record whose stored `tenant_id` differs is rejected on the same path, with the
     same outcome, as the existing wrong-user check. The record stays unconsumed.
3. S10 supplies both values from the pipeline state and never generates them:
   - `tenant_id` = `state.execution_context.tenant_id` (`ExecutionContext.tenant_id`)
   - `execution_id` = `PlanCreationResult.execution_id` (S9's output, per R1).
     If it is missing, S10 fails closed on its existing deny path. No new
     StageStatus and no new contract field.
4. No other S0–S11 contract, stage or test changes because of this ruling.

**Required tests** (in the certifier's required list, checked by OWN-12):

| Node id | Asserts |
|---|---|
| `tests/stages/test_s10_confirmation.py::test_s10_store_receives_tenant_and_execution_id` | Build the state with the shared scenario fixtures (R-T), with confirmation required. Inject a **recording fake store** that saves the exact arguments of every call. Run the real S10 handler. Assert exactly one store call, with `tenant_id == state.execution_context.tenant_id` and `execution_id == state.<S9 output>.execution_id`, compared to the values in the pipeline state (not literals copied from the fixture), and with the `Confirmation` passed unchanged. A test that only checks that S10 ran, or that a record exists, does not satisfy this ruling. |
| `tests/stages/test_s10_confirmation.py::test_s10_wrong_tenant_denies` | Store a confirmation for tenant A. Present it for consumption with tenant B (same user, same plan hash). It is denied the same way as the wrong-user case, and the stored record is still unconsumed. |
| `tests/contracts/test_confirmation_store.py::test_store_save_requires_tenant_and_execution_id` | For every store implementation: storing without `tenant_id` or without `execution_id` raises `TypeError`, and storing with either as an empty string raises `ValueError`. |

**Sabotage.** Add `SAB-11` (AUTOPILOT Part F). The patch removes the tenant
comparison when consuming, and `test_s10_wrong_tenant_denies` must then fail.
