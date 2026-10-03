# Provider API profiles — one data file for the provider-API facts that change

**Status: proposal for the owner (revision 2, 2026-10-03). No code, pinned document, catalog or milestone is changed by
it.** It applies when the first new-adapter milestone starts, after the `s12-s15-certified` tag. S12–S15 does not call
real providers (`S12_S15_EXECUTION_GATE.md:18`) and runs on `MockAdapter`, so no milestone card, golden test or gate row
moves.

It builds on, and must agree with:

- `docs/ADAPTER_IMPLEMENTATION_GUIDE.md` (the guide): adapter contract, error rules (§4), probe methods (§3.2),
  credentials (§11), registry entries (§12);
- `batch_bundles/LAYER_A/ADAPTER_SPECS/` (the Layer A specs): `README.md` (the standard), `TEMPLATE.md`, and the
  per-provider files `ghl_crm.md` and `gmail_mail.md`;
- `docs/catalog/catalog.yaml` and its loader `src/adapters/postgres/catalog.py`.

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
| `AdapterResult`, `CallMeta`, `BaseAdapter`, `CredentialProvider` | None (guide §14) |
| Guard, breaker, bulkhead, retry policy | None |
| Layer A spec | Its header values (version, base URL, idempotency, page size) move to the profile; the spec links to it and keeps the prose, the VERIFY marks and the rules |
| **Provider profile** (new) | `src/engines/<provider>/profile.yaml`, next to the adapter (`ghl_crm.md` puts the `crm` adapter in `src/engines/crm/adapter.py`) |

**Why next to the adapter and not under `docs/catalog/`:** the adapter is its only reader, so the file is deployed with
the code that reads it. The catalog goes to the database through `load_catalog.py`, but the profile does not. `<provider>`
is the catalog's `provider` id (`crm`, `mail`), the same key the breaker and bulkhead use (CONF-022).

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

Defaults are chosen to fail safe where the field affects behaviour: one page, no batching, `sync`, no idempotency
claim. A field without a default is required.

### Provider-wide

| Field | Values | Default | Example |
|---|---|---|---|
| `provider` | catalog provider id | required | `crm` |
| `profile_format` | int, the format of this file | required | `1` |
| `binding_version` | the catalog `versions.binding` this profile was certified with | required | `bind-1` (see "Version rule") |
| `api_version` | the provider's own string | required | `"2021-07-28"` (GHL), `"2022-06-28"` (Notion) |
| `version_scheme` | `header` / `path` / `none` | `none` | GHL, Notion: `header` |
| `version_header` | header name, for `header` | — | `Version`, `Notion-Version` |
| `base_url` | URL; for `path`, it contains `{api_version}` | required | `https://services.leadconnectorhq.com`, `https://api.airtable.com/{api_version}` |
| `pagination` | `cursor` / `offset_token` / `page` / `link_header` / `page_token` / `none` | `none` | GHL search `cursor`, Airtable `offset_token`, Google `page_token` |
| `max_page_size` | int | `1` | `100` |
| `idempotency` | `native_header` / `body_field` / `stamp` | `stamp` | Stripe `native_header`; GHL, Airtable `stamp` (README §1: no provider key → stamp the resource) |
| `idempotency_header` / `idempotency_field` | name, for `native_header` / `body_field` | — | `Idempotency-Key` |
| `max_url_length` | int | none | Airtable `16000` (switch a read to its POST form above it) |
| `limits` | free-form documented limits, informational | `{}` | `{burst: "100 per 10 s per location", bulkhead: 8}` |

`base_url_source` from revision 1 is gone: when the base URL differs per tenant (Salesforce `instance_url`, HubSpot
EU, Shopify shop), the profile's `base_url` holds a `{settings.<name>}` placeholder that the adapter fills from the
credential document, e.g. `https://{settings.shop}.myshopify.com/admin/api/{api_version}`.

### `kernels:` block

Keyed by catalog kernel op id. An entry states only what it needs; most need two or three lines.

| Field | Values | Default |
|---|---|---|
| `method`, `endpoint` | HTTP method, path template (`{name}` = a step param) | required |
| `api_version` | override, only when this kernel uses a different version | profile's |
| `pagination` | `none` to switch paging off | profile's (reads only) |
| `batch_max_items` | int; **reads only**, writes are always `1` | `1` |
| `update_semantics` | `patch_merge` / `put_replace`, for update ops (a label: the request code follows the spec) | — |
| `probe_method` | `provider_key` / `deterministic_id` / `stamp` / `natural_key` (guide §3.2) / `by_id` (deletes and updates) | required for W, D, IRREVERSIBLE |
| `marker` | where the stamp lives, for `stamp`: e.g. `custom_field:s12_ref`, `body_suffix` | — |
| `required_scopes` | list | `[]` |
| `deprecated_at`, `sunset_at`, `replacement_kernel_op_id` | dates, kernel op id | — |

Revision 1 also had `partial_success`, `async_mode`, `concurrency_control`, `null_means`, `field_reference` and
`redact_paths`. They are dropped, because each one either had no defined S12 behaviour or broke a rule:

- **Multi-record writes and partial success.** One step has one idempotency key, one stamp, one probe and one inverse,
  and `AdapterResult.status` is only `ok` / `error` / `timeout`. A 10-record create that half-succeeds has no correct
  result. Writes stay single-record.
- **`long_running` / `bulk_job`.** A 202 with an operation id has no path through verification. Only synchronous
  operations are supported.
- **ETag / `If-Match`.** It needs the ETag from an earlier read, and a step may not use another step's output (C36).
  An adapter that needs it reads the ETag inside the same call. That is code, not a profile value.
