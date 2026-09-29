"""
Billing contracts — usage tracking and invoicing.

Source: DATA_CONTRACTS.md §21-26, IDENTITY_AND_TENANCY.md §21
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ResourceMeter:
    """Resource consumption measurement."""
    resource_type: str                     # llm_tokens, compute_seconds, api_calls, storage_bytes
    quantity: float                        # Amount consumed
    unit: str                              # tokens, seconds, calls, bytes
    unit_price: float = 0.0                # Price per unit
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BillingUsageRecord:
    """A billing usage record for a specific resource consumption."""
    record_id: str                         # UUID v4
    execution_id: str
    tenant_id: str
    resource_meters: list[ResourceMeter]
    total_cost: float
    currency: str = "USD"
    billing_period_start: float = 0.0
    billing_period_end: float = 0.0
    created_at: float = field(default_factory=lambda: 0.0)


@dataclass(frozen=True)
class CreditBalance:
    """Tenant credit balance."""
    tenant_id: str
    balance: float
    currency: str = "USD"
    credit_limit: float = 0.0
    is_overdraft_allowed: bool = False
    updated_at: float = field(default_factory=lambda: 0.0)


# 10 billing golden rules (enforced by code, not just documentation):
BILLING_GOLDEN_RULES: tuple[str, ...] = (
    "1. LLM usage must ALWAYS be recorded, even on failure",
    "2. Budget checks must happen before resource consumption",
    "3. Budget reservations must be idempotent",
    "4. Failed executions must still record cost",
    "5. Retries must not double-count base cost",
    "6. Refunds must go through the billing service, not direct DB updates",
    "7. Invoice generation must use finalized usage records only",
    "8. Credit balance must be checked before reservation",
    "9. Currency conversion must use the rate at execution time",
    "10. All billing events must be immutable after creation",
)
