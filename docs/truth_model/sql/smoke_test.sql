-- Smoke test for step_evidence.sql. Seeds one run with twelve steps, one per evidence shape, checks every dimension
-- the view returns (D1-D7, D9), checks that one seed pruning rule (phase 2 seed d) catches a violating step, then
-- rolls back. Revised in review pass 2: steps s9-s12 (D9 events, D4 'foreign', a probe confirmed then verification
-- failed).
--
-- Run on a scratch database that has migrations 001-017 applied, as a role that bypasses RLS:
--   psql -d <db>_test -v ON_ERROR_STOP=1 -f docs/truth_model/sql/smoke_test.sql
-- Success prints "smoke test passed: 12 steps, 1 violation caught" and changes nothing.

BEGIN;
\ir step_evidence.sql

INSERT INTO tenants (tenant_id, name, policy_version_id) VALUES ('t1', 'Tenant 1', 'pv1');
INSERT INTO users (user_id, tenant_id) VALUES ('u1', 't1');
INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('w1', 't1', 'Workspace 1');
INSERT INTO kernel_ops (kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety, truth_state) VALUES
    ('op.write', 'W', 0.2, 1, 30, 'idempotent', 'PRODUCTION_ENABLED'),
    ('op.irr', 'IRREVERSIBLE', 0.9, 1, 30, 'never', 'PRODUCTION_ENABLED');
INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,
                            conversation_id, status, actor_id)
VALUES ('e1', 'req-1', 'tr-1', 'task-1', 'u1', 't1', 'w1', 'c1', 'running', 'u1');

-- s1 running, first attempt, never dispatched              (EX-1 evidence)
-- s2 pending_probe, EXECUTION episode in an attempt         (crash during_probe)
-- s3 dead_letter after an exhausted EXECUTION episode       (EX-3)
-- s4 completed, ledger success, every required layer PASS
-- s5 failed, ledger failure, a layer FAIL
-- s6 running retry: marker below attempt, ledger expired, one layer recorded
-- s7 completed IRREVERSIBLE after a probe (CONF-040: no schema/deterministic layers)
-- s8 running with a RESERVED reservation: violates seed rule d (I-3)
-- s9 running, marker current, ProviderReturned ok recorded, no ledger row  (C-9)
-- s10 running, a ledger row for its key with another kernel_op_id           (D4 foreign: IdempotencyConflict)
-- s11 completed through an idempotency hit on attempt 1                      (D9 hit)
-- s12 failed after a probe confirmed the call and provider_state FAILed      (EXECUTION closed VERIFIED_FAIL)
INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id, resolved_binding_id,
                             effective_risk, effective_mutation, request_fingerprint, status, attempt,
                             dispatched_attempt) VALUES
    ('e1:s1', 's1', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'running', 1, NULL),
    ('e1:s2', 's2', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'pending_probe', 1, 1),
    ('e1:s3', 's3', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'dead_letter', 1, 1),
    ('e1:s4', 's4', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'completed', 1, 1),
    ('e1:s5', 's5', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'failed', 1, 1),
    ('e1:s6', 's6', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'running', 2, 1),
    ('e1:s7', 's7', 'e1', 't1', 'op.irr', 'b2', 0.9, 'IRREVERSIBLE', 'f', 'completed', 1, 1),
    ('e1:s8', 's8', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'running', 1, NULL),
    ('e1:s9', 's9', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'running', 1, 1),
    ('e1:s10', 's10', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'running', 1, 1),
    ('e1:s11', 's11', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'completed', 1, 1),
    ('e1:s12', 's12', 'e1', 't1', 'op.write', 'b1', 0.2, 'W', 'f', 'failed', 1, 1);

INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status) VALUES
    ('r1', 't1', 'u1', 'e1', 'e1:s1', 1, 'locked'),
    ('r2', 't1', 'u1', 'e1', 'e1:s2', 1, 'locked'),
    ('r3', 't1', 'u1', 'e1', 'e1:s3', 1, 'locked'),
    ('r4', 't1', 'u1', 'e1', 'e1:s4', 1, 'committed'),
    ('r5', 't1', 'u1', 'e1', 'e1:s5', 1, 'released'),
    ('r6a', 't1', 'u1', 'e1', 'e1:s6', 1, 'released'),
    ('r6b', 't1', 'u1', 'e1', 'e1:s6', 1, 'locked'),
    ('r7', 't1', 'u1', 'e1', 'e1:s7', 1, 'committed'),
    ('r8', 't1', 'u1', 'e1', 'e1:s8', 1, 'reserved'),
    ('r9', 't1', 'u1', 'e1', 'e1:s9', 1, 'locked'),
    ('r10', 't1', 'u1', 'e1', 'e1:s10', 1, 'locked'),
    ('r11', 't1', 'u1', 'e1', 'e1:s11', 1, 'committed'),
    ('r12', 't1', 'u1', 'e1', 'e1:s12', 1, 'released');

INSERT INTO idempotency_ledger (idempotency_key, tenant_id, kernel_op_id, result, expires_at) VALUES
    ('req-1:s4', 't1', 'op.write', '{"status": "ok", "data": {"id": 4}}', now() + interval '1 day'),
    ('req-1:s5', 't1', 'op.write', '{"status": "error", "error_class": "client_error"}', now() + interval '1 day'),
    ('req-1:s6', 't1', 'op.write', '{"status": "ok", "data": {"id": 6}}', now() - interval '1 second'),
    ('req-1:s10', 't1', 'op.irr', '{"status": "ok", "data": {"id": 10}}', now() + interval '1 day'),
    ('req-1:s11', 't1', 'op.write', '{"status": "ok", "data": {"id": 11}}', now() + interval '1 day');

INSERT INTO step_reconciliations (episode_id, tenant_id, execution_id, step_id, kind, status, outcome, attempts,
                                  closed_at) VALUES
    ('ep2', 't1', 'e1', 'e1:s2', 'EXECUTION', 'reconciling', NULL, 1, NULL),
    ('ep3', 't1', 'e1', 'e1:s3', 'EXECUTION', 'pending_probe', 'EXHAUSTED', 3, now()),
    ('ep7', 't1', 'e1', 'e1:s7', 'EXECUTION', 'confirmed_success', 'EXECUTED_SUCCESS', 1, now()),
    ('ep12', 't1', 'e1', 'e1:s12', 'EXECUTION', 'confirmed_failure', 'VERIFIED_FAIL', 1, now());

INSERT INTO dead_letters (dead_letter_id, tenant_id, execution_id, step_id, kernel_op_id, reservation_id, episode_id,
                          error, error_type, retry_mode, context) VALUES
    ('dl3', 't1', 'e1', 'e1:s3', 'op.write', 'r3', 'ep3', 'probe_exhausted', 'unknown_unresolved', 'PROBE',
     '{"probes": 3}');

