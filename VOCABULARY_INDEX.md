# Vocabulary Index

**Purpose**: Canonical terminology for all AiagentsOS design documents.
**Rule**: Use these exact terms. Do not introduce synonyms in design docs.
**Date**: 2026-09-25
**Worker-management update (2026-09-29)**: terms from gate v10 C39–C41 and rulings RD-1…RD-18 (`WORKER_MGMT_SPEC_REVIEW.md` Part E) added; the `User` roles example and the "Skill" conflict entry corrected. Changed rows carry *(worker-management, RD-n)*.

---

## Core Concepts

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Durable Execution** | Execution state that survives process restarts, worker crashes, and node failures through checkpointing and persistent storage. | persistent run, long-lived execution, surviving execution | MASTER_ARCHITECTURE_FINAL.md, EXECUTION_PLAN.md | "The pipeline produces durable execution records in PostgreSQL." |
| **Semantic Capability Layer** | The abstraction that maps natural-language intent to typed, versioned capability contracts. It is metadata + resolution, not runtime behavior. | capability layer, semantic layer, intent mapper | MASTER_ARCHITECTURE_FINAL.md, RESOLVE_LAYER.md | "The Semantic Capability Layer resolves the user's intent to a typed Action." |
| **Provider Adapter** | A pluggable component that translates kernel operations into provider-specific API calls. Adapters NEVER raise; they always return KernelResult. | connector, integration, wrapper, client | MASTER_ARCHITECTURE_FINAL.md, PROVIDER_ADAPTERS.md | "The GoogleWorkspaceAdapter implements the ProviderAdapter interface." |
| **Capability Contract** | A typed, versioned schema defining what a capability accepts, returns, and may side-effect. Contracts are enforced at compile time and runtime. | schema, API contract, interface, definition | DATA_CONTRACTS.md, RESOLVE_LAYER.md | "The capability contract specifies input validation, output schema, and mutation risk level." |
| **Execution Plan** | A pre-computed, typed sequence of PlanSteps with dependencies, budgets, and timeouts. Plans are immutable once created. | workflow, runbook, script, pipeline | DATA_CONTRACTS.md, EXECUTION_PLAN.md | "The planner produces an ExecutionPlan with 7 PlanSteps." |
| **Pipeline Stage** | A single processing step in the 15-stage execution pipeline. Each stage has typed input/output, error handling, retry behavior, and observability hooks. | step, phase, processor, handler | PIPELINE_STAGES.md | "S8 executes the plan steps in order or parallel as specified." |
| **Worker** | A durable identity with state, capabilities, lease, and heartbeat. Workers survive process restarts and are scheduled by the kernel. | agent, bot, runner, executor | DATA_CONTRACTS.md, IDENTITY_AND_TENANCY.md | "The worker claims a task via lease acquisition." |
| **Tenant** | The top-level isolation boundary. All data, workers, capabilities, skills, and memories belong to exactly one tenant. | account, org, customer, workspace | IDENTITY_AND_TENANCY.md, DATABASE.md | "Row-Level Security enforces tenant isolation on every query." |
| **Mutation** | Any side effect that changes external state. Mutations are classified by risk level and reversibility. | action, side effect, write, operation | MUTATION_SAFETY.md, DATA_CONTRACTS.md | "HIGH mutations require human confirmation before execution." |
| **Skill** | A compiled, versioned, cached unit of reusable capability bound to typed actions. Skills are discovered by name, capability, or tag. | tool, function, plugin, module | SKILL_FACTORY_ARCHITECTURE.md, DATA_CONTRACTS.md | "The skill factory compiles and caches skills with TTL-based invalidation." |
| **HITL (Human-in-the-Loop)** | Any interaction where a human must approve, reject, or provide input before execution proceeds. | human approval, confirmation, review gate | HUMAN_IN_THE_LOOP.md, DATA_CONTRACTS.md | "HIGH mutations trigger a HITL request with a 15-minute timeout." |
| **Trace** | A distributed execution record linking all stages, spans, and events for a single execution. Identified by trace_id. | log, record, execution log, audit | TRACING_AND_CONCURRENCY.md, DATA_CONTRACTS.md | "Every execution emits a trace with spans for each stage." |
| **Lease** | A time-bounded claim on a resource or task. Leases expire automatically and must be renewed by the worker. | lock, claim, reservation, hold | DATA_CONTRACTS.md, RELIABILITY.md | "The worker renews its lease every 30 seconds." |
| **State Machine** | A formal model of valid states and transitions for a kernel object. Invalid transitions are rejected at runtime. | lifecycle, status flow, state chart | DATA_CONTRACTS.md, PIPELINE_STAGES.md | "The Task state machine defines 10 states with valid transitions." |
| **Capability Graph** | The directed graph of capabilities, their dependencies, and bindings to providers. Used for discovery and resolution. | dependency graph, capability map, binding graph | RESOLVE_LAYER.md, DATA_CONTRACTS.md | "The capability graph resolves nested capability chains." |
| **Execution Plan** | A pre-computed, typed sequence of PlanSteps with dependencies, budgets, and timeouts. Plans are immutable once created. | workflow, runbook, script, pipeline | DATA_CONTRACTS.md, EXECUTION_PLAN.md | "The planner produces an ExecutionPlan with 7 PlanSteps." |

