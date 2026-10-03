# PROVIDER_ADAPTERS.md — corrections to apply at its next re-pin

**Status: proposal for the owner (2026-10-03). `docs/implementation/PROVIDER_ADAPTERS.md` is pinned
(`docs/gates/spec_pins.sha256`) and is not edited by this file.** Each section below names the pinned section it
replaces or amends, so the owner can apply it in one change and re-pin.

Sources:

- `batch_bundles/LAYER_A/ADAPTER_SPECS/README.md` and `ghl_crm.md` (the Layer A standard and the GHL spec);
- the earlier app's reviews: the Notion tool-level knowledge appendix (2026-08-23), the Notion backend functional
  reference, and the Airtable architecture sections 1–10 (last verified 2026-08-18);
- the earlier app's API references, tested live: Airtable (2026-08-15, marks ✅ live / 📝 documented only) and Notion
  (2026-08-20, `Notion-Version: 2025-09-03`);
- `docs/proposals/PROVIDER_API_PROFILES.md` (the profile and the adapter rules).

Every provider fact below stays **VERIFY** until checked against the provider's current docs **and** a recorded
sandbox response (README §6). Facts from the earlier app are marked *(earlier app)*.

Only facts and rules that change what an adapter does are listed. The earlier app's inventories (endpoint counts,
capability maps, entity matrices, composites, aliases, certification levels) are left out on purpose: they are what
made it fail.

---

## §1 Adapter contract: superseded text

| Pinned text | Replace with | Source |
|---|---|---|
| `call()` returns `KernelResult` | returns `AdapterResult(status, retryable, error_class, data)`; `status` is `ok` / `error` / `timeout` | CONF-021, README §1 |
| `SafeAdapterWrapper` | removed: the guard (`reliability._normalise`) turns an escaped exception or an unknown `error_class` into `adapter_defect` | README §1 |
| Example: `httpx.TimeoutException` and `httpx.NetworkError` → `status="UNKNOWN"` | before send (`ConnectError`, `ConnectTimeout`, `PoolTimeout`) → `error`, `not_dispatched`; after send (read/write timeouts and errors) → `status="timeout"`, which leads to the probe | README §2.1 |
| Example: `httpx.Timeout(35.0)` "> default 30 s step timeout" | the client timeout is `ExecutionSettings.adapter_client_timeout_s`, which must be **less than** `step_timeout_s` (C37); transport `retries=0` | README §1, `ghl_crm.md` |
| `BindingRow` subclasses with provider fields (e.g. `NotionBindingRow.notion_account_id`) | per-connection values travel in the credential document `{"token", "settings"}`, keyed by `connection_id`; bindings carry no provider fields | README §5 |

## §2 GHL Public API adapter

| Pinned | Correction | Source |
|---|---|---|
| Base URL `https://rest.gohighlevel.com/v1` | LeadConnector v2, `https://services.leadconnectorhq.com`, header `Version: 2021-07-28`. v1 is end of support | `ghl_crm.md` |
| "100 requests/minute per location" | burst 100 per 10 s and 200,000 per day, per app per location | `ghl_crm.md` |
| 15 kernel operations | the catalog's `crm.*` operations and the Layer A launch allow-list decide what exists; no count in this document | `ghl_crm.md` §1 |
| `GHLTokenManager` (SQLite example) | token storage and refresh live in the credential provider (MC-058, DR-11); the adapter never refreshes | README §5 |

## §4 Notion adapter: replacement facts

