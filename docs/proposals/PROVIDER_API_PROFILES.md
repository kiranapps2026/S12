# Provider API profiles — one data file for everything that depends on a provider's API

**Status: proposal for the owner. No code, pinned document, catalog or milestone is changed by it.** It applies when
the first new-adapter milestone starts, after the `s12-s15-certified` tag. S12–S15 does not call real providers
(`S12_S15_EXECUTION_GATE.md:18`) and runs on `MockAdapter`, so no milestone card, golden test or gate row moves.

It builds on what already exists and replaces none of it:

- `docs/ADAPTER_IMPLEMENTATION_GUIDE.md`: the adapter contract, error classification (§4), the Layer A spec standard
  (§9) and the registry entries a new adapter needs (§12);
- `batch_bundles/LAYER_A/ADAPTER_SPECS/TEMPLATE.md`: the human-readable provider spec;
- `docs/catalog/catalog.yaml`: kernel ops, capabilities and bindings, loaded by `tools/load_catalog.py`.

## Problem

Adapters, kernels, bindings and capabilities all end up depending on how a provider's API works: its version, how it
pages, whether it accepts an idempotency key, how it rate-limits, where its base URL lives. Today those facts have no
machine-readable home. The Layer A spec describes them in prose, and the guide's §12 lists a "provider config"
(bulkhead size, breaker threshold, cooldown) without a format. If each adapter hard-codes them, a provider API change
means editing adapter code. If they go into the catalog, the loader refuses them: `src/adapters/postgres/catalog.py:17`
accepts only a fixed set of kernel-op fields and rejects any other.

## Proposal in one line

Add **one data file per provider**, the provider profile, next to the catalog. It holds the provider-wide API facts
and, under `kernels:`, the per-kernel API facts. Only the provider's adapter reads it. Capabilities, bindings,
`catalog.yaml` and its loader, the planner, S5, the guard and every frozen contract stay as they are.

## What each layer holds

| Layer | Depends on the provider API? | Change |
|---|---|---|
| Capability (what the user wants: "create contact") | No | None |
| Binding / `FrozenBindingIdentity` (which provider and kernel was chosen) | Only the API version | None: the catalog's existing `versions.binding` carries it (see "Version rule") |
| `catalog.yaml` kernel op (mutation, risk, cost, `timeout_seconds`, `retry_safety`, inverse, observation) | No | None: these stay registry facts (A4) |
| `AdapterResult`, `CallMeta`, `BaseAdapter` | No | None (guide §14: the protocol is complete) |
| **Provider profile** (new, one file per provider) | Yes | Provider-wide API facts, plus a `kernels:` block for per-kernel API facts |
| Connection record (per tenant connection) | Yes, for some providers | Returned by the provider's `CredentialProvider` (guide §11), so no new store |

Rate-limit headers, cursors, provider request ids and `Retry-After` stay inside the adapter. The guard does not learn
about any of them.

## Provider profile

Location: `docs/catalog/providers/<provider>.yaml`, the `provider` value used in `catalog.yaml` bindings. It is the
machine-readable form of the Layer A spec's provider-wide sections (error mapping, idempotency, rate limits), and the
"provider config" of guide §12 item 4. Every field has a fail-closed default, so a profile lists only what it knows.

| Field | Values | Default | Example |
|---|---|---|---|
| `api_version` | the provider's own string | required | `"2022-06-28"` (Notion), `"v0"` (Airtable) |
| `version_scheme` | `header` / `path` / `query` / `none` | `none` | Notion and GHL: `header` |
| `version_header` | header name | — | `Notion-Version`, `Version` (GHL) |
| `base_url_source` | `fixed` / `connection` | `fixed` | Salesforce, HubSpot EU, Zendesk, Shopify: `connection` |
| `base_url` | URL, when `fixed` | — | `https://api.notion.com/v1` |
| `pagination` | `cursor` / `offset_token` / `page` / `link_header` / `page_token` / `none` | `none` | Notion `cursor`, Airtable `offset_token`, Google `page_token`, GitHub `link_header` |
| `cursor_param`, `cursor_response_path`, `has_more_path` | names / JSON paths | — | Notion: `start_cursor`, `next_cursor`, `has_more` |
| `max_page_size`, `max_pages` | ints | `1`, `1` | `100`, `10` |
| `idempotency` | `native_header` / `body_field` / `none` | `none` | Stripe `native_header`; Airtable and GHL `none` |
| `idempotency_header`, `idempotency_window_s` | name, seconds | — | `Idempotency-Key`, `86400` |
| `rate_limit_scopes` | list of `token` / `base` / `location` / `tenant` | `[token]` | Airtable: `[token, base]` (the two-key breaker) |
| `bulkhead_size`, `breaker_threshold`, `breaker_cooldown_s` | ints | `KernelPolicy` values | guide §12 item 4 |
| `error_map` | provider status or code → `ErrorClass` | `{}` | Google `403 rateLimitExceeded` → `rate_limited` |
| `deprecation_headers` | header names | `[Sunset, Deprecation]` | — |
| `max_url_length` | int | none | Airtable `16000` (switch to POST above it) |
| `redact_paths` | JSON paths | `[]` | PII fields for logs and dead-letter evidence |

