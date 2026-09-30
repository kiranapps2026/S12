# Phase D1: registry data that multi-step chains need

A chain can be planned (S2–S11) with the registry as it is. It can only be **admitted and executed** (S12) if
every mutating operation in it says how its effect is observed, and it can only be **undone** if the registry
names an inverse. Both live on `kernel_ops` (migrations 001 and 008). The default seed and a fresh database
leave them empty, so today every W/D/IRREVERSIBLE plan is refused at S12 entry with
`verifier_metadata_unavailable`. That is the intended fail-closed behaviour.

## Columns (one row per kernel operation)

| Column | Meaning | Required for |
|---|---|---|
| `observation_method` | name of the read that shows the effect (`get_contact`, `get_message`, …) | every W, D, IRREVERSIBLE operation |
| `observation_identifier_field` | which field of the adapter's result names the resource to look up | operations that create or address a resource |
| `observation_expects_absent` | `true` for a delete: the resource must be gone | delete operations |
| `inverse` | `kernel_op_id` that undoes this operation | optional; gives `Step.inverse` and the undo token |

Example (the seed catalog; see `CHAIN_CATALOG_SQL` in `tests_postgres/seed.py`):

```sql
UPDATE kernel_ops SET inverse = 'crm.contact_delete' WHERE kernel_op_id = 'crm.contact_create';
UPDATE kernel_ops SET observation_method = 'get_contact', observation_identifier_field = 'id'
 WHERE kernel_op_id = 'crm.contact_create';
UPDATE kernel_ops SET observation_method = 'get_contact', observation_expects_absent = true,
       observation_identifier_field = 'id' WHERE kernel_op_id = 'crm.contact_delete';
```

## Readiness check: which operations would block a chain

```sql
SELECT kernel_op_id, mutation FROM kernel_ops
 WHERE truth_state = 'PRODUCTION_ENABLED' AND mutation <> 'R'
   AND (observation_method IS NULL OR observation_method = '');
```

Every row returned is an operation that S12 will refuse to run. An empty result is the D1d exit condition.
`DATABASE_URL=... python tools/registry_readiness.py` runs this check (exit 1 while any operation is blocked) and states the
rules for filling the registry.
`DATABASE_URL=... python tools/propose_observation.py > observation_proposal.sql` prints proposed `UPDATE` statements (read-only:
nothing is applied). Create/update/delete operations named `<domain>.<noun>_<verb>` get `get_<noun>` with identifier `id`, deletes
expect absence, a create gets its delete as `inverse`; everything else is marked `NEEDS OWNER` and stays blocked until the
owner names a read that really shows its effect.

## What is proved, and what is not

Proved by `tests_postgres/test_chain_full_stack.py` (real PostgreSQL, scripted provider and verifier): a
create-then-list chain runs from the request through S11, admission and the step loop to a completed run with
committed budget and an undo token; a create-then-delete chain waits for confirmation, lists every operation
with its parameters and `undoable`, and verifies the delete by absence; a failed delete verification leaves a
`partial` run with the create's budget committed and the delete's released; the kill switch between admission
and execution cancels the chain; without observation data the chain is refused at S12 entry.

**D1a, the real model: proved on 2026-09-30** (owner's machine, real `deepseek-flash`, `test_live_chain.py`, 6/6 in
21 s, about 400-800 tokens per call). The model used the `steps` form for chains, in the requested order for both
"create then list" and "first list, afterwards create"; a chain with a delete ended at S10 asking for confirmation;
"create a contact and wire 500 dollars" came back `{"intent":"unknown"}` for the second step with confidence 0.6
(S2 CLARIFY `intent_unclear`, nothing planned); "create six contacts and list them" used `items` and was stopped
at S2 as `too_many_steps`; an unsure request came back at confidence 0.5 and was stopped at S7 (`low_confidence`).
Still unobserved: ambiguous phrasing where the order is not stated, requests where the model might add a step
nobody asked for, and behaviour across many runs (one run of each case is not a rate).

**Ordering mistakes** ("email before create") cannot be detected by the system in M2a: no schema says that one
operation needs another's result. The guards are the confirmation text (which lists the chain in order) and,
for chains without a delete or high risk, the user's own request. M2b (input/output schemas) is what makes
this checkable.
