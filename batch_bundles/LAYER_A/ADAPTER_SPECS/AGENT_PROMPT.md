# Agent prompt: implement the Layer A adapters from these specs

Paste everything in the block below into the agent session. It assumes the agent works on its own machine, with its
own copy of the S12 code, on branch `s12-work`.

````text
ROLE
You are implementing Layer A provider adapters for the S12 execution core, following the adapter
specifications in the repo. Work on branch `s12-work` only. Do not open pull requests.

STEP 0 — SYNC AND READ (no code yet)
1. git fetch origin s12-work && git pull origin s12-work
2. Read, in this order, completely:
   - batch_bundles/LAYER_A/ADAPTER_SPECS/README.md    (the standard; §1.1 and §8 are mandatory)
   - batch_bundles/LAYER_A/ADAPTER_SPECS/ghl_crm.md    (GoHighLevel as provider `crm`)
   - batch_bundles/LAYER_A/ADAPTER_SPECS/gmail_mail.md (Gmail as provider `mail`)
   - batch_bundles/LAYER_A/ADAPTER_SPECS/TEMPLATE.md
   - docs/catalog/catalog.yaml (the crm.* and mail.* rows)
3. Record the baseline on YOUR machine: the full golden suite M10–M21 (pass/fail counts, sabotage count),
   `PYTHONPATH=src python tools/owner_certify.py` and `python tools/owner_certify_s12.py`. Save the results
   for your report.

STEP 1 — VERIFY README §1.1 AGAINST YOUR CODE (stop point)
The specs were checked against the batch_bundles B3–B5 reference code. Your machine's code may differ.
Confirm each item below in YOUR src/ and quote file:line for each:
  a. guard.probe returns only a ProbeOutcome. After EXECUTED_SUCCESS, verification runs with result=None,
     so spec["identifier"] is None.
  b. build_verifier sets expected = {"exists": True, "properties": dict(step.params)} for W and
     IRREVERSIBLE, and {"exists": False} for D.
  c. rollback_execution calls the inverse op through guard.call with the ORIGINAL step params and the key
     "{request_id}:{plan_step_id}:inverse": one attempt, InverseBudget, no probe.
  d. ExecutionContext and CallMeta carry no dispatch timestamp.
  e. probe_backoff_s and probe_max_attempts are global LoopSettings (the first probe runs immediately,
     then sleep b*n).
  f. CredentialProvider.credential(...) returns str; live authorization (M14) uses credential_valid.
  g. ReliabilityGuard._normalise recomputes retryable, drops data on timeout, and maps an unknown
     error_class to adapter_defect. The deadline is enforced by cancellation.
If ANY item differs: STOP. Report the difference with file:line, and write no adapter code until the
owner answers. Do not "fix" S12 code to match the specs.

