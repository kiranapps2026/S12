# GoHighLevel: adapter specification (`crm`)

> Read [`README.md`](README.md) first, especially §1.1 (how S12 really calls the adapter). Its contract (§1), error
> rules (§2), probe and observe rules (§3, §4), credentials (§5) and test plan (§6) apply unchanged. This file records
> only what is **specific** to GoHighLevel. Every fact about the GHL API is marked **VERIFY** until it has been
> checked against the current GHL documentation **and** a recorded sandbox response.

| | |
|---|---|
| Status | DRAFT (owner review). Rechecked against the B3–B5 reference code (call, probe, observe, rollback paths) |
| Provider API and version | LeadConnector API v2, base `https://services.leadconnectorhq.com`, header `Version: 2021-07-28` (VERIFY). `docs/implementation/PROVIDER_ADAPTERS.md` describes the v1 API (`rest.gohighlevel.com/v1`). v1 is end-of-support; **do not build on it** (VERIFY its status) |
| Adapter class / module | `CrmAdapter` in `src/engines/crm/adapter.py` (catalog `engine_module: engines.crm`, `adapter_class: CrmAdapter`). The catalog values are placeholders; keep them unless the owner renames the provider |
| Catalog provider id | `crm` (breaker and bulkhead key, CONF-022). See Q3 on per-location keys |
| Provider idempotency support | **none** (no idempotency header, VERIFY). Strategy: **stamp** (§0) |
| Rate limits | burst 100 requests per 10 s, and 200,000 per day, per app per location (VERIFY). Headers `X-RateLimit-Remaining`, `X-RateLimit-Max`, `X-RateLimit-Interval-Milliseconds`, `X-RateLimit-Daily-Remaining` (VERIFY). Bulkhead: 8 concurrent calls per process (start value; measure with L3) |
| Consistency | `GET` by id: treated as authoritative (VERIFY). `POST /contacts/search`: search index, **eventually consistent** (lag VERIFY; measured by L1). Lists under a contact (`/contacts/{id}/notes`, `/tasks`): VERIFY whether they are read-your-writes (L2) |

---

## 0. Conventions used in this file

**Stamp.** GHL has no idempotency key, so the adapter writes a deterministic marker derived from the **step key**
onto every resource it creates:

```python
def stamp(key: str) -> str:                       # key = the step key {request_id}:{plan_step_id}
    return "s12-" + hashlib.sha256(key.encode()).hexdigest()[:32]

def step_key(call_meta) -> str:                   # the inverse key is "{step key}:inverse" (CONF-024)
    k = call_meta.idempotency_key
    return k[: -len(":inverse")] if k.endswith(":inverse") else k
```

- **Why a hash and not the raw key?** The raw key exposes internal ids to the customer's staff in the GHL UI. The
  hash is stable across attempts, probes, recovery and rollback, because the step key is.
- **Where it goes:**
  - **Contacts:** a dedicated contact custom field, `s12_ref` (single-line text). It is created once per location at
    connection setup (§5); its field id travels in the credential document.
  - **Notes:** a trailing line in the note body: `\n\n[ref:{stamp}]`.
  - **Tasks:** a trailing line in the task description (`body`): `\n\n[ref:{stamp}]`.
  - Q1 decides whether this line may be visible to GHL users (default: yes).
- **When it is checked:** observe, probe and inverse calls compare the stamp. Text comparisons strip the trailing
  `[ref:…]` line first.

**Credential document** (README §5). The `crm` credential provider returns this JSON string; the adapter parses it
and treats the whole string as secret:

```json
{"token": "<access token or PIT>",
 "settings": {"location_id": "…", "s12_ref_field_id": "…", "default_phone_region": "US"}}
```

**Request essentials for every call:**

- Headers: `Authorization: Bearer <token>`, `Version: 2021-07-28`, `Accept: application/json`.
- HTTP client: `httpx.AsyncClient(timeout=settings.adapter_client_timeout_s)`, shared per process, with
  `transport=httpx.AsyncHTTPTransport(retries=0)` (**no** client retries).