---

## Execution

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Worker** | A durable identity with state, capabilities, lease, and heartbeat. Workers survive process restarts and are scheduled by the kernel. | agent, bot, runner, executor | DATA_CONTRACTS.md, IDENTITY_AND_TENANCY.md | "The worker claims a task via lease acquisition." |
| **Worker Runtime** | The running process/container that executes steps on behalf of Workers (FINAL_ARCHITECTURE §34). In the single-node S12–S15 phase one Worker Runtime hosts the engine for every leased Worker. Identified by `runtime_instance_id`, generated at process start. *(S12–S15 gate v9, C2.)* | runner, engine host, worker process | FINAL_ARCHITECTURE.md §34, S12_S15_EXECUTION_GATE.md §4 | "The sweeper in a fresh Worker Runtime took over the execution." |
| **Fence token** | Monotonic token from the database sequence `fence_token_seq`, issued on every lease acquisition and renewal and mirrored in `execution_ownership.fencing_token`; every durable write for an execution checks it. *(gate v9, C25.)* | epoch, version, generation | S12_S15_EXECUTION_GATE.md C5, C25 | "The stale owner's write matched 0 rows because its fence token was superseded." |
| **Step idempotency key** | `request_id:plan_step_id` — stable across attempts and recovery; the idempotency-ledger key. *(gate C9.)* | request key, call id | MUTATION_SAFETY.md §5 | "The retry reused the step idempotency key, so the provider deduplicated it." |
| **Task** | The central kernel object. Immutable specification of work: intent, strategy, capability requirements, parameters, state, priority, budget, and timing. | job, unit of work, item, work item | DATA_CONTRACTS.md, EXECUTION_PLAN.md | "The task transitions from PENDING to ASSIGNED when a worker claims it." |
| **Job** | Use "Task" instead. If referring to background processing, use "Execution." | — | — | — |
| **Run** | A single invocation of an ExecutionPlan. | execution, attempt, invocation | EXECUTION_PLAN.md | "Each run produces a trace and checkpoint." |
| **Execution** | The top-level unit of work in the system. Contains a trace_id, input, output, error, and references to the worker and tenant. | run, job, invocation | DATA_CONTRACTS.md, PIPELINE_STAGES.md | "The execution record is stored in PostgreSQL with full audit trail." |
| **Lease** | A time-bounded claim on a resource or task. Leases expire automatically and must be renewed by the worker. | lock, claim, reservation, hold | DATA_CONTRACTS.md, RELIABILITY.md | "The worker renews its lease every 30 seconds." |
| **Timeout** | A hard limit on operation duration. Enforced by the kernel, not the agent. | deadline, time limit, max duration | RELIABILITY.md, DATA_CONTRACTS.md | "Stage timeouts are configured per stage with a global fallback." |
| **Budget** | Resource limits: max_tokens, max_cost_usd, max_api_calls, max_duration_seconds, max_retries. Enforced by the kernel. | quota, limit, cap, allowance | DATA_CONTRACTS.md, RELIABILITY.md | "The budget tracker prevents spending beyond max_cost_usd." |
| **Retry** | Re-execution of a failed operation with backoff. Configured per operation with max_retries and backoff strategy. | reattempt, retry attempt | RELIABILITY.md, PIPELINE_STAGES.md | "Failed mutations retry with exponential backoff up to max_retries." |
| **runtime_type** | How a Worker executes: `llm`, `rules`, `vision`, `browser`, `rpa`, `data`, `rag`, `code`, `human` (`RuntimeType`, DATA_CONTRACTS §50). Selects routing (S7), binding family (S5) and worker eligibility (S12); never removes a pipeline stage. The only worker-type enum. *(worker-management, RD-10.)* | worker type, WorkerType, worker_type | DATA_CONTRACTS §50, DATABASE workers | "The browser worker's runtime_type makes it eligible for steps bound to the browser adapter." |
| **Worker Group** | A tenant-scoped set of Workers managed together (bulk pause, schedule, assign). Post-S15. *(worker-management.)* | pool, fleet, team | FINAL_ARCHITECTURE §34 | "Pausing the group pauses every member for new leases." |
| **Pause** | A time-bounded block on **new** runs (tenant/workspace) or **new** leases (worker/group) via `paused_until`. Running work continues (drain semantics). Not a state. *(worker-management, RD-5.)* | suspend, freeze, disable | WORKER_LIFECYCLE §16, IDENTITY_AND_TENANCY §8.4 | "The workspace is paused until 18:00; runs already RUNNING finish." |
| **Kill Switch** | An emergency stop that cancels remaining steps now (`kill_switch_engaged`, gate C23). Distinct from Pause. | pause, halt flag | IDENTITY_AND_TENANCY §8.4 | "The kill switch cancelled the remaining steps." |
| **Scheduled Activation** | `scheduled_activation_at`: before this time no new runs (tenant/workspace) or new leases (worker) are allowed. Not a state. *(worker-management, RD-5.)* | dormant state, go-live flag | WORKER_LIFECYCLE §16 | "The worker becomes eligible at 09:00." |
| **Eligibility Filter** | A pure predicate applied to candidate workers in S12 worker selection, before locality scoring (pause, activation, assignment, runtime/capability match). No candidate left → `no_worker`. *(worker-management, RD-4.)* | admission gate (for worker checks) | WORKER_LIFECYCLE §13, gate C39 | "The assignment filter removed two candidates." |
| **Operation Quota** | A count-based limit per tenant, workspace or worker and period (`operation_quotas`), consumed once per run at durable admission. Hard → deny; soft → queue. Distinct from Budget (cost). *(worker-management, RD-6.)* | quota (alone), rate limit, budget | DATA_CONTRACTS §51, DATABASE | "The hard quota of 1,000 executions per month was reached." |
| **Stability Tier** | One of T1–T7 in FINAL_ARCHITECTURE §30, ranking how stable a concern must be. Not a layer. *(worker-management, RD-15.)* | layer (for tiers), seven-layer architecture | FINAL_ARCHITECTURE §30 | "Worker routing is a T4, evolving, concern." |
| **Circuit Breaker** | A state machine (CLOSED → OPEN → HALF_OPEN) that prevents cascading failures when a provider is unhealthy. | breaker, fault blocker, trip | RELIABILITY.md, DATA_CONTRACTS.md | "The circuit breaker opens after 5 consecutive failures." |