| Topic | Fact | Adapter rule |
|---|---|---|
| Base URL and version | `https://api.notion.com/v1`; version sent as `Notion-Version`. The earlier app ran two versions: `2025-09-03` (primary) and `2026-03-11` (markdown endpoints) *(earlier app)* | profile `api_version` plus a per-kernel override for the second version |
| API change already seen | `2025-09-03` split databases into data sources; the earlier app silently remapped `/v1/data_sources` to `/v1/databases` and patched dropped `properties` afterwards *(earlier app)* | never remap: an endpoint change is a new profile version and a `versions.binding` bump |
| Auth | bearer integration token; the integration reaches only what was shared with it in the Notion UI; 403 = valid token without access to the content *(live reference)*; an unshared page may also answer 404 (VERIFY) | `client_error`, `provider_code: "not_shared"`; a 404 is "absent" only under the parent-read rule (profile proposal) |
| Append content | `PATCH /v1/blocks/{block_id}/children`. The earlier app sent `POST` and recorded "append returns 400 for integration tokens" as a Notion limitation; it was our request (VERIFY with a recorded response) | not a limitation; use `PATCH` |
| Requests | search `filter.value` accepts only `page` and `data_source`; property names in queries are case-sensitive; filters nest 3 levels with up to 100 conditions; block types are immutable; on `PATCH`, `null` removes a value (icon, cover) and omitting a key leaves it unchanged *(live reference)* | build requests from these rules; a refused request is a defect in our request, not a provider error |
| Data sources and databases | since `2025-09-03`, entries live in data sources, not databases; data source ids and database ids are different and cannot be used for each other; `database.properties` may be empty, the data source holds the schema *(live reference)* | use data source ids for queries and rows |
| Conflicts | 409 `conflict_error` exists (VERIFY whether a 409 write was applied) | until verified, a 409 on a write is `timeout` (probe decides); on a read, `server_error` |
| Users | a personal access token cannot list users (403) *(live reference)* | identity endpoints are not adapter operations; `users/me` may be used once at connection setup to record the workspace id in the credential settings |
| Rate limit | about 3 requests/second on average per integration; the earlier app warned at 120 per 60 s *(earlier app)* | breaker and bulkhead sizing (`limits`); 429 → `rate_limited` |
| Idempotency | no idempotency key; `Notion-Request-Id` is tracing only *(earlier app)* | `stamp` |
| Pagination | `start_cursor` / `next_cursor` / `has_more`, `page_size` ≤ 100 | one page per call, cursor in `data["next"]` |
| Deletes are soft | deleting a block or archiving a page moves it to the trash (`archived` / `in_trash`); a later `GET` can still return it (VERIFY) | for a delete, `observe` and `probe` treat `archived` / `in_trash: true` as absent, not only a 404 |
| Comments | create and list only, no delete *(earlier app)* | comment create is `IRREVERSIBLE` |
| Page ambiguity | a page is either a document or a database row *(earlier app)* | separate kernel ops by parent type; never one op that guesses |
| Known limits | workspace-level pages cannot be moved, archived or deleted by an integration; no change-token API *(earlier app)* | refuse workspace-level targets before send (`client_error`); no "changed since" probes |
| Async and multi-step flows | view queries (create → poll → results, with `expires_at`) and file uploads (create → send → complete; they expire; 5 MB workspace file limit in the test workspace) *(earlier app, live reference)* | off the allow-list: no verification path for them |
| Error bodies | some are very large (an invalid emoji returns a 60 KB list of valid emoji) *(live reference)* | never logged or kept; only `provider_status` and `provider_code` |

**Remove from pinned §4:**

- "`partialSuccess: true` with HTTP 200" and its `parse_response` example. That is Airtable's behaviour
  (`details.message: "partialSuccess"`), and neither earlier review shows it for Notion. VERIFY before keeping any
  Notion partial-success rule.
- "batch with 10s delay": no source.
- `_get_token` raising `ValueError`: adapters never raise (README §1).

## §6 Airtable adapter: replacement facts

