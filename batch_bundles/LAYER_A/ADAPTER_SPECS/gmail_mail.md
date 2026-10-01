# Gmail: adapter specification (`mail`)

> Read [`README.md`](README.md) first. Its contract (§1), error rules (§2), probe and observe rules (§3, §4),
> credentials (§5) and test plan (§6) apply unchanged. This file records only what is **specific** to the Gmail API.
> Every fact about Gmail is marked **VERIFY** until it has been checked against Google's current documentation **and**
> a recorded sandbox response.

| | |
|---|---|
| Status | DRAFT (owner review). **Excluded from the launch allow-list** (see §1) |
| Provider API and version | Gmail API v1, base `https://gmail.googleapis.com/gmail/v1`, user `me` (the authenticated or impersonated mailbox) (VERIFY) |
| Adapter class / module | `MailAdapter` in `src/engines/mail/adapter.py` (catalog `engine_module: engines.mail`, `adapter_class: MailAdapter`) |
| Catalog provider id | `mail` (breaker and bulkhead key, CONF-022) |
| Provider idempotency support | **none** for `messages.send` (VERIFY). Strategy: **deterministic identifier**, the RFC 5322 `Message-ID` header derived from the key (§3) |
| Rate limits | quota units: `messages.send` = 100 units; `messages.get` / `messages.list` = 5 units. Per-user limit 250 units/s, i.e. ≈ 2 sends/s per mailbox (VERIFY). **Sending limits:** ≈ 2,000 messages/day per Workspace user, ≈ 500/day for consumer accounts (VERIFY). Bulkhead: 2 concurrent sends per mailbox |
| Consistency | `messages.get` by id: authoritative. `messages.list?q=…`: search index, **eventually consistent** (lag VERIFY, measured in §6 case L1) |

---

## 0. Why this provider is different

`mail.email_send` is the only **IRREVERSIBLE** operation in the catalog. Three consequences drive this whole file:

1. **No inverse, no compensation.** A sent message cannot be recalled.
2. **A duplicate send is visible to the customer's customer.** A wrong `NOT_EXECUTED` from the probe makes M13 retry,
   which sends the message twice. So the probe for this provider **never returns `NOT_EXECUTED`** (§3), unless the
   owner relaxes that rule (Q2).
3. **"Sent" is not "delivered".** A `2xx` means Gmail accepted and sent the message. A bounce arrives later as a
   separate message from `mailer-daemon`. Observe verifies the sent state only (§4). Delivery tracking is out of
   scope for S12–S15.

---

## 1. Operations on the allow-list

| Catalog op | Mutation | Provider call (VERIFY) | Request essentials | Success identifier | Inverse | Launch? |
|---|---|---|---|---|---|---|
| `mail.email_send` | IRREVERSIBLE (`never`) | `POST /users/me/messages/send` with body `{"raw": <base64url RFC 2822>, "threadId"?: …}` | the adapter builds the MIME message (below); `From` = the connection's mailbox or a verified alias; `Message-ID` = `<{mid_local}@{mid_domain}>` (§3) | `data["id"]` ← `response["id"]`; also `data["threadId"]`, `data["message_id_header"]` | none | **no** |

**Why excluded at launch:**

- The standard launch rule allows no IRREVERSIBLE op.
- The human verification layer that IRREVERSIBLE steps require has no channel yet (D4). Every send would therefore end
  in a dead letter, or wait on a verification that cannot complete.
- **Enable it only when:**
  - the human channel exists (D4);
  - Q1–Q4 are answered;
  - the §6 matrix is green;
  - L1 and L2 are measured;
  - the owner signs a per-tenant allow-list entry.

**Building the message (inside `call`, before send):**

- Use `email.message.EmailMessage` with `policy=email.policy.SMTP`.
- Headers: `From`, `To` (and `Cc` if `params` has it; no `Bcc` at launch, Q5), `Subject`, `Date`, `Message-ID`.
  Body: `text/plain`, plus optional `text/html` as `multipart/alternative`.
- **Header injection guard:** any `\r` or `\n` in `to`, `cc`, `subject` or a display name → `client_error`, nothing
  sent.
- **Validation:** at least one recipient. Every address must pass `email.utils.parseaddr` with an `@`; otherwise
  `client_error`. Size ≤ 25 MB after encoding (VERIFY the limit); otherwise `client_error`.