---

## Data

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **State Machine** | A formal model of valid states and transitions for a kernel object. Invalid transitions are rejected at runtime. | lifecycle, status flow, state chart | DATA_CONTRACTS.md, PIPELINE_STAGES.md | "The Task state machine defines 10 states with valid transitions." |
| **Transition** | A state change from one valid state to another. Transitions may carry data (e.g., PENDING → RUNNING carries the worker_id). | change, move, shift | DATA_CONTRACTS.md, PIPELINE_STAGES.md | "The VERIFYING → COMPLETED transition requires successful verification." |
| **Mutation** | Any side effect that changes external state. Mutations are classified by risk level and reversibility. | action, side effect, write, operation | MUTATION_SAFETY.md, DATA_CONTRACTS.md | "HIGH mutations require human confirmation before execution." |
| **Side Effect** | Any observable change outside the execution context: API calls, database writes, emails, file modifications. | effect, output, result | MUTATION_SAFETY.md | "The kernel tracks all side effects for audit and rollback." |
| **Idempotency** | The property that an operation can be applied multiple times without changing the result beyond the first application. | safe retry, repeatable, deduplicable | DATA_CONTRACTS.md, RELIABILITY.md | "Every mutation uses an idempotency key to prevent duplicate execution." |
| **Reversibility** | The ability to undo a mutation: REVERSIBLE, IRREVERSIBLE, or CONDITIONAL. | undoable, rollback-able, recoverable | MUTATION_SAFETY.md, DATA_CONTRACTS.md | "Database updates are CONDITIONAL — reversible within the retention window." |