HARD RULES (all phases)
- Never edit tests_golden/**, the frozen S0–S11 code, or the M10–M21 engine code (src/engine/**,
  src/contracts/**, src/adapters/postgres/**, src/adapters/runtime/**). Adapters live in NEW modules:
  src/engines/crm/, src/engines/mail/, and a shared helper module src/engines/_http/ if needed.
- Never bypass RLS. Never print .env values, tokens, credential documents or provider error bodies.
- No real network in tests_agent/: replay only through httpx.MockTransport. Live calls only in
  tests_live/, opt-in by env vars, sandbox accounts only, never customer data.
- No retries inside adapters (httpx transport retries=0) and no deadline of their own above the step.
  Catch Exception, never BaseException or CancelledError. Never mutate params. Never raise from call,
  probe or observe.
- Never call POST /contacts/upsert (GHL). Never delete a resource that does not carry our stamp.
- On failure, `data` is at most {"provider_status", "provider_code"}.
- Commit after each phase with a clear message. Push only to origin s12-work.

PHASE A — SHARED TEST AND HTTP INFRASTRUCTURE
1. The fixture format tests_agent/fixtures/providers/<provider>/<op>/<case>.json (README §6
   "Recording"), a fixture loader, and a scrubber with its own tests. The scrubber replaces
   Authorization, cookies, tokens, e-mails, phones, names, and location/account ids with stable fakes.
2. A credential-document parser for {"token", "settings": {...}} (README §5):
   - missing connection_id → client_error / no_connection;
   - credential() raises → not_dispatched;
   - missing settings → client_error / connection_incomplete.
   Zero requests are sent in all three cases.
3. A classifier helper implementing README §2.1 (transport errors) and §2.2 (HTTP, R vs M columns).
   Check ConnectError, ConnectTimeout and PoolTimeout BEFORE NetworkError. Unit-test every row.
Exit: tests green; golden counts unchanged.

PHASE B — GHL ADAPTER (ghl_crm.md is the spec; follow it section by section)
1. CrmAdapter(BaseAdapter) in src/engines/crm/adapter.py:
   - all 11 catalog ops (§1);
   - stamp and step_key exactly as in §0;
   - locationId only from the credential document;
   - data["ref"] for notes and tasks.
2. The error mapping of §2, including the four-step duplicate rule, and 404 on DELETE → ok with
   already_absent.
3. probe() per §3:
   - contact_create never returns NOT_EXECUTED;
   - notes and tasks return NOT_EXECUTED only behind the config flag `ghl_lists_read_your_writes`
     (default False; set it to True only after measurement L2 passes);
   - updates never return NOT_EXECUTED.
4. Inverse handling per §3.1:
   - detect the ":inverse" key suffix;
   - locate the target by the stamp of the step key;
   - act only on exactly one target; otherwise return client_error with inverse_target_not_found or
     inverse_target_ambiguous, and send no destructive request.
5. observe() per §4, including identifier=None and the compared-field lists. Ignore any other keys in
   properties.
6. Tests: tests_agent/test_adapter_ghl.py with README matrix rows 1–16, P1–P5, O1–O6, I1–I3, S1–S3 and
   G1–G12. Until real recordings exist, build fixtures from the spec, mark each `"synthetic": true`, and
   list them in your report.
Exit: all GHL tests green; golden counts unchanged; grep proves no "/upsert", no "except BaseException",
and no logging of tokens.

PHASE C — CATALOG CHANGE (separate commit; stop point if blocked)
Set `identifier_field: ref` for crm.note_create, crm.note_delete, crm.task_create, crm.task_update and
crm.task_delete (ghl_crm.md §0). Then run tools/registry_readiness.py (it must exit 0) and
owner_certify_s12.py.
If the catalog is pinned or frozen, or a certifier row now fails: revert, STOP and report.
Do not change provider, engine_module or adapter_class.

PHASE D — INTEGRATION CHECK
Copy the M12 `_deps` wiring into tests_agent/ (never edit golden files). Wire CrmAdapter with recorded
transports and run the M12–M21 journeys for these cases:
- create succeeds;
- create times out (ReadTimeout), probe P1 → EXECUTED_SUCCESS, then observe with identifier=None → PASS;
- create times out (ReadTimeout), empty search → INCONCLUSIVE ×3 → PROBE dead letter;
- 429;
- 401 → credential_valid false → M14 blocks the next step;
- rollback_execution of a completed contact_create (I1), and of one whose target is missing
  (I2 → rollback dead letter).
Exit: all green; golden suite and both certifiers unchanged from the Step 0 baseline.

PHASE E — GMAIL ADAPTER (built, NOT enabled)
Build MailAdapter per gmail_mail.md:
- MIME build and guards (§1);
- error mapping with Google reason codes (§2);
- Message-ID derivation, and a probe that never returns NOT_EXECUTED (§3);
- observe with identifier=None (§4);
- tests: the rows from §6 plus M1–M8.
Do not add mail.email_send to any allow-list.

PHASE F — LIVE SMOKE AND MEASUREMENTS (only if the owner supplies sandbox credentials)
1. Write tests_live/test_ghl_live.py and tests_live/test_gmail_live.py, opt-in by env vars.
2. Run measurements L1–L3 for each provider.
3. Replace the synthetic fixtures with scrubbed recordings.
4. For every VERIFY item you checked, edit the spec file: replace "VERIFY" with
   "verified <date>: <fixture path>".
If a recording contradicts the spec: STOP and report before changing adapter behaviour.
If no credentials are supplied: skip Phase F and say so.

STOP AND ASK the owner (do not decide yourself) when:
- any Step 1 item differs from your code;
- a golden test, sabotage patch or certifier row changes state;
- the catalog edit (Phase C) is blocked;
- a recording contradicts a spec rule (error class, duplicate behaviour, consistency, Message-ID);
- a spec rule seems to need a change in frozen, golden or M10–M21 code;
- any owner question (Q1–Q6 in ghl_crm.md, Q1–Q7 in gmail_mail.md) blocks you and its default does not
  fit.
Do not proceed past a stop point on your own judgement.

DO NOT
- enable mail.email_send, or GHL update/delete as planned steps;
- store or commit any real token, credential document or customer data (MC-058 is open);
- relax a probe rule to "make a test pass" (NOT_EXECUTED rules are safety rules);
- delete, skip or weaken tests, golden or agent;
- reuse the v1 GHL API (rest.gohighlevel.com) described in PROVIDER_ADAPTERS.md.

REPORT (at each stop point and at the end), in this order:
1. Baseline vs current: golden pass/fail, sabotage, owner_certify, owner_certify_s12.
2. Step 1 results: items a–g with file:line, and any differences.
3. Per phase: done / partial / not started, with commits (hash and message).
4. The test matrix: each row id → test name → pass/fail; synthetic vs recorded fixtures.
5. VERIFY items resolved (with fixture paths) and still open.
6. Deviations from the specs, each with its reason and the owner decision it needs.
7. Owner questions you relied on a default for.
````

## Notes for the owner

- **Stop points:** Step 1, Phase C and Phase F. Expect a report at each.
- **Synthetic fixtures:** Phases A–E can be finished with synthetic fixtures. Only Phase F needs sandbox credentials
  (GHL sandbox location token; Gmail sandbox mailbox).
- **Go-live gates:** they are unchanged by this prompt (README §8): MC-058, the catalog change, every VERIFY checked,
  and for Gmail the D4 human channel.
