"""What S12 entry (gate §7.1) can rely on after a multi-step S11: one version per kind, one
binding per step, every value copied from that step's own binding. Ordinary (not golden) tests."""
import asyncio
import dataclasses

from tests.fixtures.multi import ChainRegistry, DEFAULT_CAPS, chain_deps, ChainModel, run_chain
from tests.stages.test_m2a_chain import CREATE_THEN_EMAIL


def test_a_chain_whose_bindings_carry_different_versions_is_refused_at_s11():
    class Mixed(ChainRegistry):
        async def list_bindings(self, capability_id):
            rows = await super().list_bindings(capability_id)
            if capability_id == "cap.email.send":
                rows = [dataclasses.replace(r, binding_version="bind-v9") for r in rows]
            return rows
    deps = chain_deps(ChainModel(CREATE_THEN_EMAIL))
    deps = dataclasses.replace(deps, registry=Mixed())
    result, _ = run_chain(CREATE_THEN_EMAIL, deps=deps)
    assert (result.status.value, result.final_stage, result.reason) == ("DENY", "S11", "binding_mismatch")
    assert result.final_state.execution_manifest is None


def test_the_manifest_of_a_chain_carries_single_versions_s12_can_compare():
    m = run_chain(CREATE_THEN_EMAIL)[0].final_state.execution_manifest
    assert "|" not in (m.capability_version + m.binding_version + m.risk_policy_version + m.authorization_version)


def test_every_plan_step_maps_to_one_binding_by_index():
    from engine.stages.plan_steps import plan_step_bindings
    state = run_chain([("contact.create", {"items": [{}, {}]}), ("email.send", {})])[0].final_state
    mapped = plan_step_bindings(state)
    assert [m.binding.kernel_op_id for m in mapped] == ["op.contact.create"] * 2 + ["op.email.send"]
    assert [s.kernel_op_id for s in state.plan.plan.steps] == [m.binding.kernel_op_id for m in mapped]
