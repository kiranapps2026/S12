from dataclasses import dataclass, field
from contracts.kernel_policy import KernelPolicy
from engine.stages.s8_safety_gate.dependencies import S8Dependencies

RAISE = object()   # sentinel: make a provider method raise


@dataclass
class ConfigurableAuthState:
    """Configurable auth state for tests.

    Supports two modes:
    1. Direct defaults: set user/tenant/connection/grant/scope/budget fields.
    2. Dict lookup: populate users/tenants/connections/grants/scopes/budgets dicts.
       Dict entries take priority over direct defaults.
    """
    user: object = "active"
    tenant: object = "active"
    connection: object = ("active", None)
    grant: object = True
    scope: object = True
    budget: object = True
    calls: list = field(default_factory=list)
    users: dict = field(default_factory=dict)
    tenants: dict = field(default_factory=dict)
    connections: dict = field(default_factory=dict)
    grants: dict = field(default_factory=dict)
    scopes: dict = field(default_factory=dict)
    budgets: dict = field(default_factory=dict)

    def _get(self, name, value):
        self.calls.append(name)
        if value is RAISE:
            raise RuntimeError(f"{name} unavailable")
        return value

    def user_status(self, user_id):
        val = self.users.get(user_id, self.user)
        return self._get("user_status", val)
    def tenant_status(self, tenant_id):
        val = self.tenants.get(tenant_id, self.tenant)
        return self._get("tenant_status", val)
    def connection_status(self, connection_id):
        val = self.connections.get(connection_id, self.connection)
        res = self._get("connection_status", val)
        if isinstance(res, str):
            return (res, None)
        return res
    def has_grant(self, tenant_id, user_id, capability_id):
        val = self.grants.get(capability_id, self.grant)
        return self._get("has_grant", val)
    def in_scope(self, tenant_id, user_id, workspace_id):
        val = self.scopes.get(workspace_id, self.scope)
        return self._get("in_scope", val)
    def budget_available(self, tenant_id, amount):
        val = self.budgets.get(tenant_id, self.budget)
        return self._get("budget_available", val)


@dataclass
class ConfigurableCircuitBreaker:
    value: object = "CLOSED"
    calls: list = field(default_factory=list)
    def state(self, provider_id):
        self.calls.append(("state", provider_id))
        if self.value is RAISE:
            raise RuntimeError("breaker unavailable")
        return self.value


@dataclass
class ConfigurableMutationPolicy:
    value: object = True
    calls: list = field(default_factory=list)
    def permits(self, mutation, risk):
        self.calls.append(("permits", (mutation, risk)))
        if self.value is RAISE:
            raise RuntimeError("mutation policy unavailable")
        return self.value


def make_s8_deps(*, kill_switch=False, auth=None, breaker=None,
                 mutation=None, omit=()):
    deps = dict(
        policy=KernelPolicy(kill_switch_engaged=kill_switch, risk_deny_threshold=0.95),
        auth_state=auth or ConfigurableAuthState(),
        circuit_breaker=breaker or ConfigurableCircuitBreaker(),
        mutation_policy=mutation or ConfigurableMutationPolicy(),
    )
    for name in omit:
        deps[name] = None
    return S8Dependencies(**deps)


def make_s8_deps_with_ks(kill_switch, **kwargs):
    """make_s8_deps with the kill switch as a required positional value."""
    return make_s8_deps(kill_switch=kill_switch, **kwargs)


# Compatibility aliases used by test_s7_to_s11.py
InMemoryCircuitBreaker = ConfigurableCircuitBreaker
AllowAllMutationPolicy = ConfigurableMutationPolicy
InMemoryAuthorizationStateProvider = ConfigurableAuthState
