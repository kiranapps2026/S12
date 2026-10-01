# M1 schema review (★): \d+ of every table migration 015 creates or changes

Generated from a fresh database with migrations 001–015 applied (PostgreSQL 16.13), commit 4fa314c. New tables: workers, worker_leases, step_reconciliations, dead_letters, idempotency_ledger, checkpoints; sequence fence_token_seq. Changed: bindings (+required_runtime_types), operation_quotas (+worker_id, CHECK, new unique key), state_transitions (+execution_id, machine CHECK widened, 2 indexes). Nothing in 001–014 was edited.

## workers

```text
                                                                Table "public.workers"
         Column          |           Type           | Collation | Nullable |      Default       | Storage  | Compression | Stats target | Description
-------------------------+--------------------------+-----------+----------+--------------------+----------+-------------+--------------+-------------
 worker_id               | text                     |           | not null |                    | extended |             |              |
 tenant_id               | text                     |           | not null |                    | extended |             |              |
 workspace_id            | text                     |           |          |                    | extended |             |              |
 worker_class            | text                     |           | not null |                    | extended |             |              |
 runtime_version         | text                     |           |          |                    | extended |             |              |
 capability_profile      | jsonb                    |           | not null |                    | extended |             |              |
 state                   | text                     |           | not null | 'REGISTERED'::text | extended |             |              |
 capacity                | integer                  |           | not null | 1                  | plain    |             |              |
 current_load            | integer                  |           | not null | 0                  | plain    |             |              |
 lease_epoch             | bigint                   |           | not null | 0                  | plain    |             |              |
 heartbeat_at            | timestamp with time zone |           |          |                    | plain    |             |              |
 last_assignment_at      | timestamp with time zone |           |          |                    | plain    |             |              |
 drain_state             | text                     |           |          |                    | extended |             |              |
 settings                | jsonb                    |           | not null | '{}'::jsonb        | extended |             |              |
 assigned_user_id        | text                     |           |          |                    | extended |             |              |
 paused_until            | timestamp with time zone |           |          |                    | plain    |             |              |
 scheduled_activation_at | timestamp with time zone |           |          |                    | plain    |             |              |
 runtime_type            | text                     |           | not null | 'llm'::text        | extended |             |              |
 created_at              | timestamp with time zone |           | not null | now()              | plain    |             |              |
 updated_at              | timestamp with time zone |           | not null | now()              | plain    |             |              |
Indexes:
    "workers_pkey" PRIMARY KEY, btree (worker_id)
    "idx_workers_tenant" btree (tenant_id)
    "idx_workers_workspace" btree (workspace_id)
Check constraints:
    "workers_capacity_check" CHECK (capacity >= 1)
    "workers_check" CHECK (current_load <= capacity)
    "workers_current_load_check" CHECK (current_load >= 0)
    "workers_runtime_type_check" CHECK (runtime_type = ANY (ARRAY['llm'::text, 'rules'::text, 'vision'::text, 'browser'::text, 'rpa'::text, 'data'::text, 'rag'::text, 'code'::text, 'human'::text]))
    "workers_state_check" CHECK (state = ANY (ARRAY['REGISTERED'::text, 'ACTIVE'::text, 'DRAINING'::text, 'DRAINED'::text, 'TERMINATED'::text]))
Foreign-key constraints:
    "workers_assigned_user_id_fkey" FOREIGN KEY (assigned_user_id) REFERENCES users(user_id)
    "workers_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
    "workers_workspace_id_fkey" FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
Referenced by:
    TABLE "operation_quotas" CONSTRAINT "operation_quotas_worker_id_fkey" FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
    TABLE "worker_leases" CONSTRAINT "worker_leases_worker_id_fkey" FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## worker_leases

```text
                                                     Table "public.worker_leases"
    Column    |           Type           | Collation | Nullable |    Default     | Storage  | Compression | Stats target | Description
