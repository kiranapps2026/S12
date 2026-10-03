# Provider API profiles — one data file for the provider-API facts that change

**Status: proposal for the owner (revision 5, 2026-10-03). No code, pinned document, catalog or milestone is changed by
it.** It applies when the first new-adapter milestone starts, after the `s12-s15-certified` tag. S12–S15 does not call
real providers (`S12_S15_EXECUTION_GATE.md:18`) and runs on `MockAdapter`, so no milestone card, golden test or gate row
moves.

It builds on, and must agree with:

- `batch_bundles/LAYER_A/ADAPTER_SPECS/` (the Layer A specs): `README.md` (the standard: contract §1, error rules §2,
  probe §3, credentials §5, tests §6, definition of done §7), `TEMPLATE.md`, and the per-provider files `ghl_crm.md`
  and `gmail_mail.md`;
- `docs/catalog/catalog.yaml` and its loader `src/adapters/postgres/catalog.py`;
- the ADAPTERS items of `docs/gates/S12_DEFERRED_REGISTER.md` (DR-08, DR-38, DR-41, DR-42).

It does not rely on `docs/ADAPTER_IMPLEMENTATION_GUIDE.md`: DR-08 records that the guide has about 15 factual errors
and that agents use the Layer A README and template until its v2.

## Problem

Some provider-API facts change over time and today have no machine-readable home: the API version and how it is sent,
the base URL, page size, whether the provider takes an idempotency key, endpoints, deprecation dates. The Layer A spec
holds them in prose (its header table), so an API change means editing prose and adapter code by hand, with nothing
checking that the two agree. They cannot go into the catalog: the loader rejects every kernel-op field outside a fixed
set (`catalog.py:17`).

## Proposal

One small data file per provider, the **provider profile**, shipped with the adapter. It holds only the facts that
change with the provider's API and are plain values. Logic stays in code and its rules stay in the Layer A spec.
Capabilities, bindings, `catalog.yaml`, the planner, S5, the guard and every frozen contract stay as they are.

| Layer | Change |
|---|---|
| Capability, binding, `FrozenBindingIdentity` | None |
| `catalog.yaml` kernel op (mutation, risk, cost, `timeout_seconds`, `retry_safety`, inverse, observation) | None: these stay registry facts (A4) |
| `AdapterResult`, `CallMeta`, `BaseAdapter`, `CredentialProvider` | None (README §1) |
| Guard, breaker, bulkhead, retry policy | None |
| Layer A spec | Its header values (version, base URL, idempotency, page size) move to the profile; the spec links to it and keeps the prose, the VERIFY marks and the rules |
| **Provider profile** (new) | `src/engines/<provider>/profile.yaml`, next to the adapter (`ghl_crm.md` puts the `crm` adapter in `src/engines/crm/adapter.py`) |

**Why next to the adapter and not under `docs/catalog/`:** the adapter is its only reader, so the file is deployed with
the code that reads it. The catalog goes to the database through `load_catalog.py`, but the profile does not. `<provider>`
is the catalog's `provider` id (`crm`, `mail`), the same key the breaker and bulkhead use (CONF-022).

## Lessons from the earlier app

An earlier app (OpenClaw) built Notion and Airtable adapters and failed on complexity: about 30 artefact files per
provider, two ID systems, alias files, business-entity and composite matrices, per-provider policy YAMLs, and status
counts written by hand. Its documents said every binding was verified, while its own bindings file showed 10
verified and 18 only proposed.
Its reviews (the Notion tool-level appendix, the Notion backend reference, the Airtable architecture sections 1–10)
and its two live-tested API references (Airtable 2026-08-15, Notion 2026-08-20) still hold useful provider facts. This
proposal keeps the facts and turns the failures into eight guardrails:

| Failure in the earlier app | Guardrail here |
|---|---|
| Status written by hand in several documents, then contradicting itself | Operation status lives in one place, the catalog's `truth_state` (DR-41 enables one operation at a time). No profile or document states a count or a status by hand |
| "Verified" meant "checked against the docs", not "ran against the provider" | The profile records both separately (`verified.docs`, `verified.recorded`); only a recorded sandbox response clears a Layer A VERIFY mark |
| Capabilities mapped for every endpoint, most never used or tested | Only operations the Layer A spec defines get a catalog row and a `kernels:` entry: its allow-list, plus the operations kept for later or for rollback (`ghl_crm.md` keeps `update` and planned `delete` off the launch list, and the deletes as inverses). Each is enabled for production on its own `truth_state` (DR-41). Everything else stays unbound, with a reason in the spec's "Cannot do" section |
| Two ID systems (UC-, NC-) plus aliases and endpoint ids | One id: the catalog kernel op id. No aliases, no endpoint-id layer |
| Per-provider frameworks: policy YAMLs, undo journals, assertion modules, reconciliation engines, client retries, in-adapter breakers | None. The S12 kernel already owns retry, breaker, ledger, verification and rollback; an adapter is one class, one credential provider, one profile |
| Silent provider behaviour hidden by the adapter (endpoint remapping, dropped fields) | The adapter never hides one. It refuses before send or lets verification see it (see "Provider behaviours the adapter must not hide") |
| A direct tool path (`notion_execute`) that called the adapter with no planner, no step graph and no ledger, plus silent fallbacks (a "degraded" adapter registered without a token, a resolver that fell back to another provider, a fresh random idempotency key per request) | Every adapter call goes through the guard; no API or tool path calls an adapter directly (README §7 scan). Missing credentials, an unknown provider or a missing key are refusals, never fallbacks. The idempotency key is always `call_meta.idempotency_key`, never generated |
| Limitations declared from calls that failed because of the app's own request: "append children returns 400 for integrations" came from sending `POST`, while Notion's append is `PATCH /v1/blocks/{id}/children` | A limitation enters a spec only with the provider's docs and a recorded response that show it. A failing call is first treated as a defect in our request. Missing capabilities are never emulated |

## What stays out of the profile (on purpose)

| Not in the profile | Where it stays | Why |
|---|---|---|
| Error mapping | adapter code + Layer A spec §2 | Real mappings match on body text, differ for reads and mutations, set `provider_code`, and sometimes need a lookup (the GHL duplicate-contact rule). A status-to-class table cannot express that, and would be a second source of truth |
| Probe, observe and inverse logic | adapter code + spec §3, §3.1, §4 | Consistency conditions per operation (search-index lag, read-your-writes) are logic, not values |
| Timeouts and retries | `ExecutionSettings.adapter_client_timeout_s` (< `step_timeout_s`, C37); `retry_policy` | The adapter never sets its own deadline or retries (README §1) |
| Mutation, risk, cost, `retry_safety`, inverse, observation | `catalog.yaml` | Registry facts (A4) |
| Credentials and per-connection settings | the credential document (below) | Secret |
| Breaker threshold, cooldown, bulkhead size | guard wiring | S12 applies one setting to every provider today (`InProcessCircuitBreaker()` defaults, `bootstrap.py:75`; one `InProcessBulkhead(max_concurrent)`), keyed by `binding.provider`. The profile records the provider's documented limits for sizing (`limits`), but does not configure the guard |
| Per-key breakers (Airtable per base, GHL per location) | not possible today | The breaker is keyed by provider only (CONF-022; `ghl_crm.md` Q3). A change needs a CONF ruling |
| Log redaction | not needed | `data` on success carries only identifiers and named fields; on failure only `provider_status` and `provider_code`; bodies are never kept (README §1, M18) |

## Profile fields

Defaults are chosen to fail safe where the field affects behaviour: one item per page, no pagination, and
stamping rather than trusting a provider key. A field without a default is required.

### Provider-wide

| Field | Values | Default | Example |
|---|---|---|---|
| `provider` | catalog provider id | required | `crm` |
| `profile_format` | int, the format of this file | required | `1` |
| `binding_version` | the catalog `versions.binding` this profile was certified with | required | `bind-1` (see "Version rule") |
| `api_version` | the provider's own string | required | `"2021-07-28"` (GHL), `"2025-09-03"` (Notion), `"v0"` (Airtable) |
| `version_scheme` | `header` / `path` / `none` | `none` | GHL, Notion: `header`; Airtable: `path` |
| `version_header` | header name, for `header` | — | `Version`, `Notion-Version` |
| `base_url` | URL; for `path`, it contains `{api_version}` | required | `https://services.leadconnectorhq.com`, `https://api.airtable.com/{api_version}` |
| `pagination` | `cursor` / `offset_token` / `page` / `link_header` / `page_token` / `none` | `none` | GHL search `cursor`, Airtable `offset_token`, Google `page_token` |
| `max_page_size` | int | `1` | `100` |
| `idempotency` | `native_header` / `body_field` / `stamp` | `stamp` | Stripe `native_header`; GHL, Airtable `stamp` (README §1: no provider key → stamp the resource) |
| `idempotency_header` / `idempotency_field` | name, for `native_header` / `body_field` | — | `Idempotency-Key` |
| `max_url_length` | int | none | Airtable `16000` (switch a read to its POST form above it) |
| `limits` | free-form documented limits, informational | `{}` | `{burst: "100 per 10 s per location", bulkhead: 8}` |
| `verified` | `{docs: <date and source of the provider docs checked> or null, recorded: <date of the last recorded sandbox response> or null}` | required | `{docs: "2026-08-15 Airtable API reference", recorded: null}` |
| `review_by` | date by which the provider's docs and changelog are checked again | required | `2026-11-15` |