- **Attachments:** not supported in this phase. An `attachments` param → `client_error`.
- Encode the result with `base64.urlsafe_b64encode(msg.as_bytes())`, without stripping padding (VERIFY that Gmail
  accepts padded input).

**`data` on success:** `{id, threadId, message_id_header}`. Never the body, the recipients or the subject.

---

## 2. Error mapping (Gmail-specific rows; everything else follows README §2)

M = `mail.email_send` (ceiling 1, IRREVERSIBLE, no provider idempotency). R = probe and observe reads.

Google returns errors as `{"error": {"code", "message", "status", "errors": [{"reason", "domain"}]}}`. Classify on
`code` plus `errors[0].reason` (VERIFY each reason by recording). Store at most `provider_status` and `provider_code`
(= the `reason`).

| Provider response | Meaning | R result | M result | Why |
|---|---|---|---|---|
| `400` `invalidArgument` / `badRequest` ("Invalid To header", "Recipient address required") | malformed message | `client_error` | `client_error` | — |
| `400` `failedPrecondition` ("Mail service not enabled") | mailbox has no Gmail | `client_error` | `client_error` | connection misconfigured |
| `401` `authError` / `invalid_credentials` | token invalid or expired | `client_error` | `client_error` | the credential provider refreshes; `credential_valid` turns false when refresh fails (§5) |
| `403` `insufficientPermissions` / `forbidden` | missing scope or delegation | `client_error`, `provider_code: "scope"` | `client_error` | configuration |
| `403` `domainPolicy` | the Workspace admin forbids the API | `client_error` | `client_error` | — |
| `403` `rateLimitExceeded`, `userRateLimitExceeded` | per-second or per-user quota | `rate_limited` | `rate_limited` | Google refuses before acting. **Must** map here, or the breaker never opens (README §2.2) |
| `403` `dailyLimitExceeded` / `quotaExceeded` | project daily quota | `rate_limited`, `provider_code: "daily_quota"` | `rate_limited` | the breaker stays open until the reset; WARNING log |
| `429` `rateLimitExceeded` / "User-rate limit exceeded. Retry after <timestamp>" / "Daily user sending limit exceeded" | per-mailbox sending limit or concurrency | `rate_limited` | `rate_limited` | for the daily sending limit, put the parsed retry time into a WARNING log (not into `data`) |
| `404` on `messages.get` | message absent (or deleted by the user) | `client_error`; in **observe** see §4 | — | — |
| `500` `backendError` | Google internal | `server_error` | **`timeout`** | the message may already be sent |
| `502`, `504` | gateway | `server_error` | **`timeout`** | — |
| `503` `backendError` / "The service is currently unavailable" | unavailable | `server_error` | **`timeout`** | Google gives no "not processed" guarantee for sends (VERIFY). An IRREVERSIBLE op must assume it may have sent |
| `2xx` without `id` | malformed success | `adapter_defect` | **`timeout`** | — |

**Duplicate rule:** none. Gmail does not reject a second message with the same `Message-ID` (VERIFY). It sends it
again. That is why the probe never trusts absence.

**Before send vs after send in this adapter.** These steps happen before `client.send`:

| Step | Failure | Result |
|---|---|---|
| validate `params` | invalid input | `client_error` |
| build the MIME message | any build error | `client_error` |
| fetch the credential | credential provider or Google token endpoint unreachable | `not_dispatched` |
| fetch the credential | `invalid_grant` | `client_error` |

The send itself follows README §2.1. **`WriteTimeout` / `WriteError` after the body started → `timeout`**: with a large
body, Google may already have accepted it.

---

## 3. Probe

**Deterministic identifier.**

```python
mid_local  = "s12." + hashlib.sha256(call_meta.idempotency_key.encode()).hexdigest()[:40]
mid_domain = connection.message_id_domain          # a domain the tenant controls, e.g. "mail.example.com"
message_id = f"<{mid_local}@{mid_domain}>"
```

- It is stable across attempts, so every attempt for the same step carries the same `Message-ID`.
- **Critical VERIFY (Q1):** Gmail must preserve a client-supplied `Message-ID` on `messages.send`. Record it with
  case L2.
  - If Gmail rewrites it, the probe has no reliable key. Every probe then returns INCONCLUSIVE, which is safe: after
    3 probes the step dead-letters with the budget LOCKED.