- **`field_reference`, `null_means`.** Code-level choices: they belong in the adapter and its spec, not in a value
  someone can flip.
- **`redact_paths`.** Not needed (see the table above).

`probe_method` and `marker` are **labels checked by the load check** (below). The probe logic itself stays in code and
follows the spec's §3, including guide §3.2's rule that a natural-key search alone never returns `NOT_EXECUTED`.

## Connection settings: the credential document

`CredentialProvider.credential()` returns one string (guide §11). Per-connection values travel inside it, as the Layer A
standard already defines (README §5): `{"token": …, "settings": {…}}`. The whole string is secret. Examples:

| Setting | Example |
|---|---|
| account scope | GHL `location_id`, Atlassian `cloud_id` |
| base URL parts | Shopify `shop`, Salesforce `instance_url`, HubSpot region |
| provider-side ids created at connection setup | GHL `s12_ref_field_id` |
| `granted_scopes` | checked against the kernel's `required_scopes` before send: `client_error`, `provider_code: "scope"` |

These values never come from step params (`ghl_crm.md`: "`locationId` … comes from the credential document, never
from `params`").

## Version rule

The catalog has one `versions.binding` for the whole registry. S5 copies it into `FrozenBindingIdentity.binding_version`
(`s5_provider_resolution/handler.py:55`, from `registry_versions`). S12 entry denies a plan whose binding version no
longer matches (`binding_version_mismatch`, C32, G2).

**Rule:** when a kernel's effective `api_version` changes, bump `versions.binding` in the catalog and `binding_version` in
the profile together.

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

**Rollout:** pause new entries (C39 `paused_until`), let running executions finish, load the catalog and deploy the
workers, then unpause. A step that still lands in the window fails closed as above.

## How the adapter uses the profile

At start, the adapter loads its profile and refuses to start if the profile fails the load check. On each call it:

1. checks the binding version (above);
2. builds the URL from `base_url` (placeholders from `api_version` and the credential document's settings), the
   kernel's `endpoint` and step params, and switches a read to its POST form above `max_url_length`;
3. sets the version header; for `native_header` / `body_field` it sends `call_meta.idempotency_key`;
4. fetches **one page per call**, at most `max_page_size`, and returns the provider's cursor in `data["next"]` (the
   Layer A convention, `ghl_crm.md` §1);
5. logs one WARNING without PII when a response carries a `Sunset` or `Deprecation` header. Adapters never emit events
   or call the control plane (README §1, isolation).

Error classification, probe, observe, stamping and inverse location are unchanged, as the spec defines them.

## Checks

**Load check** (in the adapter at start, and as a `tests_agent` test against `docs/catalog/catalog.yaml`):

- the profile parses, `profile_format` is known, required fields are present, and enum values are valid;
- every `kernels:` key is a kernel op of this provider in the catalog, and every catalog op of this provider has an
  entry;
- every W, D and IRREVERSIBLE kernel has a `probe_method`, and `stamp` has a `marker`. The startup guard already
  refuses W/D/IRREVERSIBLE bindings without `probe` and `observe` overrides (guide §12); this check makes sure each one
  has a defined method;
- no write has `batch_max_items` > 1;
- `version_scheme: path` ⇒ `base_url` contains `{api_version}`; `header` ⇒ `version_header` is set.

**Repository checks** (`tests_agent`):

- `binding_version` in every profile equals `versions.binding` in `catalog.yaml`;
- a kernel with `sunset_at` within N days fails;
- recorded response fixtures exist for the current `api_version` (guide §13.1 layout).

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

## Points to verify before building

- **GHL:** `PROVIDER_ADAPTERS.md` §2 describes the v1 API (`rest.gohighlevel.com/v1`). `ghl_crm.md` says v1 is end of
  support and to build on LeadConnector v2. The profile follows `ghl_crm.md`. §2 needs an owner correction when it is
  next re-pinned.
- **Airtable:** `PROVIDER_ADAPTERS.md` §6 says API v0 is deprecated and gives `/v1`. As far as this proposal's author
  knows, Airtable's Web API is still served under `/v0`. Check before an Airtable adapter is written; the §6 rate limit
  (10 requests/second per token) needs the same check.

## Not adopted (from the pyairtable review)

| Idea | Why not |
|---|---|
| Hierarchical resource model in the contract | The contract is one kernel op per step; S9 plans compositions. Fine as a private helper inside an adapter |
| Lazy identity resolution at S12 | Binding drift (I-002, I-010) and an unbudgeted provider call. Resolve at S5, or keep the id in the credential document's settings |
| Live schema introspection at run time | Registry facts are authoritative (A4); the deterministic pipeline must not depend on the network |
| Retry as an adapter property | Retry belongs to the guard (README §1, guide §7.4) |
| Side-effect ledger as an adapter contract | The ledger is the engine's. Adapters send or stamp the key and implement `probe()` (guide §3.2) |
| Paging many pages inside one call | One page per call, cursor in `data["next"]` (Layer A convention); simpler, and it stays inside the step deadline |

## Owner decisions needed (when the first new-adapter milestone starts)

1. Accept the profile, its location (`src/engines/<provider>/profile.yaml`) and the "stays out" list.
2. Accept the version rule, the adapter's binding-version check and the rollout order.
3. Update `TEMPLATE.md` and the Layer A header table to point to the profile, and add the profile to guide §12.
4. Optional, separate CONF items: per-provider breaker and bulkhead settings (today one setting for all providers),
   and per-key breakers (`ghl_crm.md` Q3).
5. When `PROVIDER_ADAPTERS.md` is next amended and re-pinned: the GHL §2 and Airtable §6 corrections above.
