# <Provider name>: adapter specification (`<provider id in catalog>`)

> Copy this file to `<provider>_<domain>.md`. Fill every section; mark unchecked provider facts **VERIFY**. Read
> [`README.md`](README.md) first, especially §1.1 (the four call paths: call, probe, observe, inverse): its contract, error rules (§2), probe and observe rules (§3, §4), credentials (§5)
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
| Credential document | `{"token": …, "settings": {<per-connection settings>}}` returned as one string by `CredentialProvider.credential` (README §5) |
| Identifier | `identifier_field` per op; a composite `ref` if the provider addresses resources under a parent (README §4: D ops get no params in `expected`) |

## 1. Operations on the allow-list

| Catalog op | Mutation | Provider call | Request essentials | Success identifier | Inverse | Launch? |
|---|---|---|---|---|---|---|
| `<domain>.<noun>_<verb>` | R/W/D/IRREVERSIBLE | `<METHOD> <path>` | <required params, how the idempotency key is sent or stamped; for a D op that is an inverse: how it locates its target from the create's params> | `data["id"]` from <response field> | `<op>` / — | yes / no (why) |

**Launch rule:** reads, plus writes that have an inverse. No IRREVERSIBLE (its human verification layer has no
channel; D4), no update or delete until the operator console exists.

## 2. Error mapping (only the provider-specific rows; everything else follows README §2)

| Provider response | Meaning | R result | M result | Why |
|---|---|---|---|---|
| `<status> <body code>` | | | | |

Duplicate / conflict rule: <exact condition under which a duplicate counts as our earlier success>.

## 3. Probe per operation

No dispatch time is available (README §1.1 item 3); the probe schedule is global (item 4).

| Op | Lookup | Proves EXECUTED_SUCCESS | Proves NOT_EXECUTED | Otherwise |
|---|---|---|---|---|

### 3.1 Inverse calls (only if an op is another op's inverse)

The inverse receives the original step's params and the key `{step key}:inverse` (README §1.1 item 2).

| Inverse of | Locate (by the original key) | Act | Zero / several targets |
|---|---|---|---|

## 4. Observe per `observation.method`

`expected` is `{"exists": True, "properties": <params>}` (W) or `{"exists": False}` (D); `identifier` may be `None`
(probe path). List the compared fields per op; every other key in `properties` is ignored.

| `observation.method` | Read (with `identifier`, and with `identifier=None`) | Compared fields and normalisation | `expected.exists = False` |
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

## 7. Open questions for the owner (each with a safe default; list go-live gates separately, README §8)

| # | Question | Default if unanswered |
|---|---|---|