--------------+--------------------------+-----------+----------+----------------+----------+-------------+--------------+-------------
 lease_id     | text                     |           | not null |                | extended |             |              |
 tenant_id    | text                     |           | not null |                | extended |             |              |
 worker_id    | text                     |           | not null |                | extended |             |              |
 execution_id | text                     |           |          |                | extended |             |              |
 task_id      | text                     |           |          |                | extended |             |              |
 fence_token  | bigint                   |           | not null |                | plain    |             |              |
 status       | text                     |           | not null | 'active'::text | extended |             |              |
 expires_at   | timestamp with time zone |           | not null |                | plain    |             |              |
 acquired_at  | timestamp with time zone |           | not null | now()          | plain    |             |              |
 released_at  | timestamp with time zone |           |          |                | plain    |             |              |
Indexes:
    "worker_leases_pkey" PRIMARY KEY, btree (lease_id)
    "idx_worker_leases_active" btree (worker_id) WHERE status = 'active'::text
    "idx_worker_leases_execution" btree (tenant_id, execution_id)
Check constraints:
    "worker_leases_status_check" CHECK (status = ANY (ARRAY['pending'::text, 'active'::text, 'expired'::text, 'released'::text]))
Foreign-key constraints:
    "worker_leases_execution_id_fkey" FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
    "worker_leases_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
    "worker_leases_worker_id_fkey" FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## step_reconciliations

```text
                                                Table "public.step_reconciliations"
    Column    |           Type           | Collation | Nullable |   Default   | Storage  | Compression | Stats target | Description
--------------+--------------------------+-----------+----------+-------------+----------+-------------+--------------+-------------
 episode_id   | text                     |           | not null |             | extended |             |              |
 tenant_id    | text                     |           | not null |             | extended |             |              |
 execution_id | text                     |           | not null |             | extended |             |              |
 step_id      | text                     |           | not null |             | extended |             |              |
 kind         | text                     |           | not null |             | extended |             |              |
 status       | text                     |           | not null |             | extended |             |              |
 outcome      | text                     |           |          |             | extended |             |              |
 evidence     | jsonb                    |           | not null | '{}'::jsonb | extended |             |              |
 attempts     | integer                  |           | not null | 0           | plain    |             |              |
 opened_at    | timestamp with time zone |           | not null | now()       | plain    |             |              |
 closed_at    | timestamp with time zone |           |          |             | plain    |             |              |
Indexes:
    "step_reconciliations_pkey" PRIMARY KEY, btree (episode_id)
    "idx_step_reconciliations_execution" btree (tenant_id, execution_id)
    "uq_step_reconciliations_open" UNIQUE, btree (step_id) WHERE closed_at IS NULL
Check constraints:
    "step_reconciliations_attempts_check" CHECK (attempts >= 0)
    "step_reconciliations_kind_check" CHECK (kind = ANY (ARRAY['EXECUTION'::text, 'VERIFICATION'::text]))
    "step_reconciliations_outcome_check" CHECK (outcome = ANY (ARRAY['EXECUTED_SUCCESS'::text, 'EXECUTED_FAILURE'::text, 'NOT_EXECUTED'::text, 'LEDGER_HIT'::text, 'VERIFIED_PASS'::text, 'VERIFIED_FAIL'::text, 'EXHAUSTED'::text]))
    "step_reconciliations_status_check" CHECK (status = ANY (ARRAY['pending_probe'::text, 'reconciling'::text, 'confirmed_success'::text, 'confirmed_failure'::text]))
Foreign-key constraints:
    "step_reconciliations_execution_id_fkey" FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
    "step_reconciliations_step_id_fkey" FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)
    "step_reconciliations_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
Referenced by:
    TABLE "dead_letters" CONSTRAINT "dead_letters_episode_id_fkey" FOREIGN KEY (episode_id) REFERENCES step_reconciliations(episode_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## dead_letters

```text
                                                          Table "public.dead_letters"
       Column       |           Type           | Collation | Nullable |      Default      | Storage  | Compression | Stats target | Description
