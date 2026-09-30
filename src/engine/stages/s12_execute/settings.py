"""S12–S15 infrastructure settings (gate §21 S1), read from the environment, validated at construction (C37).

Timeout ordering, failing fast at startup:
  adapter_client_timeout < step_timeout   (TimeoutManager is authoritative)
  probe_timeout          < step_timeout
  lease_ttl              >= 3 x lease_renewal_interval

Admission limits (gate C39 soft quota, §21 S1) have phase defaults and may be set from the environment.
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
QUOTA_RETRY_MAX = 3            # soft quota: attempts of the §7.2 transaction before DENY quota_exhausted (C39)
QUOTA_BACKOFF_S = 0.05         # wait before attempt n+1: n x this
QUOTA_RETRY_AFTER_MS = 1000    # retry_after_ms on the soft-quota DENY
_OPTIONAL_ENV = {
    "quota_retry_max": ("S12_QUOTA_RETRY_MAX", int),
    "quota_backoff_s": ("S12_QUOTA_BACKOFF_S", float),
    "quota_retry_after_ms": ("S12_QUOTA_RETRY_AFTER_MS", int),
}


@dataclass(frozen=True)
class ExecutionSettings:
    adapter_client_timeout_s: float
    step_timeout_s: float
    probe_timeout_s: float
    lease_ttl_s: float
    lease_renewal_interval_s: float
    quota_retry_max: int = QUOTA_RETRY_MAX
    quota_backoff_s: float = QUOTA_BACKOFF_S
    quota_retry_after_ms: int = QUOTA_RETRY_AFTER_MS

    def __post_init__(self) -> None:
        for f in fields(self):
            if not getattr(self, f.name) > 0:
                raise ValueError(f"{f.name} must be > 0")
        for name in ("quota_retry_max", "quota_retry_after_ms"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
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
            values = {field: float(env[name]) for field, name in _ENV.items()}
            values |= {field: kind(env[name]) for field, (name, kind) in _OPTIONAL_ENV.items() if env.get(name)}
            return cls(**values)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid S12 settings: {exc}") from exc