| Op | Lookup | Proves EXECUTED_SUCCESS | Proves NOT_EXECUTED | Otherwise |
|---|---|---|---|---|
| `email_send` | `GET /users/me/messages?q=rfc822msgid:{mid_local}@{mid_domain} in:sent&maxResults=2`, then `messages.get` (format `metadata`, `metadataHeaders=Message-ID`) on each hit to confirm the header | exactly one message in `SENT` whose `Message-ID` equals ours → return it; M13 records `data["id"]` | **never** (default, Q2). The search index lags, and a duplicate send is irreversible | INCONCLUSIVE. Two or more hits → INCONCLUSIVE plus an ERROR log (the message went out twice) |

**Probe rules:**

- `429` / `403` rate-limit / 5xx / timeout on the probe → INCONCLUSIVE, never raises.
- `probe_backoff_s` for `mail` ≥ the measured index lag (L1). Start with **30 s**.
- The probe needs the `q` parameter. The `gmail.metadata` scope **does not allow `q`** (VERIFY), so the probe needs
  `gmail.readonly` (§5, Q3). Without it, the probe always returns INCONCLUSIVE.

---

## 4. Observe per `observation.method`

| `observation.method` | Read | Compared fields and normalisation | `expects_absent` handling |
|---|---|---|---|
| `get_message` | `GET /users/me/messages/{identifier}?format=metadata&metadataHeaders=Message-ID&metadataHeaders=To&metadataHeaders=Cc&metadataHeaders=Subject` | `labelIds` contains `SENT`; `Message-ID` equals ours (from `spec["idempotency_key"]`, recomputed as in §3); `To` and `Cc` compared as sets of lower-cased addr-specs (`email.utils.getaddresses`, display names ignored); `Subject` compared after RFC 2047 decoding, whitespace-trimmed. **Never** read or compare the body | not used by any catalog op. If set: `404` → `True` |
| any other method | — | — | `None`, `error="observe_not_supported"` |

**Observe rules for this provider:**

- `404` on `get_message` without `expects_absent` → `None`, `error="message_not_found"` (**UNKNOWN, not FAIL**). The
  user can delete a sent message from the mailbox, so its absence says nothing about the send.
- `observed_state` holds only booleans: `{"sent_label": bool, "message_id_ok": bool, "recipients_ok": bool,
  "subject_ok": bool}`. Never the addresses or the subject (M15 / M18 evidence rule).

---

## 5. Credentials

| Item | Value |
|---|---|
| Secret material | **Option A (Workspace tenants):** a Google service account with domain-wide delegation, impersonating the sender mailbox (`subject` = the mailbox). The key JSON is held by the credential provider; access tokens last 1 h. **Option B (consumer or per-user consent):** an OAuth 2.0 user refresh token. Q4 decides |
| Scopes (least) | `https://www.googleapis.com/auth/gmail.send` (send). `https://www.googleapis.com/auth/gmail.readonly` (probe search and observe) **or** `gmail.metadata` (observe only, no probe). `gmail.readonly` is a **restricted** scope: an externally published OAuth app needs Google verification and a security assessment (VERIFY). That affects the launch timeline, not the code |
| Per-connection settings | `mailbox` (sender address / impersonated subject); `from_display_name`; `message_id_domain`; `allowed_from_aliases`. Stored with the connection (MC-058); never in `params` or settings |
| Connection setup | (1) obtain a token; (2) `GET /users/me/profile` returns `emailAddress` = `mailbox`; (3) check send-as aliases (`GET /users/me/settings/sendAs`, VERIFY) if aliases are used; (4) record L2 once per domain |
| `credential_valid` rule | Local and cheap. True when the material is present, not marked revoked, and (option B) a refresh token is held. No Google round trip |
| Revocation signal | `invalid_grant` at token refresh, or `401` on a call → mark revoked; `credential_valid` turns false. Option A: `unauthorized_client` at token mint → the delegation was removed → revoked |
| Refresh | In the credential provider. Option A mints a new token per hour (no stored refresh token). Option B: Google refresh tokens do not rotate on use (VERIFY), but serialise refresh per connection anyway. Never log tokens or the service-account key |

---

## 6. Recorded-response tests

**Fixtures:** `tests_agent/fixtures/providers/gmail/email_send/<case>.json`, `…/probe/`, `…/observe/`.
**Tests:** `tests_agent/test_adapter_gmail.py`.
**Live smoke:** `tests_live/test_gmail_live.py` (opt-in; it sends only **to the sandbox's own mailbox**; env
`GMAIL_SANDBOX_*`, absent in CI).

