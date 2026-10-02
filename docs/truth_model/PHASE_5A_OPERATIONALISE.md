# Phase 5a: Operationalise

Part of the [S12 truth model](README.md). Input: the validated rows and rules (phases 2 and 4). It produces §10
(reverse index) and §11 (impossible states as SQL). It runs beside phase 5b.

Revised in review pass 2 (`REVIEW_LOG.md` P2-1, P2-9, P2-15): the view now reads D9 and D4 `foreign`, and the smoke
test covers them.

## Purpose

Turn the matrix into queries an operator and a monitor can run. One view maps the tables to the phase 2 dimensions.
Every impossible-state rule becomes a predicate that must return zero rows. Every symptom an operator might report
gets a query that tells its candidate rows apart.

## Entry conditions

- Phase 4 exit criteria met. Rules rejected in phase 4 are retired in `tm_ids.json`, not deleted.
- A scratch PostgreSQL 16 database whose name ends in `_test`. Never a development or production database.

## Already built (draft, owned by this phase)

| File | What it is | State |
|---|---|---|
| `sql/step_evidence.sql` | View `truth_model.step_evidence`: one row per step with D1–D9 | Draft. Checked by the smoke test on migrations 001–015 plus drafted 016–017 |
| `sql/smoke_test.sql` | Seeds twelve steps, one per evidence shape; checks D1–D7 and D9 and one seed rule (d); rolls back | Passes. Each of five mutations of the view (no `foreign`, events of any attempt, hits ignored, the after-probe test narrowed, expiry ignored) and a mutated expectation make it fail |

The view marks five assumptions to re-check once M11, M13 and M15 are implemented: the ledger body shape, the
`verification_layer` payload, what counts as "after a probe", the `attempt_id` format, and the `ProviderReturned`
payload. It joins the ledger on the key alone, because the key is the primary key across tenants (C-14).

## Environment

```bash
# PostgreSQL refuses to run as root: use the postgres OS user and a directory it owns
D=/var/lib/postgresql/tm_scratch
runuser -u postgres -- mkdir -p $D
runuser -u postgres -- /usr/lib/postgresql/16/bin/initdb -D $D/data -U postgres -A trust
runuser -u postgres -- /usr/lib/postgresql/16/bin/pg_ctl -D $D/data \
    -o "-p 55432 -k $D -c listen_addresses=''" -l $D/log start
psql -h $D -p 55432 -U postgres -c "CREATE DATABASE tm_test"
for f in src/adapters/postgres/migrations/0*.sql \
         batch_bundles/B5_M19-M21/src/adapters/postgres/migrations/01[67]*.sql; do
  psql -h $D -p 55432 -U postgres -d tm_test -v ON_ERROR_STOP=1 -q -f "$f" || break
done
psql -h $D -p 55432 -U postgres -d tm_test -v ON_ERROR_STOP=1 -f docs/truth_model/sql/smoke_test.sql
```

Record the schema version with every result: `001-015` (on `s12-work`) or `001-015+draft016-017`.
`execution_events` exists only with the drafted 016, so the layer dimension (D5) and every history rule that reads
events need it.

## Row-level security

RLS is forced on every evidence table (`006`, `015`, drafted `016`). A predicate run as the application role sees one
tenant, or none. Two ways to run them; the choice for production is the owner's (candidate C-7, same root as
CONF-042):

- In this phase, on the scratch database, as `postgres` (a superuser bypasses RLS).
- Per tenant, with `SET app.current_tenant`, looping over tenants. That is slower, but it needs no new privilege.

## Outputs

| File | Content |
|---|---|
| `sql/impossible_states.sql` | One query per `IS-nnn`, over `truth_model.step_evidence`, returning offending steps |
| `sql/row_coherence.sql` | One query per row-level rule that is not a dimension rule (for example, an episode closed ⇔ outcome set; EXHAUSTED ⇒ status `pending_probe`) |
| `sql/history_predicates.sql` | One query per `IH-nnn` over `state_transitions` and `execution_events` (I5, I6, I14, I16 and phase 2 additions, including the write-order pairs of phase 4) |
| `sql/run_outcome.sql` | One query per `RO-nnn` over `execution_runs` and `execution_steps`: a terminal run whose status contradicts its steps (for example a run with a DEAD_LETTER step that is not DEAD_LETTER, or a RESERVED reservation after consolidation) |
| `sql/ignored_evidence.sql` | Steps whose durable evidence recovery would not read: a `ProviderReturned` with no ledger row (C-9), a recorded FAIL with no terminal step (C-10). Not violations: a monitoring list of rows likely to end in a needless dead letter |
| `sql/reverse_index.sql` | One query per symptom, parameterised by `tenant_id` and `execution_id` |
| `sql/controls/IS-nnn.sql` | Positive control per predicate: plants exactly one violation, expects exactly one row, rolls back |
| `work/P5A_RUN.md` | Run log: commit, schema version, per-predicate counts on each data set |