- **`locationId`:** sent wherever the endpoint needs it. It comes from the credential document, **never** from
  `params`. A plan step cannot choose another location. Any record the adapter reads back must carry the same
  `locationId`; otherwise it is treated as not ours.

**Never use `POST /contacts/upsert`.** Upsert merges into an existing contact that matches on e-mail or phone. The
inverse of `crm.contact_create` is `crm.contact_delete`; a rollback after an upsert would **delete a contact the
customer already had**.

**Identifier for parent-addressed resources (required catalog change).** GHL addresses notes and tasks under their
contact (`/contacts/{contactId}/notes/{id}`). For a delete, M15's `expected` is `{"exists": False}` with **no**
params (README §4), so observe cannot learn the `contactId` from it. The adapter therefore returns a composite
reference, and the catalog must point at it:

- every note and task W/D result carries `data["ref"] = "{contactId}/{id}"` as well as `data["id"]`;
- in `docs/catalog/catalog.yaml`, set `identifier_field: ref` for `crm.note_create`, `crm.note_delete`,
  `crm.task_create`, `crm.task_update` and `crm.task_delete` (contacts keep `identifier_field: id`).

The catalog is a starter (its header says so); this edit belongs to the Layer A work that registers the real
provider, then `tools/registry_readiness.py` must exit 0. Until it is made, notes and tasks still work; only their
delete observations are UNKNOWN (safe).

---

## 1. Operations on the allow-list

| Catalog op | Mutation | Provider call (VERIFY) | Request essentials | Success `data` | Inverse | Launch? |
|---|---|---|---|---|---|---|
| `crm.contact_list` | R (`safe`) | `POST /contacts/search` with body `{locationId, pageLimit, searchAfter?, query?, filters?}` | `pageLimit` ≤ 100 (VERIFY max); one page per call; the cursor goes back in `data["next"]` | `items` (list of `{id, firstName, lastName, email, phone, tags}`), `next`, `total` | — | **yes** |
| `crm.contact_create` | W | `POST /contacts/` with body `{locationId, firstName?, lastName?, email?, phone?, tags?, source?, customFields:[{id: <s12_ref_field_id>, field_value: stamp}, …]}` | stamp in `customFields`; at least one of `email` / `phone` (adapter rule, Q5; otherwise `client_error` before send) | `id` ← `response.contact.id` | `crm.contact_delete` | **yes** |
| `crm.contact_update` | W | `PUT /contacts/{params.id}` | only the fields in `params` except `id`; never touch `s12_ref` | `id` | none in the catalog | no (no inverse) |
| `crm.contact_delete` | D | `DELETE /contacts/{id}` | planned: `params.id`. **Inverse:** the target is located by the stamp (§3.1) | `id` (the body is `{succeded: true}`, sic; VERIFY) | none | no as a planned step (Q2); **implemented** for rollback |
| `crm.note_list` | R (`safe`) | `GET /contacts/{params.contactId}/notes` | — | `items` (list of `{id, body, dateAdded}`, bodies with the stamp line stripped) | — | **yes** |
| `crm.note_create` | W | `POST /contacts/{params.contactId}/notes` with body `{body, userId?}` | stamp appended to `body` | `id` ← `response.note.id`, `contactId`, `ref` | `crm.note_delete` | **yes** |
| `crm.note_delete` | D | `DELETE /contacts/{contactId}/notes/{id}` | planned: `params.contactId`, `params.id`. **Inverse:** located by the stamp (§3.1) | `id`, `contactId`, `ref` | none | no as a planned step (Q2); **implemented** for rollback |
| `crm.task_list` | R (`safe`) | `GET /contacts/{params.contactId}/tasks` | — | `items` (list of `{id, title, dueDate, completed}`) | — | **yes** |
| `crm.task_create` | W | `POST /contacts/{params.contactId}/tasks` with body `{title, body?, dueDate, completed:false, assignedTo?}` | stamp appended to `body`; `dueDate` ISO-8601 UTC | `id` ← `response.task.id`, `contactId`, `ref` | `crm.task_delete` | **yes** |
| `crm.task_update` | W | `PUT /contacts/{params.contactId}/tasks/{params.id}` | keep the stamp line when `body` is rewritten | `id`, `contactId`, `ref` | none | no (no inverse) |
| `crm.task_delete` | D | `DELETE /contacts/{contactId}/tasks/{id}` | planned: `params.contactId`, `params.id`. **Inverse:** located by the stamp (§3.1) | `id`, `contactId`, `ref` | none | no as a planned step (Q2); **implemented** for rollback |

