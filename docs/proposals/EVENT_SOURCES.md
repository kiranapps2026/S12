# Phase C: event sources and per-event-type validation

Built on 2026-09-30. Sources: signed webhooks (already), **MCP**, **API** and **schedule**. Every source goes
through one gateway (`engine/gateway/webhook.py::EventGateway`) and the ONE pipeline (`engine/gateway/run.py`).
The router, subscription matching and replay belong to S12/S13 and are not built.

## What each source is

| Source | Route / trigger | Authentication | Event type | Idempotency key (`{source}:{source_system}:{discriminator}`) |
|---|---|---|---|---|
| `webhook` | `POST /api/v1/webhooks/{ghl\|stripe\|custom}/{endpoint}` | HMAC signing secret | the body's `type` | the sender's `id`, else `sha256:` + body hash (§3.1; changed from the earlier timestamp variant to match the spec) |
| `mcp` | `POST /api/v1/mcp/{endpoint}` body `{tool_name, arguments, id?}` | HMAC signing secret of an `mcp` credential | always `mcp.tool_call` | the client `id`, else `sha256:` of the signed timestamp + body |
| `api` | `POST /api/v1/events` body `{type, payload, idempotency_key?}` | Bearer API key (identity = the key) | the body's `type` | the client key, else the request id (each request is a new event) |
| `schedule` | the scheduler (`EventScheduler.tick`) | the schedule's stored identity (a service user) | the schedule's `event_type` | `schedule_id` + the PLANNED fire time |

Identity always comes from authentication (credential, API key or stored schedule), never from the payload. All
events are stored in `event_log` (raw payload, source, auth method, schema version) before the pipeline runs and are
marked `processed` or `failed` afterwards. A repeat delivery is acknowledged (`reason: duplicate_event`) and not run.

## Per-event-type validation (C2)

`event_schemas(tenant, source_system, event_type, version, schema)`. An event is accepted only if its
`(source_system, event_type)` is **registered for the tenant** (`422 event_type_not_registered`) and the payload
satisfies the newest active schema (`422 payload_invalid`); an unusable schema is `422 event_schema_invalid`, a registry that
cannot be read is `503`. Nothing is stored for a refused event, and validation runs after authentication so an
unauthenticated caller learns nothing. Schemas are a small JSON-Schema subset (`type`, `required`, `properties`,
`additionalProperties` boolean, `enum`, `minLength`/`maxLength`, `minimum`/`maximum`, `items`, `minItems`/`maxItems`).
Anything else in a schema is **refused at registration**, not ignored, and there are no regular expressions (no
ReDoS). Register with `PostgresEventSchemas.register` (no admin API yet, Phase B4).

## Schedules

`event_schedules` (interval / daily / weekly, all UTC): a fixed identity, an event type and a payload. The scheduler
computes the latest planned fire time not after now. Missed periods are **coalesced** into that one time (never
replayed as a burst). Creating a schedule marks the newest past planned time handled, so it never fires an old one.
Two schedulers racing on one planned time create one event (the key holds the planned time). A refused event
(unregistered type, invalid payload) is marked handled so it does not refuse again every tick; an unavailable registry
or a crashing run is not marked and is retried; one failing schedule never stops the others. Enable with
`SCHEDULER_INTERVAL_SECONDS` (0 = off, the default); the task starts and stops with the app.
A scheduled event for a paused tenant is stopped at S0.1 like any run.

## Working rulings (owner may overrule)

| Ruling | Decision |
|---|---|
| R-BB | An event type must be registered per tenant before events of that type are accepted (fail closed). Existing webhooks now need a registered schema. |
| R-BC | The payload schema language is the small subset above; unenforced keywords are refused at registration. |
| R-BD | Missed schedule periods are coalesced into the latest planned time. |
| R-BE | MCP events use the signing-secret mechanism (source system `mcp`, already allowed by `webhook_credentials`), not mTLS. |
| R-BF | Deviation from §3.1 "each request is new" for MCP without a client key: the key is the signed timestamp + body hash, because a captured signed request must not run twice inside the replay window. |
| R-BG | `event_schedules` is a system table without row-level security (the scheduler lists every tenant's schedules; same reasoning as `webhook_credentials`, ruling E4). It holds a fixed service identity and no secret. |

## Not built (belongs to S12/S13 or later)

EventRouter, subscription matching, correlation/consolidation, replay after a pause or a crash (a run that fails
after its event was stored stays `received`/`failed` in `event_log` and is not re-run), the `202 Accepted` asynchronous
answer (still the interim synchronous 200), an admin API for schedules and schemas, cron expressions (only interval,
daily, weekly), time zones other than UTC, the `internal` source. `DATABASE.md` does not yet describe migration 011
(`event_schemas`, `event_schedules`, `event_log.schema_version`); add it to the deviations section and re-pin when accepted.
