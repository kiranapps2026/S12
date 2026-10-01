# GoHighLevel: adapter specification (`crm`)

> Read [`README.md`](README.md) first. Its contract (§1), error rules (§2), probe and observe rules (§3, §4),
> credentials (§5) and test plan (§6) apply unchanged. This file records only what is **specific** to GoHighLevel.
> Every fact about the GHL API is marked **VERIFY** until it has been checked against the current GHL documentation
> **and** a recorded sandbox response.

| | |
|---|---|
| Status | DRAFT (owner review) |
| Provider API and version | LeadConnector API v2, base `https://services.leadconnectorhq.com`, header `Version: 2021-07-28` (VERIFY). `docs/implementation/PROVIDER_ADAPTERS.md` describes the v1 API (`rest.gohighlevel.com/v1`). v1 is end-of-support; **do not build on it** (VERIFY its status) |
| Adapter class / module | `CrmAdapter` in `src/engines/crm/adapter.py` (catalog `engine_module: engines.crm`, `adapter_class: CrmAdapter`). The catalog values are placeholders; keep them unless the owner renames the provider |
| Catalog provider id | `crm` (breaker and bulkhead key, CONF-022). See open question Q5 on per-location keys |
| Provider idempotency support | **none** (no idempotency header, VERIFY). Strategy: **stamp** (§3 below) |
| Rate limits | burst 100 requests per 10 s, and 200,000 per day, per app per location (VERIFY). Headers `X-RateLimit-Remaining`, `X-RateLimit-Max`, `X-RateLimit-Interval-Milliseconds`, `X-RateLimit-Daily-Remaining` (VERIFY). Bulkhead: 8 concurrent calls per process (start value; measure) |
| Consistency | `GET` by id: treated as authoritative (VERIFY). `POST /contacts/search`: search index, **eventually consistent** (lag VERIFY; measure it, see §6 case L1). Lists under a contact (`/contacts/{id}/notes`, `/tasks`): VERIFY whether they read the primary store or an index |

---

## 0. Conventions used in this file

**Stamp.** GHL has no idempotency key, so the adapter writes a deterministic marker derived from the key onto every
resource it creates:

```python
stamp = "s12-" + hashlib.sha256(call_meta.idempotency_key.encode()).hexdigest()[:32]
```

- **Why a hash and not the raw key?** The raw key (`{request_id}:{plan_step_id}`) exposes internal ids to the
  customer's staff in the GHL UI. The hash is stable across attempts and recovery, because the key is.
- **Where it goes:**
  - **Contacts:** a dedicated contact custom field, `s12_ref` (type single-line text). It is created once per
    location at connection setup (§5); its field id is stored with the connection.
  - **Notes:** a trailing line in the note body: `\n\n[ref:{stamp}]`.
  - **Tasks:** a trailing line in the task description (`body`): `\n\n[ref:{stamp}]`.
  - Owner decision Q1: the stamp is visible to GHL users on notes and tasks.
- **When it is checked:** observe and probe strip the trailing `[ref:…]` line before comparing text fields.

**Request essentials for every call:**

- Headers: `Authorization: Bearer <token>`, `Version: 2021-07-28`, `Accept: application/json`.
- HTTP client: `httpx.AsyncClient(timeout=settings.adapter_client_timeout_s)`. It is shared per process, and it **does
  not retry** (`transport=httpx.AsyncHTTPTransport(retries=0)`).
- **`locationId`:** sent wherever the endpoint needs it. It comes from the connection (§5), **never** from `params`. A
  plan step cannot choose another location.

**Never use `POST /contacts/upsert`.** Upsert merges into an existing contact that matches on e-mail or phone. The
catalog's inverse of `crm.contact_create` is `crm.contact_delete`. A compensation after an upsert would therefore
**delete a contact the customer already had**.

---

## 1. Operations on the allow-list

