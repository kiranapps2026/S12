# Onboarding, usage, limits and reference content (Phase B, working rulings)

Migration 014 (`invitations`, `llm_usage`, `rate_limit_counters`). Owner may overrule any ruling.

## What exists
| Need | How |
|---|---|
| First tenant and owner | `python tools/create_tenant.py --slug acme --name "Acme" --owner "Ada"` (operator, `ADMIN_DATABASE_URL`): one transaction creates the tenant, workspace `main`, an owner user with membership and connection, and the owner's API key (printed once). Refuses an existing tenant. The admin API cannot do this: it needs an owner first. |
| Invitations | `POST/GET/DELETE /api/v1/admin/invitations` (admin/owner); the invitee redeems `POST /api/v1/invitations/accept` with the one-time token and gets their own user, membership, connection and API key. |
| Rate limiting | Every authenticated request counts against a user window and a tenant window (`RATE_LIMIT_USER_PER_MINUTE`, `RATE_LIMIT_TENANT_PER_MINUTE`); events from signed sources count against their endpoint's identity; the invitation redemption is limited per client address (`RATE_LIMIT_INVITE_PER_MINUTE`). Over the limit: `429` with `Retry-After`. |
| Usage billing | Each successful model call writes one `llm_usage` row (tenant, user, request, model, tokens). `GET /api/v1/admin/usage?days=30` sums it by day, model and user; with `LLM_PRICE_PER_MILLION_TOKENS` it adds `estimated_cost`. |
| Reference content | `POST/GET /admin/files` (metadata), `PUT/GET /admin/templates`, and `PostgresResultWriter.record_result` (for S15). |

## Rulings
| Ruling | Decision |
|---|---|
| R-BQ | Tenant creation is an operator action, never an API route; the first owner's key is shown once. |
| R-BR | An invitation token is random, shown once, stored as SHA-256, expires (default 72 h, max 30 days) and works once. The role ceiling applies (nobody invites above their own role). Redeeming is atomic. Every refusal (unknown, used, revoked, expired, tenant or workspace inactive) is the same `404 invitation_invalid`. The invitee is a person, never a service user. `invitations` has no row-level security (looked up before the tenant is known, like `api_keys`); every administrative query filters by tenant. |
| R-BS | Rate limits are fixed one-minute windows counted in PostgreSQL, so every process shares them. If the counter cannot be read the request is refused (`503`, fail closed). No limiter configured (tests) means unlimited. `rate_limit_counters` holds counters only (no tenant data, no row-level security); rows are reset in place because the application role cannot DELETE. API events are counted once (when the key authenticates). |
| R-BT | Usage is metered around the model, not inside the stages: the API binds a per-request scope, `MeteredIntentModel` records tokens after a successful call. A call outside any scope is logged and not billed to anyone. A failed call records nothing. |
| R-BU | Files: only metadata is registered (name, type, size ≤ 100 MiB). This service has no content store; the bytes live elsewhere. Template variables and file registration are admin-only (variables are substituted into requests, so they are configuration). Results are written only by the system (S15), never through the API. Nothing is deleted; a name is overwritten. |

## Not built
Email delivery of invitations (the token is returned to the inviter), per-tenant custom limits, a hard usage cap or invoicing, file content storage, deleting files/templates, the S15 caller of `record_result`.
