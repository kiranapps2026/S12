# Layer A: provider adapter specifications (standard, template, per-provider specs)

**Purpose.** These specs let a real provider run behind the S12 reliability machinery without turning it into a
dead-letter generator. One file per provider. Every file follows [`TEMPLATE.md`](TEMPLATE.md) and this standard.

| File | Provider | Catalog operations | Launch status |
|---|---|---|---|
| [`ghl_crm.md`](ghl_crm.md) | GoHighLevel (LeadConnector API v2) as the `crm` provider | `crm.contact_*`, `crm.note_*`, `crm.task_*` | reads and reversible creates on the launch allow-list |
| [`gmail_mail.md`](gmail_mail.md) | Gmail API as the `mail` provider | `mail.email_send` | **excluded at launch** (IRREVERSIBLE; see the file) |
| [`TEMPLATE.md`](TEMPLATE.md) | any further provider (Notion, Airtable, Google Calendar/Sheets, browser/RPA) | — | copy, fill, review |

**Status of this folder:**

- DRAFT for owner review.
- The catalog in `docs/catalog/catalog.yaml` is a **starter** written without knowing the real providers; its
  `provider`, `engine_module` and `adapter_class` are placeholders. Mapping `crm` → GoHighLevel and `mail` → Gmail is a
  **proposal**. If you choose other providers, keep the operation ids and write new provider files from the template.
- Facts about a provider's API (paths, headers, limits, error bodies) are marked **VERIFY**. Check each against the
  provider's current documentation and a recorded sandbox response before coding.

**Prerequisite.** M10–M19 built and green. The adapter plugs into M10's `ReliabilityGuard`, and its results flow
through M11 (ledger), M13 (probe), M15 (verification) and M17 (dead letters).

---

## 1. The contract every adapter implements (S12–S15 phase)

Source: golden `tests_golden/s12/M10_guard.py` docstring (binding), `PROVIDER_ADAPTERS.md` §1 (additive interface),
gate C31, C32, C35, C37, ruling CONF-021.

```python
class XAdapter(BaseAdapter):                      # contracts.adapter_interface.BaseAdapter
    async def call(self, kernel_op_id, params, binding, context, *, call_meta=None) -> AdapterResult: ...
    async def probe(self, kernel_op_id, params, binding, context, *, call_meta) -> ProbeOutcome: ...
    async def observe(self, kernel_op_id, observation_spec, binding, context) -> Observation: ...
```