**Launch rule (from the standard):**

- On the allow-list: the three reads, plus the three creates whose inverses exist.
- Not on it: `update`, and `delete` as a planned step. They wait for the operator console.
- The three `*_delete` ops must still be implemented and tested at launch: the explicit `rollback_execution` (D2)
  calls them as inverses, with the create's params (README §1.1).

**`data` on success** holds only what downstream steps need: identifiers and, for lists, the fields named above. Do
**not** copy the whole GHL record. Contacts carry many PII fields that no plan step asked for.

---

## 2. Error mapping (GHL-specific rows; everything else follows README §2)

R = read (`contact_list`, `note_list`, `task_list`, and every probe, observe or inverse lookup). M = mutation (all W
and D ops: ceiling 1 because `retry_safety: never`, **no** provider idempotency).

| Provider response (VERIFY each body) | Meaning | R result | M result | Why |
|---|---|---|---|---|
| `400` with `message` "This location does not allow duplicated contacts." and `meta: {contactId, matchingField}` | duplicate contact on create | — | **duplicate rule** (below) | the provider may hold our earlier attempt |
| `400` "Contact not found" / "Invalid contact id" on a note or task path | the parent contact is missing | `client_error` | `client_error` | the step's input is wrong; a retry cannot help |
| `400` / `422` with a `message` array (validation) | bad body | `client_error` | `client_error` | — |
| `401` "Invalid JWT" / "Token expired" | the token is invalid or expired | `client_error`, `provider_code: "auth"` | `client_error` | the credential provider marks the connection; M14's `credential_valid` then blocks the next step (§5) |
| `401` / `403` "The token is not authorized for this scope." | missing scope | `client_error`, `provider_code: "scope"` | `client_error` | configuration; alert the operator |
| `403` "The token does not have access to this location." | wrong `locationId` for the token | `client_error`, `provider_code: "location"` | `client_error` | connection misconfigured; never retry |
| `404` on `GET/PUT …/{id}` | resource absent | `client_error`; in **observe** with `expected.exists = False` → absent (§4) | `client_error` | — |
| `404` on `DELETE` of a contact, note or task | already gone | — | **`ok`** with the ids sent and `data["already_absent"] = true` | the D op's goal state holds, so a rollback can be re-run. **Deliberately overrides** README §2.2 row 404, for deletes only. Only the exact recorded not-found response counts |
| `429` (burst), with the rate-limit headers | throttled | `rate_limited` | `rate_limited` | GHL rejects before acting (VERIFY by recording) |
| `429` with `X-RateLimit-Daily-Remaining: 0` | daily quota spent | `rate_limited`, `provider_code: "daily_quota"` | `rate_limited` | the breaker opens; it recovers only after the daily reset. WARNING log naming the location (not the token) |
| `500`, `502`, `504`, Cloudflare `520`–`524` | server or edge failure | `server_error` | **`timeout`** | GHL sits behind Cloudflare; an edge 52x after the request was forwarded may follow an applied write |
| `503` | unavailable | `server_error` | **`timeout`** | GHL documents no "not processed" guarantee for 503 (VERIFY); without one, README §2.2 says `timeout` |
| `2xx` without `contact.id` / `note.id` / `task.id` | malformed success | `adapter_defect` | **`timeout`** | the write may have happened |

