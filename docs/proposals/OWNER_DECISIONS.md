# Owner decisions before the `s0-s11-certified` tag (2026-09-30)

Given by the owner in the session; recorded here so the tagged commit carries them.

| Decision | Ruling |
|---|---|
| Rulings R-AB to R-AL (`M2_RULINGS.md`) | **Approved as written.** |
| Rulings R-BB to R-BU (`EVENT_SOURCES.md`, `ADMIN_API.md`, `ONBOARDING.md`) | **Approved as written.** |
| Registry catalog (`docs/catalog/catalog.yaml`) | **Kept as is.** It stays a starter catalog: its provider and adapter names are placeholders and its observation methods (`get_contact`, `get_note`, `get_task`, `get_message`) are implemented by no adapter yet (milestone M10 of S12). Nothing in S0-S11 loads it into a production registry. |

## Consequences that stay open (approved as they are, not forgotten)

- **R-AF stays partly built.** `Step.inverse` is not carried to S9 and S10 does not say whether a step can be undone,
  because carrying it needs a new field on `FrozenBindingIdentity`, which is pinned by `tools/owner_certify.py`
  (OWN-17). The certifier and its hash are therefore unchanged for S0-S11. The change belongs to the S12 gate.
- **R-AG, R-AH, R-AI** remain deferred to M2b.
- **No row-level security** on `event_schedules`, `invitations` and `rate_limit_counters` (R-BG, R-BR, R-BS): approved;
  every administrative query filters by tenant.
- **Real registry:** before any live use, the owner's real operations must replace the starter catalog and
  `tools/registry_readiness.py` must report 0 blocked for them.
