# S0–S11 Rejection List

Items that must pass before S0–S11 is considered complete.
Generated during review; items correspond to architecture contract requirements.

## R0 — Stage-Map Alignment

- [ ] Item 0: Duplicate S5 handlers merged — only one `handle()` for S5
- [ ] Item 1: Lock acquisition moved out of S5 (lock belongs in worker runtime, not stage handler)
- [ ] Item 2: Kill switch folded into S8 as first check (S10 kill_switch handler removed)
- [ ] Item 3: `canonical_plan_digest()` is the single source of truth for plan hashing
- [ ] Item 4: `_replace_fields()` enforces ownership + write-once (S11 owns `execution_manifest` + `validation_result`)
- [ ] Item 5: Journey test runs S0→S11 with real handlers; asserts `execution_id != request_id`

## R1 — Contract Enforcement

- [ ] Item 0: `canonical_plan_digest()` has explicit type conversion (datetime → ISO-8601 UTC, Enum → value, Decimal → reject, tuple → list)
- [ ] Item 1: `canonical_plan_digest()` excluded fields come from a named constant
- [ ] Item 2: Field-coverage test proves every Plan field except excluded ones changes the digest
- [ ] Item 3: S11 DENY path: `execution_manifest` stays `None` on validation failure

## R2 — Journey Completeness

- [ ] Item 0: Journey runs S0→S11 with real S10 (confirmation binds to plan_hash)
- [ ] Item 1: Journey asserts `execution_id != request_id`
- [ ] Item 2: Journey asserts `confirmation.plan_hash == plan_hash`
- [ ] Item 3: Journey asserts `manifest.execution_id == plan.execution_id`

## R3 — Type Documentation

- [ ] Item 0: Answer whether PENDING SPEC markers were removed (types implemented) or restored
- [ ] Item 1: Answer whether stage-output types were added to DATA_CONTRACTS
