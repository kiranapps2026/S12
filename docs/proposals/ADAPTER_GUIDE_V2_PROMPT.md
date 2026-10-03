# Prompt: write the Adapter Implementation Guide v2 (DR-08)

Hand everything below the line to an agent working in this repository on branch `adapters-work`.

---

You are writing **`docs/ADAPTER_IMPLEMENTATION_GUIDE.md` version 2**, the guide a developer or agent follows to build a
real provider adapter for the S12–S15 execution kernel (certified at tag `s12-s15-certified`, commit `c844cdd`). Work
on branch `adapters-work` only. Never push to `s12-work`.

## Goal

One document from which a developer can build, test and enable a provider adapter (first: GoHighLevel, catalog
provider `crm`) without reading anything else first, and in which **every statement about the kernel is true of the
code**. Version 1.1 fixed 22 errors but still lacks the sections listed in its §17 (DR-08).

## Sources, in order of authority

1. **The code.** It wins every disagreement. Read before writing:
   `src/contracts/adapter_interface.py`, `src/contracts/step_execution.py`, `src/contracts/frozen_binding.py`,
   `src/engine/stages/s12_execute/{reliability,attempts,loop,retry_policy,settings,startup}.py`,
   `src/engine/stages/s13_reconciliation/{probe,verification}.py`, `src/engine/stages/s12_entry/verifiers.py`,
   `src/engine/stages/s14_dead_letter/{rollback,retry}.py`, `src/adapters/postgres/{catalog,live_authorization}.py`,
   `src/adapters/runtime/mock_adapter.py`, `src/bootstrap.py`.
2. **The pinned goldens** (`tests_golden/s12/M10–M21`): their docstrings state the interfaces. Read only; never edit.
3. **The Layer A standard**: `batch_bundles/LAYER_A/ADAPTER_SPECS/README.md`, `TEMPLATE.md`, `ghl_crm.md`,
   `gmail_mail.md`.
4. **The reviews and proposals**: `docs/proposals/ADAPTER_DOCS_REVIEW.md` (findings A1–A10, B1–B22, with file:line
   evidence), `docs/proposals/PROVIDER_API_PROFILES.md` (revision 12: engine, archetypes, hooks, profile, deadlines,
   version rule), `docs/proposals/PROVIDER_ADAPTERS_CORRECTIONS.md`.
5. **Registers**: `docs/gates/S12_DEFERRED_REGISTER.md` (DR-08, DR-11, DR-14, DR-16, DR-17, DR-38–DR-43, DR-48, DR-60),
   `docs/gates/S12_CERTIFICATION_REPORT.md` §4 and §8.
6. **Real provider evidence**: GHL captures from `tools/dev/ghl_capture.py`, if present under
   `tests_agent/fixtures/providers/ghl/captures/`. Only these clear a VERIFY mark.

Do not use `docs/implementation/PROVIDER_ADAPTERS.md` as a source for provider facts (pinned, partly wrong; see the
corrections file). Do not use memory or general knowledge of any provider API.

## Rules

- **Check every kernel claim against the code** and cite it as `path:line`. If the code and a document disagree, write
  what the code does and add the disagreement to a "Known gaps" list; do not resolve it by editing code.
- **Proposal vs. fact.** The engine / archetypes / profile design is a proposal until the owner accepts it. Write the
  guide so it is correct today (an adapter is one class implementing `BaseAdapter`), and describe the proposed
  structure in a clearly marked section, citing `PROVIDER_API_PROFILES.md`. Already implemented and safe to state as
  fact: the per-operation start-up check (`startup.verifiable_for`, `verifiable_operations()`),
  `CredentialProvider.credential_valid`, `Observation.observed_state: dict | None` (commit `e3e9cae`).
- **Provider facts carry their status**: VERIFY until a recorded response in this repository confirms them; then cite
  the fixture file.