**Sandbox:** a dedicated Workspace test domain or a test Google account. No customer data. Recipients are sandbox
mailboxes only.

**Scrubbing:** besides README §6, scrub `raw` from recorded requests completely. Keep only its decoded header *names*
and the `Message-ID` value.

**Standard matrix (README §6):**

| Row | Gmail case to record |
|---|---|
| 1 | `send/ok.json` |
| 2 | `send/ok_no_id.json` → `timeout` |
| 3 | `send/400_invalid_to.json` → `client_error` |
| 4 | `send/401.json`, `send/403_insufficient.json` → `client_error` |
| 5 | `send/403_rate_limit.json`, `send/403_user_rate_limit.json` → `rate_limited`; `send/403_daily.json` → `rate_limited` / `daily_quota` |
| 6 | `observe/404.json` → `None`, `message_not_found` |
| 7 | not applicable (no duplicate rule). Add `send/second_same_message_id.json` from the live smoke: Gmail accepts it (documents why the probe never trusts absence) |
| 8 | `send/429_sending_limit.json` → `rate_limited` |
| 9, 10 | `send/500.json`, `send/502.json`, `send/503.json`, `send/504.json` → `timeout`; the same on probe/observe → INCONCLUSIVE / `None` |
| 11–13 | as README |
| P1 | `probe/one_hit.json` → `EXECUTED_SUCCESS`, with the id |
| P2 | `probe/no_hit.json` → **INCONCLUSIVE** (not NOT_EXECUTED; the default rule) |
| P3–P5 | as README; P4 = `probe/two_hits.json` |
| O1–O4 | `observe/match.json`, `observe/subject_differs.json`, (O3 not applicable), `observe/500.json` |
| S1–S3 | S3 = the same `Message-ID` header in every attempt's `raw` (decode it in the test) |

**Provider-specific cases:**

| # | Case | Expected |
|---|---|---|
| M1 | CR/LF in `subject` or `to` | `client_error`; zero requests sent |
| M2 | `attachments` in `params` | `client_error`; zero requests sent |
| M3 | `From` not the mailbox nor an allowed alias | `client_error`; zero requests sent |
| M4 | token endpoint unreachable while fetching the credential | `not_dispatched` |
| M5 | `WriteTimeout` during the upload of a large `raw` | `timeout` |
| M6 | observe: To/Cc equal but with different case and display names | `True` |
| M7 | observe: the message lacks the `SENT` label | `False` |
| M8 | adapter output never contains the body, subject or recipients | scan every result and log record |

**Measurement cases (live smoke only):**

| # | Measure | Used for |
|---|---|---|
| L1 | send to self; poll `messages.list?q=rfc822msgid:…` every 2 s until found (20 runs; p99) | `probe_backoff_s` |
| L2 | send with our `Message-ID`; `messages.get` the sent copy and a received copy (another sandbox mailbox); compare `Message-ID` | Q1: does Gmail preserve it? Without it, the probe is INCONCLUSIVE forever |
| L3 | 5 sends in 1 s from one mailbox | the real per-user rate response (403 vs 429, reason codes) |

---

## 7. Open questions for the owner

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Does Gmail preserve our `Message-ID` (L2)? | Assume no until L2 proves it. The probe returns INCONCLUSIVE |
| Q2 | May the probe ever return NOT_EXECUTED for a send (e.g. after N searches spaced over 5 min)? | **Never.** A duplicate e-mail is irreversible; a dead letter is recoverable by a human |
| Q3 | Grant `gmail.readonly` (enables the probe, a restricted scope with Google verification) or only `gmail.metadata` (observe only)? | `gmail.metadata` until the send goes on the allow-list |
| Q4 | Workspace service account with delegation, or per-user OAuth? | Service account for Workspace tenants; per-user OAuth deferred |
| Q5 | Allow `Bcc` and attachments? | No in this phase |
| Q6 | Which domain is `message_id_domain`: the tenant's sending domain or ours? | The tenant's sending domain (keeps headers consistent with DKIM/SPF alignment) |
| Q7 | What carries the human verification for IRREVERSIBLE (D4), and when? | Not before the operator console; the op stays off the allow-list |
| Q8 | MC-058: credential storage and tenancy | **Blocking.** No real customer credential is stored until it is resolved |
