# Provider adapters: one engine, operation archetypes, provider profiles

**Status: proposal for the owner (revision 9, 2026-10-03). No code, pinned document, catalog or milestone is changed by
it.** It applies when the first new-adapter milestone starts, after the `s12-s15-certified` tag. S12–S15 does not call
real providers (`S12_S15_EXECUTION_GATE.md:18`) and runs on `MockAdapter`, so no milestone card, golden test or gate row
moves.

It builds on, and must agree with:

- `batch_bundles/LAYER_A/ADAPTER_SPECS/` (the Layer A specs): `README.md` (the standard: contract §1, error rules §2,
  probe §3, observe §4, credentials §5, tests §6, definition of done §7), `TEMPLATE.md`, and the per-provider files
  `ghl_crm.md` and `gmail_mail.md`;
- `docs/catalog/catalog.yaml` and its loader `src/adapters/postgres/catalog.py`;
- the ADAPTERS items of `docs/gates/S12_DEFERRED_REGISTER.md` (DR-08, DR-38, DR-40, DR-41, DR-42).

It does not rely on `docs/ADAPTER_IMPLEMENTATION_GUIDE.md` (DR-08: about 15 factual errors; agents use the Layer A
README and template until its v2). Provider facts and the corrections they imply for the pinned `PROVIDER_ADAPTERS.md`
are in `docs/proposals/PROVIDER_ADAPTERS_CORRECTIONS.md`.

Revisions 1–5 described a data file next to hand-written adapters. Revision 6 changed the structure, not the rules:
one shared engine and a closed set of operation archetypes, so most of an adapter's behaviour is written once, and a
provider writes only what is really its own. Revisions 7–9 are consistency reviews of that structure.

## Problem

Every adapter must do the same things the same way: build the URL, send the version, stamp or send the idempotency
key, fetch one page, classify the response by README §2, probe by README §3, observe by README §4, locate an inverse
target by the stamp. The Layer A specs show how much of this repeats: `ghl_crm.md` writes out the same probe, observe
and inverse recipes for contacts, notes and tasks, differing only in endpoints, the stamp location and the compared
fields.

If each adapter re-implements those recipes, each adapter can get the safety rules wrong in its own way (a wrong
`NOT_EXECUTED` is a duplicate side effect; a 404 read as "deleted" hides a revoked grant). And the provider-API facts
that change (version, base URL, endpoints, page size) sit in prose and code with nothing checking that they agree;
the catalog loader cannot hold them (`catalog.py:17` rejects unknown fields).

## Proposal

Three pieces, each with one owner:

| Piece | What it is | Who writes it |
|---|---|---|
| **Engine** (`src/engines/_http/`) | One `BaseAdapter` implementation that runs every call path (`call`, `probe`, `observe`, the inverse) for every archetype: URL and headers, binding-version and scope checks, the README §2 classification table, the README §3 probe rules, the README §4 observe rules, inverse location, one trace log line | Once, for all providers |
| **Profile** (`src/engines/<provider>/profile.yaml`) | Plain values: version, base URL, page size, and per operation its archetype, endpoint, stamp marker and compared fields | Per provider; changes when the provider's API changes |
| **Hooks** (`src/engines/<provider>/adapter.py`) | The few things only the provider knows: build a request, extract the id from a response, provider-specific error rows, find resources by the step key, normalise a compared value, decide whether a record is ours | Per provider; changes when the provider's behaviour changes |

A provider adapter is a subclass of the engine with those hooks, plus its `CredentialProvider` and its profile. The
engine is extracted when the second provider is built (the first adapter is written in this shape from the start, so
the extraction is a move, not a rewrite).

**What this makes dynamic, safely:** a new operation of an existing provider that fits an archetype needs a catalog row,
a profile entry, a few lines of `build_request` / `extract`, and recorded fixtures. Its probe, observe and inverse come
from the engine, already tested. It is enabled for production on its own `truth_state` (DR-41) once its recorded tests
pass. Nothing is discovered or decided at run time: archetypes, endpoints and compared fields are fixed in the profile
before S5 freezes the binding.

| Layer | Change |
|---|---|
| Capability, binding, `FrozenBindingIdentity`, `ExecutionManifest` | None |
| `catalog.yaml` kernel op (mutation, risk, cost, `timeout_seconds`, `retry_safety`, inverse, observation) | None: registry facts (A4) |
| `AdapterResult`, `CallMeta`, `BaseAdapter`, `CredentialProvider` | None (README §1) |
| Guard, breaker, bulkhead, retry policy, probe and verification stages | None |
| Layer A spec | Keeps its prose, VERIFY marks and provider rules; its header values, endpoints and compared fields move to the profile, and the spec links to it |

`<provider>` is the catalog's `provider` id (`crm`, `mail`), the key the breaker and bulkhead already use (CONF-022).
The profile ships with the adapter because the adapter is its only reader; it is not loaded into the database.

