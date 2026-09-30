"""S12–S15 infrastructure settings (gate §21 S1), read from the environment, validated at construction (C37).

Timeout ordering, failing fast at startup:
  adapter_client_timeout < step_timeout   (TimeoutManager is authoritative)
  probe_timeout          < step_timeout
  lease_ttl              >= 3 x lease_renewal_interval
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields

_ENV = {
    "adapter_client_timeout_s": "S12_ADAPTER_CLIENT_TIMEOUT_S",
    "step_timeout_s": "S12_STEP_TIMEOUT_S",
    "probe_timeout_s": "S12_PROBE_TIMEOUT_S",
    "lease_ttl_s": "S12_LEASE_TTL_S",
    "lease_renewal_interval_s": "S12_LEASE_RENEWAL_INTERVAL_S",
}


@dataclass(frozen=True)
class ExecutionSettings:
    adapter_client_timeout_s: float
    step_timeout_s: float
    probe_timeout_s: float
    lease_ttl_s: float
    lease_renewal_interval_s: float

    def __post_init__(self) -> None:
        for f in fields(self):
            if not getattr(self, f.name) > 0:
                raise ValueError(f"{f.name} must be > 0")
        if not self.adapter_client_timeout_s < self.step_timeout_s:
            raise ValueError("adapter_client_timeout_s must be < step_timeout_s (C37)")
        if not self.probe_timeout_s < self.step_timeout_s:
            raise ValueError("probe_timeout_s must be < step_timeout_s (C37)")
        if not self.lease_ttl_s >= 3 * self.lease_renewal_interval_s:
            raise ValueError("lease_ttl_s must be >= 3 x lease_renewal_interval_s (C37)")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ExecutionSettings:
        missing = [name for name in _ENV.values() if not env.get(name)]
        if missing:
            raise ValueError(f"missing settings: {', '.join(missing)}")
        try:
            return cls(**{field: float(env[name]) for field, name in _ENV.items()})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid S12 settings: {exc}") from exc