---

## Identity

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Tenant** | The top-level isolation boundary. All data, workers, capabilities, skills, and memories belong to exactly one tenant. | account, org, customer, workspace | IDENTITY_AND_TENANCY.md, DATABASE.md | "Row-Level Security enforces tenant isolation on every query." |
| **Worker Identity** | A durable identifier for a worker, scoped to a tenant, with credentials, permissions, rate limits, and lifecycle. | agent identity, bot ID, runner ID | IDENTITY_AND_TENANCY.md, DATA_CONTRACTS.md | "Worker identity persists across process restarts." |
| **User** | A human operator who may manage multiple tenants and workers. | human, admin, operator, person | IDENTITY_AND_TENANCY.md | "Users hold a workspace-scoped role through a membership: owner, admin, member or viewer (`UserRole`)." *(worker-management, RD-7: the former TENANT_ADMIN/TENANT_OPERATOR/TENANT_VIEWER example did not match `UserRole`.)* |
| **Session** | A conversation or execution session identified by a SessionId. Sessions have context, history, and memory. | conversation, chat, interaction | DATA_CONTRACTS.md, MEMORY_ARCHITECTURE.md | "The session context is injected into every LLM call." |
| **Principal** | The authenticated entity making a request: a User, Worker, or Service. Use this when discussing authorization generally. | caller, requester, actor | IDENTITY_AND_TENANCY.md, SECURITY.md | "The authorization layer checks the principal's capabilities." |
| **Scope** | The set of capabilities, resources, and policies available to a principal. Scopes are immutable and scoped to a tenant. | permission set, access list, policy set | IDENTITY_AND_TENANCY.md, DATA_CONTRACTS.md | "The worker's scope limits it to read-file and write-file capabilities." |

---

