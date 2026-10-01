# M15: verification and VERIFICATION episodes (gate commit I, part 1) ⚙

| | |
|---|---|
| Gate | §8 step 9, C12, C19, D1, D4, D6, §21 S8, suite 9; FINAL_ARCHITECTURE §43; WORKER_LIFECYCLE §6–§9; Appendix A.2, A.7 |
| Rulings | CONF-005 (**open**: no AutonomyLevel source), CONF-036 (layer results = `verification_layer` events), CONF-040 (after a probe: no schema/deterministic layers), CONF-041 (follow `required_verification_layers`, no autonomy) |
| Golden | `tests_golden/s12/M15_verification.py`: 51 cases (29 functions) |
| Sabotage | `M15_lenient_semantic_parse`, `M15_provider_state_skipped`, `M15_verification_as_execution` |
| Depends on | M10 guard `observe`, M12 loop and `execution_events`, M13 `PostgresEpisodes` and probe path |
| Reference | `src/contracts/verification.py`, `src/engine/stages/s13_reconciliation/verification.py` (143 lines), `loop.py` (`_verify`, `_verification_episode`, `_settle_success`, `_verification_failed`) |

## Files

| File | Action |
|---|---|
| `src/contracts/verification.py` | **new**: `Verdict`, `VerificationLayer`, `LayerResult`, `VerificationOutcome` |
| `src/engine/stages/s13_reconciliation/verification.py` | **new**: `required_verification_layers`, `parse_semantic`, `StepVerifier` |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopSettings.verification_max_attempts=3`, `verification_backoff_s=1.0`; `LoopDeps.verification=None`; the verification step and episode paths |
| `src/adapters/postgres/reconciliation.py` | `PostgresEpisodes.close` raises `ValueError` (nothing written) for NOT_EXECUTED on a VERIFICATION episode |
| `src/adapters/runtime/mock_adapter.py` | additive: success `data["id"]`; `program(..., observe="inconclusive", observe_unknown=k)`; `observations` list |

## Interface (from the golden docstring; exact)

```python
# contracts/verification.py
class Verdict(StrEnum): PASS; FAIL; UNKNOWN
class VerificationLayer(StrEnum): schema; deterministic; provider_state; semantic; human   # run order
@dataclass(frozen=True) class LayerResult: layer; verdict; evidence
@dataclass(frozen=True) class VerificationOutcome: verdict; layers
    def pending(self) -> tuple: ...       # layers not yet PASS, in run order

# engine/stages/s13_reconciliation/verification.py
def required_verification_layers(mutation, risk) -> tuple[str, ...]
def parse_semantic(raw) -> Verdict
class StepVerifier:
    def __init__(self, guard, *, semantic=None, sleep): ...
    async def verify(self, step, binding, result, *, verifier, context, idempotency_key, layers=None) -> VerificationOutcome