--------------------+--------------------------+-----------+----------+-------------------+----------+-------------+--------------+-------------
 dead_letter_id     | text                     |           | not null |                   | extended |             |              |
 tenant_id          | text                     |           | not null |                   | extended |             |              |
 execution_id       | text                     |           | not null |                   | extended |             |              |
 step_id            | text                     |           | not null |                   | extended |             |              |
 kernel_op_id       | text                     |           | not null |                   | extended |             |              |
 reservation_id     | text                     |           |          |                   | extended |             |              |
 attempt_id         | text                     |           |          |                   | extended |             |              |
 episode_id         | text                     |           |          |                   | extended |             |              |
 error              | text                     |           | not null |                   | extended |             |              |
 error_type         | text                     |           | not null |                   | extended |             |              |
 mutation_type      | text                     |           | not null | 'R'::text         | extended |             |              |
 is_idempotent      | boolean                  |           | not null | false             | plain    |             |              |
 retry_count        | integer                  |           | not null | 0                 | plain    |             |              |
 max_retries        | integer                  |           | not null | 3                 | plain    |             |              |
 next_retry_at      | timestamp with time zone |           |          |                   | plain    |             |              |
 context            | jsonb                    |           | not null | '{}'::jsonb       | extended |             |              |
 status             | text                     |           | not null | 'pending'::text   | extended |             |              |
 resolved           | boolean                  |           | not null | false             | plain    |             |              |
 retry_mode         | text                     |           | not null |                   | extended |             |              |
 resolution_outcome | text                     |           |          |                   | extended |             |              |
 origin             | text                     |           | not null | 'execution'::text | extended |             |              |
 created_at         | timestamp with time zone |           | not null | now()             | plain    |             |              |
 updated_at         | timestamp with time zone |           | not null | now()             | plain    |             |              |
Indexes:
    "dead_letters_pkey" PRIMARY KEY, btree (dead_letter_id)
    "idx_dead_letters_execution" btree (tenant_id, execution_id)
Check constraints:
    "chk_dead_letters_outcome" CHECK ((status <> ALL (ARRAY['resolved'::text, 'abandoned'::text])) OR resolution_outcome IS NOT NULL)
    "chk_dead_letters_resolved" CHECK (resolved = (status = ANY (ARRAY['resolved'::text, 'abandoned'::text])))
    "chk_dead_letters_rollback" CHECK (origin <> 'rollback'::text OR retry_mode = 'NONE'::text)
    "dead_letters_error_type_check" CHECK (error_type = ANY (ARRAY['transient'::text, 'permanent'::text, 'data'::text, 'unknown_unresolved'::text]))
    "dead_letters_max_retries_check" CHECK (max_retries >= 0)
    "dead_letters_mutation_type_check" CHECK (mutation_type = ANY (ARRAY['R'::text, 'W'::text, 'D'::text, 'IRREVERSIBLE'::text]))
    "dead_letters_origin_check" CHECK (origin = ANY (ARRAY['execution'::text, 'rollback'::text]))
    "dead_letters_resolution_outcome_check" CHECK (resolution_outcome = ANY (ARRAY['EXECUTED'::text, 'NOT_EXECUTED'::text, 'UNDETERMINED'::text]))
    "dead_letters_retry_count_check" CHECK (retry_count >= 0)
    "dead_letters_retry_mode_check" CHECK (retry_mode = ANY (ARRAY['PROBE'::text, 'VERIFY'::text, 'NONE'::text]))
    "dead_letters_status_check" CHECK (status = ANY (ARRAY['pending'::text, 'retrying'::text, 'resolved'::text, 'abandoned'::text]))
Foreign-key constraints:
    "dead_letters_episode_id_fkey" FOREIGN KEY (episode_id) REFERENCES step_reconciliations(episode_id)
    "dead_letters_execution_id_fkey" FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
    "dead_letters_reservation_id_fkey" FOREIGN KEY (reservation_id) REFERENCES budget_reservations(reservation_id)
    "dead_letters_step_id_fkey" FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)
    "dead_letters_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## idempotency_ledger

