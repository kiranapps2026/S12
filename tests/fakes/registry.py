"""In-memory capability registry with a small standard catalog."""
from __future__ import annotations

from supragents.contracts.registry import BindingRow, CapabilityMetadata, KernelOperation, RegistryVersions
from supragents.contracts.vocabulary import Mutation, RetrySafety, TruthState

VERSIONS = RegistryVersions(
    capability_version="cap-7", binding_version="bind-3",
    risk_policy_version="risk-1", authorization_version="auth-4",
    worker_runtime_version="rt-1", model_version="model-9",
)


def capability(intent: str, mutation: Mutation, risk: float = 0.1,
               truth: TruthState = TruthState.PRODUCTION_ENABLED, suffix: str = "") -> CapabilityMetadata:
    return CapabilityMetadata(
        capability_id=f"cap.{intent}{suffix}", name=intent, intent=intent, mutation=mutation,
        risk_floor=risk, risk_rule=0.0, risk_implied=0.0, truth_state=truth,
    )


def kernel_op(op_id: str, mutation: Mutation, cost: int = 1, risk: float = 0.0,
              truth: TruthState = TruthState.PRODUCTION_ENABLED) -> KernelOperation:
    return KernelOperation(
        kernel_op_id=op_id, mutation=mutation, risk_floor=risk, cost=cost, timeout_seconds=30,
        retry_safety=RetrySafety.SAFE, truth_state=truth,
    )


def binding(cap: CapabilityMetadata, op_id: str, binding_id: str = "b-1", priority: int = 1,
            created_at: float = 1.0, active: bool = True, provider: str = "crm") -> BindingRow:
    return BindingRow(
        binding_id=binding_id, capability_id=cap.capability_id, kernel_op_id=op_id,
        provider=provider, engine_module="engines.crm", adapter_class="CrmAdapter",
        priority=priority, created_at=created_at, is_active=active,
    )


class FakeRegistry:
    def __init__(self) -> None:
        self.capabilities: list[CapabilityMetadata] = []
        self.bindings: list[BindingRow] = []
        self.kernel_ops: dict[str, KernelOperation] = {}

    def add(self, cap: CapabilityMetadata, op: KernelOperation, **binding_args) -> FakeRegistry:
        self.capabilities.append(cap)
        self.kernel_ops[op.kernel_op_id] = op
        self.bindings.append(binding(cap, op.kernel_op_id, **binding_args))
        return self

    async def capabilities_for_intent(self, tenant_id, intent):
        return tuple(c for c in self.capabilities if c.intent == intent)

    async def bindings_for(self, tenant_id, capability_id):
        return tuple(b for b in self.bindings if b.capability_id == capability_id)

    async def kernel_operation(self, kernel_op_id):
        return self.kernel_ops.get(kernel_op_id)

    async def versions(self):
        return VERSIONS


def standard_registry() -> FakeRegistry:
    """contact.list (R), contact.create (W), contact.delete (D), email.send (IRREVERSIBLE)."""
    registry = FakeRegistry()
    registry.add(capability("contact.list", Mutation.READ), kernel_op("crm.contact_list", Mutation.READ))
    registry.add(capability("contact.create", Mutation.WRITE, 0.2),
                 kernel_op("crm.contact_create", Mutation.WRITE, cost=3), binding_id="b-2")
    registry.add(capability("contact.delete", Mutation.DELETE, 0.5),
                 kernel_op("crm.contact_delete", Mutation.DELETE, cost=5), binding_id="b-3")
    registry.add(capability("email.send", Mutation.IRREVERSIBLE, 0.6),
                 kernel_op("mail.send", Mutation.IRREVERSIBLE, cost=3), binding_id="b-4")
    return registry