`base_url_source` from revision 1 is gone: when the base URL differs per tenant (Salesforce `instance_url`, HubSpot
EU, Shopify shop), the profile's `base_url` holds a `{settings.<name>}` placeholder that the adapter fills from the
credential document, e.g. `https://{settings.shop}.myshopify.com/admin/api/{api_version}`.

### `kernels:` block

Keyed by catalog kernel op id. An entry states only what it needs; most need two or three lines.

| Field | Values | Default |
|---|---|---|
| `method`, `endpoint` | HTTP method, path template: `{name}` is a step param, `{settings.name}` a credential-document setting | required |
| `api_version` | override, only when this kernel uses a different version (Notion runs two: `2025-09-03`, and `2026-03-11` for its markdown endpoints) | profile's |
| `pagination` | `none` to switch paging off | profile's (reads only) |
| `update_semantics` | `patch_merge` for an update op, `put_replace` for a replace op (a label; the request code follows the spec) | — |
| `probe_method` | `provider_key` / `deterministic_id` / `stamp` / `natural_key` (README §3) / `by_id` (deletes and updates) | required for W, D, IRREVERSIBLE |
| `marker` | where the stamp lives, for `stamp`: e.g. `custom_field:s12_ref`, `body_suffix` | — |
| `required_scopes` | list | `[]` |
| `deprecated_at`, `sunset_at`, `replacement_kernel_op_id` | dates, kernel op id | — |

Earlier revisions also had `batch_max_items`, `partial_success`, `async_mode`, `concurrency_control`, `null_means`,
`field_reference` and `redact_paths`. They are dropped, because each one either had no defined S12 behaviour or broke a
rule:

- **Batches.** One step has one idempotency key, one stamp, one probe and one inverse, and `AdapterResult.status` is
  only `ok` / `error` / `timeout`, so a 10-record create that half-succeeds has no correct result. Every operation
  handles one resource (a list returns one page). A single-record write that is only partly applied is covered under
  "Provider behaviours the adapter must not hide".
- **`long_running` / `bulk_job`.** A 202 with an operation id has no path through verification. Only synchronous
  operations are supported.
- **ETag / `If-Match`.** It needs the ETag from an earlier read, and a step may not use another step's output (C36).
  An adapter that needs it reads the ETag inside the same call. That is code, not a profile value.
- **`field_reference`, `null_means`.** Code-level choices: they belong in the adapter and its spec, not in a value
  someone can flip.
- **`redact_paths`.** Not needed (see the table above).

`probe_method` and `marker` are **labels checked by the profile check** (below). The probe logic itself stays in code and
follows the spec's §3, including README §3's rule that a natural-key search alone never returns `NOT_EXECUTED`.

## Connection settings: the credential document

`CredentialProvider.credential()` returns one string. Per-connection values travel inside it, as the Layer A standard
already defines (README §5): `{"token": …, "settings": {…}}`. The whole string is secret. Examples:

| Setting | Example |
|---|---|
| account scope | GHL `location_id`, Atlassian `cloud_id` |
| base URL parts | Shopify `shop`, Salesforce `instance_url`, HubSpot region |
| provider-side ids created at connection setup | GHL `s12_ref_field_id` |
| `granted_scopes` | checked against the kernel's `required_scopes` before send: `client_error`, `provider_code: "scope"` |

| resource scope | Airtable base ids, a Notion root page: when a step param names a resource container, the adapter refuses one outside the scope before send (`client_error`, `provider_code: "out_of_scope"`) |