```text
                                                 Table "public.idempotency_ledger"
     Column      |           Type           | Collation | Nullable | Default | Storage  | Compression | Stats target | Description
-----------------+--------------------------+-----------+----------+---------+----------+-------------+--------------+-------------
 idempotency_key | text                     |           | not null |         | extended |             |              |
 tenant_id       | text                     |           | not null |         | extended |             |              |
 kernel_op_id    | text                     |           | not null |         | extended |             |              |
 result          | jsonb                    |           | not null |         | extended |             |              |
 created_at      | timestamp with time zone |           | not null | now()   | plain    |             |              |
 expires_at      | timestamp with time zone |           | not null |         | plain    |             |              |
Indexes:
    "idempotency_ledger_pkey" PRIMARY KEY, btree (idempotency_key)
    "idx_idempotency_ledger_tenant_key" btree (tenant_id, idempotency_key)
Foreign-key constraints:
    "idempotency_ledger_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## checkpoints

```text
                                                      Table "public.checkpoints"
     Column      |           Type           | Collation | Nullable |   Default   | Storage  | Compression | Stats target | Description
-----------------+--------------------------+-----------+----------+-------------+----------+-------------+--------------+-------------
 checkpoint_id   | text                     |           | not null |             | extended |             |              |
 tenant_id       | text                     |           | not null |             | extended |             |              |
 execution_id    | text                     |           | not null |             | extended |             |              |
 sequence        | integer                  |           | not null |             | plain    |             |              |
 completed_steps | jsonb                    |           | not null | '[]'::jsonb | extended |             |              |
 failed_steps    | jsonb                    |           | not null | '[]'::jsonb | extended |             |              |
 pending_steps   | jsonb                    |           | not null | '[]'::jsonb | extended |             |              |
 current_step    | text                     |           |          |             | extended |             |              |
 created_at      | timestamp with time zone |           | not null | now()       | plain    |             |              |
 expires_at      | timestamp with time zone |           |          |             | plain    |             |              |
Indexes:
    "checkpoints_pkey" PRIMARY KEY, btree (checkpoint_id)
    "checkpoints_execution_id_sequence_key" UNIQUE CONSTRAINT, btree (execution_id, sequence)
    "idx_checkpoints_execution" btree (tenant_id, execution_id)
Check constraints:
    "checkpoints_sequence_check" CHECK (sequence >= 0)
Foreign-key constraints:
    "checkpoints_execution_id_fkey" FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
    "checkpoints_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## bindings

```text
                                                           Table "public.bindings"
         Column         |           Type           | Collation | Nullable |   Default   | Storage  | Compression | Stats target | Description
------------------------+--------------------------+-----------+----------+-------------+----------+-------------+--------------+-------------
 binding_id             | text                     |           | not null |             | extended |             |              |
 capability_id          | text                     |           | not null |             | extended |             |              |
 kernel_op_id           | text                     |           | not null |             | extended |             |              |
 provider               | text                     |           | not null |             | extended |             |              |
 engine_module          | text                     |           | not null |             | extended |             |              |
 adapter_class          | text                     |           | not null |             | extended |             |              |
 priority               | integer                  |           | not null | 1           | plain    |             |              |
 is_active              | boolean                  |           | not null | true        | plain    |             |              |
 created_at             | timestamp with time zone |           | not null | now()       | plain    |             |              |
 required_runtime_types | jsonb                    |           | not null | '[]'::jsonb | extended |             |              |
Indexes:
    "bindings_pkey" PRIMARY KEY, btree (binding_id)
    "idx_bindings_capability" btree (capability_id)
Foreign-key constraints:
    "bindings_capability_id_fkey" FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id)
    "bindings_kernel_op_id_fkey" FOREIGN KEY (kernel_op_id) REFERENCES kernel_ops(kernel_op_id)
Access method: heap

```

## operation_quotas