## Memory

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Short-term Memory** | L0: Current execution state. In-memory, volatile. | context, working set, scratch | MEMORY_ARCHITECTURE.md | "Short-term memory holds recent observations and intermediate results." |
| **Working Memory** | L1: Current task/session context. In-memory with TTL. | scratchpad, temp memory | MEMORY_ARCHITECTURE.md | "Working memory decays exponentially over the session." |
| **Long-term Memory** | L2-L4: Persistent worker/project/organizational knowledge. Stored in PostgreSQL + LanceDB. | persistent memory, stored memory, knowledge base | MEMORY_ARCHITECTURE.md | "Long-term memory is searched via semantic vector search." |
| **Episodic Memory** | L5-L6: Execution history and immutable audit/provenance. Stored in PostgreSQL. | history, log, trace | MEMORY_ARCHITECTURE.md | "Episodic memory records complete execution outcomes with full provenance." |
| **Memory Consolidation** | Periodic merging of related memories into higher-level abstractions. | memory merge, memory summarization | MEMORY_ARCHITECTURE.md | "Memory consolidation runs daily to extract patterns." |
| **Memory Decay** | Gradual reduction of memory quality/access priority over time. | forgetting, TTL, expiration | MEMORY_ARCHITECTURE.md | "Working memory uses exponential decay to prioritize recent context." |
| **Memory Provenance** | Metadata for every memory: who created it, when, from what evidence, for which tenant/worker/goal, confidence, expiration, mutability. | source, origin, metadata | MEMORY_ARCHITECTURE.md | "Memory provenance makes the memory system auditable." |

---

## Safety

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Human-in-the-Loop (HITL)** | Any interaction where a human must approve, reject, or provide input before execution proceeds. | human approval, confirmation, review gate | HUMAN_IN_THE_LOOP.md, DATA_CONTRACTS.md | "HIGH mutations trigger a HITL request with a 15-minute timeout." |
| **Confirmation Gate** | A checkpoint where a mutation's risk level determines whether human confirmation is required. | approval gate, review gate, check | HUMAN_IN_THE_LOOP.md, MUTATION_SAFETY.md | "The confirmation gate evaluates mutation risk before execution." |
| **Approval Workflow** | A multi-step approval chain: sequential, parallel, or delegated. | review chain, approval process | HUMAN_IN_THE_LOOP.md | "CRITICAL mutations require sequential approval from two approvers." |
| **Escalation** | Automatic promotion of a HITL request to a higher authority when the original approver times out or rejects. | promotion, handoff, transfer | HUMAN_IN_THE_LOOP.md, DATA_CONTRACTS.md | "Unresponded HITL requests escalate to the tenant admin after timeout." |
| **Risk Classification** | Assignment of a mutation to LOW, MEDIUM, HIGH, or CRITICAL based on impact and reversibility. | risk level, danger level, severity | MUTATION_SAFETY.md, DATA_CONTRACTS.md | "Risk classification determines the confirmation gate behavior." |

---

## Observability

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Trace** | A distributed execution record linking all stages, spans, and events for a single execution. Identified by trace_id. | log, record, execution log, audit | TRACING_AND_CONCURRENCY.md, DATA_CONTRACTS.md | "Every execution emits a trace with spans for each stage." |
| **Span** | A single operation within a trace. Spans have a span_id, parent_span_id, operation name, status, and timing. | segment, unit, operation | TRACING_AND_CONCURRENCY.md | "Each pipeline stage emits a span with duration_ms." |
| **Log** | A structured JSON record of an event. Logs have timestamp, severity, trace_id, span_id, tenant_id, worker_id, and message. | entry, record, output | TRACING_AND_CONCURRENCY.md, OBSERVABILITY_AND_DEBUGGING.md | "Logs are structured JSON with correlation via trace_id." |
| **Metric** | A numeric measurement over time: execution count, duration percentiles, error rate, token usage, queue depth. | stat, measurement, counter | TRACING_AND_CONCURRENCY.md, OBSERVABILITY_AND_DEBUGGING.md | "Metrics include P50, P95, P99 execution latency." |
| **Event** | A discrete occurrence in the system: pod_created, pod_terminated, mutation_executed, hitl_requested. | notification, signal, message | DATA_CONTRACTS.md, PIPELINE_STAGES.md | "The runner emits pod_terminated event when a pod stops." |
| **Correlation ID** | An identifier that links related traces, logs, and events across services. Use CorrelationId from ExecutionContext. | request ID, trace ID, correlation ID | DATA_CONTRACTS.md, TRACING_AND_CONCURRENCY.md | "Correlation ID propagates across gRPC and HTTP boundaries." |
| **Activation Mode** | The source of execution initiation: HUMAN, SCHEDULE, API, EVENT_DRIVEN, or INTERNAL. The mode determines S0 input format; all downstream stages are identical. | trigger type, invocation mode, start mode | FINAL_ARCHITECTURE.md | "Event-driven mode enters through the Event Gateway, creating an EventEnvelope." |
| **EventEnvelope** | An immutable wrapper for externally-triggered events. Created by the Event Gateway. Contains event_id, correlation_id, tenant_id (from gateway auth), payload_ref, and timestamp. | event, external trigger | FINAL_ARCHITECTURE.md, EVENT_GATEWAY_AND_ROUTER.md | "The EventEnvelope is passed to S0, which extracts event_id as task_id." |
| **Event Gateway** | The authentication and validation entry point for external events. Authenticates the event source, validates the event, creates the EventEnvelope, and passes it to S0. Tenant identity comes from gateway auth, never from event payload. | event source, event ingress, external trigger | FINAL_ARCHITECTURE.md, EVENT_GATEWAY_AND_ROUTER.md | "The Event Gateway validates webhook signatures before creating an EventEnvelope." |