| Catalog op | Mutation | Provider call (VERIFY) | Request essentials | Success identifier | Inverse | Launch? |
|---|---|---|---|---|---|---|
| `crm.contact_list` | R (`safe`) | `POST /contacts/search` with body `{locationId, pageLimit, searchAfter?, query?, filters?}` | `pageLimit` ≤ 100 (VERIFY max); one page per call; the cursor goes back in `data["next"]` | `data["items"]` (list of `{id, firstName, lastName, email, phone, tags}`), `data["next"]`, `data["total"]` | — | **yes** |
| `crm.contact_create` | W | `POST /contacts/` with body `{locationId, firstName?, lastName?, email?, phone?, tags?, source?, customFields:[{id: <s12_ref id>, field_value: stamp}, …]}` | stamp in `customFields`; reject when neither `email` nor `phone` is given (`client_error`, before send) | `data["id"]` ← `response["contact"]["id"]` | `crm.contact_delete` | **yes** |
| `crm.contact_update` | W | `PUT /contacts/{contactId}` | only the fields in `params`; never touch `s12_ref` | `data["id"]` ← `response["contact"]["id"]` | none in the catalog | no (no inverse; needs the operator console) |
| `crm.contact_delete` | D | `DELETE /contacts/{contactId}` | — | `data["id"]` = the `contactId` sent (the body is `{succeded: true}`, sic; VERIFY) | none | no as a plan step; **yes as the compensation** of `contact_create` (Q2) |
| `crm.note_list` | R (`safe`) | `GET /contacts/{contactId}/notes` | `contactId` required | `data["items"]` (list of `{id, body, dateAdded}`) | — | **yes** |
| `crm.note_create` | W | `POST /contacts/{contactId}/notes` with body `{body, userId?}` | stamp appended to `body` | `data["id"]` ← `response["note"]["id"]`, `data["contactId"]` | `crm.note_delete` | **yes** |
| `crm.note_delete` | D | `DELETE /contacts/{contactId}/notes/{noteId}` | `contactId` and `id` required | `data["id"]` = the `noteId` sent | none | compensation only (Q2) |
| `crm.task_list` | R (`safe`) | `GET /contacts/{contactId}/tasks` | `contactId` required | `data["items"]` (list of `{id, title, dueDate, completed}`) | — | **yes** |
| `crm.task_create` | W | `POST /contacts/{contactId}/tasks` with body `{title, body?, dueDate, completed:false, assignedTo?}` | stamp appended to `body`; `dueDate` ISO-8601 UTC | `data["id"]` ← `response["task"]["id"]`, `data["contactId"]` | `crm.task_delete` | **yes** |
| `crm.task_update` | W | `PUT /contacts/{contactId}/tasks/{taskId}` | keep the stamp line when `body` is rewritten | `data["id"]` | none | no (no inverse) |
| `crm.task_delete` | D | `DELETE /contacts/{contactId}/tasks/{taskId}` | — | `data["id"]` = the `taskId` sent | none | compensation only (Q2) |

**Launch rule (from the standard):**

- On the allow-list: the three reads, plus the three creates whose inverses exist.
- Not on it: `update`, and `delete` as a planned step. They wait until the operator console can show and undo them.
- The `*_delete` operations must still be implemented and tested at launch, because compensation calls them.

**`data` on success** holds only what downstream steps need: the identifier, the parent id, and for lists the fields
named above. Do **not** copy the whole GHL record. Contacts carry many PII fields that no plan step asked for.

**Parent id for notes and tasks.** `observation.identifier_field` is `id`, but GHL addresses notes and tasks under
their contact. The adapter therefore returns `data["contactId"]`, and `observe` reads the parent from
`spec["expected"]["contactId"]` (Q3).

---

## 2. Error mapping (GHL-specific rows; everything else follows README §2)

R = read (`contact_list`, `note_list`, `task_list`, and every probe or observe read). M = mutation (all W and D ops,
ceiling 1 because `retry_safety: never`, **no** provider idempotency).

| Provider response (VERIFY each body) | Meaning | R result | M result | Why |
|---|---|---|---|---|
| `400` with `message` "This location does not allow duplicated contacts." and `meta: {contactId, matchingField}` | duplicate contact on create | — | **duplicate rule** (below) | the provider may hold our earlier attempt |
| `400` "Contact not found" / "Invalid contact id" on a note or task path | the parent contact is missing | `client_error` | `client_error` | the step's input is wrong; a retry cannot help |
| `400` / `422` with a `message` array (validation) | bad body | `client_error` | `client_error` | — |
| `401` "Invalid JWT" / "Token expired" | the token is invalid or expired | `client_error`, `provider_code: "auth"` | `client_error` | the credential provider refreshes; `credential_valid` must turn false if refresh fails (§5) |
| `401` / `403` "The token is not authorized for this scope." | missing scope | `client_error`, `provider_code: "scope"` | `client_error` | configuration; alert the operator |
| `403` "The token does not have access to this location." | wrong `locationId` for the token | `client_error`, `provider_code: "location"` | `client_error` | connection misconfigured; never retry |
| `404` on `GET/PUT/DELETE …/{id}` | resource absent | `client_error`; in **observe** with `expects_absent` → absent (§4) | `client_error` for PUT. For DELETE: see below | — |
| `404` on `DELETE` of contact, note or task | already gone | — | **`ok`** with `data["id"]` = the id sent, `data["already_absent"] = true` | the D op's goal state holds. It makes compensation re-runnable. **Deliberately overrides** README §2.2 row 404 for deletes only. Only the exact recorded not-found response counts |
| `429` (burst), with the rate-limit headers | throttled | `rate_limited` | `rate_limited` | GHL rejects before acting (VERIFY by recording) |
| `429` with `X-RateLimit-Daily-Remaining: 0` | daily quota spent | `rate_limited`, `provider_code: "daily_quota"` | `rate_limited` | the breaker opens; it recovers only after the daily reset. Emit a WARNING log naming the location (not the token) |
| `500`, `502`, `504`, Cloudflare `520`–`524` | server or edge failure | `server_error` | **`timeout`** | GHL sits behind Cloudflare. An edge 52x after the request was forwarded may follow an applied write |
| `503` | unavailable | `server_error` | **`timeout`** | GHL documents no "not processed" guarantee for 503 (VERIFY). Without one, README §2.2 says `timeout` |
| `2xx` without `contact.id` / `note.id` / `task.id` | malformed success | `adapter_defect` | **`timeout`** | the write may have happened |