```text
                                                      Table "public.operation_quotas"
    Column     |           Type           | Collation | Nullable |      Default       | Storage  | Compression | Stats target | Description
---------------+--------------------------+-----------+----------+--------------------+----------+-------------+--------------+-------------
 quota_id      | text                     |           | not null |                    | extended |             |              |
 tenant_id     | text                     |           | not null |                    | extended |             |              |
 workspace_id  | text                     |           |          |                    | extended |             |              |
 resource_type | text                     |           | not null | 'executions'::text | extended |             |              |
 period_start  | timestamp with time zone |           | not null |                    | plain    |             |              |
 period_end    | timestamp with time zone |           | not null |                    | plain    |             |              |
 limit_value   | integer                  |           | not null |                    | plain    |             |              |
 used_count    | integer                  |           | not null | 0                  | plain    |             |              |
 is_hard       | boolean                  |           | not null | true               | plain    |             |              |
 created_at    | timestamp with time zone |           | not null | now()              | plain    |             |              |
 worker_id     | text                     |           |          |                    | extended |             |              |
Indexes:
    "operation_quotas_pkey" PRIMARY KEY, btree (quota_id)
    "idx_quotas_lookup" btree (tenant_id, resource_type, period_start, period_end)
    "uq_operation_quotas_scope" UNIQUE CONSTRAINT, btree (tenant_id, workspace_id, worker_id, resource_type, period_start) NULLS NOT DISTINCT
Check constraints:
    "chk_operation_quotas_no_worker" CHECK (worker_id IS NULL)
    "operation_quotas_check" CHECK (used_count >= 0 AND limit_value >= 0)
    "operation_quotas_check1" CHECK (used_count <= limit_value)
    "operation_quotas_check2" CHECK (period_end > period_start)
    "operation_quotas_resource_type_check" CHECK (resource_type = 'executions'::text)
Foreign-key constraints:
    "operation_quotas_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
    "operation_quotas_worker_id_fkey" FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
    "operation_quotas_workspace_id_fkey" FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## state_transitions

```text
                                                                            Table "public.state_transitions"
       Column        |           Type           | Collation | Nullable |                         Default                          | Storage  | Compression | Stats target | Description
---------------------+--------------------------+-----------+----------+----------------------------------------------------------+----------+-------------+--------------+-------------
 transition_id       | bigint                   |           | not null | nextval('state_transitions_transition_id_seq'::regclass) | plain    |             |              |
 tenant_id           | text                     |           | not null |                                                          | extended |             |              |
 entity_type         | text                     |           | not null |                                                          | extended |             |              |
 entity_id           | text                     |           | not null |                                                          | extended |             |              |
 from_state          | text                     |           |          |                                                          | extended |             |              |
 to_state            | text                     |           | not null |                                                          | extended |             |              |
 reason              | text                     |           |          |                                                          | extended |             |              |
 runtime_instance_id | text                     |           |          |                                                          | extended |             |              |
 fence_token         | bigint                   |           |          |                                                          | plain    |             |              |
 occurred_at         | timestamp with time zone |           | not null | now()                                                    | plain    |             |              |
 execution_id        | text                     |           |          |                                                          | extended |             |              |
Indexes:
    "state_transitions_pkey" PRIMARY KEY, btree (transition_id)
    "idx_state_transitions_entity" btree (entity_type, entity_id)
    "idx_state_transitions_execution" btree (tenant_id, execution_id, transition_id)
    "idx_state_transitions_machine" btree (tenant_id, entity_type, entity_id, transition_id)
Check constraints:
    "chk_state_transitions_machine" CHECK (entity_type = ANY (ARRAY['run'::text, 'step'::text, 'reservation'::text, 'lease'::text, 'dead_letter'::text, 'episode'::text, 'confirmation'::text]))
Foreign-key constraints:
    "state_transitions_tenant_id_fkey" FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
Policies (forced row security enabled):
    POLICY "tenant_isolation"
      USING ((tenant_id = current_setting('app.current_tenant'::text, true)))
      WITH CHECK ((tenant_id = current_setting('app.current_tenant'::text, true)))
Access method: heap

```

## fence_token_seq

```text
                      Sequence "public.fence_token_seq"
  Type  | Start | Minimum |       Maximum       | Increment | Cycles? | Cache
--------+-------+---------+---------------------+-----------+---------+-------
 bigint |     1 |       1 | 9223372036854775807 |         1 | no      |     1

```