**Error classification is not redefined here.** Guide §4.1 and §4.2 stay the rule, including "whenever the request
may have been processed, return `timeout`" and the per-mutation 5xx column. `error_map` lists only a provider's
exceptions to that table, exactly the rows the Layer A spec's §2 asks for.

### `kernels:` block (per-kernel API facts)

Keyed by the kernel op id from `catalog.yaml`. An entry inherits the whole profile and states only its own facts; most
need two or three lines. A key that is not a kernel op in the catalog is an error.

| Field | Values | Default |
|---|---|---|
| `method`, `endpoint` | HTTP method, path template | required |
| `api_version` | override, only when this kernel is on a different version | profile's |
| `pagination` | `none` to switch paging off | profile's |
| `batch_max_items` | int | `1` |
| `partial_success` | `none` / `records_and_errors` / `flag` | `none` |
| `update_semantics` | `patch_merge` / `put_replace` | `patch_merge` |
| `null_means` | `clear` / `ignore` | `ignore` |
| `concurrency_control` | `etag` / `version_field` / `updated_at` / `none` | `none` |
| `probe_method` | guide §3.2: `provider_key` / `deterministic_id` / `stamped_marker` / `natural_key` | none (probe stays `INCONCLUSIVE`) |
| `marker_field`, `natural_key` | field names, for `stamped_marker` / `natural_key` | — |
| `async_mode` | `sync` / `long_running` / `bulk_job` | `sync` |
| `field_reference` | `by_id` / `by_name` | `by_id` |
| `required_scopes` | list | `[]` |
| `deprecated_at`, `sunset_at`, `replacement_kernel_op_id` | dates, kernel op id | — |

`natural_key` keeps guide §3.2's rule: it is never used alone to return `NOT_EXECUTED`.

Mutation, risk, cost, `timeout_seconds`, `retry_safety`, inverse and observation stay in `catalog.yaml`. The profile
never repeats them.

## Connection settings

For providers whose `base_url_source` is `connection`, the per-tenant values come from the provider's
`CredentialProvider` (guide §9 item 2 already has it return per-connection settings), keyed by the `connection_id` that
`ExecutionContext` carries:

| Setting | Example |
|---|---|
| `base_url` or `region` | Salesforce `instance_url`, HubSpot `eu1`, Zendesk subdomain, Shopify shop domain |
| `external_account_id` | GHL `locationId`, Airtable base, Notion workspace, Atlassian `cloudId` |
| `granted_scopes` | checked against the kernel's `required_scopes` before the call (`client_error` if missing) |
| `environment` | `sandbox` / `production`; must match the execution mode, or the call is refused |

## Version rule (no contract change)

`catalog.yaml` already has one `versions.binding` for the whole catalog. It is frozen into every binding at S5, and S12
entry denies a plan whose binding row version differs from `manifest.binding_version` (`binding_version_mismatch`,
gate C32, G2).

**Rule: when any kernel's effective `api_version` changes (profile or kernel override), bump `versions.binding` in the
same change.** Then:

- a plan built on the old API version is refused at S12 entry instead of running against the new one (fail closed,
  through the C32 check that already exists);
- the API version is frozen with the binding, as I-002 / I-010 require, without a new field.

Because `versions.binding` is catalog-wide, a bump refuses every in-flight plan, not only the changed provider's. That
is coarse but simple and safe. Per-provider versions would need a catalog format change and are not proposed.

An upgrade is a new profile version that goes through the provider's recorded-response tests (guide §13.1), never an
edit in place.

