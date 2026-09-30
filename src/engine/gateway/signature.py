"""Webhook signature check: `X-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>`.

The signed text is `<t>.<raw body>` (EVENT_GATEWAY_AND_ROUTER §11). The timestamp must be
within 300 s of server time (replay window). Comparison is constant-time.
"""
from __future__ import annotations

import hashlib
import hmac
import re

MAX_SKEW_SECONDS = 300
_HEADER = re.compile(r"^t=(\d{1,12}),v1=([0-9a-f]{64})$")


class SignatureProblem(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_header(header: str | None) -> tuple[int, str]:
    match = _HEADER.match((header or "").strip())
    if match is None:
        raise SignatureProblem("bad_signature_header")
    return int(match.group(1)), match.group(2)


def check_timestamp(timestamp: int, now: float) -> None:
    if abs(now - timestamp) > MAX_SKEW_SECONDS:
        raise SignatureProblem("stale_timestamp")


def matches(secret: bytearray, timestamp: int, raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(bytes(secret), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign(secret: bytes, timestamp: int, raw_body: bytes) -> str:
    """The header value a sender produces (used by tests and by sources we control)."""
    digest = hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"