---

## Skills

| Term | Canonical Definition | Do Not Use | Document | Usage Example |
|------|----------------------|------------|----------|---------------|
| **Skill** | A compiled, versioned, cached unit of reusable capability bound to typed actions. Skills are discovered by name, capability, or tag. | tool, function, plugin, module | SKILL_FACTORY_ARCHITECTURE.md, DATA_CONTRACTS.md | "The skill factory compiles and caches skills with TTL-based invalidation." |
| **Capability** | A typed, versioned contract defining what a skill or provider can do. | feature, ability, operation | DATA_CONTRACTS.md, RESOLVE_LAYER.md | "The read-file capability is implemented by the filesystem adapter." |
| **Tool** | A low-level primitive exposed to agents: file read/write, HTTP call, shell execution. Tools are bound to capabilities. | primitive, operation, function | SKILL_FACTORY_ARCHITECTURE.md, AIOS-main-manifest.md | "Tools are managed by the ToolManager with MCP server integration." |
| **Adapter** | A ProviderAdapter that translates kernel operations into provider-specific API calls. | connector, integration, wrapper | PROVIDER_ADAPTERS.md, DATA_CONTRACTS.md | "The NotionAdapter implements the ProviderAdapter interface." |
| **Binding** | A mapping between a capability and a provider adapter. Bindings are stored in the Registry and resolved at runtime. | mapping, link, connection | RESOLVE_LAYER.md, DATA_CONTRACTS.md | "The binding maps read-file to the filesystem adapter." |
| **Skill Composition** | A `SkillDefinition` (DATA_CONTRACTS §53): a data-defined DAG of capability steps, planned at S9 into ordinary PlanSteps. Recorded browser/RPA sequences are skill compositions. Post-S15. *(worker-management, RD-8.)* | workflow (for recorded sequences), macro, script | DATA_CONTRACTS §53 | "The lead-qualification skill composition plans into six PlanSteps." |
| **Resolution** | The process of looking up a capability, finding its binding, and returning the adapter and parameters. | lookup, discovery, finding | RESOLVE_LAYER.md, PIPELINE_STAGES.md | "Capability resolution happens in S4 of the pipeline." |

---

## Terms to Avoid

