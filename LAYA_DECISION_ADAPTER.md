# LayaDecisionAdapter — Design Note

**Status**: DESIGN NOTE — DEFERRED. Not authorized for implementation.
**Revision**: v3.3 — v3.2 plus: exactly one temperature layer, with runtime clamping recorded in the pin (§9.2 rule 11); romanised Telugu and Hindi as explicit slices with their own detection and evaluation (§9.2 rules 6 and 9).

**Previous revision**: v3.2 — v3.1 plus: exhaustive LR6; canonical candidate form and single-target substitution (§7.2b); candidates bounded by a schema-declared universe; examples cannot leak evaluation data; calibration keyed per (question, slice, option count) with no neighbour fallback; confidence method for generative fallbacks; DecisionContract conformance suite (§14.1); per-candidate recall **and** precision; order-sensitivity measurement; pre-registered evaluation plan and `PromotionEvidence` record (§13.1); promotion revalidated atomically; reconstruction bounded by source retention; external evidence cited as motivating only (§3.3); per-event-type metrics for event noise.

**Earlier revision**: v3.1 — v3 plus three findings from an independent zero-shot evaluation of Laya (github.com/glukicov/laya_router; 180 labelled requests, ±9.5-point interval, treated as directional evidence): description wording is a first-class artifact (§7.2a), per-candidate recall gate (§13 item 7), blind labelling (§12.3, OD-L5).

**Earlier revision**: v3 — v2 plus: provider arbitration contract and `DecisionResolution` (§10.4), `uncertain` status, no threshold shopping (LR13), compatibility boundary (LR14), `parameter_path` / `parameter_schema_hash`, decision hash chain, profile lifecycle and tenant scope, promotion lifecycle authority, S10 change-control blocker (LB10), promotion state-machine blocker (LB11), cross-reference to the S12–S15 terminal-reason gap (XS-1).