## Lessons from the earlier app

An earlier app (OpenClaw) built Notion and Airtable adapters and failed on complexity: about 30 artefact files per
provider, two ID systems, alias files, business-entity and composite matrices, per-provider policy YAMLs, and status
counts written by hand. Its documents said every binding was verified, while its own bindings file showed 10
verified and 18 only proposed. Its reviews and its two live-tested API references (Airtable 2026-08-15, Notion
2026-08-20) still hold useful provider facts. The guardrails:

| Failure in the earlier app | Guardrail here |
|---|---|
| Status written by hand in several documents, then contradicting itself | Operation status lives in one place, the catalog's `truth_state` (DR-41). No profile or document states a count or a status by hand |
| "Verified" meant "checked against the docs", not "ran against the provider" | The profile records both separately (`verified.docs`, `verified.recorded`); only a recorded sandbox response **in this repository** clears a VERIFY mark |
| Capabilities mapped for every endpoint, most never used or tested | Only operations the Layer A spec defines get a catalog row and a profile entry (its allow-list, plus those kept for later or for rollback). Each is enabled on its own `truth_state`. Everything else stays unbound, with a reason in the spec's "Cannot do" section |
| Two ID systems (UC-, NC-) plus aliases and endpoint ids | One id: the catalog kernel op id. No aliases, no endpoint-id layer |
| Per-provider frameworks: policy YAMLs, undo journals, assertion modules, reconciliation engines, client retries, in-adapter breakers | One shared engine, a closed set of archetypes, and hooks. The S12 kernel owns retry, breaker, ledger, verification and rollback |
| Silent provider behaviour hidden by the adapter (endpoint remapping, dropped fields) | The engine never hides one. It refuses before send or lets verification see it ("Provider behaviours the engine must not hide") |
| A direct tool path (`notion_execute`) with no planner, step graph or ledger; silent fallbacks (an adapter registered without a token, a resolver falling back to another provider, a fresh random idempotency key per request) | Every adapter call goes through the guard; no API or tool path calls an adapter directly (README §7 scan). Missing credentials, an unknown provider or a missing key are refusals. The key is always `call_meta.idempotency_key` |
| Limitations declared from the app's own bad requests ("append returns 400" came from `POST`; Notion's append is `PATCH /v1/blocks/{id}/children`) | A limitation enters a spec only with the provider's docs and a recorded response. A failing call is first a defect in our request. Missing capabilities are never emulated |

## Operation archetypes

Each catalog operation declares exactly one archetype in its profile entry. The set is closed: a new archetype is an
owner decision, not a profile edit.