These values never come from step params (`ghl_crm.md`: "`locationId` … comes from the credential document, never
from `params`"). When a provider does not report granted scopes (Airtable `whoami` returns only `id` and `email`),
`granted_scopes` is left out and the provider's own 403 is the check.

## Version rule

The catalog has one `versions.binding` for the whole registry. S5 copies it into `FrozenBindingIdentity.binding_version`
(`s5_provider_resolution/handler.py:55`, from `registry_versions`). S12 entry denies a plan whose binding version no
longer matches (`binding_version_mismatch`, C32, G2).

**Rule:** any change to what the adapter sends (`api_version`, `version_*`, `base_url`, or a kernel's `method`,
`endpoint` or `api_version`) bumps `versions.binding` in the catalog. `verified`, `review_by` and `limits` change
without a bump.

**Cost of one catalog-wide version:** every profile carries the same `binding_version`, so one bump must update
**every** provider's profile in the same change, and the rollout below pauses all providers, not only the changed one.
The repository check catches a profile left behind. That is acceptable while there are a few providers; a per-provider
binding version would need a catalog format change (owner decision 6).

**Runtime check (in the adapter, before send):** if `binding.binding_version` ≠ the profile's `binding_version`, the
adapter sends nothing:

| Path | Result | Effect |
|---|---|---|
| `call` | `client_error`, `provider_code: "binding_version_mismatch"` | step fails, nothing was sent, breaker not counted (C37) |
| `probe` | `INCONCLUSIVE` | the step dead-letters after the bounded probes, safe |
| `observe` | `matches_expected=None` | verification `UNKNOWN`, never silent success |
| inverse | `client_error` | a `rollback` dead letter for a human |

The S12 entry check alone is not enough. It does not cover executions that were already admitted when the new version
went live: one recovered by another worker (M19) would otherwise run an old plan against the new API version. Every
path above fails safe.

**Rollout:** pause new entries (C39 `paused_until`, for every tenant), let running executions finish, load the catalog
and deploy the workers, then unpause. A step that still lands in the window fails closed as above.

## How the adapter uses the profile

At start, the adapter loads its profile and refuses to start if the profile fails the profile check (below). On each
call it:

1. checks the binding version (above);
2. builds the URL from `base_url` and the kernel's `endpoint`, filling `{api_version}`, `{settings.*}` and step
   params, and checks any resource container against the connection's scope. Above `max_url_length` a read switches
   to its POST form; which endpoint that is (Airtable `/listRecords`) is adapter code;
3. sets the version header; for `native_header` / `body_field` it sends `call_meta.idempotency_key`;
4. fetches **one page per call**, at most `max_page_size`, and returns the provider's cursor in `data["next"]` (the
   Layer A convention, `ghl_crm.md` §1). Today nothing can use that cursor: a step cannot take another step's output
   (C36), and the S15 envelope does not return result data (DR-40). Until DR-40 is fixed, a list returns its first page
   only;
5. logs one WARNING without PII when a response carries a `Sunset` or `Deprecation` header. Adapters never emit events
   or call the control plane (README §1, isolation).

Error classification, probe, observe, stamping and inverse location are unchanged, as the spec defines them.

### Provider behaviours the adapter must not hide

These come from the earlier app's Airtable and Notion work. Each one follows from rules S12 already has, so it adds
lines to a provider spec but no machinery.

| Provider behaviour (example) | Rule |
|---|---|
| A write is accepted with HTTP 200 but only partly applied (Airtable `details.message: "partialSuccess"`, e.g. an attachment failed) | Return `ok` with the identifier: the resource exists, so verification and rollback must be able to see it. Never return `error` for a write that took effect, because that leaves an orphan no inverse will remove. `observe` then compares the fields and fails the step. The Airtable reference's own rule ("never yield an `ok` envelope for `partialSuccess`") is still met: the step ends FAIL, never success |
| Fields silently ignored on write (Airtable computed fields; legacy Notion database create dropping `properties`) | `observe` compares every field the step wrote (Layer A README §4, "observe fields"), so a silent drop becomes a verification FAIL, not a success |
| `PUT` clears every field it does not send (Airtable `records.replace`) | A replace is its own kernel op with its own risk, never a variant or flag of an update |
| Deprecated endpoints quietly remapped by the adapter (Notion `/v1/data_sources` → `/v1/databases`) | Never. An endpoint change is a new profile version (see "Version rule") |
| A pagination cursor expires or is invalidated by concurrent writes (Airtable `offset`, 422 on iteration timeout) | `client_error`, `provider_code: "cursor_expired"`; a new request starts without a cursor |
| No delete endpoint, or the action notifies people (Airtable and Notion comments) | The catalog marks it `IRREVERSIBLE` |
| A secret returned only once (Airtable webhook `macSecretBase64`) | Never in `data`. The operation stays off the allow-list until a secret store can take it (DR-11, MC-058) |
| No connection mapped for the caller | `client_error`, `provider_code: "no_connection"` (README §5). Never fall back to a default account, a token file or an environment variable |
| Empty values are left out of responses (Airtable: `false`, `""` and `[]` come back absent) | `observe` treats an absent field as equal to an empty value the step wrote. It never invents a value for an absent field, and never fails a step because an empty value is absent |
| A 404 can mean "no access", not "gone" (Airtable answers 404 for every record of a base the token is not granted, and for webhooks without the scope) | For a delete (its call, including a rollback inverse, its `observe` and its `probe`), a 404 counts as "absent" only when a read of the parent (the table, the page) in the same call succeeds. Otherwise: the call returns `client_error`, the probe `INCONCLUSIVE`, the observation `UNKNOWN`. A revoked grant must never look like a successful delete |
| A request flag that changes the provider's schema as a side effect (Airtable `typecast: true` creates new select options) | The adapter always sends it off; step params cannot turn it on |
| Responses keyed by names that users can rename (Airtable field names, table names) | Requests and comparisons use ids (Airtable `returnFieldsByFieldId: true`, table and field ids in paths) |
| Very large or data-bearing error bodies (Notion answers an invalid emoji with a 60 KB body) | Never logged or stored; `data` on failure holds only `provider_status` and `provider_code` (README §1) |