**Duplicate rule (contact_create).** GHL refuses a second contact with the same e-mail or phone when the location
setting "Allow duplicate contact" is off (VERIFY: the setting's name and its default).

1. Read `meta.contactId` from the 400 body. Keep only the id; drop the body.
2. `GET /contacts/{contactId}`. If its `s12_ref` custom field equals our `stamp`, the earlier attempt created it:
   return `ok` with `data["id"] = contactId`, `data["deduplicated"] = true`.
3. Otherwise the contact belongs to someone else: return `client_error`, `provider_code: "duplicate_contact"`.
   **Never adopt** a foreign contact as ours. The compensation would delete it.
4. If the `GET` itself fails, return `timeout`. M13's probe settles it.

If the location **allows** duplicates, a repeated create makes a second contact. That is why `retry_safety` stays
`never`, and the probe (§3) must never say NOT_EXECUTED on weak evidence.

**Before-send / after-send inside the adapter.** The adapter takes these steps before the HTTP request, and it fails
them **before send**:

- validate `params`;
- fetch the credential;
- resolve the `s12_ref` field id from the connection.

Failures there map as follows: invalid input → `client_error`. Credential provider unreachable → `not_dispatched`.
Credential revoked → `client_error`. Everything after `client.send` follows README §2.1.

---

## 3. Probe per operation

M13 calls `probe` after an attempt was dispatched and the ledger has no result. `call_meta.idempotency_key` gives the
stamp. "Dispatch time" is the attempt's `dispatched_at`, available through `context` (VERIFY the field name in the
M13 wiring).

| Op | Lookup | Proves EXECUTED_SUCCESS | Proves NOT_EXECUTED | Otherwise |
|---|---|---|---|---|
| `contact_create` | (1) `POST /contacts/search` with a filter on custom field `s12_ref` = stamp (VERIFY the filter syntax for custom fields). (2) For each hit, `GET /contacts/{id}` to confirm `s12_ref` | exactly one contact whose `GET` shows our stamp | **never from search alone.** The index lags. Optional owner rule Q4: allowed only when (a) two searches spaced ≥ the measured lag both return nothing, **and** (b) a natural-key search (`email` or `phone` from `params`) shows no contact created after the dispatch time | INCONCLUSIVE. Two or more stamped hits: INCONCLUSIVE, plus an ERROR log (duplicate side effect) |
| `note_create` | `GET /contacts/{contactId}/notes`; match the trailing `[ref:{stamp}]` | exactly one note with our stamp | only if the per-contact list is verified as read-your-writes (§6 case L2), **and** the probe runs ≥ `probe_backoff_s` after dispatch, **and** the contact exists. Until verified: never | INCONCLUSIVE |
| `task_create` | `GET /contacts/{contactId}/tasks`; match the stamp in `body` | exactly one task with our stamp | same condition as `note_create` | INCONCLUSIVE |
| `contact_update`, `task_update` | `GET` by id | every field in `params` equals the stored value (state-based: re-applying the same PUT has the same effect) | the stored `dateUpdated` (VERIFY the field) is **before** the dispatch time and a field differs | INCONCLUSIVE (a field differs and `dateUpdated` is after the dispatch: someone else wrote) |
| `contact_delete`, `note_delete`, `task_delete` | `GET` by id | `404` (the goal state holds) | `200` (the resource still exists; a `GET` by id is authoritative) | INCONCLUSIVE on any error |
| reads | — | not called (reads have `retry_safety: safe`; M13 retries them instead) | — | — |

