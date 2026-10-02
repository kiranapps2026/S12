-- S12 truth model: the evidence view (phase 5a input, dimensions of phase 2).
--
-- One row per execution step, with the phase 2 dimensions D1-D8 as read from the database. Every impossible-state
-- predicate and reverse-index query of phase 5a reads this view, so the mapping from tables to dimensions is written
-- once. Draft: phase 5a owns it and must re-check it against the implemented M11/M13/M15/M17 code.
--
-- Schema: migrations 001-015 (s12-work) plus the drafted 016_execution_events and 017_recovery_candidates
-- (batch_bundles/B5_M19-M21). Checked on PostgreSQL 16 by docs/truth_model/sql/smoke_test.sql.
--
-- Read it as a role that bypasses row-level security, or set app.current_tenant per tenant: RLS is forced on every
-- evidence table (candidate C-7). Never create it in a production database without the owner's decision.
--
-- Assumptions to re-check when the code exists (each is marked ASSUMPTION below):
--   * the ledger body carries {"status": "ok" | ...} (reference implementation; the golden M11 fixes only the kind);
--   * a verification_layer event carries payload {"layer", "verdict"} and the step_id column (golden M15 draft);
--   * "after a probe" means the step has an EXECUTION episode closed EXECUTED_SUCCESS, or VERIFIED_FAIL (a probe
--     confirmed the call and verification then failed; M13 draft) (CONF-040);
--   * attempt_id is "att-{step_index}-{attempt}" (golden M11 attempt_id()), and ProviderReturned carries
--     payload {"status"} (golden M11 draft). D9 reads the events of the step's current attempt.
--
-- Revised in review pass 2 (REVIEW_LOG.md P2-1, P2-9, P2-15): D4 'foreign', D9 attempt events, the after-probe test,
-- and the open episode preferred as the latest one.

CREATE SCHEMA IF NOT EXISTS truth_model;

CREATE OR REPLACE VIEW truth_model.step_evidence AS
WITH layer_latest AS (
    -- latest verdict per (step, layer); execution_events is append-only and ordered by seq
    SELECT DISTINCT ON (e.tenant_id, e.step_id, e.payload->>'layer')
           e.tenant_id, e.step_id, e.payload->>'layer' AS layer, e.payload->>'verdict' AS verdict
      FROM execution_events e
     WHERE e.event_type = 'verification_layer'                      -- ASSUMPTION (golden M15 draft, CONF-036)
     ORDER BY e.tenant_id, e.step_id, e.payload->>'layer', e.seq DESC
),
base AS (
    SELECT s.tenant_id, s.execution_id, s.step_id, s.plan_step_id, s.kernel_op_id, s.attempt, s.dispatched_attempt,
           s.status, s.effective_mutation, s.effective_risk, r.request_id, r.status AS run_status,
           k.retry_safety,
           EXISTS (SELECT 1 FROM step_reconciliations p
                    WHERE p.tenant_id = s.tenant_id AND p.step_id = s.step_id
                      AND p.kind = 'EXECUTION'
                      AND p.outcome IN ('EXECUTED_SUCCESS', 'VERIFIED_FAIL')) AS after_probe     -- ASSUMPTION
      FROM execution_steps s
      JOIN execution_runs r ON r.execution_id = s.execution_id AND r.tenant_id = s.tenant_id
      LEFT JOIN kernel_ops k ON k.kernel_op_id = s.kernel_op_id
),
required AS (
    -- required_verification_layers(mutation, risk) of the golden M15 draft; CONF-005: no autonomy input;
    -- CONF-040: after a probe, schema and deterministic do not apply
    SELECT b.tenant_id, b.step_id, l.layer
      FROM base b
     CROSS JOIN LATERAL (VALUES ('schema', NOT b.after_probe),
                                ('deterministic', NOT b.after_probe),
                                ('provider_state', b.effective_mutation IN ('W', 'D', 'IRREVERSIBLE')),
                                ('semantic', b.effective_risk >= 0.7 OR b.effective_mutation = 'IRREVERSIBLE'),
                                ('human', b.effective_mutation = 'IRREVERSIBLE')) AS l(layer, needed)
     WHERE l.needed
)
SELECT
    b.tenant_id, b.execution_id, b.step_id, b.plan_step_id, b.run_status, b.attempt, b.dispatched_attempt,

    -- D1 step status
    b.status AS d1_step,

    -- D2 reservation: the live row (at most one, 010 unique index), else 'released' when only released rows exist
    COALESCE(res.live_status, CASE WHEN res.n > 0 THEN 'released' ELSE 'none' END) AS d2_reservation,

    -- D3 dispatch marker (C35)
    CASE WHEN b.dispatched_attempt IS NULL THEN 'null'
         WHEN b.dispatched_attempt < b.attempt THEN 'below'
         WHEN b.dispatched_attempt = b.attempt THEN 'current'
         ELSE 'above' END AS d3_marker,

    -- D4 ledger; key = request_id:plan_step_id (C9, CONF-024); an expired row authorises nothing. The key is the
    -- table's primary key across tenants, so a row of another tenant or operation is 'foreign' (IdempotencyConflict)
    CASE WHEN led.idempotency_key IS NULL THEN 'none'
         WHEN led.tenant_id <> b.tenant_id OR led.kernel_op_id <> b.kernel_op_id THEN 'foreign'
         WHEN led.expires_at <= now() THEN 'expired'
         WHEN led.result->>'status' = 'ok' THEN 'success'                -- ASSUMPTION (ledger body shape)
         ELSE 'failure' END AS d4_ledger,

    -- D5 layer verdicts against the layers required on this step's path
    CASE WHEN lay.recorded = 0 THEN 'none'
         WHEN lay.failed > 0 THEN 'fail'
         WHEN lay.required_open = 0 THEN 'pass'
         ELSE 'open' END AS d5_layers,

    -- D6 latest episode: KIND:status for an open or confirmed episode, KIND:exhausted for an exhausted one (A.7)
    CASE WHEN ep.kind IS NULL THEN 'none'
         WHEN ep.closed_at IS NOT NULL AND ep.outcome = 'EXHAUSTED' THEN ep.kind || ':exhausted'
         ELSE ep.kind || ':' || ep.status END AS d6_episode,
    ep.closed_at IS NULL AND ep.kind IS NOT NULL AS d6_open,
    ep.outcome AS d6_outcome,

    -- D7 uncertainty dead letter (error_type unknown_unresolved, origin execution)
    CASE WHEN dl.status IS NULL THEN 'none'
         WHEN dl.status IN ('pending', 'retrying') THEN 'open:' || dl.retry_mode
         WHEN dl.status = 'resolved' THEN 'resolved:' || dl.resolution_outcome
         ELSE 'abandoned' END AS d7_dead_letter,

    -- D8 operation class, raw: phase 2 decides what "retry allowed" means (candidate C-8)
    b.effective_mutation AS d8_mutation,
    b.retry_safety AS d8_retry_safety,

    -- D9 events of the current attempt (each event is its own fenced write; recovery does not read them, C-9)
    CASE WHEN ev.n = 0 THEN 'none'
         WHEN ev.hit THEN 'hit'
         WHEN ev.returned_status = 'ok' THEN 'returned_ok'                  -- ASSUMPTION (ProviderReturned payload)
         WHEN ev.returned_status IS NOT NULL THEN 'returned_error'
         WHEN ev.called THEN 'called'
         ELSE 'started' END AS d9_events