## Checks

**Profile check** (in the adapter at start, and in `tests_agent`). It reads only the profile; an adapter never reads
the registry (README §1, isolation):

- the profile parses, `profile_format` is known, required fields are present, and enum values are valid;
- every W, D and IRREVERSIBLE kernel has a `probe_method`, and `stamp` has a `marker`;
- `version_scheme: path` ⇒ `base_url` contains `{api_version}`; `header` ⇒ `version_header` is set;
- every `{settings.name}` placeholder names a setting the spec's credential document lists.

**Catalog check** (`tests_agent`, against `docs/catalog/catalog.yaml`):

- every `kernels:` key is a kernel op of this provider in the catalog, and every catalog op of this provider has an
  entry;
- `binding_version` in every profile equals `versions.binding`.

For a deployment, whose catalog lives in the database, the same comparison belongs in the Worker Runtime start-up check
next to `unverifiable_mutation` (M21, DR-41), which already reads the bindings. That is S12 code: owner decision 5.

**Date checks** (`tests_agent`, reported, so the date alone never blocks unrelated work): a kernel whose `sunset_at` is
within N days, and a profile whose `review_by` date has passed. Recorded response fixtures exist for the current
`api_version` (README §6 test plan).

A drift report against the provider's published schema can be added later, offline only. Nothing checks the network at
run time.

## Example: `crm` (GoHighLevel)

Values from `ghl_crm.md`; every one is still VERIFY there.

```yaml
# src/engines/crm/profile.yaml
provider: crm
profile_format: 1
binding_version: bind-1
api_version: "2021-07-28"
version_scheme: header
version_header: Version
base_url: https://services.leadconnectorhq.com
pagination: cursor
max_page_size: 100
idempotency: stamp
verified: {docs: null, recorded: null}   # not yet checked against GHL's docs; ghl_crm.md VERIFY marks open
review_by: 2026-12-31
limits: {burst: "100 per 10 s per location", daily: "200000 per location", bulkhead: 8}

kernels:
  crm.contact_list:   {method: POST, endpoint: /contacts/search}
  crm.contact_create: {method: POST, endpoint: /contacts/, probe_method: stamp, marker: "custom_field:s12_ref"}
  crm.contact_update: {method: PUT, endpoint: "/contacts/{id}", update_semantics: patch_merge, probe_method: by_id}
  crm.contact_delete: {method: DELETE, endpoint: "/contacts/{id}", probe_method: by_id}
  crm.note_list:      {method: GET, endpoint: "/contacts/{contactId}/notes"}
  crm.note_create:    {method: POST, endpoint: "/contacts/{contactId}/notes", probe_method: stamp, marker: body_suffix}
  crm.note_delete:    {method: DELETE, endpoint: "/contacts/{contactId}/notes/{id}", probe_method: by_id}
  crm.task_list:      {method: GET, endpoint: "/contacts/{contactId}/tasks"}
  crm.task_create:    {method: POST, endpoint: "/contacts/{contactId}/tasks", probe_method: stamp, marker: body_suffix}
  crm.task_update:    {method: PUT, endpoint: "/contacts/{contactId}/tasks/{id}", update_semantics: patch_merge, probe_method: by_id}
  crm.task_delete:    {method: DELETE, endpoint: "/contacts/{contactId}/tasks/{id}", probe_method: by_id}
```