### Predicate format

```sql
-- IS-007 | D1 in (running, timeout, pending_probe) => D2 = locked | basis gate | A.2 :2365 (I-3) | rows TM-...
SELECT tenant_id, execution_id, step_id, d1_step, d2_reservation
  FROM truth_model.step_evidence
 WHERE d1_step IN ('running', 'timeout', 'pending_probe') AND d2_reservation <> 'locked';
```

Where a phase 2 rule is an implication over dimensions ("if D1 ∈ X then D2 ∈ Y"), generate its query from the
rule's definition in the phase 2 script, so the rule and its SQL cannot drift apart. Write SQL by hand only for
row-coherence and history rules.

### Reverse index format

| Field | Content |
|---|---|
| symptom | In the operator's or customer's words ("budget held, nothing happened") |
| candidates | The TM rows that produce it |
| query | One query whose output names which candidate the execution is in |
| next action | The operator action from phase 5b for each candidate |

Start from the symptoms in phase 5b. Every candidate row must be distinguishable by the query. When two rows cannot be
told apart from the database, that is a principle 1 finding (see the `after_dispatch_marker_before_call` /
`after_adapter_call_before_ledger` pair in phase 4: indistinguishable by design, so the reverse index says so).

## Data sets the predicates run on

| Data set | How | Expected |
|---|---|---|
| Clean fixture | The smoke test's seed without its planted violation, extended with one step per reachable TM row | 0 rows for every predicate |
| Positive controls | `sql/controls/IS-nnn.sql` | Exactly 1 row for its own predicate |
| Reference run | Golden B3–B5 suites on the `batch_bundles` reference in a scratch worktree. The golden fixture drops each module schema at teardown (`tests_golden/fixtures/db.py:96`), so add a predicate call before teardown in the scratch worktree only. Never commit that change | 0 rows. A row here is a finding against the reference or the golden draft |
| Implementation run | The same, once M10 onward is built on `s12-work` | 0 rows |

## Procedure

1. Re-check the five assumptions in `step_evidence.sql` against the current golden drafts. Change the view only if
   a draft changed, and log the change in `P5A_RUN.md`.
2. Generate `impossible_states.sql` from the phase 2 rule definitions. Hand-write `row_coherence.sql` and
   `history_predicates.sql`.
3. Write one positive control per predicate. A predicate whose control returns 0 rows, or more than 1, is wrong.
4. Extend the clean fixture until every reachable TM row has at least one step in it.
5. Run all predicates on each data set and record the counts.
6. Write the reverse-index queries; run each against the clean fixture and check it names the right row for every
   candidate.
7. Mark which predicates are cheap enough to run as periodic monitors (index-supported, bounded by tenant), and give
   each a suggested interval. This is the monitoring specification of §11.

## Exit criteria

- Every `IS-nnn`, `IH-nnn` and `RO-nnn` has a query and a positive control.
- On the clean fixture every predicate returns 0; on its control, exactly 1.
- Every reverse-index entry runs, and on the clean fixture it names the right candidate.
- `P5A_RUN.md` records the commit, the schema version and every count, including the reference-run result.

## Can it split?

It runs beside 5b. Within 5a, predicates can be split by rule family (state, row coherence, history), but only one
person edits `step_evidence.sql`.

## Traps

- Dimensions that depend on `now()` (an expired ledger row, a lapsed lease) change while you watch. For reproducible
  runs, compare against a fixed timestamp parameter instead of `now()`.
- The ledger has no `step_id`; it joins through `request_id || ':' || plan_step_id`. A step whose run has no
  `request_id` match silently reads as "no ledger row".
- A superuser bypasses RLS, so a predicate that passes as `postgres` proves nothing about tenant isolation. Tenant
  isolation is I15, a separate history rule.
