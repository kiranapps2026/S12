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

## What is proved, and what is not

Proved by `tests_postgres/test_chain_full_stack.py` (real PostgreSQL, scripted provider and verifier): a
create-then-list chain runs from the request through S11, admission and the step loop to a completed run with
committed budget and an undo token; a create-then-delete chain waits for confirmation, lists every operation
with its parameters and `undoable`, and verifies the delete by absence; a failed delete verification leaves a
`partial` run with the create's budget committed and the delete's released; the kill switch between admission
and execution cancels the chain; without observation data the chain is refused at S12 entry.

**Not proved: D1a, the real model.** `tests_postgres/test_live_chain.py` (run with `-s`, needs the DeepSeek key)
asks the real model for a create-then-list chain, for the reverse order, for a chain with a delete, for an
operation the registry does not offer, for more than five operations and for an unsure request. It is verified
here only against a scripted stand-in. Its failure messages print the raw model answer, so the prompt in
`adapters/llm/deepseek_request.py` can be tuned from evidence.

**Ordering mistakes** ("email before create") cannot be detected by the system in M2a: no schema says that one
operation needs another's result. The guards are the confirmation text (which lists the chain in order) and,
for chains without a delete or high risk, the user's own request. M2b (input/output schemas) is what makes
this checkable.