| Topic | Fact | Adapter rule |
|---|---|---|
| Base URL and version | `https://api.airtable.com/v0`, version in the path, no version header; live-verified 2026-08-15 *(earlier app)* | profile `version_scheme: path`, `base_url: https://api.airtable.com/{api_version}` |
| Auth | personal access token (bearer), no expiry; needs the scope **and** a per-base grant; schema and webhook operations need the base creator role *(earlier app)*. Errors carry `error.type`: 401 `AUTHENTICATION_REQUIRED`, 403 `UNAUTHORIZED_RECORD_OPERATION` / `UNAUTHORIZED_SCHEMA_OPERATION` *(live reference)* | 401 → `client_error` `auth`; 403 → `client_error` `scope`; map `error.type` to a short `provider_code`, never keep the body |
| No access looks like "not found" | a token without a grant on the base gets 404 from every record, table and field endpoint, and `meta/bases` returns 200 with `bases: []`; webhooks answer 404 without `webhook:manage` *(live reference)* | a 404 is "absent" only when a read of the parent table in the same call succeeds (profile proposal); otherwise `INCONCLUSIVE` / `UNKNOWN` |
| Rate limits | 5 requests/second per base with a burst of about 30, 10 concurrent requests per token; higher plans allow more; no rate-limit headers, and 429 carries no `Retry-After` *(live reference)*; Airtable asks clients to wait about 30 s after a 429 (VERIFY) | 429 → `rate_limited`; breaker cooldown ≥ 30 s; bulkhead ≤ 10 |
| Idempotency | none | `stamp` (marker field per table, VERIFY the best place) |
| Upsert | `performUpsert` / `batchUpsert` merges into an existing record that matches | never use upsert for a create: a rollback would delete a record the customer already had (same rule as GHL upsert) |
| Pagination | opaque `offset`, `pageSize` ≤ 100; can be invalidated when data changes; an iteration timeout answers 422 *(live reference)* | one page per call; that 422 → `client_error` `cursor_expired`, and the caller restarts without an offset |
| Batch | at most 10 records per request | S12 writes one record per step (one key, one probe, one inverse) |
| URL length | 16,000 characters | above it, a list read switches to `POST /{base}/{table}/listRecords` |
| Partial success | HTTP 200 with `details.message: "partialSuccess"` (e.g. attachments failed); not yet triggered live (📝) *(live reference)* | `ok` with the record id; verification compares the fields and fails the step |
| Empty values | `false`, `""` and `[]` are omitted from responses, not returned as values *(live reference: a checkbox written `false` reads back absent)* | `observe` treats absent as equal to the empty value written; never synthesise `false` |
| Request flags | `typecast: true` can create new select options; `returnFieldsByFieldId` switches response keys from names to ids *(live reference)* | always send `typecast: false` and `returnFieldsByFieldId: true` |
| Delete of a deleted record | returns `{id, deleted: true}` again, not an error *(live reference, VERIFY)* | a rollback can be re-run; no special 404 rule needed if confirmed |
| Silent behaviours | writes to computed fields (formula, rollup, lookup, count, autoNumber) are ignored; `PUT` clears unsent fields (documented, not demonstrated live 📝); webhooks stop after 7 days without an error *(earlier app, live reference)* | `observe` compares every written field; a replace is its own kernel op and stays off the allow-list until demonstrated; webhooks are not adapter operations (event sources) |
| Schema and admin endpoints | deleting a base, table or field is irreversible; a table with records cannot be deleted; formula and rollup fields cannot be created with the table; the checkbox colour enum is undocumented *(live reference)* | bases, tables and fields are not adapter operations for launch; only record operations are |
| One-time secret | webhook create returns `macSecretBase64` once *(earlier app)* | never in `data`; off the allow-list until a secret store takes it |
| Comments | create only, notifies collaborators *(earlier app)* | `IRREVERSIBLE` |
| Formula filters | `filterByFormula` is a formula language, so text from step params is an injection surface *(earlier app)* | never build a formula from free text; build it from structured params with escaping, or refuse (`client_error`) |
| Field addressing | records are addressed by record id and field id; field names can change | use field ids in requests and in the stamp marker |

**Remove from pinned §6:**

- "API v0 deprecated — use API v1" and `https://api.airtable.com/v1`: wrong.
- "10/second per token": it is 10 concurrent requests per token.
- "Two-key circuit breaker" (the `AirtableCircuitBreaker` example): the S12 guard keys its breaker by provider only
  (CONF-022). Per-key breakers are a CONF question (`ghl_crm.md` Q3), not adapter code.
- "Missing 8 standard engine files" and "37 kernel operations": see §7/§8 below.

## §7 and §8 Testing and adding a provider

| Pinned | Replace with | Source |
|---|---|---|
| "Every adapter must have all 7 required files" (`kernels.py`, `kernel_meta.py`, `aliases.py`, `policy.py`, `schema.py`, `assertions.py`, `policy/execution.yaml`) | one adapter class, one credential provider, one profile (`src/engines/<provider>/profile.yaml`), one Layer A spec, and catalog rows. This multi-file layout is what the earlier app built per provider, and it did not survive | README §7, profile proposal |
| `make scaffold-adapter`, generators (`generate_kernel_meta`, `generate_tools`, `generate_migration`) | none: catalog rows are loaded by `tools/load_catalog.py`; `tools/registry_readiness.py` must exit 0 | README §7 |
| Contract-test list | README §6 recorded-response test matrix, plus the profile check and the catalog check | README §6 |
| "verified" in any form | only a recorded sandbox response clears a VERIFY mark; operation status lives in the catalog's `truth_state` only, never as a count in a document | profile proposal, "Lessons from the earlier app" |
