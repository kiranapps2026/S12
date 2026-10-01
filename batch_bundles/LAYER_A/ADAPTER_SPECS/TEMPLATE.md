# <Provider name>: adapter specification (`<provider id in catalog>`)

> Copy this file to `<provider>_<domain>.md`. Fill every section; mark unchecked provider facts **VERIFY**. Read
> [`README.md`](README.md) first: its contract, error rules (§2), probe and observe rules (§3, §4), credentials (§5)
> and test plan (§6) apply unchanged. This file only records what is **specific** to the provider.

| | |
|---|---|
| Status | DRAFT / REVIEWED / APPROVED (owner) |
| Provider API and version | <base URL, version header or path> (VERIFY) |
| Adapter class / module | `<Class>` in `src/engines/<provider>/adapter.py` (matches catalog `engine_module`, `adapter_class`) |
| Catalog provider id | `<id>` (breaker and bulkhead key, CONF-022) |
| Provider idempotency support | yes (<header>) / no (stamp strategy: <field>) |
| Rate limits | <limit per scope> (VERIFY); bulkhead size <n> |
| Consistency | reads by id: <strong / eventual>; search: <lag> (VERIFY) |

## 1. Operations on the allow-list

| Catalog op | Mutation | Provider call | Request essentials | Success identifier | Inverse | Launch? |
|---|---|---|---|---|---|---|
| `<domain>.<noun>_<verb>` | R/W/D/IRREVERSIBLE | `<METHOD> <path>` | <required params, how the idempotency key is sent or stamped> | `data["id"]` from <response field> | `<op>` / — | yes / no (why) |

**Launch rule:** reads, plus writes that have an inverse. No IRREVERSIBLE (its human verification layer has no
channel; D4), no update or delete until the operator console exists.

## 2. Error mapping (only the provider-specific rows; everything else follows README §2)

| Provider response | Meaning | R result | M result | Why |
|---|---|---|---|---|
| `<status> <body code>` | | | | |

Duplicate / conflict rule: <exact condition under which a duplicate counts as our earlier success>.

## 3. Probe per operation

| Op | Lookup | Proves EXECUTED_SUCCESS | Proves NOT_EXECUTED | Otherwise |
|---|---|---|---|---|

## 4. Observe per `observation.method`

| `observation.method` | Read | Compared fields and normalisation | `expects_absent` handling |
|---|---|---|---|

## 5. Credentials

| Item | Value |
|---|---|
| Secret material | <token type> |
| Scopes / permissions (least) | |
| Per-connection settings | <e.g. account/location id> stored with the connection, read via `CredentialProvider` |
| `credential_valid` rule | |
| Revocation signal | |
| Refresh | |

## 6. Recorded-response tests

Fixture directory `tests_agent/fixtures/providers/<provider>/`. List the matrix rows (README §6) that apply, the extra
provider-specific cases, and the sandbox account used for recording (no customer data).

## 7. Open questions for the owner

| # | Question | Default if unanswered |
|---|---|---|