**Readiness**: DESIGN-READY / NOT IMPLEMENTATION-READY. Blocking before an implementation gate: LB1, LB2, LB7–LB11, XS-1, OD-L3.
**Target phase**: LLM layer (evaluation harness, model fallback, cost), per the phase order in S12_S15_EXECUTION_GATE §21 "Deferred register".
**Phase lock**: Nothing in this note may be implemented, migrated or tested inside the S0–S11 or S12–S15 gates. Every contract change it proposes to S5, S9 or S11 goes through the change-control procedure of S12_S15_EXECUTION_GATE §19.3 when the target phase opens. This note is an input to that phase's gate, not a gate itself.

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §38 Runtime Contract, §39 Immutable Intent Specification. [RESOLVE_LAYER.md](RESOLVE_LAYER.md) — §2 FrozenBindingIdentity. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §4 Plan & Step, §27 ExecutionManifest, AutonomyLevel, §41 AutonomyBounds. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S7, S8, S9, S11, §21 Execution Strategy Selection. [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §7 EventCorrelator, §8 EventEnvelope State Machine. [SECURITY.md](SECURITY.md) — §10 Guardrail Precedence. [RELIABILITY.md](RELIABILITY.md) — §1 guard components. [S12_S15_EXECUTION_GATE.md] — §8 step loop, §13 recovery, §21 S3/S7.

**Purpose**: Record how an encoder-based typed-decision model (Laya) may be attached to superagents: where it sits, what it may decide, and what it may never decide.

---

## Table of Contents

1. [Scope](#1-scope)
2. [Vocabulary](#2-vocabulary)
3. [What Laya Provides](#3-what-laya-provides)
4. [Placement Under the Runtime Contract](#4-placement-under-the-runtime-contract)
5. [Contract Types](#5-contract-types)
6. [Non-Negotiable Rules](#6-non-negotiable-rules)
7. [Use Site A — REFLEX Choice Steps](#7-use-site-a--reflex-choice-steps)
8. [Use Site B — Event Noise Filtering](#8-use-site-b--event-noise-filtering)
9. [Calibration and Thresholds](#9-calibration-and-thresholds)
10. [Failure, Retry and Reliability](#10-failure-retry-and-reliability)
11. [Security and Data Handling](#11-security-and-data-handling)
12. [Observability, Persistence Limits and Billing](#12-observability-persistence-limits-and-billing)
13. [Promotion Gate](#13-promotion-gate)
14. [Required Tests](#14-required-tests)
15. [Blocker Register Entries](#15-blocker-register-entries)
16. [Owner Decisions](#16-owner-decisions)

---

## 1. Scope

### In scope

| Use site | Location | Role of Laya |
|---|---|---|
| A — REFLEX choice steps | S12, a plan step carrying a frozen `ReflexChoice` (§7) | Selects one candidate value from a set frozen at S9 and covered by `plan_hash` |
| B — Event noise filtering | Event Gateway, `EventCorrelator.filter_noise` (before S0) | Classifies an event as noise or actionable |

### Out of scope (explicitly)

| Location | Why excluded |
|---|---|
| S1 injection detection | Not requested. A future note may add Laya as an advisory signal only; `DataSanitizer` remains authoritative. |
| S2 Intent Analysis | Laya cannot extract entities or parameters, and accuracy collapses above ~20 options. S2 remains the single unconditional LLM call. |
| S5 Resolution, S7 Path Routing, S8 Safety Gate | Deterministic stages. No model output enters them. |
| S9 Planning | Laya does not plan. S9 decides whether a step carries a `ReflexChoice` and what its candidates are. |
| S10 Confirmation | A human act. |
| S13 Verification (any layer) | Laya is not a verification layer, including the semantic layer (D6). |
| Selecting among different kernel ops or bindings | Requires multiple FrozenBindingIdentities per plan; deferred (§7.8, LB6). |
| REACT, DAG, PLAN_EXECUTE, HUMAN_ASSISTED, BATCH | Not affected. |

---

## 2. Vocabulary

Add to VOCABULARY_INDEX.md when the phase opens.

| Term | Meaning |
|---|---|
| **Advisory Decision Provider** | A model-backed component that selects one option from a previously compiled and frozen decision space. It cannot authorize, resolve, plan, mutate, execute, or add options. Its output is an input to a deterministic gate. Laya is the first one. |
| **DecisionContract** | The interface every Advisory Decision Provider implements (§4). Not an authoritative decision layer; the name refers only to typed-question answering. |
| **REFLEX Choice Set** | The `ReflexChoice` attached to one plan Step at S9: one parameter name and a frozen set of concrete candidate values, all covered by `plan_hash`. |
| **Decision record** | The persisted outcome of one Advisory Decision Provider call for one step (§7.5). |
| **Decision attempt** | One call to one provider for one decision. Distinct from an execution attempt (`execution_steps.attempt`). |
| **DecisionResolution** | The single record of how one decision was reached: every attempt, in order, and the provider of record. Exactly one per decision (§10.4). |
| **Provider of record** | The provider whose answer the deterministic gate evaluates. At most one per DecisionResolution. |
| **Uncertain answer** | A well-formed answer whose `answer_confidence` is below its threshold. A valid answer, not a failure. |

---

## 3. What Laya Provides

Laya is an open-source (Apache 2.0) encoder model family that answers typed questions over a state in a single forward pass. It does not generate text.

| Primitive | Output | Use in this note |
|---|---|---|
| `choice` | Top label, per-option probabilities, confidence | Use sites A and B |
| `score` | Ordinal level and distribution | Not used (weakest primitive; position bias on multilingual) |
| `noul` | P(true) | Not used (label-following defect on English checkpoint) |

| Checkpoint | Encoder | Params | Context | Notes |
|---|---|---|---|---|
| `laya` | ModernBERT-large | 421M | 512 | English only; collapses on other scripts while staying confident |
| `laya-multilingual` | mmBERT-base | 322M | 1024 (up to 8192) | Ships **without** fitted temperatures |
| `laya-typed-decisions` | ModernBERT-large | 421M | 1024 | Fine-tuned example; not our domain |

### 3.1 Validation pin

The limits below were read from the upstream repository on 2026-09-27. A README version is mutable and is not a pin. Before the phase gate is written, fill this block and treat it as the only valid reference:

```text
Validated against:
  repository:            github.com/NandhaKishorM/laya
  repository commit:     <immutable SHA>
  package version:       <laya==x.y.z, from the lockfile>
  checkpoint revisions:  laya=<HF revision SHA>
                         laya-multilingual=<HF revision SHA>
  weights digest:        <sha256 of model.safetensors per checkpoint>
  temperature behaviour: <shipped temperatures present? runtime clamp range, e.g. [0.5, 5.0]? how to disable>
  validated by / date:   <owner> / <date>
```

### 3.2 Known limits that shape the rules

1. Base checkpoints are near chance zero-shot on typed decisions (0.36 vs 0.46 majority baseline). All usable accuracy comes from fine-tuning on domain data.
2. Choice questions above ~20 options degrade sharply (Banking77: 0.425).
3. Negated requests can select the negated option with probability near 1.0 (upstream issue #377).
4. `noul` can follow its option labels rather than the state (#156). `score` on multilingual has a first-level position bias (#131).
5. Shipped confidence is over-confident. Calibration must be fitted before any threshold means anything.
6. Choice keys that look boolean (`yes`/`no`, `true`/`false`) can dominate the answer.
7. The English checkpoint can be confidently wrong on non-Latin scripts, so language routing must happen before inference, not be inferred from confidence.
8. Option-description wording alone moved zero-shot accuracy by 21 points (0.428 → 0.639) with the same model and data, in an independent evaluation.
9. Accuracy can hide class collapse: in the same evaluation, 97% of one class was correct but only 7 of 56 of a middle class.
10. Shipped calibration temperatures can be pathological: one shipped bucket (`choice:11+`) is 0.1006, which sharpens logits about tenfold and reports a coin flip as near-certainty. Upstream clamps fitted temperatures to [0.5, 5.0] from v0.3.5, so runtime behaviour depends on the package version.
11. Romanised Indian-language text (Telugu or Hindi typed in Latin letters, common on WhatsApp) has no non-Latin script and few diacritics, so script-based routing can treat it as English. The English checkpoint is confidently wrong outside English (item 7).

Items 8 and 9 come from the external study cited in §3.3; item 10 from the laya-mlx port's documentation, also cited there; item 11 is a property of our own traffic and routing, to be measured on our data. They motivated rules in §7.2a, §12.3 and §13. No threshold, floor, promotion decision or other number in this note depends on their values; the rules they motivated are conservative whether or not the numbers reproduce.

### 3.3 External evidence (motivating only)

External studies can justify adding a safeguard. They never certify a provider. Certification-grade evidence is only our own `PromotionEvidence` (§13.1).

```text
External evidence:
  source:            github.com/glukicov/laya_router
  commit:            <immutable SHA — fill when validating §3.1>
  files:             README.md, docs/EVAL.md, data/
  design:            180 hand-written requests; zero-shot; single laptop; no domain calibration
  uncertainty:       ±9.5-point 95% interval on the paired difference (as reported)
  label quality:     independent model disagreed with ~25% of gold labels (as reported)
  model evaluated:   <Laya revision from the study's lockfile — fill>
  status:            DIRECTIONAL — not reproduced by us

External evidence:
  source:            github.com/mizorewww/laya-mlx (independent MLX port of Laya; Apple Silicon only)
  commit:            <immutable SHA — fill when validating §3.1>
  files:             README.md, BENCHMARKS.md
  relevant findings: shipped `choice:11+` temperature 0.1006; upstream clamp to [0.5, 5.0] from v0.3.5;
                     FP16 and FP32 probabilities differ slightly even when the selected label agrees
  status:            DIRECTIONAL — not reproduced by us; runtime not used by superagents
```

Each limit is re-checked against the pinned commit in §3.1; any that no longer applies is recorded, not silently dropped.

---

## 4. Placement Under the Runtime Contract

### 4.1 The gap

`RuntimeContract` (FINAL_ARCHITECTURE §38) defines `generate`, `stream`, `capabilities` and `cost_model`. It has no `decide`. The REFLEX sketch (PIPELINE_STAGES §21) calls `worker.provider.decide(state, questions)`, which no contract defines. The sketch is non-normative, so this is a gap. Recorded as **LB1**.

### 4.2 Proposed placement (OD-L1)

A sibling interface under §38, implemented only by Advisory Decision Providers:

```text
S12 REFLEX choice step ─┐
EventCorrelator ────────┼─→ DecisionContract → LayaDecisionAdapter → laya-serve (self-hosted)
                        │                    → ClaudeRuntimeAdapter (structured-output fallback)
                        │
                        └─ every call wrapped by the canonical injected CircuitBreaker (§10.3)
```

```python
# Non-normative sketch
class DecisionContract(ABC):
    """Advisory typed decisions over a state. Never raises — returns DecisionResult.
    Implementations select among supplied options only; they never authorize,
    resolve, plan, mutate or execute."""

    CONTRACT_VERSION: str

    @abstractmethod
    async def decide(self, request: DecisionRequest,
                     context: ExecutionContext) -> DecisionResult: ...

    @abstractmethod
    def decision_capabilities(self) -> DecisionCapabilities: ...

    @abstractmethod
    def cost_model(self) -> CostModel: ...
```

`RuntimeContract` and `RuntimeCapabilities` are unchanged. Callers resolve a `DecisionContract` by use site through an injected registry; no stage imports `LayaDecisionAdapter` directly.

### 4.3 Compatibility boundary

`DecisionContract` and the types in §5 are the only canonical decision interface in superagents. Laya exposes its own `decide()` method and its own schema-driven request and response formats; these are upstream implementation details. They are translated inside `LayaDecisionAdapter` and never appear in any canonical contract, table, event or test outside the adapter package (LR14). An upstream API change is absorbed by the adapter or fails its contract tests; it never propagates.

---

## 5. Contract Types

Non-normative sketches. Final shapes belong in DATA_CONTRACTS.md when the phase opens. Hash fields are contractual, not trace conventions.

```python
@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: str                  # system-authored, from a versioned schema file
    options: dict[str, str]            # opaque key ("A", "B", …) → system-authored description; ≤ 20

@dataclass(frozen=True)
class DecisionRequest:
    use_site: str                      # "reflex" | "event_noise"
    state: dict[str, Any]              # untrusted data, filtered to the schema's fields
    questions: dict[str, ChoiceQuestion]
    calibration_profile_id: str
    language_hint: str | None          # BCP-47 if known; forwarded as lang_guess
    # ─── provenance (computed by the caller, verified by the adapter) ───
    request_hash: str                  # canonical hash of state + questions
    state_schema_hash: str             # which state fields were allowed
    question_schema_hash: str          # instructions + option descriptions
    option_space_hash: str             # REFLEX: ReflexChoice.candidate_set_hash; noise: fixed schema hash

@dataclass(frozen=True)
class DecisionAnswer:
    selected: str                      # option key
    distribution: dict[str, float]     # calibrated, after profile temperatures (telemetry only)
    answer_confidence: float           # calibrated probability of `selected`; the ONLY gate input (§9.2 rule 3)
    threshold: float                   # from the profile, for audit
    passed_threshold: bool

@dataclass(frozen=True)
class DecisionResult:
    status: str                        # "ok" | "uncertain" | "unavailable" | "timeout" | "circuit_open"
                                       # | "profile_mismatch" | "malformed" | "rejected" | "integrity_violation"
                                       # ("ok" = passed threshold; "uncertain" = valid answer below threshold)
    answers: dict[str, DecisionAnswer]
    error_class: str | None            # classified; never raw text
    latency_ms: float
    # ─── provenance ───
    request_hash: str                  # echoed; must equal the request's
    state_schema_hash: str
    question_schema_hash: str
    option_space_hash: str
    model_repo: str
    model_revision: str                # immutable revision actually served
    serving_dtype: str
    adapter_version: str
    decision_contract_version: str
    calibration_profile_id: str
```

`DecisionResult` carries no action, parameter value, authorization or risk. It names an option key. Mapping that key to a concrete value is done by the deterministic gate against the frozen candidate set. `decision_result_hash` is the canonical hash of a result's provenance, status and answers, computed by the caller on receipt.

---

## 6. Non-Negotiable Rules

These apply to every use site. A use-site section may narrow them; none may widen them.

| ID | Rule |
|---|---|
| **LR1 — Never sole authority on mutations** | No W, D or IRREVERSIBLE operation executes because of an Advisory Decision Provider's answer alone. D and IRREVERSIBLE steps never carry a `ReflexChoice`. For W, the selection is necessary but never sufficient: every condition in §7.4 must also hold. |
| **LR2 — S8 remains the enforcer** | Provider output is never an input to any S8 check, never populates `ExecutionContext`, never sets `auth_passed`, and never changes `effective_risk` or `effective_mutation`. S8 stays deterministic with no model in its path. Laya runs only after S8, S10 and S11 have accepted the plan (use site A) or before S0 exists (use site B), so it cannot reorder or short-circuit the guardrail cascade (SECURITY §10). |
| **LR3 — Thresholds come from calibration** | Every gate on a provider answer uses a threshold from an approved `CalibrationProfile` (§9). Spec defaults (0.9, 0.7, 0.5) apply to S2 LLM confidence only and are **not** valid for provider scores. No profile or a mismatched profile disables the use site. |
| **LR4 — Frozen candidates only** | A provider may select only one candidate from an immutable REFLEX Choice Set frozen at S9, covered by `plan_hash`, confirmed at S10 where confirmation applies, and validated at S11. Every candidate shares the step's single FrozenBindingIdentity, kernel op, mutation class and risk. The provider cannot create, resolve, authorize, modify or expand a candidate. |
| **LR5 — No resolution side effects** | A selection never triggers a capability lookup, binding lookup, provider lookup, risk or mutation derivation, parameter generation, or plan change. The selected key maps to a pre-validated concrete value by table lookup only. |
| **LR6 — Uncertainty resolves toward the safe side** | The gate proceeds only when a provider of record exists and its status is `ok`. Every other outcome — `uncertain`, `unavailable`, `timeout`, `circuit_open`, `profile_mismatch`, `malformed`, `rejected`, `integrity_violation`, or no provider of record — means the REFLEX step is not executed (§7.6) and event filtering passes the event through. The rule is defined by complement, so a status added later is non-executable until this rule is amended. No failure ever causes an execution or drops an event. |
| **LR7 — State is data** | State is untrusted data. Instructions and option descriptions are system-authored and fixed per schema; no user or provider text reaches `instructions` or `options`. |
| **LR8 — Pinned and auditable** | Every call records the provenance fields of §5. Unpinned checkpoints (`main`, latest) are rejected at adapter start. |
| **LR9 — Supported question shape only** | `choice` with opaque option keys, ≤ 20 options, descriptions carrying the meaning. No `score`, no `noul`, no boolean-looking keys. |
| **LR10 — Decide once per step** | A REFLEX step's decision is persisted before anything that depends on it (§7.5). Retries and crash recovery reuse the persisted decision. A step is never re-decided. |
| **LR11 — Decision attempts are not execution attempts** | A failed or repeated decision call never increments `execution_steps.attempt`, never consumes a provider execution attempt, and never reserves or locks budget. |
| **LR12 — Never raises** | The adapter follows the §38 never-raise contract. |
| **LR13 — No threshold shopping** | An `uncertain` answer is a valid answer. It never triggers another provider. Fallback exists only for provider failure (§10.4), so no sequence of attempts can turn one provider's "not confident" into an execution. |
| **LR14 — Compatibility boundary** | Laya's native `decide()` API and schemas never become a superagents contract (§4.3). |

---

## 7. Use Site A — REFLEX Choice Steps

### 7.1 The integrity problem this section solves

The pipeline freezes the operation before S12: S5 produces exactly one FrozenBindingIdentity (RESOLVE_LAYER §2), S9 freezes each Step's `kernel_op_id` and `params` under `plan_hash`, S10 confirms that plan, and S11 freezes the manifest. v1 of this note let Laya choose an action at S12 from observation candidates, which could execute a different operation than the one confirmed. That would be a post-confirmation mutation of the plan. v2 removes it: Laya may choose only among values the plan already froze.

### 7.2 Model: one kernel op, one binding, a frozen value set

A REFLEX choice step is an ordinary Step with one additional frozen field. Its `kernel_op_id`, binding, `mutation`, `risk`, `cost` and every other parameter are fixed exactly as for any Step. Only one named parameter is left to be chosen, and only from a frozen set.

```python
# Non-normative sketch — proposed additive field on DATA_CONTRACTS §4 Step
@dataclass(frozen=True)
class ReflexChoice:
    param_name: str                    # must equal the final reference token of parameter_path
    parameter_path: str                # exactly one RFC 6901 JSON Pointer into Step.params (§7.2b)
    parameter_schema_hash: str         # hash of the kernel input-schema fragment at parameter_path,
                                       # at the manifest-pinned capability/binding version
    candidates: dict[str, Any]         # opaque key → concrete value; 2 ≤ len ≤ 20; canonical form §7.2b
    candidate_set_hash: str            # order-independent canonical hash (§7.2b)
    question_schema_id: str            # versioned instructions + option descriptions
    state_schema_id: str               # which observed fields may be sent as state
    state_source_step_ids: list[str]   # R steps whose outputs form the state; ⊆ depends_on
    calibration_profile_id: str
    decision_contract_version: str

@dataclass(frozen=True)
class Step:
    ...                                # all existing fields unchanged
    reflex_choice: ReflexChoice | None = None
```

S11 validates each candidate against the schema fragment identified by `parameter_schema_hash`, and rejects the plan if the fragment at `parameter_path` in the pinned kernel schema hashes differently. Option keys are assigned by the canonical order in §7.2b and never encode meaning; the meaning lives only in the system-authored descriptions.

### 7.2a Descriptions are versioned artifacts

Because wording alone can move accuracy by tens of points (§3.2 item 8), question instructions and option descriptions are treated like model weights, not like copy:

1. They live in versioned schema files identified by `question_schema_id`; their hash is part of every calibration profile (§9.2 rules 4–5). Any wording change, including a typo fix, requires a new profile before it is served.
2. Each option description states what distinguishes the candidate from its neighbours, in owner-authored wording approved through evaluation. Examples are optional. When used, they are part of the versioned schema (so they are covered by its hash and evaluated with it); every candidate in the schema carries the same number of examples, so examples do not act as an unevaluated prior toward one option; and no example is taken or paraphrased from any fit, eval, drift or promotion item, because that would contaminate the evaluation.
3. A wording change is evaluated like a model change: temperatures are refitted on the fit set, then thresholds and all metrics are measured once on the eval set and compared per candidate with the previous version (§13 item 7). Competing wordings are compared on the fit set only; the eval set scores only the chosen wording, once.
4. Descriptions are authored by the owner or reviewed by them. They are never generated at runtime, and never derived from user or provider text (LR7).
5. **Candidate universe.** A question schema declares the full set of values its candidates may take, each with its description. A `ReflexChoice` selects a subset of that universe; S9 never writes a description per plan. S11 rejects a candidate value that is not in the declared universe.

### 7.2b Canonical form and single-target substitution

1. **Canonical order.** Candidate values are ordered by their RFC 8785 (JCS) canonical JSON serialization. Duplicate values are invalid and S11 rejects the plan. Keys `A`, `B`, `C`, … are assigned in that order. The same set of values supplied in any order therefore yields the same keys.
2. **Hash.** `candidate_set_hash` = SHA-256 of the JCS serialization of `{param_name, parameter_path, parameter_schema_hash, candidates: [[key, value], …] in canonical order}`. It is independent of input order and serialization whitespace.
3. **Presentation.** In production, options are always presented to a provider in canonical key order. Permuted presentation exists only in the evaluation harness (§9.2 rule 10), so production decisions never depend on an incidental ordering.
4. **Single target.** `parameter_path` is exactly one RFC 6901 JSON Pointer. It addresses a member of a JSON object: no array index, no `-` token. Its parent object exists in `Step.params`, and the target member itself is absent at S9. `param_name` equals the pointer's final reference token.
5. **Substitution.** At S12, the chosen value is set at `parameter_path` and nowhere else. The gate verifies that the resulting params equal the frozen params everywhere except that one member; any other difference is `integrity_violation`. No candidate can alter siblings, parents, array structure or any other field.
6. **Validation.** S11 validates the complete params once per candidate, with that candidate substituted, against the pinned kernel input schema.

Example: a step `ghl.opportunity_update_stage` with `params = {"opportunity_id": "<id>", "stage_id": <chosen>}` and `candidates = {"A": "stage-qualified", "B": "stage-nurture", "C": "stage-lost"}`. The operation, record and binding are fixed and confirmed; Laya chooses which of three pre-approved stages, based on the contact history read by an earlier R step.

### 7.3 Where each part is fixed

| Stage | Responsibility for a REFLEX choice step |
|---|---|
| S9 | Decides whether a step carries `reflex_choice` (strategy authority, OD-L7). Only for FAST or WORKFLOW paths. Only if the step's frozen mutation is R, or W where OD-L4 allows. Never for D or IRREVERSIBLE. Builds candidates from the frozen IntentSpecification, restricted to the question schema's declared candidate universe (§7.2a item 5), in canonical form (§7.2b). Includes `reflex_choice` in `plan_hash`. |
| S10 | Where confirmation is required, the confirmation presents the full candidate set, not a single value, and the user confirms the set. **This changes certified S10 behavior and requires change control (LB10).** Until LB10 is decided, S9 must not attach `reflex_choice` to any step that requires confirmation. |
| S11 | Validates every candidate value exactly as it validates a concrete parameter: kernel input schema and resource scope. Any candidate failing → plan invalid (fail closed). Records `decision_contract_version` and the profile IDs in the manifest version chain (LB8). |
| S12 | Makes the decision (§7.5), maps the key to its frozen value, then runs the unchanged S12 step sequence. |

Because every candidate is inside `plan_hash`, the S12 entry digest check (S12_S15 gate §7.1 item 5) already proves that no candidate was added or changed after S11.

### 7.4 Gate conditions by mutation class

The deterministic gate executes the step with the chosen value only if every condition in the row holds.

| Frozen `mutation` | Conditions |
|---|---|
| **R** | Selected key ∈ `candidates`; `answer_confidence ≥ threshold`; result provenance matches the request (§5). |
| **W** (not in first release, OD-L4) | All R conditions; `autonomy_level != CONFIRM_ALL`; frozen `risk` ≤ the REFLEX risk ceiling (never recomputed); S10 confirmation, where required, covered this candidate set; pre-flight (S12 step 6) passes for the chosen value. |
| **D / IRREVERSIBLE** | Not eligible. S9 never attaches `reflex_choice`; S11 rejects a plan that does. |

### 7.5 Position in the S12 step loop and persistence

The decision runs once, between lease acquisition and budget reservation, in the slot the S12–S15 gate left empty as step 4:

```text
1 admission → 2 worker selection → 3 lease
→ 4 REFLEX decision (only for steps with reflex_choice)
     a. if a decision record exists for (execution_id, step_id): reuse it; do not call the provider
     b. else: build state from state_source_step_ids outputs filtered by state_schema_id;
        run provider arbitration (§10.4) to produce one DecisionResolution
     c. persist the DecisionResolution through fenced_write()
     d. if the gate conditions (§7.4) fail → §7.6
→ 5 budget reserve → 6 pre-flight (with the chosen value) → 7 … as specified by the gate
```

Decision records live in an additive table:

```text
step_decisions(
  decision_id PK, tenant_id NOT NULL, execution_id, step_id,
  use_site, final_status, provider_of_record,          -- NULL if no provider of record
  selected_key, selected_value_hash, answer_confidence, threshold, passed_threshold,
  distribution JSONB,                                  -- option keys → probabilities only
  attempts JSONB,                                      -- ordered DecisionAttempt telemetry (§10.4)
  plan_hash, request_hash, decision_result_hash,       -- hash chain (§12.2)
  state_schema_hash, question_schema_hash, option_space_hash,
  model_repo, model_revision, serving_dtype, adapter_version,
  decision_contract_version, calibration_profile_id,
  created_at,
  UNIQUE (execution_id, step_id)
)
```

It follows the S12–S15 gate §21 S7 rule: a new tenant-data table carries `tenant_id` and the standard RLS policy.

The unique constraint enforces LR10. Because the step idempotency key is `f"{request_id}:{step_id}"`, a re-decision after a crash could otherwise send a different value under the same key; persisting the decision before budget reservation removes that possibility. Recovery (S12–S15 gate §13) reads the record and never re-decides.

### 7.6 When the decision does not pass

No HITL channel exists yet, so "escalate" maps onto existing legal transitions only:

- The step goes `PENDING → CANCELLED` with terminal reason `reflex_<final_status>`, one per non-`ok` status in LR6 (for example `reflex_uncertain`, `reflex_timeout`, `reflex_circuit_open`, `reflex_malformed`, `reflex_integrity_violation`). These values extend the XS-1 enum. It never ran; no budget was reserved.
- CANCELLED is deliberate. SKIPPED must **not** be used: SKIPPED means "dependency failed, step not needed", and consolidation treats COMPLETED + SKIPPED with no failures as SUCCESS, which would report success for a required step that never ran. CANCELLED yields PARTIAL or FAILED.
- The step state machine currently annotates `PENDING → CANCELLED` as user cancellation only, and `execution_steps` has no structured terminal-reason column. Both gaps already affect the S12–S15 gate (admission REJECT, budget exhaustion, pre-flight failure). They are tracked as **XS-1** (§15.1), not as a Laya blocker. This note uses whatever terminal-reason mechanism XS-1 establishes.
- Dependents become SKIPPED per the gate's step 12. The run consolidates normally (PARTIAL or FAILED).
- S15 tells the user which step was not performed and that it needs a manual choice among the confirmed options.
- Whether a fallback provider is consulted is decided only by §10.4. An uncertain answer never reaches a fallback (LR13).

### 7.7 Shadow mode

Before promotion, the decision of record comes from the fallback provider (or from S9 choosing a fixed value, if no fallback exists). Laya runs in parallel, is persisted with `use_site = "reflex_shadow"`, and never reaches the gate, never delays the step beyond its own timeout, and never affects budget.

### 7.8 Deferred: choosing among different operations

Selecting between different kernel ops (for example, `update_contact` vs `create_task`) would require one FrozenBindingIdentity per candidate. RESOLVE_LAYER §2 says S5 produces exactly one. That is a change to a certified S0–S11 contract and is recorded as **LB6**, not designed here.

---

## 8. Use Site B — Event Noise Filtering

### 8.1 Where it runs

In `EventCorrelator.filter_noise`, after exact deduplication and after the deterministic noise list. The deterministic list stays authoritative: an event it discards is never sent to Laya.

The tenant for every eligibility check, profile lookup and configuration read comes from the gateway's authenticated context, never from payload data (IDENTITY_AND_TENANCY §8; `test_event_envelope_tenant_from_auth_not_payload()`). Eligibility is evaluated against a tenant configuration snapshot read once per event and recorded by version in the `event_log` row.

### 8.2 Eligibility

An event is classified only if all hold:

- Its `event_type` is in the tenant's opted-in classification list (configuration, default empty).
- It is not HIGH priority.
- No active `WorkerSubscription` matching it targets a capability the tenant has marked "never filter".
- A valid `event_noise` profile exists for the event's traffic slice (§9.2 rule 6).

### 8.3 Question

| Key | Description (system-authored) |
|---|---|
| `A` | Actionable: a person or system needs a response or follow-up |
| `B` | Noise: automated, informational, duplicate in meaning, or needing no action |

### 8.4 Decision

- `B` selected and `answer_confidence ≥ threshold` → the event is dropped.
- Anything else → the event proceeds to subscription matching unchanged (LR6).

### 8.5 False-drop invariant

The consequences are asymmetric: a wrong pass-through costs processing; a wrong drop loses an event. Therefore:

- **INV-N1**: Use site B cannot be ACTIVE for a tenant unless a false-drop ceiling is set for it. There is no default and no "unset means unlimited".
- **INV-N2**: The threshold is chosen so that measured false-drop rate on the eval set is at or below the ceiling; the profile is invalid otherwise.
- **INV-N3**: In production, a monitored false-drop rate above the ceiling demotes the use site to SHADOW automatically. Demotion does not require a human.

- **INV-N4**: The false-drop ceiling applies per eligible `event_type` as well as in aggregate, and each opted-in `event_type` needs the owner-set minimum of labelled actionable examples. An aggregate that passes while one event type exceeds the ceiling fails; an event type with too few examples is not eligible for classification.

Event-noise evaluation reports, separately: false-drop rate (actionable events dropped ÷ actionable eligible events), false-pass rate, coverage, and actionable recall per `event_type`, per tenant and per language slice.

The ceiling's value is an owner decision (OD-L3). The existence and enforcement of the ceiling are not.

### 8.6 Storage and state

- A drop uses the existing legal transition `deduplicated → dropped`. No new state.
- The `event_log` row records reason code `classified_noise` and the decision telemetry of §12.2.
- Dropped events are retained under normal retention and can be replayed by an operator; replay creates a normal S0 entry, with no bypass path.
- The `dropped` definition ("No subscription matched or duplicate") needs a third reason: **LB3**.

### 8.7 Adversarial note

Event payloads are untrusted, and a webhook can carry content authored by a third party (for example, a customer message inside a CRM event). A crafted payload may influence the classification of the event that contains it, which could cause a legitimate business event to be dropped, or noise to pass through. It cannot directly cause execution. Event-loss impact is bounded by tenant opt-in, priority exclusion, never-filter subscriptions, the calibrated threshold, the false-drop ceiling (INV-N1–N3) and replayability.

### 8.8 Shadow mode

Classification runs and is logged; nothing is dropped.

---

## 9. Calibration and Thresholds

### 9.1 CalibrationProfile

The only source of thresholds.

```python
@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    use_site: str                         # "reflex" | "event_noise"
    provider_id: str                      # which DecisionContract implementation
    confidence_method: str                # how answer_confidence is produced (§10.4 rule 7)
    model_repo: str
    model_revision: str                   # immutable
    weights_digest: str
    package_version: str
    serving_dtype: str                    # "bf16" | "fp16" | "fp32"
    device_class: str
    question_schema_hash: str
    temperatures: dict[tuple[str, str, int], float]  # per (question_id, slice, option_count)
    temperature_layering: str             # "runtime_disabled" | "fitted_over_runtime" (§9.2 rule 11)
    runtime_temperature_clamp: tuple[float, float] | None
    language_detector_version: str        # §9.2 rule 9
    thresholds: dict[tuple[str, str, int], float]    # per (question_id, slice, option_count)
    fit_dataset_hash: str
    eval_dataset_hash: str                # must differ from fit_dataset_hash
    metrics: CalibrationMetrics           # accuracy at coverage, coverage, ECE, n, per slice;
                                          # per-candidate recall, precision and example count;
                                          # order sensitivity; event_noise metrics per §8.5
    evidence_id: str                      # PromotionEvidence that approved this profile (§13.1)
    allowed_slices: list[str]             # e.g. ["lang:en", "lang:te"]
    tenant_scope: list[str] | None        # None = platform-wide; else only these tenants
    profile_status: str                   # "draft" | "approved" | "superseded" | "revoked"
    supersedes_profile_id: str | None
    fitted_at: str
    approved_by: str                      # owner, not the coding agent
    approved_at: str
    review_due_at: str                    # after this, treated as profile_mismatch until re-approved
```

### 9.2 Rules

1. **Held-out selection.** Temperatures fitted on `fit_dataset`; thresholds chosen on a disjoint `eval_dataset`. Equal hashes → invalid.
2. **Threshold is a policy.** Chosen as the lowest value at which eval accuracy meets the owner's floor (and, for event noise, false-drop ≤ ceiling). The resulting coverage is recorded.
3. **Gate on `answer_confidence` only.** `answer_confidence` is the calibrated probability of the selected option after profile temperatures. No other signal may become a gate input: not Laya's entropy-based `confidence`, not a separately computed `max(distribution)`, not raw probabilities, logits or margins.
4. **Exact match.** A request is served only if model revision, weights digest, package version, dtype, device class and question schema hash match the profile; otherwise `profile_mismatch`.
5. **Invalidation.** A new profile is required after any change to those fields, or when drift exceeds tolerance.
6. **Slices.** Metrics include language (at minimum `en`, `hi`, `te`, and the romanised slices `hi-Latn` and `te-Latn`), negated phrasing and option count. Traffic outside `allowed_slices` is not sent to the provider.
7. **Multilingual.** `laya-multilingual` is unusable until a profile is fitted.
8. **Status and scope.** Only `approved` profiles that are not past `review_due_at` are served, and only for tenants inside `tenant_scope`. Profile status changes are audited events.
9. **Calibration keying.** A request is served only if the profile holds a fitted temperature and threshold for its exact `(question_id, slice, option_count)`. There is no fallback to a neighbouring bucket, another language, or another tenant's profile: a missing key is `profile_mismatch`. The slice is determined before inference by deterministic language detection and the authenticated tenant; an undetected or unlisted language is not served. A profile fitted on English data can therefore never gate Telugu traffic, even when the model revision matches.

   **Romanised text.** Latin script alone never implies `en`. Detection must positively identify English; text it cannot positively identify is either classified into a listed romanised slice (`te-Latn`, `hi-Latn`) or left undetected and not served. Romanised slices are routed to the multilingual checkpoint, never the English one, and each needs its own fitted temperatures, thresholds and eval examples like any other slice. The language detector is itself versioned, recorded in the profile, and evaluated on a labelled set that includes romanised Telugu, romanised Hindi, code-mixed text and short messages; its confusion rate between `en` and the romanised slices must be within the owner's ceiling (OD-L3). A detector change requires a new profile.
10. **Order sensitivity.** For every `(question_id, option_count)`, the evaluation harness presents each eval item under a fixed, seeded set of permutations and reports the flip rate (share of items whose selected candidate *value* changes across permutations) and the first-position selection rate against the first-position base rate. Values are compared by candidate value, not key, because keys follow presentation order in the harness. Both must be within the owner's ceiling (OD-L3). This is a measured model property with a ceiling, not a pass/fail unit test: production always uses canonical order (§7.2b item 3), so the risk being bounded is systematic position bias, not nondeterminism.
11. **Exactly one temperature layer.** The profile's temperatures are the only calibration applied to a provider's output. The adapter either disables the runtime's shipped temperatures, or, if they cannot be disabled, the profile is fitted on top of them and records that it did so. Any runtime clamping of temperatures (for example to [0.5, 5.0]) is recorded in the §3.1 pin and the profile, and profile temperatures are fitted under the same clamp that serving will apply. A package upgrade that changes shipped temperatures or clamping invalidates the profile (rule 5, via `package_version`). Fitted temperatures outside the clamp range are recorded as clamped, never silently used.

---

## 10. Failure, Retry and Reliability

### 10.1 Failure mapping

| Condition | Status | Class (§10.4) | REFLEX | Event noise |
|---|---|---|---|---|
| Valid answer ≥ threshold | `ok` | ANSWER | Gate evaluates it | Drop if `B`, else pass |
| Valid answer < threshold | `uncertain` | ANSWER | CANCELLED `reflex_uncertain`; **no fallback** | Pass through |
| Unreachable / 5xx / 401 | `unavailable` (+ alert on 401) | PROVIDER_FAILURE | Fallback, else CANCELLED | Pass through |
| Timeout | `timeout` | PROVIDER_FAILURE | Fallback, else CANCELLED | Pass through |
| Circuit open | `circuit_open` | PROVIDER_FAILURE | Fallback, else CANCELLED | Pass through |
| Profile mismatch / expired / out of scope | `profile_mismatch` | PROVIDER_FAILURE | Fallback, else CANCELLED | Pass through |
| Unparseable response | `malformed` | PROVIDER_FAILURE | Fallback, else CANCELLED | Pass through |
| 422 (our request invalid) | `rejected` | REQUEST_DEFECT | CANCELLED; **no fallback**; defect alert | Pass through |
| Provenance mismatch, or key ∉ candidates | `integrity_violation` | INTEGRITY | CANCELLED; **no fallback**; security alert | Pass through |

### 10.2 Retry semantics

- One decision attempt per provider per decision. A failed decision attempt is not retried by the REFLEX step.
- Decision attempts are counted in the decision record, never in `execution_steps.attempt` (LR11).
- A decision attempt happens before budget reservation, so it never touches RESERVED/LOCKED state.
- Execution retries of the step (S12 step 8) reuse the persisted decision (LR10).

### 10.3 Circuit breaker ownership

There is no Laya-specific breaker. Decision calls go through the canonical injected `CircuitBreaker` component (RELIABILITY §1; S12–S15 gate §21 S3), keyed by `(decision_provider, use_site)`. While open, the use site behaves as if the provider were unavailable. Health recording follows the same wrapper rule as provider adapters. No second reliability subsystem is created.

### 10.4 Provider arbitration

Arbitration is deterministic and produces exactly one `DecisionResolution` per decision.

```python
# Non-normative sketch
@dataclass(frozen=True)
class DecisionAttempt:
    sequence: int                      # 1 or 2
    provider_id: str
    status: str                        # DecisionResult.status
    attempt_class: str                 # "ANSWER" | "PROVIDER_FAILURE" | "REQUEST_DEFECT" | "INTEGRITY"
    decision_result_hash: str
    latency_ms: float

@dataclass(frozen=True)
class DecisionResolution:
    attempts: list[DecisionAttempt]    # ordered; 1 or 2 entries
    provider_of_record: str | None     # provider whose ANSWER the gate evaluates
    final_status: str                  # status of the provider-of-record attempt, else of the last attempt
```

Rules:

1. Providers are tried in the order configured for the use site: primary, then at most one fallback (OD-L6). Never more than two attempts.
2. After each attempt, by class:
   - **ANSWER** (`ok` or `uncertain`): stop. This provider is the provider of record. No further attempts (LR13).
   - **PROVIDER_FAILURE**: try the next provider if one remains; otherwise stop with no provider of record. No answer was obtained, so trying another provider cannot shop for a threshold.
   - **REQUEST_DEFECT** or **INTEGRITY**: stop immediately with no provider of record. A defect in our request would reach the fallback unchanged; an integrity failure indicates a bug or misrouting and must fail closed.
3. The gate runs only if there is a provider of record and its status is `ok`.
4. Each provider is gated by its own calibration profile. Thresholds are never mixed across providers.
5. Shadow calls (§7.7, §8.8) are not attempts and never appear in a DecisionResolution.
6. The whole resolution, including every attempt, is persisted in one `fenced_write()` before budget reservation (§7.5).
7. **Conformance.** Every provider in a use site's order receives the byte-identical `DecisionRequest` — same state, questions, keys, descriptions and schema hashes — and must answer over exactly those keys. Its `answer_confidence` must come from the `confidence_method` declared in its profile and be calibrated like any other (§9). Verbal or self-reported confidence from a generative model is prohibited. Where a generative runtime does not expose token probabilities, an acceptable method is selection frequency over N independent samples with pinned sampling settings, with N and the settings recorded in the profile. A provider that cannot produce a calibrated `answer_confidence` cannot be configured for any use site. Every provider passes the conformance suite in §14.1.

Event noise uses the same arbitration, but by default no fallback is configured for it (OD-L6), so any non-ANSWER outcome passes the event through.

---

## 11. Security and Data Handling

1. **Self-hosted only.** laya-serve runs inside our infrastructure.
2. **Authentication.** Bearer token via `CredentialProvider`; never in logs, traces, profiles, plans or decision records.
3. **Minimization.** State contains only fields named in `state_schema_id`. A redaction hook removes secrets before the call; a test asserts it.
4. **Tenant isolation.** One tenant per request; no cross-tenant batching. laya-serve does not persist request bodies.
5. **No instructions from state.** LR7.

---

## 12. Observability, Persistence Limits and Billing

### 12.1 Logs and metrics

Structured log per call with `trace_id`, `execution_id` or `event_id`, `step_id` where applicable, `tenant_id`, `use_site`, the §5 provenance fields, `selected`, `answer_confidence`, `threshold`, `passed_threshold`, `latency_ms`, `status`. Counters: calls, passed, not passed, unavailable, profile mismatch, per use site.

### 12.2 What may be persisted — decision telemetry only

Decision records and `event_log` entries may store **decision telemetry**: option keys, the calibrated distribution over option keys, confidence, threshold, status, hashes and version identifiers.

The persisted hash chain is `plan_hash → option_space_hash (= candidate_set_hash) → question_schema_hash → calibration_profile_id → request_hash → decision_result_hash`, together with `model_revision` and `decision_contract_version`. Given the persisted plan and schema versions, it lets an auditor prove which frozen candidate set, question and model produced a decision.

They must **not** store: the state payload, instruction or option text (reconstructable from the schema hash), secrets, credentials, tokens, or provider response bodies. The request can be reconstructed for forensics from the source step outputs, the schema versions and `request_hash`. Reconstruction is performed only by an operator authorized for that tenant, is audited, and is bounded by the source outputs' own retention, redaction and deletion policies. Once a source output is deleted, the decision can still be verified by its hashes but can no longer be reconstructed. Decision records never extend the retention of any source data.

### 12.3 Drift monitoring

A sample of production decisions is labelled (source per OD-L3) and compared with the profile's expected accuracy and per-candidate recall at its coverage.

**Labelling is blind.** A labeller, human or model, sees the state, the instructions and the option descriptions, and never the provider's answer, the fallback's answer or any prior label. Reviewing an existing answer and approving or correcting it measures anchoring, not correctness, and is not an accepted labelling method for any eval, drift or promotion set. Where a model assists labelling, its blind labels are recorded separately. Inter-labeller agreement is reported as a measure of label reliability, naming the statistic used (for example Cohen's or Fleiss' κ) and the adjudication rule. Reliability below the owner's minimum (OD-L3) blocks promotion of the affected slice or candidate rather than being averaged away. The confidence-interval method and the smallest difference worth detecting are fixed in the evaluation plan before labels are collected (§13.1); differences between providers inside that interval are unresolved, not evidence of superiority.

### 12.4 Billing

`resource_type = "decision.inference"`, `unit = "question"`, `kernel_op_ref = "decision.<use_site>"`. Billing records inference work performed, not successful decisions: every attempt that reached a provider is recorded with `provider_id`, `sequence`, `status` and question count, including `uncertain`, `malformed`, `timeout`, fallback and shadow attempts. Attempts stopped locally before any provider call (`circuit_open`, `profile_mismatch`) record zero quantity. Recorded like S2's `llm.token`.

---

## 13. Promotion Gate

Each use site moves independently: `DISABLED → SHADOW → ACTIVE`.

**Authority.** Promotion state is durable (one row per use site and tenant scope) and changes only through a single transition function owned by a `DecisionGovernanceController` in the control plane. Promotions require an owner action. Demotions (drift, INV-N3, profile revocation or expiry) are automatic, go through the same function, and emit an audit event. Workers, Runners, adapters and laya-serve never write promotion state. This lifecycle is not yet in STATE_TRANSITIONS.md: **LB11**.

**Atomic revalidation.** A promotion is committed only if, inside the same transaction that writes the new state, the transition function re-checks: the profile is `approved` and not revoked or superseded; `review_due_at` is in the future; the profile ID and hash equal those in the referenced `PromotionEvidence`; that evidence has status `passed` and is not superseded; `tenant_scope` is unchanged; and the promotion row's version equals the version read (compare-and-set). Any mismatch aborts the transition with no state change. Serving-time checks (§9.2 rules 4, 8 and 9) remain a second line, so a profile revoked after promotion stops being served on the next request.

**DISABLED → SHADOW**: approved profile, §14 tests passing, §3.1 validation pin filled, owner sign-off.

**SHADOW → ACTIVE** requires all of:

1. At least the owner-set minimum number of shadow decisions.
2. **Normalized comparison.** Both the decision of record and the Laya decision are converted to `NormalizedDecision {candidate_key | NONE, eligible: bool}` before comparison: REFLEX answers map to a key in the frozen candidate set or NONE; event answers map to `A`, `B` or NONE. Agreement is computed only on normalized values, so label or format differences never count as disagreement.
3. On labelled shadow decisions, **ground-truth accuracy** at the profile's coverage meets the floor overall and on every allowed slice, including negation.
4. REFLEX: zero passing Laya decisions whose normalized key is outside the candidate set (structurally impossible; the test proves it).
5. Event noise: INV-N1, INV-N2 and INV-N4 satisfied on shadow data.
6. The evaluation harness exits non-zero on failure; its report is attached to the promotion record.
7. **Per-candidate recall and precision.** For each candidate *k*, over blind-labelled cases:
   - `recall(k)` = cases with true candidate *k* where the provider of record selected *k* with status `ok`, ÷ all cases with true candidate *k*. `uncertain` answers and failures count as misses. This detects class collapse.
   - `precision(k)` = cases where *k* was selected with status `ok` and the true candidate is *k*, ÷ all cases where *k* was selected with status `ok`. This bounds wrong executions per candidate, which recall alone cannot.

   Both must meet their per-candidate floors (OD-L3), and the eval set must contain at least the owner-set minimum examples of each candidate. A profile whose overall accuracy passes while any candidate fails either floor is not promotable. A candidate with too few labelled examples blocks promotion of that choice set rather than being ignored. Neither metric may be replaced by selection frequency, agreement or overall accuracy.
8. Order sensitivity within the ceiling for every `(question_id, option_count)` in scope (§9.2 rule 10).
9. A `PromotionEvidence` record with status `passed` exists for exactly this profile (§13.1).

These metrics are reported separately and never substituted for one another: provider agreement (item 2), ground-truth accuracy (item 3), per-candidate recall and precision (item 7), order sensitivity (item 8), coverage, calibration (ECE), and for event noise the §8.5 metrics. Agreement with the fallback provider is **not** accuracy and never satisfies an accuracy floor.

### 13.1 PromotionEvidence

The only certification-grade evidence for a profile. The evaluation plan is fixed and hashed **before** labels are collected, so metrics, floors, the interval method and the permutation set cannot be chosen after seeing results.

```python
# Non-normative sketch
@dataclass(frozen=True)
class PromotionEvidence:
    evidence_id: str
    use_site: str
    tenant_scope: list[str] | None
    calibration_profile_id: str
    profile_hash: str
    provider_id: str
    model_revision: str
    weights_digest: str
    package_version: str
    serving_dtype: str
    device_class: str
    question_schema_hash: str
    evaluation_plan_hash: str          # metrics, floors, CI method, minimum detectable difference,
                                       # permutation set, slices — fixed before labelling
    eval_dataset_id: str
    eval_dataset_hash: str
    sample_count: int
    sampling_method: str               # how items were drawn from traffic or authored
    label_protocol_version: str        # blind protocol (§12.3)
    label_distribution: dict           # per candidate / event type and per slice
    label_reliability: dict            # statistic, value, adjudication rule
    harness_commit: str
    random_seed: int
    results: dict                      # overall, per slice, per candidate recall and precision,
                                       # order sensitivity, ECE, coverage, §8.5 event metrics
    status: str                        # "passed" | "failed" | "superseded"
    created_at: str
    approved_by: str
```

A use site returns to SHADOW automatically on drift or on INV-N3.

---

## 14. Required Tests

| Test | Asserts |
|---|---|
| `test_laya_adapter_never_raises()` | Every §10.1 failure returns a `DecisionResult` |
| `test_laya_no_profile_disables_use_site()` | Missing profile → fallback / pass-through |
| `test_laya_profile_mismatch_each_field()` | Each §9.2 rule 4 field mismatch disables |
| `test_laya_profile_rejects_shared_fit_eval_data()` | Equal dataset hashes → invalid |
| `test_laya_gate_uses_answer_confidence()` | Entropy `confidence` never read by a gate |
| `test_laya_spec_defaults_not_applied()` | No code path compares a provider score to 0.9, 0.7 or 0.5 constants |
| `test_laya_result_provenance_must_match_request()` | Mismatched `request_hash` or `option_space_hash` → rejected |
| `test_reflex_choice_in_plan_hash()` | Changing any candidate changes `plan_hash`; S12 entry denies a tampered set |
| `test_reflex_choice_never_on_d_or_irreversible()` | S9 never attaches one; S11 rejects a plan that does |
| `test_reflex_s11_validates_every_candidate()` | One invalid candidate → plan invalid |
| `test_reflex_selection_never_changes_binding_or_kernel_op()` | Kernel op, binding, mutation, risk and other params identical before and after decision |
| `test_reflex_no_resolution_calls_after_decision()` | Architecture: no resolver, registry or risk code reachable from the decision path |
| `test_reflex_decision_persisted_before_budget()` | Decision record exists before any reservation row |
| `test_reflex_recovery_reuses_decision()` | Crash after decision, recover: provider called 0 more times, same value used |
| `test_reflex_unique_decision_per_step()` | Second insert for the same step fails |
| `test_reflex_decision_attempt_not_execution_attempt()` | Failed decision leaves `execution_steps.attempt` unchanged, no reservation |
| `test_reflex_not_confident_cancels_step()` | `PENDING → CANCELLED`, reason code, dependents SKIPPED, budget untouched |
| `test_reflex_cancelled_terminal_reason_is_structured()` | Every REFLEX cancellation writes a non-null `terminal_reason` from the closed enum (XS-1) |
| `test_lr6_every_non_ok_status_blocks_execution()` | Each status other than `ok`, and a missing provider of record, prevents execution |
| `test_reflex_confirm_all_excludes_w()` | CONFIRM_ALL → no W choice step |
| `test_reflex_shadow_does_not_affect_decision()` | Shadow answer never reaches the gate |
| `test_s8_has_no_decision_layer_import()` | Architecture: S8 imports nothing from the decision layer |
| `test_decision_output_never_writes_execution_context()` | Architecture |
| `test_decision_calls_use_canonical_circuit_breaker()` | Architecture: no breaker class defined in the decision layer |
| `test_decision_record_contains_no_state_or_secrets()` | Injected secrets and state text absent from `step_decisions` and `event_log` |
| `test_event_noise_failure_passes_through()` | Every §10.1 failure → router |
| `test_event_noise_high_priority_never_classified()` | HIGH skips Laya |
| `test_event_noise_requires_false_drop_ceiling()` | No ceiling → cannot be ACTIVE (INV-N1) |
| `test_event_noise_auto_demotes_on_ceiling_breach()` | INV-N3 |
| `test_event_noise_drop_uses_existing_transition()` | `deduplicated → dropped`, reason `classified_noise` |
| `test_event_noise_dropped_event_replayable()` | Replay creates a normal S0 entry |
| `test_shadow_comparison_is_normalized()` | Differently formatted but equivalent answers count as agreement |
| `test_candidate_set_hash_order_independent()` | Same values in any input order → same keys and same hash |
| `test_duplicate_candidate_values_rejected()` | S11 rejects duplicate values |
| `test_candidates_within_schema_universe()` | Value outside the declared universe → S11 rejects |
| `test_parameter_path_single_object_member()` | Array index, `-` token, missing parent or pre-existing target → S11 rejects |
| `test_substitution_changes_only_target()` | Any difference outside `parameter_path` → `integrity_violation` |
| `test_calibration_key_exact_match()` | Missing `(question_id, slice, option_count)` → `profile_mismatch`; no neighbour fallback |
| `test_unlisted_language_not_served()` | Undetected or unlisted language never reaches a provider |
| `test_romanised_indic_never_routed_to_english()` | Romanised Telugu/Hindi and code-mixed samples classify as `te-Latn`/`hi-Latn` or undetected, never `en` |
| `test_latin_script_alone_does_not_imply_english()` | Latin text without positive English identification is not served as `en` |
| `test_detector_version_mismatch_is_profile_mismatch()` | Changed detector version → `profile_mismatch` |
| `test_single_temperature_layer()` | Output probabilities equal logits scaled once by the profile temperature; shipped temperatures not applied twice |
| `test_package_change_in_temperature_behaviour_invalidates_profile()` | Different shipped temperatures or clamp → `profile_mismatch` |
| `test_examples_disjoint_from_eval_items()` | Harness rejects a schema whose examples match fit/eval/drift items |
| `test_promotion_revalidates_in_transaction()` | Profile revoked or expired between evaluation and commit → promotion aborts |
| `test_promotion_cas_conflict_aborts()` | Concurrent promotion-row change → no state change |
| `test_promotion_requires_passed_evidence()` | No `passed` PromotionEvidence for this exact profile → not promotable |
| `test_promotion_fails_on_single_candidate_precision()` | One candidate below its precision floor → not promotable |
| `test_event_noise_per_event_type_ceiling()` | Aggregate passes, one event type exceeds ceiling → not promotable |
| `test_reconstruction_requires_tenant_authorization()` | Unauthorized operator cannot reconstruct; attempts are audited |
| `test_description_change_requires_new_profile()` | Any edit to instructions or option text changes `question_schema_hash` → `profile_mismatch` |
| `test_promotion_fails_on_single_candidate_recall()` | Overall accuracy above floor, one candidate below its recall floor → not promotable |
| `test_promotion_blocks_on_undersampled_candidate()` | Candidate below minimum labelled examples → promotion blocked |
| `test_labelling_tool_hides_answers()` | Labelling interface payload contains no provider, fallback or prior label |
| `test_arbitration_uncertain_never_falls_back()` | `uncertain` from primary → exactly one attempt, step CANCELLED |
| `test_arbitration_failure_classes()` | Each PROVIDER_FAILURE status triggers fallback; REQUEST_DEFECT and INTEGRITY do not |
| `test_arbitration_max_two_attempts()` | Fallback failure → no third attempt |
| `test_arbitration_single_resolution_persisted()` | One DecisionResolution with all attempts, written before budget |
| `test_arbitration_thresholds_not_mixed()` | Fallback answer gated by the fallback's own profile |
| `test_reflex_parameter_schema_hash_checked()` | Schema fragment drift at `parameter_path` → S11 rejects |
| `test_reflex_no_choice_on_confirmation_steps_until_lb10()` | S9 never attaches `reflex_choice` to a step requiring confirmation |
| `test_reflex_uses_cancelled_not_skipped()` | Non-passing decision → CANCELLED; run never consolidates to SUCCESS |
| `test_profile_expired_or_out_of_scope_is_mismatch()` | `review_due_at` passed or tenant ∉ scope → `profile_mismatch` |
| `test_promotion_state_single_writer()` | Architecture: only DecisionGovernanceController writes promotion state |
| `test_event_noise_tenant_from_auth_context()` | Payload `tenant_id` never selects profile or configuration |
| `test_no_laya_native_types_outside_adapter()` | Architecture: no import of `laya` outside the adapter package |
| `test_billing_records_failed_and_shadow_attempts()` | Every provider-reaching attempt billed with status |
| `test_laya_no_cross_tenant_batch()` | Two-tenant batch rejected |
| `test_laya_state_text_never_in_instructions()` | User/provider text cannot reach `instructions` or `options` |

---

### 14.1 DecisionContract conformance suite

Every provider, primary or fallback, must pass this suite before it can be named in any use site's provider order. It tests the contract, not model quality.

| Test | Asserts |
|---|---|
| `conformance_identical_request()` | Provider receives the byte-identical `DecisionRequest` given to any other provider |
| `conformance_key_closure()` | Every answer's `selected` key ∈ the request's option keys |
| `conformance_never_raises()` | All failure modes return a `DecisionResult` with a §10.1 status |
| `conformance_status_taxonomy()` | Only the §5 status values appear |
| `conformance_provenance_echo()` | `request_hash` and schema hashes are echoed exactly |
| `conformance_confidence_method_declared()` | `confidence_method` present and not verbal or self-reported |
| `conformance_no_native_types_leak()` | No provider-native type crosses the adapter boundary (LR14) |
| `conformance_order_sensitivity_reported()` | Harness produces §9.2 rule 10 metrics for the provider |
| `conformance_temperature_layering_declared()` | Provider's profile declares `temperature_layering` and any runtime clamp |

## 15. Blocker Register Entries

Add to `SUPERSESSION_AWARE_BLOCKER_REGISTER.md`, target phase **LLM layer**.

| ID | Documents | Conflict or gap | Proposed resolution | Status |
|---|---|---|---|---|
| **LB1** | FINAL_ARCHITECTURE §38; PIPELINE_STAGES §21 | REFLEX calls `provider.decide()`; `RuntimeContract` has no `decide` | `DecisionContract` sibling interface (OD-L1) | DECISION_REQUIRED |
| **LB2** | PIPELINE_STAGES §21; S7 matrix; DATA_CONTRACTS §4 | §21 says strategy is chosen at S7; S7 emits only FAST/WORKFLOW/CLARIFY/DENY; Step has no strategy field | Strategy authority = S9, expressed by `Step.reflex_choice`; S7 unchanged; correct §21's "selected at S7" (OD-L7) | DECISION_REQUIRED |
| **LB3** | EVENT_GATEWAY_AND_ROUTER §8 | `dropped` covers only no-match or duplicate | Extend definition, add reason codes; no new state | PROPAGATION_REQUIRED |
| **LB4** | PIPELINE_STAGES §21 catalog | REFLEX lists "safety-critical tasks" as a use case, contradicting LR1 | Remove from the REFLEX row | DECISION_REQUIRED |
| **LB5** | This note; S7 | Spec confidence thresholds could be applied to provider scores | LR3 + `test_laya_spec_defaults_not_applied()` | DECIDED (pending propagation) |
| **LB6** | RESOLVE_LAYER §2; §7.8 | Choosing among different kernel ops needs one FrozenBindingIdentity per candidate; S5 produces exactly one | Out of scope; future change control under S12_S15 §19.3 | OPEN |
| **LB7** | DATA_CONTRACTS §4 | Step has no field for a frozen choice set | Additive `Step.reflex_choice` (§7.2); S9 and S11 changes via §19.3 | DECISION_REQUIRED |
| **LB8** | DATA_CONTRACTS §27 | ExecutionManifest version chain has no decision-contract or calibration-profile entries | Additive fields `decision_contract_version`, `calibration_profile_ids`; candidate sets already covered by `plan_hash` | DECISION_REQUIRED |
| **LB9** | S12_S15 gate §8 | Step loop has no decision position; step 4 slot is empty | Decision at step 4 (§7.5); `step_decisions` table | DECISION_REQUIRED |
| **LB10** | This note §7.3; PIPELINE_STAGES S10; S12_S15 gate §19.3 | REFLEX requires S10 to present and confirm a frozen candidate set rather than a single concrete value; S10 is certified | Additive S10 confirmation-content contract via change control before the LLM-layer phase opens; until then, no `reflex_choice` on confirmation-requiring steps | DECISION_REQUIRED |
| **LB11** | This note §13; STATE_TRANSITIONS.md | New lifecycle DISABLED → SHADOW → ACTIVE with automatic demotion has no canonical state machine or owner | Add the machine to STATE_TRANSITIONS with DecisionGovernanceController as sole writer | DECISION_REQUIRED |

Register IDs are stable and never renumbered.

### 15.1 External reference

| ID | Register | Gap | Relation to this note |
|---|---|---|---|
| **XS-1** | S12–S15 gate register (entry to be created) | Step `PENDING → CANCELLED` annotated as user-only although the gate uses it for system reasons; `execution_steps` has no structured terminal-reason column and its status comment omits `cancelled`; STATE_TRANSITIONS invariant I-1 omits `cancelled` from terminal step states | §7.6 depends on its resolution. Not a Laya blocker; created and resolved in the S12–S15 register |

---

## 16. Owner Decisions

Recommended options pre-selected.

**OD-L1 — Contract shape.** **Selected:** `DecisionContract` sibling interface; `RuntimeContract` unchanged.

**OD-L2 — Hosting.** **Selected:** self-hosted laya-serve with preloaded checkpoints; GPU when REFLEX is ACTIVE; CPU acceptable for SHADOW and low-volume event noise. Measured p50/p95 recorded in the profile.

**OD-L3 — Promotion numbers.** Owner sets, per use site, in the evaluation plan before labelling: accuracy floor (overall and per slice); per-candidate recall and precision floors and minimum labelled examples per candidate; order-sensitivity ceilings (flip rate and first-position excess); minimum label reliability and its statistic; language-detector confusion ceiling between `en` and the romanised slices; confidence-interval method and smallest difference worth detecting; minimum shadow decisions; event-noise false-drop ceiling, aggregate and per event type, with minimum examples per event type (INV-N1, INV-N4); drift tolerance and labelling source. Must be set before any use site goes ACTIVE.

**OD-L4 — First release scope.** **Selected:** REFLEX choice steps on **R steps only** in the first ACTIVE release. W becomes eligible only after a second promotion cycle with its own shadow data.

**OD-L5 — Training data.** **Selected:** training labels may come from logged decisions of record. Eval, drift and promotion sets are labelled **blind** by humans (§12.3); a model may add independent blind labels, but approving or correcting an existing answer never produces an eval label. Tenant data used for fine-tuning requires consent defined in the data-governance phase; until then, internal and synthetic data only.

**OD-L6 — Fallback provider.** **Selected:** for REFLEX, `ClaudeRuntimeAdapter` implementing `DecisionContract` through structured output, with its own calibration profile, consulted only on PROVIDER_FAILURE (§10.4). Its `confidence_method` must satisfy §10.4 rule 7; if it needs N samples per decision, N multiplies the fallback's latency and cost, and both are recorded in its profile. If no calibrated method is achievable, run without a fallback. For event noise, no fallback: failure passes the event through. If no fallback is configured for REFLEX, a failed decision cancels the step (§7.6).

**OD-L7 — Strategy authority.** **Selected:** S9 decides REFLEX eligibility per step and freezes it in the plan. S7 remains unchanged. Alternatives considered: S7 (would require a new PathDecision value and S7 contract change) and worker configuration (not frozen, not covered by `plan_hash`; rejected).

---

*End of LayaDecisionAdapter design note.*
