"""
Data sanitizer — input sanitization and injection defense.

Source: SECURITY.md §4, DATA_CONTRACTS.md §9
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
import types
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """Injection detection severity levels."""
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SeverityAction(StrEnum):
    """Actions for each severity level."""
    ALLOW = "ALLOW"
    SANITIZE = "SANITIZE"
    WARN = "WARN"
    BLOCK = "BLOCK"


# Severity → Action mapping (explicit, from SECURITY.md)
SEVERITY_ACTION_MAP = types.MappingProxyType({
    Severity.SAFE: SeverityAction.ALLOW,
    Severity.LOW: SeverityAction.ALLOW,
    Severity.MEDIUM: SeverityAction.WARN,
    Severity.HIGH: SeverityAction.SANITIZE,
    Severity.CRITICAL: SeverityAction.BLOCK,
})


# Injection patterns (from SECURITY.md §4)
INJECTION_PATTERNS = types.MappingProxyType({
    "sql_injection": (r"(?i)(union\s+select|drop\s+table|insert\s+into|delete\s+from|;--|exec\()", Severity.HIGH),
    "prompt_injection": (r"(?i)(ignore\s+(previous|all)\s+instructions|you\s+are\s+now|disregard\s+above)", Severity.CRITICAL),
    "code_injection": (r"(?i)(eval\(|exec\(|__import__|subprocess|os\.system)", Severity.HIGH),
    "path_traversal": (r"(\.\.\/|\.\.\\)", Severity.MEDIUM),
    "xss_basic": (r"(?i)(<script|javascript:|onload=|onerror=)", Severity.MEDIUM),
    "command_injection": (r"(?i)(\|\s*\w+|`.*`|\$\(.*\))", Severity.HIGH),
    "ldap_injection": (r"(?i)(\*\)\(\|.*\|)", Severity.HIGH),
    "xml_injection": (r"(?i)(<!DOCTYPE|<!ENTITY)", Severity.MEDIUM),
    "template_injection": (r"(?i)(\{\{.*\}\}|\{\%.*\%\})", Severity.MEDIUM),
})


@dataclass(frozen=True)
class SanitizationResult:
    """Result of sanitizing an input value."""
    original: Any
    sanitized: Any
    severity: Severity
    action: SeverityAction
    pattern_matched: str | None = None
    was_modified: bool = False


class DataSanitizer:
    """
    Input sanitization and injection detection.

    Canonical owner: S1 / Normalize
    All user input MUST pass through this sanitizer before reaching any other stage.
    """

    @classmethod
    def sanitize(cls, value: Any) -> SanitizationResult:
        """Sanitize a single value."""
        if not isinstance(value, str):
            return SanitizationResult(
                original=value, sanitized=value,
                severity=Severity.SAFE, action=SeverityAction.ALLOW,
            )

        for pattern_name, (pattern, severity) in INJECTION_PATTERNS.items():
            match = re.search(pattern, value)
            if match:
                action = SEVERITY_ACTION_MAP[severity]
                sanitized = cls._apply_action(value, action, severity)
                return SanitizationResult(
                    original=value, sanitized=sanitized,
                    severity=severity, action=action,
                    pattern_matched=pattern_name,
                    was_modified=(action in (SeverityAction.SANITIZE, SeverityAction.BLOCK)),
                )

        return SanitizationResult(
            original=value, sanitized=value,
            severity=Severity.SAFE, action=SeverityAction.ALLOW,
        )

    @staticmethod
    def _apply_action(value: str, action: SeverityAction, severity: Severity) -> str:
        """Apply the appropriate action to a detected injection."""
        if action == SeverityAction.ALLOW:
            return value
        elif action == SeverityAction.SANITIZE:
            return re.sub(r"[<>\"';\\]", "", value)
        elif action == SeverityAction.BLOCK:
            return ""
        return value

    @classmethod
    def is_safe(cls, value: Any) -> bool:
        """Quick check if a value is safe (no injection detected)."""
        result = cls.sanitize(value)
        return result.severity in (Severity.SAFE, Severity.LOW)