## Who reads the profile

Only the provider's adapter. It loads the profile once at start and uses it to:

1. build the URL from `base_url` (profile or connection), `endpoint` and the version scheme, and switch to POST above
   `max_url_length`;
2. set the version header and, where `idempotency` is `native_header`, send `CallMeta.idempotency_key`;
3. classify every response by guide §4, then `error_map`, so `call()` never raises and every error has an
   `error_class`;
4. page up to `max_pages` within the step deadline, and report truncation in `data`, never by streaming results across
   `call()`;
5. turn a `Sunset` / `Deprecation` header into an alert event.

To stay simple, write this code inside the first adapter. Move it to a shared module only when a second adapter needs
the same code. The adapter never retries (retry stays in the guard, guide §7.4), never reads profile fields from step
params (LLM output cannot change a registry fact, A4), and never resolves a name to an id at S12 (that belongs to S5,
I-002).

## CI checks (one small script in `tests_agent/`)

- every profile validates against the tables above, and every `kernels:` key is a kernel op in `catalog.yaml` for
  that provider;
- a kernel whose `sunset_at` is within N days fails the build;
- an `api_version` change without a `versions.binding` change in the same commit fails the build;
- recorded response fixtures exist per `api_version` (guide §13.1 layout);
- optional, offline only: compare the catalog's schemas with the provider's published schema and report drift. Never at
  run time.

## Example (illustrative; verify every value against the provider's docs when the adapter is built)

```yaml
# docs/catalog/providers/airtable.yaml
provider: airtable
api_version: "v0"
version_scheme: path
base_url_source: fixed
base_url: https://api.airtable.com/v0
pagination: offset_token
cursor_param: offset
cursor_response_path: offset
max_page_size: 100
max_pages: 10
idempotency: none
rate_limit_scopes: [token, base]
max_url_length: 16000

kernels:
  airtable.record_list:
    method: GET
    endpoint: /{base_id}/{table_id}
  airtable.record_create:
    method: POST
    endpoint: /{base_id}/{table_id}
    pagination: none
    batch_max_items: 10
    partial_success: records_and_errors
    probe_method: stamped_marker
    marker_field: external_id
```

The matching `catalog.yaml` entries are unchanged in format:

```yaml
  - {id: airtable.record_list, mutation: R, risk_floor: 0.1, cost: 1, timeout_seconds: 30, retry_safety: safe}
  - {id: airtable.record_create, mutation: W, risk_floor: 0.2, cost: 3, timeout_seconds: 30, retry_safety: never, inverse: airtable.record_delete, observation: {method: get_record, identifier_field: id}}
```

## Points to verify before building

- `PROVIDER_ADAPTERS.md` §6 says Airtable API v0 is deprecated and gives `https://api.airtable.com/v1` as the base URL.
  As far as this proposal's author knows, Airtable's Web API is still served under `/v0`. Check before an Airtable
  adapter is written; if confirmed, §6 needs an owner correction.
- The per-token rate limit in §6 (10 requests/second) should be checked against the provider's current docs.

## Not adopted (from the pyairtable review)

| Idea | Why not |
|---|---|
| Hierarchical resource model in the contract | The contract is one kernel op per step; S9 plans compositions. Fine as a private helper inside an adapter. |
| Lazy identity resolution at S12 | Binding drift (I-002, I-010) and an unbudgeted provider call. Resolve at S5 and freeze the id. |
| Live schema introspection at run time | Registry facts are authoritative (A4); the deterministic pipeline must not depend on the network. Offline drift check only. |
| Retry as an adapter property | Retry lives in the guard (guide §7.4) so the probe runs first and the budget stays locked. |
| Side-effect ledger as an adapter contract | The ledger is the engine's; `MockAdapter`'s is a test oracle. Real adapters send the key where supported and implement `probe()` (guide §3.2). |

## Owner decisions needed (when the first new-adapter milestone starts)

1. Accept the provider profile with its `kernels:` block, at `docs/catalog/providers/<provider>.yaml`.
2. Accept the version rule ("`api_version` change ⇒ `versions.binding` bump").
3. Add the profile to the Layer A spec template and to guide §12 item 4 as the format of "provider config".
4. Optionally amend and re-pin `PROVIDER_ADAPTERS.md` (§6 Airtable rows if the v0 point is confirmed).