| Rule | Detail |
|---|---|
| Return type | `contracts.step_execution.AdapterResult(status, retryable, error_class, data)`, **not** `KernelResult` (CONF-021). `status` is `"ok"`, `"error"` or `"timeout"`; `error_class` is a `contracts.adapter_interface.ErrorClass` value |
| Never raise | `call`, `probe` and `observe` return; they never raise. If something escapes anyway, the guard turns it into `adapter_defect` (non-retryable, ERROR alert); treat that as a bug in your adapter |
| No own deadline above the step | the HTTP client timeout comes from `ExecutionSettings.adapter_client_timeout_s`, which is **< `step_timeout_s`** (C37). The guard's `TimeoutManager` decides timeouts. The `PROVIDER_ADAPTERS.md` example (35 s client timeout > 30 s step timeout) predates C37: do not copy it |
| No own retries | never retry inside the adapter. Retry ceilings, backoff and the retry-storm guard belong to S12 (M11, `retry_policy.ceiling`) |
| Credentials | only via the injected `CredentialProvider` (`credential(tenant_id, connection_id)`, `credential_valid(...)`). Never from settings, files or the environment; never in a result, a log line or `data` (§21 S6, M18) |
| `data` on success | a JSON dict. It **must** contain the field named by the operation's `observation.identifier_field` (normally `id`); otherwise M15's deterministic layer fails every write |
| `data` on failure | at most `{"provider_status": <int>, "provider_code": <short code>}`. **Never** the provider's error body (M18 `ledger_keeps_bodies`; bodies can carry tokens and PII) |
| Idempotency key | `call_meta.idempotency_key` (`{request_id}:{plan_step_id}`) is stable across attempts and recovery. Send it to the provider when the provider supports idempotency; otherwise **stamp it on the created resource** so `probe` can find it (§4) |
| Params | never mutate the `params` dict (contract test `test_adapter_does_not_mutate_params`) |
| Isolation | no calls to the control plane, other adapters or S12 code; no authorization decisions (S8 and M14's live check own those) |

---

## 2. Error classification: the before-send / after-send rule

Classification decides what S12 does next:

- `not_dispatched`, `rate_limited`, `server_error` may be **retried**, but only within the ceiling.
- `timeout` goes to the **probe** (M13).
- `client_error` **fails** without a retry and without counting against the breaker.

**The ceiling matters more than the class.** In the catalog every W/D/IRREVERSIBLE operation has
`retry_safety: never`, so `retry_policy.ceiling` is **1**: a mutation is never retried. A mutation result classified
as `server_error` or `not_dispatched` therefore **fails the step immediately, with no probe**. If the provider did the
work anyway, you now have a side effect the run says never happened.

> **The rule.** Return a retryable *error* class only when you can prove the request never reached the provider's
> application, or that the provider rejected it without acting. Whenever the request **may** have been processed,
> return `status="timeout"`. That is the class that leads to a probe, and the probe decides.

### 2.1 Transport exceptions (httpx; map other clients the same way)

| Exception | When it happens | Request reached the provider? | Result |
|---|---|---|---|
| `httpx.ConnectError` (refused, DNS, TLS handshake) | before any byte of the request | no | `error`, `not_dispatched`, retryable |
| `httpx.ConnectTimeout` | before the connection exists | no | `error`, `not_dispatched` |
| `httpx.PoolTimeout` | waiting for a pooled connection | no | `error`, `not_dispatched` |
| `httpx.WriteTimeout`, `httpx.WriteError` | while sending the body | **maybe** (partial body; some servers act on headers or a partial body) | `timeout` |
| `httpx.ReadTimeout` | after sending, waiting for the response | **maybe** | `timeout` |
| `httpx.ReadError`, `httpx.RemoteProtocolError` (reset or closed after send) | after sending | **maybe** | `timeout` |
| `asyncio.TimeoutError` / `TimeoutError` from your own code | — | — | do not create one: let the guard's deadline act (CONF-023 already maps an escaping `TimeoutError` to `timeout`) |
| any other exception inside the adapter | — | unknown | catch it at the top of `call`: return `timeout` if it happened after the send, else `error`, `adapter_defect`. Never raise |

`ConnectError` is a subclass of `NetworkError` in httpx. `PROVIDER_ADAPTERS.md` §1 maps `httpx.NetworkError` to
UNKNOWN; under gate C35 a refused connection is `not_dispatched`. **Check `ConnectError` / `ConnectTimeout` /
`PoolTimeout` before the broader classes.**

### 2.2 HTTP responses

`M` = the operation mutates (W, D, IRREVERSIBLE); `R` = read.

| Response | R | M (no provider idempotency) | M (provider honours an idempotency key) |
|---|---|---|---|
| 2xx, body parses, identifier present | `ok` | `ok` | `ok` |
| 2xx, but the body is not JSON or lacks the identifier | `error`, `adapter_defect` | **`timeout`** (the provider may have acted) | `timeout` |
| 2xx with a provider-level partial or failure flag (e.g. Notion `partialSuccess`) | provider file decides | `timeout` (probe) | `timeout` |
| 400 / 422 validation | `client_error` | `client_error` | `client_error` |
| 401 / 403 auth or permission | `client_error` (also makes M14's `credential_valid` false next time) | `client_error` | `client_error` |
| 403 that is really a rate limit (Google `rateLimitExceeded`, `userRateLimitExceeded`) | `rate_limited` | `rate_limited` (the request was refused, not processed) | `rate_limited` |
| 404 on an addressed resource | `client_error` | `client_error` (update/delete of a missing resource) | `client_error` |
| 409 conflict / duplicate | `client_error`, unless the provider file defines a duplicate rule | see the provider file: a duplicate that carries **our** key is success | `ok` with the existing id, if the provider says it replayed |
| 429 | `rate_limited` | `rate_limited` (rejected before acting) | `rate_limited` |
| 408 | `server_error` | **`timeout`** (be conservative) | `server_error` |
| 500 | `server_error` | **`timeout`** | `server_error` (retry is safe with the key) |
| 502, 504 (gateway: the upstream may have acted) | `server_error` | **`timeout`** | `server_error` |
| 503 with `Retry-After`, or an explicit "not processed" body | `server_error` | `server_error` (fails at ceiling 1; acceptable because the provider says it did not act). VERIFY per provider; otherwise `timeout` | `server_error` |
| anything unlisted | `server_error` | `timeout` | `server_error` |

**Breaker interaction (M10):** `client_error` is ignored by the breaker; every other error class and every `timeout`
counts as a failure. A provider that answers rate limits with 403 and is not mapped to `rate_limited` will **not**
open the breaker, and will keep hammering the provider.

---

## 3. Probe (`probe()` → `ProbeOutcome`)

M13 calls `guard.probe` only after the ledger has no record and the step's attempt was dispatched. The question is
always the same: **did the call identified by `call_meta.idempotency_key` take effect?**

| Outcome | Return it only when |
|---|---|
| `EXECUTED_SUCCESS` | you found the resource or effect, **and** it carries our idempotency key (or is otherwise proven to be ours) |
| `EXECUTED_FAILURE` | the provider records the attempt as failed (rare; only where the provider has an operation log) |
| `NOT_EXECUTED` | you can **prove absence**: an authoritative, strongly consistent read for our key returned nothing, after the provider's documented propagation delay. M13 will then **retry the operation**, so a wrong NOT_EXECUTED is a duplicate side effect |
| `INCONCLUSIVE` | anything else: search index lag, a read error, ambiguous matches, more than one match. After 3 INCONCLUSIVE the step dead-letters with its budget LOCKED, which is safe |

**Finding the key** (choose per operation, most reliable first):

1. **Provider idempotency key:** send it, then look the operation up by it.
2. **Deterministic identifier:** derive the resource id or a unique field from the key (e.g. the e-mail `Message-ID`
   `<{idempotency_key}@{our-domain}>`).
3. **Stamped marker:** write the key into a dedicated, non-user-facing field (a custom field, metadata, an external
   id), then read by it.
4. **Natural key plus time window:** search by the operation's unique business field (e.g. contact e-mail) created
   after the dispatch time. Use it only where the provider guarantees uniqueness; otherwise it is at best a
   candidate for EXECUTED_SUCCESS, **never** a basis for NOT_EXECUTED.

**Search indexes are eventually consistent.** A search returning nothing proves nothing. NOT_EXECUTED needs a read by
id, or by a strongly consistent index; or the provider file documents the delay and the probe waits for it. M13
spaces probe attempts by `probe_backoff_s`. Set it at least as large as the provider's lag.

A probe is read-only, takes its own bulkhead slot and `probe_timeout_s`, bypasses the breaker, and never raises.

---

## 4. Observe (`observe()` → `Observation`)

M15's `provider_state` layer calls `guard.observe(kernel_op_id, spec, binding, context)` with
`spec = {"method", "identifier", "expected", "idempotency_key"}`. `method` comes from the catalog's
`observation.method` (`get_contact`, …).

| Result | `matches_expected` | Verdict |
|---|---|---|
| resource read, fields equal `expected` (or absent when `expects_absent`) | `True` | PASS |
| resource read, fields differ (or present when it should be absent) | `False`, with `error=None` | **FAIL** (the step fails; the budget is released) |
| read failed, timed out, 5xx, 429, permission error | `None`, with `error` set | UNKNOWN (VERIFICATION episode, re-observed; never FAIL) |
| `method` not implemented | `None`, `error="observe_not_supported"` | UNKNOWN |

**Rules:**

- `observed_state` carries only the compared fields, never the full provider record (M15 and M18: evidence never holds
  provider data).
- `expected` compares only the fields the step wrote. Ignore server-generated fields (timestamps, normalised phone
  formats). Each provider file states its normalisation rules.
- An observation that errors **and** reports a mismatch is UNKNOWN, not FAIL (M15 golden).
- Bounded: M15 retries `verifier.max_attempts` times with `attempt_delay_ms`. The adapter observes once per call.

---

## 5. Credentials

- Every call, probe and observe asks `CredentialProvider.credential(tenant_id, context.connection_id)`. One connection
  is one provider account of one tenant (C34, MC-058).
- `credential_valid(tenant_id, connection_id)` (CONF-030) answers M14's live check before every call. Make it a cheap
  local check (token present, not expired or revoked, refreshable), not a provider round trip on every step.
- Token refresh happens inside the credential provider, not the adapter, and never logs the token.
- Each provider file lists the scopes, the secret material, where per-connection settings live (e.g. a GHL
  `locationId`), and how revocation shows up (`401` → `client_error`, and `credential_valid` turns false).
- **Blocking for launch:** credential storage and tenancy (blocker MC-058) must be resolved before real customer
  secrets are stored.

---

## 6. Recorded-response test plan (applies to every provider)

**Where:**

- Recorded fixtures: `tests_agent/fixtures/providers/<provider>/<operation>/<case>.json`.
- Tests: `tests_agent/test_adapter_<provider>.py` (offline, always run in CI).
- Live smoke: `tests_live/test_<provider>_live.py` (opt-in, sandbox credentials, never in CI by default; the repo
  already uses `tests_live/` for DeepSeek).

**Recording:**

1. Record against a **sandbox** account, never a customer account.
2. Scrub before saving: `Authorization`, cookies, tokens, e-mail addresses, phone numbers, names, location and
   account ids. Replace them with stable fakes; the scrubber is part of the test suite.
3. Store method, path, request-body keys (not values), status, response headers you rely on (`Retry-After`,
   rate-limit headers), and the scrubbed body.
4. Replay through `httpx.MockTransport`, so no network is touched.
5. Re-record when the provider changes its API version. Keep the API version in each fixture.

**Matrix: every operation on the allow-list gets every row that applies:**

| # | Case | Expected adapter result |
|---|---|---|
| 1 | 2xx with identifier | `ok`, `data[identifier_field]` present, `data` holds no secret |
| 2 | 2xx malformed or without identifier | R: `adapter_defect`; M: `timeout` |
| 3 | 400 / 422 | `client_error`, `data` without body |
| 4 | 401, 403 (auth) | `client_error` |
| 5 | 403 rate-limit variant (if the provider has one) | `rate_limited` |
| 6 | 404 | `client_error` |
| 7 | 409 / duplicate | per the provider file |
| 8 | 429 with `Retry-After` | `rate_limited` |
| 9 | 500, 502, 504 | R: `server_error`; M: `timeout` |
| 10 | 503 "not processed" | per §2.2 |
| 11 | `ConnectError`, `ConnectTimeout`, `PoolTimeout` | `not_dispatched` |
| 12 | `WriteTimeout`, `ReadTimeout`, `ReadError`, `RemoteProtocolError` | `timeout` |
| 13 | unexpected exception inside the adapter | never raises; `adapter_defect`, or `timeout` if after the send |
| P1 | probe: resource with our key exists | `EXECUTED_SUCCESS` |
| P2 | probe: authoritative read shows absence | `NOT_EXECUTED` |
| P3 | probe: search empty, but only an eventually consistent index exists | `INCONCLUSIVE` |
| P4 | probe: two candidates | `INCONCLUSIVE` |
| P5 | probe: read fails (5xx, 429, timeout) | `INCONCLUSIVE`, never raises |
| O1 | observe: fields match | `matches_expected=True` |
| O2 | observe: a field differs | `matches_expected=False`, `error=None` |
| O3 | observe: delete, resource gone (404) | `True` when `expects_absent` |
| O4 | observe: read error | `matches_expected=None`, `error` set |
| S1 | secrets: run every case with a credential containing `SECRET-TOKEN` | the string appears in no result, no `data`, no log record |
| S2 | params unchanged | `params` deep-equals its copy after every case |
| S3 | key propagation | the key reaches the provider request (header or stamped field) on every attempt, unchanged |

**Equivalence with the M10 mock.** Each `MockAdapter` behaviour has a recorded counterpart:

| `MockAdapter` behaviour | Recorded rows |
|---|---|
| `success` | 1 |
| `fail_500_then_success` | 9 (R) |
| `rate_limit_429` | 8 |
| `auth_401`, `validation_422` | 4, 3 |
| `timeout_executed` | 12 + P1 |
| `timeout_not_executed` | 12 + P2 |
| `connect_refused` | 11 |
| `verify_mismatch` | O2 |
| `raise_exception` | 13 |

Run the M12–M21 journeys once with the real adapter wired in and recorded transport, as an integration check.
**Never** edit the golden files to do it; use a `tests_agent` copy of the M12 `_deps` wiring.

---

## 7. Definition of done for one provider

- [ ] The provider file complete: no `TODO`, every VERIFY checked against the docs and a recorded response.
- [ ] Catalog rows for its operations: `observation.method` and `identifier_field` set; reads `retry_safety: safe`;
      `tools/registry_readiness.py` exits 0.
- [ ] The test matrix green offline; the live smoke green once in the sandbox.
- [ ] The credential provider implements `credential` and `credential_valid` for this provider; MC-058 resolved.
- [ ] The breaker key and rate limits documented; the bulkhead size set from the provider's concurrency limit.
- [ ] M10–M21 golden still green, and the IMPROVEMENT_GUIDE scans pass (no exception text in logs, no unfenced
      writes, no direct adapter calls outside the guard).
- [ ] Owner sign-off on the launch allow-list for this provider.