`contact_update` is a `PUT` that sends only the fields in `params` (`ghl_crm.md` §1), so its effect is a merge; the
label records that. The catalog entries for `crm` stay exactly as they are.

## Provider facts

The provider facts collected from `ghl_crm.md` and the earlier app's Airtable and Notion reviews, and the corrections
they imply for the pinned `PROVIDER_ADAPTERS.md` (§1, §2, §4, §6), are in
`docs/proposals/PROVIDER_ADAPTERS_CORRECTIONS.md`, ready to apply at its next re-pin. Two of them settle earlier open
points:

- **Airtable is `/v0`.** The earlier app ran live against `https://api.airtable.com/v0` on 2026-08-15. The pinned §6
  (`/v1`, "v0 deprecated") is wrong.
- **Airtable's second limit is concurrency, not a rate.** It is 5 requests/second per base and 10 concurrent requests
  per token, not "10 requests/second per token".

## Not adopted (from the pyairtable review and the earlier app)

| Idea | Why not |
|---|---|
| Hierarchical resource model in the contract | The contract is one kernel op per step; S9 plans compositions. Fine as a private helper inside an adapter |
| Lazy identity resolution at S12 | Binding drift (I-002, I-010) and an unbudgeted provider call. Resolve at S5, or keep the id in the credential document's settings |
| Live schema introspection at run time | Registry facts are authoritative (A4); the deterministic pipeline must not depend on the network |
| Retry as an adapter property | Retry belongs to the guard (README §1) |
| Side-effect ledger as an adapter contract | The ledger is the engine's. Adapters send or stamp the key and implement `probe()` (README §3) |
| Paging many pages inside one call | One page per call, cursor in `data["next"]` (Layer A convention); simpler, and it stays inside the step deadline |
| Client retries inside the adapter (the earlier Airtable client retried 3 times, Notion up to 3 with backoff) | Retries are the guard's, and an adapter retry of a write can duplicate it. Transport `retries=0` (`ghl_crm.md`) |
| A breaker inside the adapter (the earlier `_TwoKeyBreaker`) | The guard's breaker is the only one (CONF-022); per-key breakers are a CONF question (`ghl_crm.md` Q3) |
| `status="partial"` | `AdapterResult` has `ok` / `error` / `timeout` only; a partly applied write is `ok` plus a verification FAIL (above) |
| Async multi-step provider flows (Notion view queries, three-step file uploads) | No verification path for a 202 or a chunked lifecycle; off the allow-list |
| Business-entity matrices, composite capabilities, workflow IR in the adapter layer | Plans and chains belong to S4/S9 (M2a); adapters stay one operation per call |
| Hot credential reload from files, token fallback chains, multi-account adapter registries | One `CredentialProvider` per provider, keyed by `connection_id` (README §5) |

## Owner decisions needed (when the first new-adapter milestone starts)

1. Check the profile against the Notion and Airtable v2 adapter package (DR-38, prepared for `adapters-work`, not in
   this repository). Revisions 3–5 took provider facts from the earlier app's reviews and API references, not from
   that package's code.
2. Accept the profile, its location (`src/engines/<provider>/profile.yaml`) and the "stays out" list.
3. Accept the version rule (including its all-providers cost), the adapter's binding-version check and the rollout
   order.
4. Update `TEMPLATE.md`, the Layer A header tables and README §7 (definition of done) to point to the profile; include
   it in the guide's v2 (DR-08).
5. Add the catalog check to the Worker Runtime start-up check (S12 code, next to `unverifiable_mutation`).
6. Optional, separate CONF items: a per-provider binding version (removes the all-providers bump), per-provider
   breaker and bulkhead settings (today one setting for all providers), per-key breakers (`ghl_crm.md` Q3), and the
   routing adapter for several providers in one runtime (DR-42; each adapter keeps loading only its own profile).
7. Add two short sections to `TEMPLATE.md`: "Cannot do" (operations left unbound, with the reason) and "Fails
   silently" (each with the rule from "Provider behaviours the adapter must not hide").
8. When `PROVIDER_ADAPTERS.md` is next amended and re-pinned, apply `PROVIDER_ADAPTERS_CORRECTIONS.md`.