INSERT INTO execution_events (event_id, tenant_id, execution_id, trace_id, event_type, step_id, payload) VALUES
    ('v4a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s4', '{"layer": "schema", "verdict": "PASS"}'),
    ('v4b', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s4', '{"layer": "deterministic", "verdict": "PASS"}'),
    ('v4c', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s4', '{"layer": "provider_state", "verdict": "UNKNOWN"}'),
    ('v4d', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s4', '{"layer": "provider_state", "verdict": "PASS"}'),
    ('v5a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s5', '{"layer": "schema", "verdict": "PASS"}'),
    ('v5b', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s5', '{"layer": "deterministic", "verdict": "FAIL"}'),
    ('v6a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s6', '{"layer": "schema", "verdict": "PASS"}'),
    ('v7a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s7', '{"layer": "provider_state", "verdict": "PASS"}'),
    ('v7b', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s7', '{"layer": "semantic", "verdict": "PASS"}'),
    ('v7c', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s7', '{"layer": "human", "verdict": "PASS"}'),
    ('v11a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s11', '{"layer": "schema", "verdict": "PASS"}'),
    ('v11b', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s11', '{"layer": "deterministic", "verdict": "PASS"}'),
    ('v11c', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s11', '{"layer": "provider_state", "verdict": "PASS"}'),
    ('v12a', 't1', 'e1', 'tr-1', 'verification_layer', 'e1:s12', '{"layer": "provider_state", "verdict": "FAIL"}');

-- D9: attempt events (attempt_id att-{step_index}-{attempt}); s6 (attempt 2) has attempt 1's events, which must be ignored
INSERT INTO execution_events (event_id, tenant_id, execution_id, trace_id, event_type, step_id, attempt_id,
                              payload) VALUES
    ('a9a', 't1', 'e1', 'tr-1', 'step_attempt', 'e1:s9', 'att-8-1', '{"attempt": 1}'),
    ('a9b', 't1', 'e1', 'tr-1', 'ProviderCalled', 'e1:s9', 'att-8-1', '{}'),
    ('a9c', 't1', 'e1', 'tr-1', 'ProviderReturned', 'e1:s9', 'att-8-1', '{"status": "ok"}'),
    ('a10', 't1', 'e1', 'tr-1', 'step_attempt', 'e1:s10', 'att-9-1', '{"attempt": 1}'),
    ('a11', 't1', 'e1', 'tr-1', 'idempotency_hit', 'e1:s11', 'att-10-1', '{"kind": "success"}'),
    ('a6a', 't1', 'e1', 'tr-1', 'step_attempt', 'e1:s6', 'att-5-1', '{"attempt": 1}'),
    ('a6b', 't1', 'e1', 'tr-1', 'ProviderCalled', 'e1:s6', 'att-5-1', '{}'),
    ('a6c', 't1', 'e1', 'tr-1', 'ProviderReturned', 'e1:s6', 'att-5-1', '{"status": "error"}');

DO $$
DECLARE
    expected TEXT[] := ARRAY[
        -- step | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d9
        'e1:s1|running|locked|null|none|none|none|none|none',
        'e1:s10|running|locked|current|foreign|none|none|none|started',
        'e1:s11|completed|committed|current|success|pass|none|none|hit',
        'e1:s12|failed|released|current|none|fail|EXECUTION:confirmed_failure|none|none',
        'e1:s2|pending_probe|locked|current|none|none|EXECUTION:reconciling|none|none',
        'e1:s3|dead_letter|locked|current|none|none|EXECUTION:exhausted|open:PROBE|none',
        'e1:s4|completed|committed|current|success|pass|none|none|none',
        'e1:s5|failed|released|current|failure|fail|none|none|none',
        'e1:s6|running|locked|below|expired|open|none|none|none',
        'e1:s7|completed|committed|current|none|pass|EXECUTION:confirmed_success|none|none',
        'e1:s8|running|reserved|null|none|none|none|none|none',
        'e1:s9|running|locked|current|none|none|none|none|returned_ok'];
    actual TEXT[];
    violations INT;
BEGIN
    SELECT array_agg(concat_ws('|', step_id, d1_step, d2_reservation, d3_marker, d4_ledger, d5_layers, d6_episode,
                               d7_dead_letter, d9_events) ORDER BY step_id)
      INTO actual FROM truth_model.step_evidence WHERE execution_id = 'e1';
    IF actual IS DISTINCT FROM expected THEN
        RAISE EXCEPTION E'step_evidence mismatch\nexpected:\n%\nactual:\n%', array_to_string(expected, E'\n'),
            array_to_string(actual, E'\n');
    END IF;

    -- seed rule d (A.2 I-3): a running, timeout or pending_probe step holds a LOCKED reservation
    SELECT count(*) INTO violations FROM truth_model.step_evidence
     WHERE d1_step IN ('running', 'timeout', 'pending_probe') AND d2_reservation <> 'locked';
    IF violations <> 1 THEN
        RAISE EXCEPTION 'seed rule d: expected exactly the planted violation (e1:s8), got %', violations;
    END IF;
    RAISE NOTICE 'smoke test passed: 12 steps, 1 violation caught';
END $$;

ROLLBACK;