```

## Logic and conditions

**Layer selection** (`required_verification_layers`; CONF-041, no autonomy branch):

| Condition | Layers added |
|---|---|
| always | `schema`, `deterministic` |
| mutation in W, D, IRREVERSIBLE | `provider_state` |
| `risk >= 0.7` or IRREVERSIBLE | `semantic` (0.69 → no, 0.7 → yes) |
| IRREVERSIBLE | `human` (D gets no human layer in this phase) |

**Each layer** (run order; stop after the first FAIL):

| Layer | PASS | FAIL | UNKNOWN |
|---|---|---|---|
| schema | an `ok` AdapterResult whose `data` is a JSON dict | anything else (an error result FAILs) | never |
| deterministic | `data[verifier.observation_params["identifier_from_result"]]` is a non-empty str or int | otherwise | never |
| provider_state | `guard.observe(kernel_op_id, spec, binding, context)` → `matches_expected is True` | `matches_expected is False` **and no error** | observation error, missing, or exception. Retry up to `verifier.max_attempts`, `await sleep(attempt_delay_ms/1000)` between attempts (bounded 3 × 1 s) |
| semantic | `parse_semantic(await semantic.assess(expected_state=..., observed_state=...))` is PASS | it is FAIL | no assessor, an exception, or a malformed answer |
| human | never | never | always, at once, never retried |

- `spec` = `{"method", "identifier", "expected", "idempotency_key"}`.
- The semantic model sees exactly (expected state, observed state) from one observation, **never the adapter's
  result data**. Text injected in a provider response must not reach it.
- `parse_semantic`: strip whitespace, then the exact strings `PASS` / `FAIL` / `UNKNOWN`. Anything else, including
  `"PASS -- confident"`, is UNKNOWN.
- Overall verdict: any FAIL → FAIL; else any UNKNOWN → UNKNOWN; else PASS.
- `result=None` (a probe confirmed the execution; CONF-040): skip schema and deterministic.
- `layers=` given: run only those, in run order.
- The verifier **never calls the adapter or the probe**.
- Layer evidence never holds provider observation data or the model's raw text.

**In the loop** (after an `ok` result, or after a probe confirmed EXECUTED_SUCCESS):

1. Read the step's persisted verifier (D1).
2. Write each layer result as a `verification_layer` event (`layer`, `verdict`, `evidence`) through the fenced path
   **before** the step commit.
3. Then apply the verdict:

| Verdict | Transitions |
|---|---|
| PASS, no pending human layer | step `completed (verification_passed)` (or the probe path's reason); budget COMMITTED |
| FAIL | step `failed (verification_failed)`; budget RELEASED; dependents SKIPPED; not retryable |
| UNKNOWN | step `running → pending_probe (verification_uncertain)` (after a probe the step is already there and its EXECUTION episode closes `confirmed_success`); open a **VERIFICATION** episode |

**VERIFICATION episode:**

- Each attempt is `attempt_started` and re-runs `outcome.pending()` minus `human` via `layers=`.
- FAIL → close `confirmed_failure (verified_fail)`, step failed, budget released.
- All PASS and no human layer pending → close `confirmed_success (verified_pass)`, step completed, budget committed.
- Still open → the attempt is `inconclusive`; wait `verification_backoff_s` between attempts, none after the last.
- After `verification_max_attempts`: close EXHAUSTED (event `episode_closed`), step `dead_letter
  (verification_exhausted)`. If **only** the human layer is open, the step goes `dead_letter
  (human_verification_pending)` at once, without re-attempts. Either way the budget stays **LOCKED** and every
  remaining PENDING step is `cancelled (run_dead_lettered)`.
- The episode **never** calls the probe or the adapter, and **never** closes NOT_EXECUTED.

**Injected `verify`:** when `LoopDeps.verification is None`, M12's injected `verify` decides. It may return a
`VerificationOutcome`. A string that is not a `Verdict` **fails closed**.

**Takeover during verification** (`FencedOut`): no further layer event, no commit, lease released `fenced_out`.

## Traps

- Treating every non-PASS as FAIL. UNKNOWN has its own episode path (a past reference defect).
- Opening an EXECUTION episode for a verification uncertainty (sabotage `M15_verification_as_execution`).
- Skipping `provider_state` and trusting the adapter's self-report (sabotage `M15_provider_state_skipped`).
- Lenient parsing of the model's answer (sabotage `M15_lenient_semantic_parse`).
- `.observe(` anywhere outside `s13_reconciliation/`, `reliability.py`, `adapter_interface.py`, `mock_adapter.py`
  (case `test_verification_code_lives_in_the_s13_package`). The loop calls the verifier; it never observes directly.
- A mock success without `data["id"]`: no deterministic layer can ever pass.

## Done when

- [ ] 51/51 in `M15_verification.py`; M01–M14 unchanged and green; `pytest tests -q` green.
- [ ] `owner_certify_s12.py --milestone M15`: all rows PASS, sabotage 3/3 caught.
- [ ] CONF-005 ruled by the owner. Otherwise report M15 as blocked on S12-REC.
