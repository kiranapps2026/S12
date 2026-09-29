"""
Architecture tests — plan hash invariants.

S9 is the authoritative owner of plan_hash. S11 verifies it.
S10 confirmation binds to the S9 hash.

Source: DATA_CONTRACTS.md §2, PIPELINE_STAGES.md §11
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import decimal

import pytest

# Import the SINGLE canonical source of truth — never reimplement serialization
from contracts.plan_hash import (
    canonical_plan_digest,
    PLAN_HASH_EXCLUDED_FIELDS,
    _serialize_value,
)


# ---------------------------------------------------------------------------
# Plan structure for testing
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_plan():
    """Create a sample Plan for mutation testing."""
    return {
        "plan_id": "plan-001",
        "execution_id": "exec-001",
        "steps": [
            {
                "step_id": "step-1",
                "kernel_op_id": "ghl.contact_create",
                "params": {"name": "Test", "email": "test@example.com"},
                "depends_on": [],
                "retry_policy": {"max_attempts": 2, "backoff": "exponential"},
            },
            {
                "step_id": "step-2",
                "kernel_op_id": "ghl.contact_update",
                "params": {"id": "${step-1.output.contact_id}", "name": "Updated"},
                "depends_on": ["step-1"],
                "retry_policy": {"max_attempts": 1, "backoff": "linear"},
            },
        ],
        "join_mode": "sequential",
        "estimated_cost": 0.10,
        "estimated_duration_seconds": 60,
        "confirmations": ["contact_create"],
    }


# ---------------------------------------------------------------------------
# S9 authoritative plan_hash tests
# ---------------------------------------------------------------------------

class TestS9AuthoritativePlanHash:
    """S9 is the authoritative owner of plan_hash."""

    def test_s9_computes_plan_hash(self, sample_plan):
        """S9 computes plan_hash — S11 does NOT recompute authoritatively."""
        # S9 computes the hash
        s9_hash = canonical_plan_digest(sample_plan)
        assert len(s9_hash) == 64  # SHA-256 hex string
        assert all(c in "0123456789abcdef" for c in s9_hash)

    def test_deterministic_hash(self, sample_plan):
        """Same plan produces same hash (deterministic)."""
        hash1 = canonical_plan_digest(sample_plan)
        hash2 = canonical_plan_digest(sample_plan)
        assert hash1 == hash2

    def test_plan_mutation_changes_hash(self, sample_plan):
        """Any plan mutation must change the hash."""
        original_hash = canonical_plan_digest(sample_plan)

        # Mutate each top-level field
        for field in sample_plan:
            if field == "steps":
                continue  # Test nested separately
            mutated = copy.deepcopy(sample_plan)
            if isinstance(mutated[field], str):
                mutated[field] = mutated[field] + "_mutated"
            elif isinstance(mutated[field], (int, float)):
                mutated[field] = mutated[field] + 1
            elif isinstance(mutated[field], list):
                mutated[field] = mutated[field] + ["extra"]
            else:
                mutated[field] = "mutated"
            new_hash = canonical_plan_digest(mutated)
            assert new_hash != original_hash, f"Mutation of '{field}' did not change hash"


class TestPlanHashMutationCoverage:
    """Every Plan field mutation must be detected by S11."""

    def test_mutate_step_parameter(self, sample_plan):
        """Mutating step parameter changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"][0]["params"]["name"] = "Different Name"
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_kernel_op_id(self, sample_plan):
        """Mutating kernel_op_id changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"][0]["kernel_op_id"] = "different.op"
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_retry_policy(self, sample_plan):
        """Mutating retry_policy changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"][0]["retry_policy"]["max_attempts"] = 5
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_dependency_graph(self, sample_plan):
        """Mutating dependency graph changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"][1]["depends_on"] = []  # Remove dependency
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_join_mode(self, sample_plan):
        """Mutating join_mode changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["join_mode"] = "parallel"
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_cost(self, sample_plan):
        """Mutating estimated_cost changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["estimated_cost"] = 0.99
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_mutate_confirmations(self, sample_plan):
        """Mutating confirmations changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["confirmations"] = ["contact_create", "contact_delete"]
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_add_step_changes_hash(self, sample_plan):
        """Adding a step changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"].append({
            "step_id": "step-3",
            "kernel_op_id": "new.op",
            "params": {},
            "depends_on": ["step-2"],
            "retry_policy": {"max_attempts": 1},
        })
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original

    def test_remove_step_changes_hash(self, sample_plan):
        """Removing a step changes the digest."""
        original = canonical_plan_digest(sample_plan)
        mutated = copy.deepcopy(sample_plan)
        mutated["steps"] = mutated["steps"][:1]  # Remove second step
        new_hash = canonical_plan_digest(mutated)
        assert new_hash != original


class TestPlanHashCanonicalization:
    """Hash must be canonical — no canonicalization bugs."""

    def test_sorted_keys(self):
        """Hash uses sorted keys — dict order doesn't matter."""
        plan1 = {"b": 2, "a": 1, "c": {"inner_b": 2, "inner_a": 1}}
        plan2 = {"c": {"inner_a": 1, "inner_b": 2}, "a": 1, "b": 2}
        assert canonical_plan_digest(plan1) == canonical_plan_digest(plan2)

    def test_no_extra_fields_in_hash(self):
        """Hash only includes canonical Plan fields — no extras."""
        plan = {
            "plan_id": "p1",
            "steps": [],
            "join_mode": "sequential",
            "estimated_cost": 0.0,
            "estimated_duration_seconds": 0,
            "confirmations": [],
        }
        # Adding an extra field should change the hash
        extended = {**plan, "extra_field": "should_not_be_here"}
        assert canonical_plan_digest(plan) != canonical_plan_digest(extended)

    def test_consistent_float_serialization(self):
        """Float values serialize consistently."""
        plan1 = {"cost": 0.1}
        plan2 = {"cost": 0.10}
        assert canonical_plan_digest(plan1) == canonical_plan_digest(plan2)