**Probe rules for this provider:**

- A probe that hits `429` or any 5xx returns INCONCLUSIVE. It does not sleep or retry. M13 spaces the attempts.
- `probe_backoff_s` for `crm` ≥ the measured search lag (§6 case L1). Start with **10 s** until it has been measured.
- After 3 INCONCLUSIVE, M13 dead-letters the step with the budget LOCKED. For `contact_create` that is the expected
  outcome under the default rule. It is rare, because it needs a post-send timeout, and it is safe.

---

## 4. Observe per `observation.method`

`spec = {method, identifier, expected, idempotency_key}`. `expected` holds the fields the step wrote.

| `observation.method` | Read | Compared fields and normalisation | `expects_absent` handling |
|---|---|---|---|
| `get_contact` | `GET /contacts/{identifier}` | Only the keys present in `expected`. Normalisation: `email` lower-cased and trimmed; `phone` compared in E.164 (GHL stores E.164; normalise `expected` with the same rule, default region from the connection, VERIFY); `tags` as a case-insensitive set (GHL lower-cases tags, VERIFY); names trimmed; `customFields` by field id. **Always** also check that `s12_ref` = the stamp; a mismatch means the id points at a contact that is not ours → `False` | `404` → `True`. `200` → `False`. Any other error → `None` with `error` |
| `get_note` | `GET /contacts/{expected.contactId}/notes/{identifier}` | `body` with the trailing `[ref:…]` line stripped, whitespace-trimmed; stamp equals ours | `404` (or the recorded "note not found" 400) → `True` |
| `get_task` | `GET /contacts/{expected.contactId}/tasks/{identifier}` | `title`; `body` with the stamp stripped; `dueDate` compared as a UTC instant at second precision; `completed` as a bool; `assignedTo` as an id | as `get_note` |
| `get_message` and others | — | — | `None`, `error="observe_not_supported"` |

**`observed_state` rules:**

- It contains only the compared keys, plus `"stamp_ok": bool`. Never put the record or its other fields in it.
- `provider_response_code` is the HTTP status.
- A missing `expected.contactId` for notes or tasks gives `None`, `error="observe_missing_parent"` (UNKNOWN, never
  FAIL).

---

## 5. Credentials

| Item | Value |
|---|---|
| Secret material | **Option A (default proposal):** an OAuth 2.0 access token from a GHL Marketplace app, installed per location. Access token lifetime ≈ 24 h; the refresh token **rotates** on every refresh (VERIFY). **Option B:** a Private Integration Token (PIT) per location: static, rotated by the customer (90-day rotation advised, VERIFY). Q6 decides |
| Scopes (least) | `contacts.readonly`, `contacts.write` (notes and tasks sit under the contact scopes, VERIFY). At setup only: `locations/customFields.readonly`, `locations/customFields.write` |
| Per-connection settings | `locationId`; `s12_ref_field_id`; `default_phone_region`; token expiry. Stored with the connection (MC-058), read via `CredentialProvider`; never in `params` or settings |
| Connection setup (one time, operator action, not a plan step) | (1) verify the token can read the location; (2) find or create the custom field `s12_ref` (`POST /locations/{locationId}/customFields`, VERIFY); (3) store its id; (4) run one read (`contact_list` with `pageLimit: 1`) |
| `credential_valid` rule | Local and cheap. True when the token is present and not marked revoked, and **either** not expired **or** a refresh token is held. No GHL round trip |
| Revocation signal | `401` on a call, or `invalid_grant` at refresh → mark the connection revoked; `credential_valid` turns false, and M14 blocks further steps on the connection. App uninstall webhook (`AppUninstall`, VERIFY) → same |
| Refresh | Inside the credential provider. With rotating refresh tokens, two concurrent refreshes invalidate each other. **Serialise refresh per connection** (an advisory lock on the connection id), and persist the new refresh token in the same transaction as the new access token. Never log either token |

**Token-in-error check.** GHL error bodies can echo request data. Under the §1 rule the adapter never stores bodies.
Case S1 proves it.

---

## 6. Recorded-response tests

**Fixtures:** `tests_agent/fixtures/providers/ghl/<op>/<case>.json`.
**Tests:** `tests_agent/test_adapter_ghl.py`.
**Live smoke:** `tests_live/test_ghl_live.py` (opt-in; env `GHL_SANDBOX_TOKEN`, `GHL_SANDBOX_LOCATION`, both absent
in CI).