| Archetype | Catalog mutation | `call` | `probe` (README §3) | `observe` (README §4) | Inverse |
|---|---|---|---|---|---|
| `read_one` | R | GET one resource by id | not called (reads retry) | — | — |
| `list_page` | R | one page, at most `max_page_size`; cursor in `data["next"]` | not called | — | — |
| `create` | W | build the request with the stamp (or the provider key), send; `data` carries the identifier (see "Identifier rule") | `find_by_key`: exactly one of ours → `EXECUTED_SUCCESS`; none → `NOT_EXECUTED` **only** if the operation's `lookup` is `consistent`, else `INCONCLUSIVE`; several → `INCONCLUSIVE` and an ERROR log | read via `reads[read]`; with no identifier, `find_by_key` first; compare the written `compare` fields; check `owns` | is the inverse **target**: located by `find_by_key`, never by a natural key alone |
| `update` | W | merge only the fields in params | read by id: every written compared field equal → `EXECUTED_SUCCESS`; otherwise `INCONCLUSIVE` (never `NOT_EXECUTED`: a differing field may be someone else's later write) | as `create`, by identifier | — |
| `replace` | W | send the full record; clears what is not sent | as `update` | as `update` | — (off the allow-list until a recorded response shows the clearing) |
| `delete` | D | planned: by id; "not found" (see the shared rules) → `ok` with `data["already_absent"] = true` (`ghl_crm.md` §2). Inverse (key ends `:inverse`, the create's params): `find_by_key` on the create's resource; exactly one → delete; none → `client_error` `inverse_target_not_found`; several → `inverse_target_ambiguous` | read by id: not found → `EXECUTED_SUCCESS`; present and ours → `NOT_EXECUTED` only if `read_by_id` is `consistent`, else `INCONCLUSIVE` | not found → `True`; present → `False`; no identifier (probe path) → `UNKNOWN` (`observe_no_identifier`, `ghl_crm.md` §4) | — |
| `send` | IRREVERSIBLE | send once with a deterministic id derived from the step key (Gmail `Message-ID`) | `find_by_key` on the deterministic id, with the same `lookup` rule as `create` (Gmail: `eventual`, so never `NOT_EXECUTED`) | find by the deterministic id, compare | none (README §1.1: never for IRREVERSIBLE) |
| `custom` | any | the hook implements the call path itself | hook | hook | hook |

The engine picks the README §2.2 column itself: read or mutation from `binding.effective_mutation`, and "provider
honours the key" from the profile's `idempotency`.

**Identifier rule.** A W, D or IRREVERSIBLE operation names its observation read (`read`, equal to the catalog's
`observation.method`), and the engine composes the catalog's identifier value from the parts of that read's
`identifier` pattern (GHL `ref` = `"{contactId}/{id}"`). Where the parts come from depends on the archetype:

- `create` and `send`: from the response, through `extract`. A 2xx without them is `timeout` (the write may have
  happened; the probe decides), as README §2.2 and `ghl_crm.md` §2 ("2xx without `contact.id`") require.
- `update`, `replace` and `delete`: from the step's params (the addressed resource). Responses such as GHL's delete
  body `{succeded: true}` carry no id and need none.

For a read, a response `extract` cannot parse is `adapter_defect`.

Rules every archetype shares, implemented once in the engine:

- **Not found means gone only where the provider says so.** The profile's `not_found` decides. `absent`: the provider
  answers "no access" with 403, so a 404 means gone (GHL: 403 "does not have access to this location", `ghl_crm.md`
  §2). `needs_parent_read`: the provider answers "no access" with 404 too (Airtable), so a 404 counts as gone only when
  a read of the `parent` succeeds in the same call; otherwise the call returns `client_error`, the probe
  `INCONCLUSIVE`, the observation `UNKNOWN`. The default is `needs_parent_read`, and without a `parent` a 404 is never
  "gone". Soft deletes count as gone through `absent_when` (Notion `in_trash: true`).
- **Compare what was written.** Only `compare` fields present in the step's params are compared (`ghl_crm.md` §4:
  "compared, if present"); an entry naming an object (`fields`, `properties`) compares the keys written inside it. An
  absent field equals an empty value written (`false`, `""`, `[]`).
- **Ours means ours, in two strengths.** `owns(op, record, settings, stamped)` always checks the account scope (GHL
  `locationId`). It also checks the stamp **only** where S12 created the record in this step: `create` and `send`
  probes and observations, and the `delete` inverse. A planned `update` or `delete` addresses a record the user named,
  which may predate S12 or carry another step's stamp, so there the stamp is not checked. A record failing the check
  is never adopted or deleted.
- `custom` is the escape hatch for an operation no archetype fits. Each `custom` entry needs a line in the spec saying
  why, and the profile check reports the count per provider; many `custom` entries mean a missing archetype or an
  operation that should not exist.

## Hooks

The provider writes these, and only these (each has a safe default where one exists):

| Hook | Used by | Default |
|---|---|---|
| `build_request(op, params, key, settings)` | every call: returns the query and the body. It computes the stamp or the deterministic id from the step key (the spec's format, e.g. `ghl_crm.md` §0 `stamp()`, `gmail_mail.md` §3 `Message-ID`); paging values and `fixed_params` are added by the engine afterwards | required |
| `extract(op, response)` | every call: the identifier, or `items` and `next` for `list_page`; only named fields, never the whole record | required |
| `classify(op, response)` | every call: the provider's own rows (Layer A spec §2), returning an error class, `ok`, `not_found` (a provider-specific not-found shape, e.g. GHL's recorded "note not found" 400), or "not mine" | "not mine": the engine's README §2 table decides; a plain 404 is `not_found`. `not_found` follows the `not_found` rule for a `delete` call and for probe and observe reads; anywhere else it is `client_error` |
| `find_by_key(op, params, key, settings)` | `create` and `send` probes, observe without identifier, `delete` inverse: the resources carrying our stamp or deterministic id, or "lookup failed". For the inverse the engine passes the step key with `:inverse` removed (`ghl_crm.md` §0 `step_key()`), so the create's stamp is found | required when a `create` or `send` exists |
| `normalize(op, field, value)` | comparisons | identity |
| `owns(op, record, settings, stamped)` | every read used by probe, observe, inverse (the two strengths above) | required unless the provider has only reads |

`op` is the operation's profile entry, so hooks read `stamp_marker` and the other values from it rather than
repeating them in code. Hooks make provider calls only through the engine's client (`http`), never their own: same
transport (`retries=0`), same deadline (`adapter_client_timeout_s`), same trace line.

The GHL duplicate-contact rule (`ghl_crm.md` §2) is a `classify` row that does one `GET` through `http`; the stamp hash is
`ghl_crm.md` §0's `stamp()`; the trailing `[ref:…]` stripping is `normalize`. Nothing else in `ghl_crm.md` needs
provider code.

## Profile fields

Defaults fail safe where the field affects behaviour. A field without a default is required.

### Provider-wide

| Field | Values | Default | Example |
|---|---|---|---|
| `provider` | catalog provider id | required | `crm` |
| `profile_format` | int | required | `1` |
| `compatible_binding_versions` | list of catalog `versions.binding` values this profile runs | required | `[bind-1]` (see "Version rule") |
| `api_version` | the provider's own string | required | `"2021-07-28"` (GHL), `"2025-09-03"` (Notion), `"v0"` (Airtable) |
| `version_scheme` | `header` / `path` / `none` | `none` | GHL, Notion `header`; Airtable `path` |
| `version_header` | header name, for `header` | — | `Version`, `Notion-Version` |
| `base_url` | URL; `{api_version}` for `path`; `{settings.name}` for per-tenant parts | required | `https://services.leadconnectorhq.com`, `https://api.airtable.com/{api_version}`, `{settings.instance_url}/services/data/v{api_version}` |
| `paging` | names the engine uses for one page: `{size: <param>, cursor: <param>, next: <response path or "header:Link">}`; in the query for GET, in the body otherwise | none (no paging) | Airtable `{size: pageSize, cursor: offset, next: offset}`; Notion `{size: page_size, cursor: start_cursor, next: next_cursor}` |
| `max_page_size` | int | `1` | `100` |
| `not_found` | `absent` / `needs_parent_read` (shared rules) | `needs_parent_read` | GHL `absent`; Airtable `needs_parent_read` |
| `idempotency` | `native_header` / `body_field` / `stamp` | `stamp` | Stripe `native_header`; GHL, Airtable, Notion `stamp` |
| `idempotency_header` / `idempotency_field` | name | — | `Idempotency-Key` |
| `read_by_id` | `consistent` / `eventual` | `eventual` | GHL `consistent` (VERIFY) |
| `max_url_length` | int | none | Airtable `16000` |
| `fixed_params` | values the engine always sends, last, so params cannot override them; in the query for GET and DELETE, in the body otherwise | `{}` | Airtable `{typecast: false, returnFieldsByFieldId: true}` |
| `request_id_header` | the response header carrying the provider's request id, for the trace line | none | VERIFY per provider |
| `limits` | documented limits, informational (guard sizing) | `{}` | `{burst: "100 per 10 s per location", bulkhead: 8}` |
| `verified` | `{docs: <date and source> or null, recorded: <date of the last recorded response in this repo> or null}` | required | `{docs: null, recorded: null}` |
| `review_by` | date of the next docs and changelog check | required | `2026-12-31` |

### `reads:` block

Keyed by the catalog's `observation.method` names. Today those names (`get_contact`, `get_note`, `get_task`) are
defined nowhere a machine can check; the block gives each one its endpoint.

| Field | Values | Default |
|---|---|---|
| `endpoint` | GET path template | required |
| `identifier` | how the catalog's `identifier_field` value splits into placeholders | `"{id}"` (GHL notes and tasks: `"{contactId}/{id}"`, the composite `ref` of `ghl_crm.md` §0) |
| `parent` | GET path template of the parent, for `not_found: needs_parent_read` | none (then a 404 is never "gone") |
| `absent_when` | field values that mean deleted | `{}` |

### `kernels:` block

Keyed by catalog kernel op id.

| Field | Values | Default |
|---|---|---|
| `archetype` | one of the table above | required |
| `method`, `endpoint` | HTTP method; path template: `{name}` a step param, `{settings.name}` a credential setting | required |
| `api_version` | override, only when this operation uses another version (Notion markdown endpoints `2026-03-11`) | profile's |
| `paging` | override of the provider's paging names (GHL search: body `pageLimit`, `searchAfter`) | provider's |
| `long_url_endpoint` | for a GET read: the POST form used when the URL would exceed `max_url_length` (Airtable `/{baseId}/{tableId}/listRecords`); query values move to the body | none (above the limit: `client_error` `url_too_long`) |
| `read` | the `reads:` entry used to observe this operation; must equal the catalog's `observation.method` | required for W, D, IRREVERSIBLE |
| `stamp_marker` | where the stamp lives, for `create`: e.g. `custom_field:s12_ref`, `body_suffix` | required for `create` with `idempotency: stamp` |
| `lookup` | `consistent` / `eventual`: may an empty `find_by_key` prove `NOT_EXECUTED`? | `eventual` (never) |
| `compare` | fields `observe` and `probe` compare (only those the step wrote) | required for `create`, `update`, `replace`, `send` |
| `required_scopes` | list | `[]` |
| `deprecated_at`, `sunset_at`, `replacement_kernel_op_id` | dates, kernel op id | — |

Dropped in earlier revisions and still out: batches (one resource per operation), partial-success flags, async jobs,
ETag flow (C36), `null_means`, `field_reference`, `redact_paths`. Revision 6 replaced `probe_method` and
`update_semantics` with `archetype`, which decides the behaviour instead of labelling it; revision 7 replaced the
`pagination` label with `paging` names the engine actually uses. Every field has a reader.

## What stays out of the profile

| Not in the profile | Where it stays | Why |
|---|---|---|
| Request bodies and filters | `build_request` | Provider bodies are nested and typed; body templates in data are where the earlier app's complexity grew |
| Provider error rows | `classify` + Layer A spec §2 | They match on body text, sometimes need a lookup (GHL duplicates) |
| Timeouts and retries | `ExecutionSettings.adapter_client_timeout_s` (< `step_timeout_s`, C37); `retry_policy` | The adapter never sets its own deadline or retries (README §1) |
| Mutation, risk, cost, `retry_safety`, inverse, observation method | `catalog.yaml` | Registry facts (A4). The profile's `read` repeats the observation method because the engine never reads the registry; the catalog check keeps them equal |
| Credentials, per-connection settings | the credential document | Secret |
| Breaker threshold, cooldown, bulkhead size | guard wiring | One setting for every provider today (`bootstrap.py:75`), keyed by `binding.provider`; `limits` informs sizing |
| Per-key breakers (Airtable per base, GHL per location) | not possible today | CONF-022; `ghl_crm.md` Q3 |

## Connection settings: the credential document

`CredentialProvider.credential()` returns one string: `{"token": …, "settings": {…}}` (README §5). The whole string is
secret.

| Setting | Example |
|---|---|
| account scope | GHL `location_id`, Atlassian `cloud_id` |
| base URL parts | Shopify `shop`, Salesforce `instance_url` (a full URL) |
| provider-side ids created at connection setup | GHL `s12_ref_field_id`, an Airtable stamp field id per table |
| `granted_scopes` (inside `settings`) | checked against `required_scopes` before send (`client_error`, `scope`); left out when the provider cannot report scopes (Airtable `whoami`), and the provider's 403 is the check |
| resource scope | Airtable base ids, a Notion root page: a step param naming a container outside it is refused before send (`client_error`, `out_of_scope`) |

These values never come from step params (`ghl_crm.md`: "`locationId` … comes from the credential document, never
from `params`").

## Version rule

S5 copies the catalog's one `versions.binding` into `FrozenBindingIdentity.binding_version`; S12 entry denies a plan
whose binding row version no longer matches (`binding_version_mismatch`, C32, G2).

**Rule:** every profile change bumps `versions.binding`, except changes to `verified`, `review_by`, `limits`,
`deprecated_at`, `sunset_at` and `replacement_kernel_op_id`. (`compare` bumps: dropping a field makes probe and
verification check less for executions already running.) (A list of what does *not* bump is shorter and
safer than a list of what does: a new field bumps until someone decides otherwise.) In the same change, the changed
provider's profile lists **only** the new value; every other profile **adds** it to its list.

**Runtime check (engine, before send):** if `binding.binding_version` is not in `compatible_binding_versions`, nothing
is sent:

| Path | Result | Effect |
|---|---|---|
| `call` | `client_error`, `provider_code: "binding_version_mismatch"` | step fails, nothing sent, breaker not counted (C37) |
| `probe` | `INCONCLUSIVE` | dead letter after the bounded probes, safe |
| `observe` | `matches_expected=None` | verification `UNKNOWN` |
| inverse | `client_error` | a `rollback` dead letter for a human |

Why a list: with one catalog-wide version, a single string would make one provider's change fail every other
provider's running executions. With the list, only the changed provider's admitted executions fail closed; the others
keep running. S12 entry still refuses every plan built before the bump (C32), for every provider: a plan waiting at
S10 for confirmation, or suspended, must be requested again. That is the existing behaviour, and the reason bumps
should be rare and batched.

**Rollout:** pause new entries only for tenants using the changed provider (C39 `paused_until`), let their running
executions finish, load the catalog and deploy, unpause. After that, old values can be pruned from every list. A
per-provider binding version in the catalog would remove the extra list entries; that is a catalog format change
(owner decision 6).

## How a call runs

1. **Binding version** in the list, else refuse (above).
2. **Credential document** (README §5): `connection_id` missing → `client_error` `no_connection`; `credential()`
   raising → `not_dispatched`; a required setting missing → `client_error` `connection_incomplete`; then scopes and
   resource scope.
3. **URL**: `base_url` + `endpoint`; `{api_version}` and `{settings.*}` filled from the profile and the document; each
   `{name}` filled from step params **as one URL-encoded path segment** (a value containing `/`, `?`, `#` or `..` is
   refused before send, `client_error` `bad_path_param`); a placeholder left unfilled is refused the same way. A
   read whose URL would exceed `max_url_length` switches to its `long_url_endpoint`, or is refused.
4. **Request**: `build_request` gives the query and body; the engine adds the paging values, the version header,
   the provider key for `native_header` / `body_field`, and `fixed_params` last.
5. **Archetype** runs the call (and, for probe, observe and inverse, the paths in the archetype table) with the hooks.
6. **Classification**: `classify`, then the README §2 table. `data` on failure holds only `provider_status` and
   `provider_code`; bodies are never logged or kept.
7. **One trace line** (INFO, no PII, no values): `trace_id`, `kernel_op_id`, archetype, call path, attempt,
   `binding_version`, `api_version`, method, endpoint **template**, provider status, provider request id (from
   `request_id_header`), latency. This
   is how an operator finds which API version and endpoint an execution used, without changing the manifest.
8. A `Sunset` or `Deprecation` response header adds one WARNING line. Adapters never emit events (README §1).

**Cursor note:** `data["next"]` is returned, but today nothing can use it: a step cannot take another step's output
(C36) and the S15 envelope does not return result data (DR-40). Until DR-40 is fixed a list returns its first page.

## Provider behaviours the engine must not hide

From the earlier app's Airtable and Notion work. Most are now engine rules (above); the rest are spec lines.

| Provider behaviour (example) | Rule |
|---|---|
| A write accepted with HTTP 200 but only partly applied (Airtable `details.message: "partialSuccess"`) | `ok` with the identifier, so verification and rollback see the resource; `observe` compares and fails the step. Never `error` for a write that took effect (it would leave an orphan). The step ends FAIL, never success |
| Fields silently ignored on write (Airtable computed fields) | `compare` covers every field the step writes; a silent drop becomes a verification FAIL |
| `PUT` clears unsent fields (Airtable `records.replace`) | Its own operation, archetype `replace`, never a flag of an update |
| Deprecated endpoints remapped by the adapter (Notion `/v1/data_sources` → `/v1/databases`) | Never. An endpoint change is a profile change and a version bump |
| A cursor expires (Airtable `offset`, 422 on iteration timeout) | `client_error` `cursor_expired`; a new request starts without one |
| No delete endpoint, or the action notifies people (comments) | The catalog marks it `IRREVERSIBLE` (archetype `send` or `custom`) |
| A secret returned only once (Airtable webhook `macSecretBase64`) | Never in `data`; off the allow-list until a secret store takes it (DR-11, MC-058) |
| No connection mapped for the caller | `client_error` `no_connection`; never a default account, token file or environment variable |
| Empty values left out of responses (Airtable `false`, `""`, `[]`) | Engine rule "compare what was written" |
| A 404 meaning "no access" (Airtable no-grant bases) | `not_found: needs_parent_read` |
| Request flags that change the provider's schema (Airtable `typecast: true`) | `fixed_params` |
| Response keys users can rename (Airtable field and table names) | Ids in paths, `compare` and `fixed_params` (`returnFieldsByFieldId: true`) |
| Very large or data-bearing error bodies (Notion: a 60 KB body for an invalid emoji) | Never logged or kept |

## Checks

**Profile check** (engine at adapter start, and `tests_agent`). It reads only the profile; an adapter never reads the
registry (README §1, isolation):

- parses; `profile_format` known; required fields present; enum values valid;
- every `create` with `stamp` has a `stamp_marker`; every `create`, `update`, `replace` and `send` has `compare`;
  every W, D and IRREVERSIBLE operation has a `read` that names a `reads:` entry; no value is a `VERIFY` placeholder;
- `version_scheme: path` ⇒ `base_url` contains `{api_version}`; `header` ⇒ `version_header` set;
- every placeholder in an endpoint, a `reads:` entry or a `stamp_marker` is a step param, an `identifier` part,
  `{api_version}` or a `{settings.name}`;
- the subclass implements every hook its archetypes require; the count of `custom` entries is reported.

**Catalog check** (`tests_agent`, against `docs/catalog/catalog.yaml`):

- every `kernels:` key is an operation of this provider, and every operation of this provider has an entry;
- archetype fits the catalog mutation (`read_one`/`list_page` ↔ R; `create`/`update`/`replace` ↔ W; `delete` ↔ D;
  `send` ↔ IRREVERSIBLE; `custom` any);
- every W, D and IRREVERSIBLE operation's `read` equals its catalog `observation.method`, and that name has a
  `reads:` entry; every
  `create` with a catalog `inverse` points at a `delete`;
- `versions.binding` is in every profile's `compatible_binding_versions`.

For a deployment, whose catalog lives in the database, the same catalog check belongs in the Worker Runtime start-up
check next to `unverifiable_mutation` (M21, DR-41), which already reads the bindings (owner decision 5).

**Conformance tests from the profile** (`tests_agent`): the README §6 matrix is generated per operation from its
archetype, so a new operation gets its cases automatically and fails until its recorded fixtures exist
(`tests_agent/fixtures/providers/<provider>/<operation>/<case>.json`).

**Engine tests** (`tests_agent`, once, for all providers): the engine concentrates the safety rules, so a bug in it
reaches every provider at once. It gets its own README §6 matrix against a fake provider, plus sabotage patches in the
M10 pattern: `NOT_EXECUTED` from an `eventual` lookup, a 404 taken as gone without the parent read, an unencoded path
parameter, a `fixed_params` value overridden by params, a probe or observe that skips `owns`, a write answered 2xx
without its identifier taken as `ok`, a `delete` inverse that deletes a record without our stamp. Each must be
caught.

**Date checks** (reported, never blocking unrelated work): `sunset_at` within N days; `review_by` passed.

## Example: `crm` (GoHighLevel)

Values from `ghl_crm.md`; every one is still VERIFY there. Matches the catalog's eleven `crm.*` operations.

```yaml
# src/engines/crm/profile.yaml
provider: crm
profile_format: 1
compatible_binding_versions: [bind-1]
api_version: "2021-07-28"
version_scheme: header
version_header: Version
base_url: https://services.leadconnectorhq.com
max_page_size: 100
idempotency: stamp
not_found: absent               # GHL answers "no access" with 403 (ghl_crm.md §2)
read_by_id: consistent          # ghl_crm.md: GET by id treated as authoritative (VERIFY)
verified: {docs: null, recorded: null}
review_by: 2026-12-31
limits: {burst: "100 per 10 s per location", daily: "200000 per location", bulkhead: 8}

reads:
  get_contact: {endpoint: "/contacts/{id}"}
  get_note:    {endpoint: "/contacts/{contactId}/notes/{id}", identifier: "{contactId}/{id}"}
  get_task:    {endpoint: "/contacts/{contactId}/tasks/{id}", identifier: "{contactId}/{id}"}

kernels:
  crm.contact_list:   {archetype: list_page, method: POST, endpoint: /contacts/search,
                       paging: {size: pageLimit, cursor: searchAfter, next: VERIFY}}   # the profile check refuses VERIFY: record it first
  crm.contact_create: {archetype: create, method: POST, endpoint: /contacts/, read: get_contact,
                       stamp_marker: "custom_field:s12_ref",
                       compare: [firstName, lastName, email, phone, tags, source, customFields]}
  crm.contact_update: {archetype: update, method: PUT, endpoint: "/contacts/{id}", read: get_contact,
                       compare: [firstName, lastName, email, phone, tags, source, customFields]}
  crm.contact_delete: {archetype: delete, method: DELETE, endpoint: "/contacts/{id}", read: get_contact}
  crm.note_list:      {archetype: list_page, method: GET, endpoint: "/contacts/{contactId}/notes"}
  crm.note_create:    {archetype: create, method: POST, endpoint: "/contacts/{contactId}/notes", read: get_note,
                       stamp_marker: body_suffix, compare: [body]}
  crm.note_delete:    {archetype: delete, method: DELETE, endpoint: "/contacts/{contactId}/notes/{id}", read: get_note}
  crm.task_list:      {archetype: list_page, method: GET, endpoint: "/contacts/{contactId}/tasks"}
  crm.task_create:    {archetype: create, method: POST, endpoint: "/contacts/{contactId}/tasks", read: get_task,
                       stamp_marker: body_suffix, compare: [title, body, dueDate, completed, assignedTo]}
  crm.task_update:    {archetype: update, method: PUT, endpoint: "/contacts/{contactId}/tasks/{id}", read: get_task,
                       compare: [title, body, dueDate, completed, assignedTo]}
  crm.task_delete:    {archetype: delete, method: DELETE, endpoint: "/contacts/{contactId}/tasks/{id}", read: get_task}
```

`lookup` stays `eventual` everywhere: GHL's contact search is an eventually consistent index, and the note and
task lists may become `consistent` only after `ghl_crm.md`'s L2 measurement. `contact_update` is a `PUT` that sends
only the fields in params (`ghl_crm.md` §1), so its archetype is `update`. The note and task `identifier` patterns need the
catalog change `ghl_crm.md` §0 already asks for (`identifier_field: ref`); until it is made, their delete observations
stay UNKNOWN, as the spec says. The hooks GHL needs: `build_request`, `extract`, `classify` (duplicate-contact rule),
`find_by_key`, `normalize` (stamp-line stripping, E.164 phones, lower-cased email), `owns` (stamp and `locationId`).
`classify` also maps GHL's recorded "note not found" / "contact not found" 400s to `not_found`.

**A finding in `ghl_crm.md` itself (owner decision 9):** its §4 says `get_contact` "always" checks `s12_ref` = the
stamp. `crm.contact_update` and `crm.task_update` observe through the same reads, and the record they update carries
the stamp of the step that created it, or none if it predates S12. Under that rule every update verification would
FAIL. It is latent today (updates are off the launch list), and the "two strengths" rule above resolves it: the stamp
is checked only where S12 created the record in this step.

## Sketches for other providers (illustrative; need catalog rows and VERIFY)

Airtable, showing path versioning, fixed params and the parent read:

```yaml
provider: airtable
api_version: "v0"
version_scheme: path
base_url: https://api.airtable.com/{api_version}
paging: {size: pageSize, cursor: offset, next: offset}
max_page_size: 100
max_url_length: 16000
not_found: needs_parent_read    # no grant on a base answers 404 everywhere
fixed_params: {typecast: false, returnFieldsByFieldId: true}
reads:
  get_record: {endpoint: "/{baseId}/{tableId}/{id}", identifier: "{baseId}/{tableId}/{id}",
               parent: "/{baseId}/{tableId}"}   # the engine asks the parent for one item
kernels:
  airtable.record_list:   {archetype: list_page, method: GET, endpoint: "/{baseId}/{tableId}",
                           long_url_endpoint: "/{baseId}/{tableId}/listRecords"}
  airtable.record_create: {archetype: create, method: POST, endpoint: "/{baseId}/{tableId}", read: get_record,
                           stamp_marker: "field:{settings.stamp_field_id}", compare: [fields]}
  airtable.record_update: {archetype: update, method: PATCH, endpoint: "/{baseId}/{tableId}/{id}", read: get_record,
                           compare: [fields]}
  airtable.record_delete: {archetype: delete, method: DELETE, endpoint: "/{baseId}/{tableId}/{id}", read: get_record}
```

Notion, showing a soft delete through `PATCH` and `absent_when` (Notion has no `DELETE /v1/pages`):

```yaml
provider: notion
api_version: "2025-09-03"
version_scheme: header
version_header: Notion-Version
base_url: https://api.notion.com/v1
paging: {size: page_size, cursor: start_cursor, next: next_cursor}
max_page_size: 100
not_found: needs_parent_read    # VERIFY whether an unshared page answers 403 or 404
reads:
  get_page: {endpoint: "/pages/{id}", absent_when: {in_trash: true}, parent: "/data_sources/{settings.data_source_id}"}
kernels:
  notion.row_create:  {archetype: create, method: POST, endpoint: /pages, read: get_page,
                       stamp_marker: "property:{settings.stamp_property}", compare: [properties]}
  notion.page_update: {archetype: update, method: PATCH, endpoint: "/pages/{id}", read: get_page, compare: [properties]}
  notion.page_trash:  {archetype: delete, method: PATCH, endpoint: "/pages/{id}", read: get_page}   # build_request sends {in_trash: true}
```

## Not adopted

| Idea | Why not |
|---|---|
| Hierarchical resource model in the contract | One kernel op per step; S9 plans compositions |
| Lazy identity resolution at S12 | Binding drift (I-002, I-010) and an unbudgeted call |
| Live schema introspection at run time | Registry facts are authoritative (A4); no network dependency in the pipeline |
| Retry, a breaker or client retries inside the adapter | The guard owns them; transport `retries=0` |
| Side-effect ledger as an adapter contract | The ledger is the engine's (S12's) |
| Paging many pages in one call | One page per call (Layer A convention) |
| `status="partial"` | `AdapterResult` is `ok` / `error` / `timeout` |
| Async multi-step flows (Notion view queries, file uploads) | No verification path; off the allow-list |
| Business-entity matrices, composites, workflow IR in the adapter layer | Plans belong to S4/S9 (M2a) |
| Hot credential reload, token fallback chains, multi-account registries | One `CredentialProvider`, keyed by `connection_id` |
| Request-body templates in the profile | `build_request` code; nested typed bodies in data are hard to review and test |
| Profile fields (`api_version`, profile version) in the `ExecutionManifest` | The manifest is a frozen S0–S11 contract; the trace line records them instead |
| The adapter checking the catalog's version at start | Isolation (README §1); the catalog check is a test and a Worker Runtime start-up check |
| A plugin registry or dynamically loaded adapters | The catalog's `engine_module` / `adapter_class` already name the class; one routing adapter is DR-42 |

## Owner decisions needed (when the first new-adapter milestone starts)

1. Check this structure against the Notion and Airtable v2 adapter package (DR-38, prepared for `adapters-work`, not in
   this repository).
2. Accept the engine, the closed archetype set and the hook list; the first adapter is written in this shape, the
   engine is extracted with the second, and the engine tests and sabotage patches are part of that extraction.
3. Accept the profile, its location, the `reads:` block as the definition of `observation.method` names, and the
   `not_found` rule (default `needs_parent_read`).
4. Accept the version rule with `compatible_binding_versions` and the per-provider rollout.
5. Add the catalog check to the Worker Runtime start-up check (S12 code, next to `unverifiable_mutation`).
6. Optional CONF items: a per-provider binding version in the catalog; per-provider breaker and bulkhead settings;
   per-key breakers (`ghl_crm.md` Q3); the routing adapter for several providers in one runtime (DR-42).
7. Update `TEMPLATE.md`: point its header table, endpoints and compared fields to the profile; add "Cannot do" and
   "Fails silently" sections; list the hooks the provider implements.
8. When `PROVIDER_ADAPTERS.md` is next amended and re-pinned, apply `PROVIDER_ADAPTERS_CORRECTIONS.md`.
9. Correct `ghl_crm.md` §4: the stamp check applies to the create's observation and the inverse, not to update
   observations (see the finding under the GHL example).