**Duplicate rule (contact_create).** GHL refuses a second contact with the same e-mail or phone when the location
setting "Allow duplicate contact" is off (VERIFY the setting's name and default).

1. Read `meta.contactId` from the 400 body. Keep only the id; drop the body.
2. `GET /contacts/{contactId}`. If its `s12_ref` equals `stamp(step_key)` and its `locationId` is ours, the earlier
   attempt created it: return `ok` with `data["id"] = contactId`, `data["deduplicated"] = true`.
3. Otherwise the contact belongs to someone else: return `client_error`, `provider_code: "duplicate_contact"`.
   **Never adopt** a foreign contact as ours; a rollback would delete it.
4. If the `GET` itself fails, return `timeout`. M13's probe settles it.

If the location **allows** duplicates, a repeated create makes a second contact. That is why `retry_safety` stays
`never`, and why the probe never says NOT_EXECUTED for a contact create (§3).

**Before send vs after send inside the adapter.** These steps run before the HTTP request, so their failures are
before send:

| Step | Failure | Result |
|---|---|---|
| validate `params` | invalid input | `client_error` |
| `context.connection_id` | `None` | `client_error`, `no_connection` |
| `credential()` and parse the credential document | raises, or the document lacks `token` / `location_id` / `s12_ref_field_id` | `not_dispatched` (raise) / `client_error`, `connection_incomplete` (missing settings) |
| inverse lookup (§3.1) | no target / ambiguous / lookup error | `client_error` `inverse_target_not_found` / `inverse_target_ambiguous` / the lookup's R result |

Everything from `client.send` on follows README §2.1.

---

## 3. Probe per operation

M13 calls `probe` after a dispatched attempt timed out and the ledger has no result. It runs immediately, then after
about 1×b and 3×b (`b = probe_backoff_s`, default 1 s; README §1.1 item 4). `call_meta.idempotency_key` is the step
key, so `stamp(step_key(call_meta))` is the marker to look for. No dispatch time is available, and none is used.

| Op | Lookup | Proves EXECUTED_SUCCESS | Proves NOT_EXECUTED | Otherwise |
|---|---|---|---|---|
| `contact_create` | (1) `POST /contacts/search` filtered on custom field `s12_ref` = stamp (VERIFY the filter syntax for custom fields). (2) For each hit, `GET /contacts/{id}` to confirm `s12_ref` and `locationId` | exactly one confirmed contact | **never** (decided). The search index lags, and a wrong NOT_EXECUTED makes M13 create a second contact | INCONCLUSIVE. Two or more confirmed hits: INCONCLUSIVE plus an ERROR log without PII (duplicate side effect) |
| `note_create` | `GET /contacts/{params.contactId}/notes`; match the trailing `[ref:{stamp}]` | exactly one note with our stamp | only after L2 has proven the per-contact list read-your-writes, **and** the list call succeeded, **and** no note carries the stamp. Until L2 passes: never | INCONCLUSIVE |
| `task_create` | `GET /contacts/{params.contactId}/tasks`; match the stamp in `body` | exactly one task with our stamp | same condition as `note_create` | INCONCLUSIVE |
| `contact_update`, `task_update` | `GET` by id | every compared field in `params` equals the stored value (state-based: re-applying the same PUT has the same effect) | **never**. Without a dispatch time, a differing field cannot be told apart from a later write by someone else | INCONCLUSIVE |
| `contact_delete`, `note_delete`, `task_delete` (planned steps) | `GET` by id | `404` (the goal state holds) | `200` with our `locationId` (a `GET` by id is authoritative) | INCONCLUSIVE on any error |
| reads | — | not called: reads are `retry_safety: safe` and M11 retries them | — | — |

**Probe rules for this provider:**

- A probe that hits `429` or any 5xx returns INCONCLUSIVE. It never sleeps or retries; M13 spaces the attempts.
- After 3 INCONCLUSIVE, M13 dead-letters the step (`unknown_unresolved`, `retry_mode PROBE`, budget LOCKED). M17's
  `retry_dead_letter` probes again later, when the search index has caught up: an `EXECUTED_SUCCESS` then resolves
  the letter as EXECUTED. This is the expected path for a timed-out contact create; it is rare (it needs a post-send
  timeout) and safe.

### 3.1 Inverse calls (explicit rollback)

`rollback_execution` calls the delete op with the **create's params** and the key `{step key}:inverse`, once, through
the guard, with no probe (README §1.1). The delete op recognises the inverse by the key suffix and locates its target:

| Inverse of | Locate | Act |
|---|---|---|
| `contact_create` | `POST /contacts/search` on `s12_ref` = `stamp(step_key)`; `GET` each hit; keep those with our stamp and `locationId` | exactly one → `DELETE /contacts/{id}`; `2xx` or `404` → `ok`. Zero → `client_error` `inverse_target_not_found`. Two or more → `client_error` `inverse_target_ambiguous` |
| `note_create` | `GET /contacts/{params.contactId}/notes`; match the stamp | as above, with `DELETE /contacts/{contactId}/notes/{id}` |
| `task_create` | `GET /contacts/{params.contactId}/tasks`; match the stamp | as above, with `DELETE /contacts/{contactId}/tasks/{id}` |

- Rollback runs on a terminal run, normally long after the create, so the search index has caught up. Zero hits
  still never means "already deleted": it becomes a `rollback` dead letter for a human (`retry_mode NONE`).
- No destructive request is ever sent for a target that does not carry our stamp. This also protects a deduplicated
  contact that belongs to someone else (it never carries our stamp).
- The lookup's own failures map as reads (`429` → `rate_limited`, 5xx → `server_error`); with one attempt they
  become the rollback dead letter, which is correct: nothing was deleted.
- `confirm_executed(step)` (the caller's check before each inverse) can use `observe` with `get_contact` /
  `get_note` / `get_task` and `identifier=None`: the same stamp lookup.

---

## 4. Observe per `observation.method`

`spec = {method, identifier, expected, idempotency_key}`. For W: `expected = {"exists": True, "properties": <step
params>}`. For D: `expected = {"exists": False}`. `identifier` is `None` after the probe path (README §4).

| `observation.method` | Read | Compared fields and normalisation | `expected.exists = False` |
|---|---|---|---|
| `get_contact` | `identifier` set: `GET /contacts/{identifier}`. `identifier` `None`: the §3 stamp search with `stamp(spec.idempotency_key)`, then `GET`; zero or several hits → `None`, `observe_no_identifier` | Compared, if present in `properties`: `firstName`, `lastName` (trimmed); `email` (lower-cased, trimmed); `phone` (E.164 on both sides, region from `default_phone_region`, VERIFY that GHL stores E.164); `tags` (case-insensitive set, VERIFY that GHL lower-cases tags); `source`; `customFields` (by field id). Ignored: every other key (`id`, `locationId`, paging). **Always** checked: `s12_ref` = the stamp and `locationId` = ours; a mismatch means the id is not our contact → `False` | `404` → `True`. `200` → `False`. Any other error → `None` with `error` |
| `get_note` | `identifier` = `ref` (`"{contactId}/{noteId}"`): `GET /contacts/{contactId}/notes/{noteId}`. `None`: list `properties.contactId`'s notes and match the stamp | `body` with the stamp line stripped, whitespace-trimmed; stamp equals ours | `404` (or the recorded "note not found" 400) → `True`. With `identifier` `None` (no properties for a D op) → `None`, `observe_no_identifier` |
| `get_task` | as `get_note`, under `/tasks/` | `title`; `body` with the stamp stripped; `dueDate` as a UTC instant at second precision; `completed` as a bool; `assignedTo` as an id | as `get_note` |
| any other method | — | — | `None`, `error="observe_not_supported"` |

**Rules:**

- `observed_state` contains only the compared keys' match results, plus `"stamp_ok": bool`. Never the record.
- `provider_response_code` is the HTTP status (0 when no request completed).
- Until the catalog change in §0 is made, `identifier` for notes and tasks is the bare note/task id. Then read the
  parent from `properties.contactId` for W ops; for D ops return `None`, `observe_missing_parent` (UNKNOWN, safe).
- Verification makes up to 3 observations, 1 s apart; a `GET` by id is consistent, so creates normally PASS on the
  first one.

---

## 5. Credentials

| Item | Value |
|---|---|
| Secret material | **Option A (default):** an OAuth 2.0 access token from a GHL Marketplace app, installed per location. Access token lifetime ≈ 24 h; the refresh token **rotates** on every refresh (VERIFY). **Option B:** a Private Integration Token (PIT) per location: static, rotated by the customer (90-day rotation advised, VERIFY). Q4 decides |
| Delivered as | the credential document in §0 (one JSON string from `CredentialProvider.credential`) |
| Scopes (least) | `contacts.readonly`, `contacts.write` (notes and tasks sit under the contact scopes, VERIFY). At setup only: `locations/customFields.readonly`, `locations/customFields.write` |
| Per-connection settings | `location_id`, `s12_ref_field_id`, `default_phone_region`: stored with the connection by the credential provider (MC-058), never in `params` or settings |
| Connection setup (one time, operator action, not a plan step) | (1) verify the token can read the location; (2) find or create the custom field `s12_ref` (`POST /locations/{locationId}/customFields`, VERIFY); (3) store its id; (4) run one `contact_list` with `pageLimit: 1` |
| `credential_valid` rule | Local and cheap: the document is present and complete, the connection is not marked revoked, and **either** the token is not expired **or** a refresh token is held. No GHL round trip |
| Revocation signal | `401` on a call, or `invalid_grant` at refresh → the credential provider marks the connection revoked; `credential_valid` turns false and M14 blocks further steps on it (CONF-030). App uninstall webhook (`AppUninstall`, VERIFY) → same. The adapter reports the 401 only as `client_error`; marking is the credential provider's job (it sees the refresh failure) |
| Refresh | Inside the credential provider. Rotating refresh tokens mean two concurrent refreshes invalidate each other: **serialise refresh per connection** (an advisory lock on the connection id) and persist the new refresh token in the same transaction as the new access token. Never log either token |

---

## 6. Recorded-response tests

**Fixtures:** `tests_agent/fixtures/providers/ghl/<op>/<case>.json`.
**Tests:** `tests_agent/test_adapter_ghl.py`.
**Live smoke:** `tests_live/test_ghl_live.py` (opt-in; env `GHL_SANDBOX_TOKEN`, `GHL_SANDBOX_LOCATION`, both absent
in CI).

**Sandbox:** a dedicated GHL test sub-account (location) with no customer data. Use one location with "Allow
duplicate contact" **off** and one with it **on**, so both duplicate paths are recorded.

**Standard matrix (README §6):** rows 1–16, P1–P5, O1–O6, I1–I3 and S1–S3 apply.

| Row | GHL case to record |
|---|---|
| 5 (403 rate-limit variant) | not applicable (GHL throttles with 429, VERIFY); assert that a plain 403 maps to `client_error` |
| 7 (duplicate) | `contact_create/duplicate_ours.json`: 400 + meta, then a GET showing our stamp → `ok`, `deduplicated`. `duplicate_foreign.json` → `client_error` / `duplicate_contact`. `duplicate_get_fails.json` → `timeout` |
| 9 | `500.json`, `502.json`, `cf_522.json`, `cf_524.json`: reads → `server_error`; creates → `timeout` |
| 10 | `503.json` → `timeout` for M (no "not processed" contract) |
| P2 | for `contact_create`: an empty search → **INCONCLUSIVE**. For planned deletes: `GET` 200 → NOT_EXECUTED. For notes/tasks: NOT_EXECUTED only behind the L2 flag |
| O5 | `get_contact` with `identifier=None` finds the contact by stamp; `get_note` with `identifier=None` lists `properties.contactId`'s notes |
| I1–I3 | `contact_delete` / `note_delete` / `task_delete` called with the create's params and an `:inverse` key |
| S3 | the stamp (never the raw key) is present in `customFields` / the note body / the task body on every attempt, unchanged; the inverse locates by the stamp of the key **without** `:inverse` |

**Provider-specific cases:**

| # | Case | Expected |
|---|---|---|
| G1 | `429` with `X-RateLimit-Daily-Remaining: 0` | `rate_limited`, `provider_code: "daily_quota"` |
| G2 | `403` "does not have access to this location" | `client_error`, `provider_code: "location"` |
| G3 | planned `DELETE` → `404` | `ok`, `already_absent: true` |
| G4 | `params` contains another `locationId` | ignored on the request (the document's `location_id` is sent) and in observe |
| G5 | `contact_create` without e-mail or phone | `client_error`; `MockTransport` call count 0 |
| G6 | the adapter never calls `/contacts/upsert` | across all fixtures, no request path ends in `/upsert` |
| G7 | note/task observe with the stamp line present and the text otherwise equal | `True` |
| G8 | observe of a contact whose `s12_ref` or `locationId` is not ours | `False` |
| G9 | probe: two stamped contacts found | INCONCLUSIVE, plus an ERROR log without PII |
| G10 | the credential document lacks `s12_ref_field_id` | `client_error`, `connection_incomplete`; zero requests |
| G11 | inverse of `contact_create` where the only e-mail match lacks our stamp | `client_error`, `inverse_target_not_found`; **no** `DELETE` sent |
| G12 | `ref` parsing: `"{contactId}/{id}"` with a malformed value | `None`, `observe_no_identifier` (no request) |

**Measurement cases (live smoke only; record the results in this file's header):**

| # | Measure | Used for |
|---|---|---|
| L1 | create a stamped contact; poll `/contacts/search` by `s12_ref` every 1 s until it appears (20 runs; p99) | documents why a timed-out contact create ends in a PROBE dead letter, and when `retry_dead_letter` can resolve it |
| L2 | create a note/task; immediately `GET /contacts/{id}/notes` / `tasks` (20 runs) | turns on NOT_EXECUTED for notes and tasks only if all 20 are read-your-writes |
| L3 | 120 requests in 10 s against one location | the real burst limit, the 429 headers, the bulkhead size |

**MockAdapter equivalence:** as README §6. `timeout_not_executed` maps to a planned-delete `GET` 200 (or notes/tasks
behind L2); for `contact_create` the matching test asserts INCONCLUSIVE instead.

---

## 7. Open questions for the owner (none blocks building; each has a safe default)

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | May the `[ref:…]` stamp line be visible in GHL note and task text? | Yes. Without it, every post-send timeout and every rollback of a note or task needs a human |
| Q2 | Are the `*_delete` ops allowed as planned steps at launch, or only as rollback inverses? | Rollback inverses only |
| Q3 | Breaker key: one `crm` breaker for every tenant (CONF-022 as written), or `crm:{locationId}`? One noisy location can open the breaker for all | `crm`, as CONF-022 says. Raise a new CONF if L3 shows cross-tenant impact |
| Q4 | OAuth Marketplace app (rotating refresh, per-install consent) or a Private Integration Token per location? | OAuth for customers; PIT for the sandbox only |
| Q5 | Keep the adapter rule "a contact needs an e-mail or a phone"? (It makes the duplicate rule meaningful; GHL itself may accept name-only contacts, VERIFY) | Keep it |
| Q6 | Is GoHighLevel the provider behind `crm` at all? | The proposal in this file; otherwise copy `TEMPLATE.md` |

**Go-live gates (not questions):** MC-058 resolved before any customer token is stored; the §0 catalog change made;
every VERIFY checked by a recording (README §8).