**Sandbox:** a dedicated GHL test sub-account (location) with no customer data. Create one location with "Allow
duplicate contact" **off** and one with it **on**, so both duplicate paths get recorded.

**Standard matrix (README §6):** rows 1–13, P1–P5, O1–O4 and S1–S3 apply.

| Row | GHL case to record |
|---|---|
| 5 (403 rate-limit variant) | not applicable (GHL throttles with 429, VERIFY); assert that a plain 403 maps to `client_error` |
| 7 (duplicate) | `contact_create/duplicate_ours.json`: 400 + meta, then a GET showing our stamp → `ok`, `deduplicated`. `duplicate_foreign.json`: GET without the stamp → `client_error` / `duplicate_contact`. `duplicate_get_fails.json` → `timeout` |
| 9 | `500.json`, `502.json`, `cf_522.json`, `cf_524.json`: reads → `server_error`; creates → `timeout` |
| 10 | `503.json` → `timeout` for M (no "not processed" contract) |
| S3 | the stamp (not the raw key) is present in `customFields` / the note body / the task body on every attempt, unchanged |

**Provider-specific cases:**

| # | Case | Expected |
|---|---|---|
| G1 | `429` with `X-RateLimit-Daily-Remaining: 0` | `rate_limited`, `provider_code: "daily_quota"` |
| G2 | `403` "does not have access to this location" | `client_error`, `provider_code: "location"` |
| G3 | `DELETE` → `404` | `ok`, `already_absent: true` (compensation is re-runnable) |
| G4 | `params` contains `locationId` of another location | ignored; the request carries the connection's `locationId` (assert on the recorded request) |
| G5 | `contact_create` without e-mail or phone | `client_error`, no request sent (`MockTransport` call count 0) |
| G6 | the adapter never calls `/contacts/upsert` | assert across all fixtures: no request path ends in `/upsert` |
| G7 | note/task observe with the stamp line present and the text otherwise equal | `True`; the stamp line is stripped before comparison |
| G8 | observe of a contact whose `s12_ref` is not ours | `False` |
| G9 | probe: two stamped contacts found | INCONCLUSIVE, plus an ERROR log without PII |
| G10 | `401` → `credential_valid` turns false through the fake credential provider | M14 blocks the next step |

**Measurement cases (live smoke only; results go into §0 of this file):**

| # | Measure | Used for |
|---|---|---|
| L1 | create a stamped contact; poll `/contacts/search` by `s12_ref` every 1 s; record when it appears (20 runs; take p99) | `probe_backoff_s`; whether Q4 can ever be enabled |
| L2 | create a note/task; immediately `GET /contacts/{id}/notes` / `tasks` (20 runs) | whether per-contact lists are read-your-writes (enables NOT_EXECUTED for notes and tasks) |
| L3 | 120 requests in 10 s against one location | the real burst limit and the 429 headers |

**MockAdapter equivalence:** as README §6. `timeout_executed` → a ReadTimeout fixture plus a P1 search fixture;
`timeout_not_executed` → a ReadTimeout fixture plus P2. P2 is valid **only** for deletes and updates, and for notes and
tasks once L2 has passed. For `contact_create`, the matching test asserts INCONCLUSIVE.

---

## 7. Open questions for the owner

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | May the `[ref:…]` stamp line be visible in GHL note and task text? | Yes. The alternative is no stamp, which makes every post-send timeout on a note or task create dead-letter |
| Q2 | Are the `*_delete` ops allowed as planned steps at launch, or only as compensation? | Compensation only |
| Q3 | Does M15 put the step's `params` (incl. `contactId`) into `spec["expected"]`? If not, the identifier becomes `"{contactId}/{id}"` | Use `expected.contactId`. Check it in the M15 wiring before coding |
| Q4 | Allow NOT_EXECUTED for `contact_create` under the "settled search" rule (§3)? | No. Always INCONCLUSIVE, which leads to a dead-letter |
| Q5 | Breaker key: one `crm` breaker for every tenant (CONF-022 as written), or `crm:{locationId}`? One noisy location can open the breaker for all | `crm`, as CONF-022 says. Raise it as a new CONF if L3 shows cross-tenant impact |
| Q6 | OAuth Marketplace app (rotating refresh, per-install consent) or a Private Integration Token per location? | OAuth for customers; PIT for the sandbox only |
| Q7 | Is GoHighLevel the provider behind `crm` at all? | The proposal in this file; if not, copy `TEMPLATE.md` |
| Q8 | MC-058: credential storage and tenancy | **Blocking.** No real customer token is stored until it is resolved |