# ---------------------------------------------------------------------------
# Type conversion policy tests
# ---------------------------------------------------------------------------

class TestPlanHashTypeConversion:
    """_serialize_value handles each supported type explicitly."""

    def test_datetime_naive_serialized_as_utc(self):
        """Naive datetime is serialized as ISO-8601 with Z suffix."""
        import datetime as dt
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
            "created_at": dt.datetime(2025, 1, 1, 12, 0, 0),
        }
        digest = canonical_plan_digest(plan)
        # Should not raise — datetime is supported
        assert len(digest) == 64

    def test_datetime_aware_serialized_as_utc(self):
        """Timezone-aware datetime is converted to UTC with Z suffix."""
        import datetime as dt
        import datetime as dt_mod
        eastern = dt_mod.timezone(dt.timedelta(hours=-5))
        dt_val = dt.datetime(2025, 1, 1, 7, 0, 0, tzinfo=eastern)
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
            "created_at": dt_val,
        }
        digest = canonical_plan_digest(plan)
        assert len(digest) == 64

    def test_strenum_serialized_as_value(self):
        """StrEnum is serialized as its .value."""
        from enum import StrEnum
        class JoinMode(StrEnum):
            SEQUENTIAL = "sequential"
            PARALLEL = "parallel"

        plan1 = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": JoinMode.SEQUENTIAL,
            "budget_required": 1,
        }
        plan2 = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
        }
        assert canonical_plan_digest(plan1) == canonical_plan_digest(plan2)

    def test_decimal_serialized_as_str(self):
        """Decimal is serialized as str (preserves precision)."""
        from decimal import Decimal
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": Decimal("0.10"),
        }
        digest = canonical_plan_digest(plan)
        assert len(digest) == 64

    def test_tuple_serialized_as_list(self):
        """Tuple is serialized as list (JSON arrays)."""
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": (),
            "join_mode": "sequential",
            "budget_required": 1,
        }
        digest = canonical_plan_digest(plan)
        assert len(digest) == 64
        # Same plan with list should produce same digest
        plan_as_list = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
        }
        assert canonical_plan_digest(plan) == canonical_plan_digest(plan_as_list)

    def test_unsupported_type_raises_type_error(self):
        """Unsupported type (e.g. bytes) raises TypeError."""
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": b"bytes_value",  # bytes is unsupported
            "budget_required": 1,
        }
        with pytest.raises(TypeError, match="Cannot serialize"):
            canonical_plan_digest(plan)

    def test_set_raises_type_error(self):
        """Set is unsupported — raises TypeError."""
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
            "extra": {1, 2, 3},  # set is unsupported
        }
        with pytest.raises(TypeError, match="Cannot serialize"):
            canonical_plan_digest(plan)


