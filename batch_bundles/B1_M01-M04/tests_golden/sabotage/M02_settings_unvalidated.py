"""M2 sabotage: settings accept inverted timeouts (C37 not enforced)."""
def apply():
    from dataclasses import dataclass
    import engine.stages.s12_execute.settings as s

    @dataclass(frozen=True)
    class ExecutionSettings:
        adapter_client_timeout_s: float
        step_timeout_s: float
        probe_timeout_s: float
        lease_ttl_s: float
        lease_renewal_interval_s: float

        @classmethod
        def from_env(cls, env):
            return cls(*(float(env[k]) for k in ("S12_ADAPTER_CLIENT_TIMEOUT_S", "S12_STEP_TIMEOUT_S",
                         "S12_PROBE_TIMEOUT_S", "S12_LEASE_TTL_S", "S12_LEASE_RENEWAL_INTERVAL_S")))
    s.ExecutionSettings = ExecutionSettings
