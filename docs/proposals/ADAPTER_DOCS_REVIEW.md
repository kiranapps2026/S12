# Adapter documents: architecture review against the code

**Status: review for the owner (2026-10-03). Applied: the guide is corrected (revision 1.1, section B) and the
proposal through revision 12 (sections C and the A1/A3 recommendations); the code fixes A4 and A5 and the A1
per-operation start-up condition are implemented in `7e0b5bf`.** Scope: `docs/ADAPTER_IMPLEMENTATION_GUIDE.md` (the guide, commit
`4181585`), `docs/proposals/PROVIDER_API_PROFILES.md` (the proposal, revision 9) and
`docs/proposals/PROVIDER_ADAPTERS_CORRECTIONS.md`. Every finding was checked against the code on `s12-work`, not
against another document; each cites the line that decides it. The guide is not edited here (DR-08 schedules its v2;
this list is input for it). The proposal is corrected in its revision 10, and the corrections file where noted.

Severity: **High** = following the document gives a wrong or unsafe result, or the runtime refuses to start.
**Medium** = a contradiction or a missing rule a builder will trip on. **Low** = imprecise or stale wording.

## A. Code-level facts both documents get wrong or leave out

| # | Sev | Finding | Evidence | Consequence and fix |
|---|---|---|---|---|
| A1 | High | The start-up check accepts an adapter class only if **its own class body** defines `probe` and `observe` | `startup.py:25` (`"probe" in adapter_class.__dict__`) | An adapter that inherits them, as the proposal's "subclass of the engine" did, is refused (`unverifiable_mutation`) and the Worker Runtime does not start. The guide (§6.4, §12) says "overrides", which reads as inheritance. Fix (proposal rev 10): composition: each provider class defines `call`, `probe`, `observe` in its own body and delegates to an engine instance. Because that makes the class-level check pass for every operation, also extend the check to ask the adapter per operation. **Done (`7e0b5bf`)**: `verifiable_for()`; the catalog check waits for the first profile |
| A2 | High | The rollback inverse is called with the **create's** binding and params, and the inverse's own `kernel_op_id` | `rollback.py:109` (`GuardedCall(step.inverse_kernel_op_id, step.params, step.binding, …)`) | `binding.kernel_op_id` is the create, and `binding.effective_mutation` is `W`, not `D`. Anything that picks behaviour from the binding (the proposal's README §2.2 column choice) treats the delete as a write. Fix: use the `kernel_op_id` argument and the archetype's mutation; use the binding only for provider and version |
| A3 | High | `probe` and `observe` run under one guard deadline, `probe_timeout_s`, whose default is **0.5 s** | `reliability.py:150`, `:160`, `:230`, `:251`; DR-17 | Everything inside one probe or observation (credential, a stamp search, a GET per hit, a parent read) must fit in that one deadline; on expiry the result is `INCONCLUSIVE` / `observe_timeout`. Real providers need 5–10 s (DR-17). The proposal said hooks share `adapter_client_timeout_s`, which is wrong for these paths. Fix: per-request timeout = min(`adapter_client_timeout_s`, time left); at most three sequential requests per probe or observation |
| A4 | Medium | `Observation.observed_state` is typed `str \| None`, but the semantic layer's assessor takes `dict \| None`, and the Layer A README describes a dict of match results | `adapter_interface.py:48`; `verification.py:54` | Two contracts disagree; an adapter cannot satisfy both annotations. Fix in code (S12 file, not frozen): make it `dict \| None` holding only compared-key match results (DR-60). **Done (`7e0b5bf`)** |
| A5 | Medium | `CredentialProvider` declares only `credential()`, but M14 calls `credential_valid()` on it | `adapter_interface.py:124`; `live_authorization.py:81` | A provider written to the protocol has no `credential_valid` and is revoked on every step. The guide's §2 and §11 and the README describe the method as part of the protocol. Fix in code: add `credential_valid` to the protocol. **Done (`7e0b5bf`)**; the M14 golden's interface text already required it (`M14_revocation_cancel.py:21`) |
| A6 | Medium | Reads that time out are re-executed, never probed | `loop.py:421–425` (`read_reexecution_safe`) | The guide (§8 "On timeout → PENDING_PROBE") and the corrections file (§1 "after send → timeout, which leads to the probe") say every timeout probes. True for W, D, IRREVERSIBLE only |
| A7 | Medium | Verification's deterministic layer requires `result.data[identifier_field]` to be a non-empty string or int | `verification.py:75`; `verifiers.py:57` | Field name comes from the catalog (`id`, or `ref` after `ghl_crm.md` §0). The proposal's engine never reads the catalog, so it did not know the name. Fix: `identifier_field` in each `reads:` entry, kept equal to the catalog by the catalog check |
| A8 | Medium | `expected.properties` is the step's **full** params, unfiltered | `verifiers.py:46` | The guide says "filtered per op" (§3.3). Filtering is the adapter's job (`compare`) |
| A9 | Medium | Probes and observations take a slot from the **same** per-provider bulkhead as calls | `reliability.py:79`, `:224`, `:247` | The guide says "its own bulkhead slot (separate from the call slot)" (§3.2, §7.1). A slow probe reduces call capacity for that provider |
| A10 | Medium | No production path reaches an adapter yet: the Worker Runtime is composed only in tests, the guard holds one adapter, the API never admits a plan to S12, and `rollback_execution()` has no caller outside tests | DR-14, DR-42, DR-48; `grep rollback_execution src` | The guide's "A new adapter is additive … Nothing else" (§14) is not true today. The proposal now lists DR-14 and DR-48 as prerequisites of the first adapter milestone |

## B. The guide (`docs/ADAPTER_IMPLEMENTATION_GUIDE.md`)

Input for its v2 (DR-08). Line numbers are those of commit `4181585`. **All 22 are fixed in the guide's revision 1.1
(2026-10-03)**, together with the section A facts that concern it (A2, A3, A4, A5, A6, A7, A8, A9, A10) and one more
found while editing: §6.1 said `MockAdapter` never raises, but its `raise_exception` mode raises on purpose. Sections
the guide still lacks are listed in its new §17.

| # | Sev | Line | Says | Code says | Fix |
|---|---|---|---|---|---|
| B1 | High | 125 | Observe is called "after a successful probe" | `_settle_success` verifies every successful W/D/IRREVERSIBLE call (`loop.py` `_settle_success` → `_verify`), and after a probe | Observe runs on every verification; the probe path is the case with `identifier=None` |
| B2 | High | 417 | Verification calls `guard.probe()` | `verification.py` calls only `guard.observe` | Remove the probe from the verification flow |
| B3 | High | 423 vs 151 | FAIL → dead letter, budget **LOCKED** (§8) vs FAIL → budget **released** (§3.3) | `loop.py:585`: FAILED, budget released, dead letter `data` / `NONE` | §3.3 is right; fix §8, and FAIL comes from any layer, not only semantic |
| B4 | High | 610 | Catalog entry has `observation.compared_fields` | `catalog.py:20`: `OBS_FIELDS` = method, identifier_field, expects_absent; anything else is rejected | Compared fields live in the provider spec (and the proposal's `compare`) |
| B5 | High | 609 | A binding row carries `effective_risk`, `effective_mutation` | `catalog.py:19`: `BIND_FIELDS` has neither; S5 computes them | Remove |
| B6 | High | 521–525 | Skeleton resolves the credential **before** checking `connection_id is None` | README §5: `no_connection` before anything | A provider raising for `None` returns `not_dispatched`, which is retryable; swap the order |
| B7 | High | 660 | "one class file, one credential file, registry entries. Nothing else" | A10 | List DR-14, DR-42, DR-48 as prerequisites |
| B8 | Medium | 418 | Deterministic layer: `result.data["id"]` "matches expected" | `verification.py:75` checks presence and type only | "is present" |
| B9 | Medium | 427 | Dead letter `retry_mode`: NONE for W/D/IRREVERSIBLE, PROBE for R | `loop.py`: `PROBE` after probe exhaustion, `VERIFY` after verification UNKNOWN, `NONE` for data failures and rollbacks; reads are re-executed, never probed | Replace with the three cases |
| B10 | Medium | 411 | Every timeout → PENDING_PROBE | A6 | Reads: re-executed |
| B11 | Medium | 166 | The inverse runs when an operator calls `retry_dead_letter` with a rollback resolution | `rollback.py:1`: a separate, explicit `rollback_execution()`; first `confirm_executed`; called with the create's binding (A2) | Describe `rollback_execution` and `confirm_executed`; say the binding is the create's |
| B12 | Medium | 712 | `_settle_success` → COMPLETED → S13 verification | Verification runs first; commit only on PASS (`loop.py` `_settle_success`) | Reverse the order |
| B13 | Medium | 56 | An adapter may return any of the eight `ErrorClass` values | README §1: `circuit_open`, `retry_storm` (and `timeout` as a class) belong to the guard; adapters use five classes or `status="timeout"` | Restrict the list |
| B14 | Medium | 95, 345 | Probe and observe take their own, separate bulkhead slot | A9 | Same pool |
| B15 | Medium | 273 | No settings reads | README §1: the client timeout is `ExecutionSettings.adapter_client_timeout_s` | Settings are injected at construction, not read |
| B16 | Medium | 595 vs README §5 | `credential()` never raises; return a string meaning "not available" | README §5 maps a raise to `not_dispatched`; the protocol says "never raise" | Pick one; the safe reading is both: the provider should not raise, the adapter treats a raise as `not_dispatched` |
| B17 | Medium | 135 | `properties` "filtered per op" | A8 | Full params; the adapter compares its own fields |
| B18 | Medium | §6.4, 612 | Start-up refuses an adapter that does not "override" probe and observe | A1 | "defines them in its own class body" |
| B19 | Low | 17 | Adapters plug in "the way the Layer A (GoHighLevel, Gmail) adapters do" | No GHL or Gmail adapter exists in `src`; Layer A holds specs | "will plug in" |
| B20 | Low | 48 | Example kernel ops `vision.analyze_image`, `market.signal_query` | Not in any catalog; the catalog has `crm.*`, `mail.*` | Use catalog examples |
| B21 | Low | §4.2 | "409 duplicate with our key" has a read (R) column result | A read cannot create a duplicate | Drop the R cell |
| B22 | Low | §2, §11 | `CredentialProvider` has `credential_valid` | A5 | Note the protocol gap until it is fixed |

## C. The proposal (`PROVIDER_API_PROFILES.md`, revision 9 → 10)

All fixed in revision 10.

| # | Sev | Finding | Fix |
|---|---|---|---|
| C1 | High | "A provider adapter is a subclass of the engine" fails the start-up check (A1) | Composition: the provider class defines `call`, `probe`, `observe` and delegates to its engine; per-operation verifiability exposed for an extended start-up check |
| C2 | High | "The engine picks the README §2.2 column from `binding.effective_mutation`" is wrong for the inverse (A2) | Column from the archetype's mutation; profile lookup by the `kernel_op_id` argument |
| C3 | High | Hooks "share `adapter_client_timeout_s`" ignores the probe/observe deadline (A3) | Deadline section: `probe_timeout_s` bounds the whole probe or observation; per-request timeout is the smaller of the two; at most three sequential requests |
| C4 | Medium | The engine composes the identifier but did not know the catalog field name it must write (A7) | `identifier_field` in `reads:`; the engine writes `data[identifier_field]`; catalog check keeps it equal |
| C5 | Medium | `update` observe on the probe path had no identifier and no rule | Take the id from `expected.properties` (the step's params) |
| C6 | Medium | `observed_state` format unspecified, and the contract type disagrees (A4) | Engine emits only compared-key match results and `stamp_ok`, never values (DR-60); type fix listed as an owner decision |
| C7 | Medium | The credential section did not mention `credential_valid` (A5) | Added, with the protocol gap |
| C8 | Medium | Prerequisites missing: no production runtime (DR-14), no API path to S12 (DR-48) | Added to the status paragraph and owner decisions |

## D. The corrections file (`PROVIDER_ADAPTERS_CORRECTIONS.md`)

| # | Sev | Finding | Fix |
|---|---|---|---|
| D1 | Medium | §1 row: "after send → `status="timeout"`, which leads to the probe" | Fixed: for W, D and IRREVERSIBLE; a read is re-executed (A6) |

The rest of the file was rechecked against the code and stands.

## E. Recommended order

1. Owner decisions on A1 (composition plus a per-operation start-up check) and A3 (deadline, DR-17 setting), because
   both shape the first adapter.
   The recommended answers are in `PROVIDER_API_PROFILES.md` ("Per-operation verifiability", "Deadlines", owner
   decisions 5 and 11), as revised in revision 12: the client timeout is 8 s, so the three requests a call can make
   fit in the 30 s step timeout.
2. ~~The two small code fixes (A4, A5)~~ and the A1 per-operation start-up condition: done in `7e0b5bf`. Verified:
   goldens M01–M21 896 passed, `tests_agent` 110 (9 new), `tests/` 836, `owner_certify_s12.py --milestone M21 --fast`
   27/27 PASS.
3. The guide's v2 (DR-08): section B is applied (revision 1.1); what remains is the guide's §17.
4. Then the first adapter, which also tests the proposal against real recorded responses.