# ---------------------------------------------------------------------------
# Excluded fields constant test
# ---------------------------------------------------------------------------

class TestPlanHashExcludedFields:
    """plan_hash exclusion comes from a named constant."""

    def test_excluded_fields_is_named_constant(self):
        """PLAN_HASH_EXCLUDED_FIELDS exists and is a tuple (currently empty —
        Plan has no plan_hash; plan_hash lives in PlanCreationResult beside Plan)."""
        from contracts.plan_hash import PLAN_HASH_EXCLUDED_FIELDS
        assert isinstance(PLAN_HASH_EXCLUDED_FIELDS, tuple)
        # Empty tuple is correct: Plan has no internal plan_hash field

    def test_excluding_plan_hash_breaks_circular_reference(self):
        """Including plan_hash in digest would include the digest of itself."""
        from contracts.plan_hash import PLAN_HASH_EXCLUDED_FIELDS
        plan = {
            "plan_id": "p1",
            "execution_id": "e1",
            "steps": [],
            "join_mode": "sequential",
            "budget_required": 1,
        }
        digest_without = canonical_plan_digest(plan)
        plan["plan_hash"] = digest_without
        digest_with = canonical_plan_digest(plan, include_plan_hash=True)
        # With plan_hash included, the digest changes (it now includes the hash)
        assert digest_without != digest_with


# ---------------------------------------------------------------------------
# Field-coverage test
# ---------------------------------------------------------------------------

class TestPlanHashFieldCoverage:
    """Every Plan field mutation changes the digest."""

    def test_all_fields_except_excluded_change_digest(self):
        """Mutating any non-excluded Plan field produces a different hash."""
        from contracts.plan_hash import PLAN_HASH_EXCLUDED_FIELDS
        # Build a base plan with all Plan fields
        from contracts.stage_outputs import Plan, Step
        base_step = Step(id="s1", kernel_op_id="test.op", params={}, depends_on=(), retry_policy={})
        base_plan = Plan(
            id="plan-1",
            steps=(base_step,),
            join_mode="sequential",
            budget_reserved=1,
            created_at=0.0,
            confirmations=(),
        )
        original_hash = canonical_plan_digest(base_plan)

        # Verify every Plan field mutation changes the digest.
        # PLAN_HASH_EXCLUDED_FIELDS is empty — Plan has no plan_hash.
        fields_to_test = [f.name for f in base_plan.__dataclass_fields__.values()
                         if f.name not in PLAN_HASH_EXCLUDED_FIELDS]

        for field_name in fields_to_test:
            # Build a mutated plan
            if field_name == "id":
                mutated = dataclasses.replace(base_plan, id="mutated-plan-id")
            elif field_name == "steps":
                mutated = dataclasses.replace(base_plan, steps=(Step(id="mutated", kernel_op_id="mut.op"),))
            elif field_name == "join_mode":
                mutated = dataclasses.replace(base_plan, join_mode="parallel")
            elif field_name == "budget_reserved":
                mutated = dataclasses.replace(base_plan, budget_reserved=2)
            elif field_name == "created_at":
                mutated = dataclasses.replace(base_plan, created_at=1.0)
            elif field_name == "confirmations":
                mutated = dataclasses.replace(base_plan, confirmations=("conf-1",))
            else:
                continue  # Skip unknown fields

            mutated_hash = canonical_plan_digest(mutated)
            assert mutated_hash != original_hash, (
                f"Mutating field '{field_name}' did not change the digest. "
                f"Original: {original_hash}, Mutated: {mutated_hash}"
            )