- **No hand-written counts or statuses** (operation status lives only in the catalog's `truth_state`).
- Never edit `tests_golden/**`, `docs/implementation/**`, pinned files in `docs/gates/`, or frozen S0–S11 source.
- Plain, direct English; short sentences; tables for rules and mappings; no marketing tone.

## Required structure

1. **Purpose, status, how to read this.** Version, date, branch, what changed since 1.1.
2. **What an adapter is, and is not.** One class plus a credential provider; what the kernel owns (retry, breaker,
   bulkhead, budget, ledger, probe scheduling, verification, rollback, dead letters).
3. **Prerequisites before production.** DR-14 (Worker Runtime composition), DR-42 (one adapter per guard / routing),
   DR-48 (API path to S12), DR-11 / MC-058 (credential store), DR-17 (probe timeout), DR-39 (params), DR-40 (step
   data in S15), DR-21 (semantic assessor). Say which block testing and which block production.
4. **The contracts.** Exact signatures and types from `adapter_interface.py` and `step_execution.py`; what each field
   means; `GuardedCall`; what the guard's `_normalise` does to each status and class.
5. **The four call paths**, each with entry point, timing, what is passed, what must come back, failure handling:
   call, probe, observe, inverse. Include: reads re-executed not probed; observe on every verification; the inverse
   carries the create's binding; `probe_timeout_s` bounds the whole probe or observation.
6. **Error classification.** Before-send / after-send rule, transport table, HTTP table, the five adapter classes,
   breaker interaction, provider-specific rows go in the provider spec.
7. **Idempotency, stamping and probes.** Key format, stamp vs. provider key, the four lookup methods, when
   `NOT_EXECUTED` is allowed, the two strengths of the "is this record ours" check.
8. **Observe and verification.** The spec dict, identifier field and the deterministic layer, compared fields,
   absent-means-empty, `observed_state` content (DR-60), verdict mapping, attempts.
9. **Credentials.** The credential document, `credential_valid`, connection settings, no fallbacks.
10. **Deadlines and settings.** `step_timeout_s`, `adapter_client_timeout_s`, `probe_timeout_s`, C37, recommended
    values and the three-request budget (from the proposal, marked as recommended).
11. **Start-up checks.** `privileged_role`; `unverifiable_mutation` with the own-class-body rule and the
    per-operation `verifiable_operations()` condition.
12. **Registry and catalog.** The exact fields the loader accepts, bindings, `truth_state` and DR-41 enablement,
    `registry_readiness.py`.
13. **Provider spec (Layer A).** What a provider file must contain; "Cannot do" and "Fails silently".
14. **Proposed structure (not yet accepted).** Engine, archetypes, hooks, profile, version rule, with owner decisions
    pending. Keep it to what a builder needs; link the proposal for the rest.
15. **Testing.** Recorded-response tests (fixture layout), how to capture real responses with
    `tools/dev/ghl_capture.py`, live smoke tests (opt-in), the M12–M21 journeys with the adapter wired into the test
    composition, sabotage cases, which suites must stay green and how to run them (Postgres, `TEST_DATABASE_URL`,
    `PYTHONPATH`).
16. **Worked example: GoHighLevel.** End to end for `crm.contact_create` and `crm.contact_delete`: request, stamp,
    classification, probe, observe, inverse, with the fixtures that prove each step.
17. **Step-by-step checklist** for adding a provider, ending with owner sign-off and `truth_state` enablement.
18. **Known gaps** (code vs. documents) and **document index**.

## Acceptance

- Every kernel statement has a `path:line` citation that a reviewer can open and confirm.
- Every finding in `ADAPTER_DOCS_REVIEW.md` sections A and B is either reflected or listed under Known gaps.
- No statement contradicts the code, the pinned goldens or the Layer A README; where the README and the code differ,
  the code is stated and the difference listed.
- Run `python tools/doc_consistency.py` (must exit 0) and, if any example code is included, make sure it imports and
  runs against the current contracts.
- Commit on `adapters-work` with a message that lists what changed, and report: sections written, gaps found, and any
  claim you could not verify.