| Incorrect Term | Why It's Wrong | Use Instead |
|---------------|----------------|-------------|
| agent | Ambiguous — could mean worker, bot, or framework agent | Worker |
| bot | Informal — lacks architectural precision | Worker |
| runner | Conflicts with the AgentsMesh Runner component | Worker (the durable identity) or Worker Runtime (the process) |
| executor | Too generic | Worker or Execution |
| workflow | Implies a fixed sequence; execution plans can be dynamic | Execution Plan |
| script | Implies linear, non-durable execution | Execution Plan |
| plugin | Informal — lacks versioning and contract semantics | Skill |
| module | Too generic | Skill or Component |
| connector | Informal — lacks adapter contract semantics | Provider Adapter |
| wrapper | Implies pass-through; adapters translate | Provider Adapter |
| client | Too generic | Provider Adapter or Consumer |
| server | Too generic | Service or Component |
| job | Ambiguous — could mean Task, Execution, or background job | Task or Execution |
| run | Ambiguous — could mean Execution, Run, or invocation | Execution |
| attempt | Part of Task.attempt, not a standalone concept | Task with attempt number |
| queue | Too generic — use specific queue type | Request Queue, Dead Letter Queue |
| cache | Too generic — use specific cache level | L1 Cache, L2 Cache |
| log | Ambiguous — could mean Log, Trace, or Event | Log, Trace, or Event |
| record | Too generic — use specific record type | Execution, Task, Mutation, MemoryEntry |
| worker type / `WorkerType` / `worker_type` | Overlaps `runtime_type` and trigger source *(RD-10)* | `runtime_type`; plan/event/hybrid is derived from subscriptions |
| TENANT_ADMIN / TENANT_OWNER / TENANT_OPERATOR | Not roles in `UserRole` *(RD-7)* | membership role `owner`, `admin`, `member`, `viewer` |
| Seven-Layer Architecture (for T1–T7) | Collides with FINAL_ARCHITECTURE §6 layers *(RD-15)* | Stability Tiers T1–T7 |
| browser path / B0–B7 / RPA path | No bypass path exists (I-029) *(RD-8)* | browser adapter under S0→S15 |
| batch table / batch state | A batch is ordinary PlanSteps *(RD-12)* | BATCH strategy; PlanStep |

---

## Terminology Conflicts Checked

| Conflict | Resolution | Status |
|----------|-----------|--------|
| "Execution" vs "Run" | Execution is the top-level unit. Run is a single invocation of an ExecutionPlan. | RESOLVED |
| "Worker" vs "Agent" | Worker is the durable identity. Agent is the LLM-powered runtime inside a worker pod. | RESOLVED |
| "Task" vs "Job" | Task is the kernel execution object. Job is the scheduled task (cron). | RESOLVED |
| "Skill" vs "Capability" | Capability is the contract. Skill is the compiled, cached implementation. | RESOLVED |
| "Skill" vs "Skill Composition" | A Skill is compiled and cached; a Skill Composition (`SkillDefinition`) is data planned at S9. When the Skill Factory lands, a composition compiles into a Skill. *(worker-management.)* | RESOLVED (post-S15 detail open) |
| "Pause" vs "Kill Switch" | Pause blocks new work and lets running work finish; the kill switch cancels now. *(RD-5.)* | RESOLVED |
| "Operation Quota" vs "Budget" | Quota counts runs; budget limits cost. Both are checked; neither replaces the other. *(RD-6.)* | RESOLVED |
| "Layer" vs "Tier" | Layers are FINAL_ARCHITECTURE §6; tiers rank stability (§30). *(RD-15.)* | RESOLVED |
| "Adapter" vs "Connector" | Adapter is the formal interface. Connector is informal and ambiguous. | RESOLVED |
| "Mutation" vs "Action" | Mutation is the kernel-level side effect. Action is the model-level choice. | RESOLVED |
| "Trace" vs "Log" | Trace is the distributed execution record. Log is a structured event record. | RESOLVED |
| "Lease" vs "Lock" | Lease is time-bounded and auto-expiring. Lock is indefinite until released. | RESOLVED |
| "Task" vs "Job" | Task is the kernel execution object. Job is the scheduled task (cron). | work item, unit, execution | IDENTITY_AND_TENANCY.md, FINAL_ARCHITECTURE.md | "The task_id identifies a kernel task; a cron job is a scheduled trigger that creates tasks." |
| "HITL" vs "Approval" | HITL is the pattern. Approval is one specific HITL interaction type. | RESOLVED |