FROM base b
LEFT JOIN LATERAL (
    SELECT count(*) AS n, max(br.status) FILTER (WHERE br.status <> 'released') AS live_status
      FROM budget_reservations br
     WHERE br.tenant_id = b.tenant_id AND br.step_id = b.step_id
) res ON true
LEFT JOIN idempotency_ledger led
       ON led.idempotency_key = b.request_id || ':' || b.plan_step_id          -- the key alone: see 'foreign'
LEFT JOIN LATERAL (
    SELECT count(*) AS recorded,
           count(*) FILTER (WHERE ll.verdict = 'FAIL') AS failed,
           (SELECT count(*) FROM required q
             WHERE q.tenant_id = b.tenant_id AND q.step_id = b.step_id
               AND NOT EXISTS (SELECT 1 FROM layer_latest p
                                WHERE p.tenant_id = q.tenant_id AND p.step_id = q.step_id
                                  AND p.layer = q.layer AND p.verdict = 'PASS')) AS required_open
      FROM layer_latest ll
     WHERE ll.tenant_id = b.tenant_id AND ll.step_id = b.step_id
) lay ON true
LEFT JOIN LATERAL (
    SELECT e.kind, e.status, e.outcome, e.closed_at
      FROM step_reconciliations e
     WHERE e.tenant_id = b.tenant_id AND e.step_id = b.step_id
     ORDER BY (e.closed_at IS NULL) DESC, e.opened_at DESC, e.episode_id DESC   -- the open episode, if any, first
     LIMIT 1
) ep ON true
LEFT JOIN LATERAL (
    SELECT d.status, d.retry_mode, d.resolution_outcome
      FROM dead_letters d
     WHERE d.tenant_id = b.tenant_id AND d.step_id = b.step_id
       AND d.error_type = 'unknown_unresolved' AND d.origin = 'execution'
     ORDER BY d.created_at DESC, d.dead_letter_id DESC
     LIMIT 1
) dl ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS n,
           bool_or(v.event_type = 'idempotency_hit') AS hit,
           bool_or(v.event_type = 'ProviderCalled') AS called,
           max(v.payload->>'status') FILTER (WHERE v.event_type = 'ProviderReturned') AS returned_status
      FROM execution_events v
     WHERE v.tenant_id = b.tenant_id AND v.step_id = b.step_id
       AND v.event_type IN ('step_attempt', 'idempotency_hit', 'ProviderCalled', 'ProviderReturned')
       AND split_part(v.attempt_id, '-', 3) = b.attempt::text              -- ASSUMPTION (attempt_id format)
) ev ON true;
