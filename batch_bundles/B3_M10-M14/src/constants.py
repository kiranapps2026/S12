"""
Canonical vocabulary constants for S0–S11.

These constants prevent misspellings and ensure vocabulary is sourced
from a single place. String literals in src/ code that match NON_CANONICAL
in owner_certify.py are forbidden — use these constants instead.

Source: DATA_CONTRACTS.md §MUTATION_SAFETY, PIPELINE_STAGES.md §7, §12, §15
"""
from __future__ import annotations

# === Mutation types (R-P canonical: R | W | D | IRREVERSIBLE) ===
MUTATION_READ = "R"
MUTATION_WRITE = "W"
MUTATION_DELETE = "D"
MUTATION_IRREVERSIBLE = "IRREVERSIBLE"

# === Path decision (lowercase per R-P: fast | workflow | agentic | clarify | deny) ===
PATH_DECISION_AGENTIC = "agentic"
PATH_DECISION_CLARIFY = "clarify"
PATH_DECISION_DENY = "deny"
PATH_DECISION_FAST = "fast"
PATH_DECISION_WORKFLOW = "workflow"

# === Confirmation statuses (R-P canonical: pending | consumed | rejected | expired) ===
CONFIRMATION_STATUS_PENDING = "pending"
CONFIRMATION_STATUS_CONSUMED = "consumed"
CONFIRMATION_STATUS_REJECTED = "rejected"
CONFIRMATION_STATUS_EXPIRED = "expired"

# === Execution outcome (DATA_CONTRACTS §4) ===
EXECUTION_OUTCOME_SUCCESS = "SUCCESS"
EXECUTION_OUTCOME_PARTIAL = "PARTIAL"
EXECUTION_OUTCOME_FAILURE = "FAILURE"
EXECUTION_OUTCOME_UNKNOWN = "UNKNOWN"
EXECUTION_OUTCOME_NOT_EXECUTED = "NOT_EXECUTED"
EXECUTION_OUTCOME_DEAD_LETTER = "DEAD_LETTER"

# === Graph complexity (R-P canonical: simple | chain | complex) ===
GRAPH_COMPLEXITY_SINGLE_STEP = "simple"
GRAPH_COMPLEXITY_LINEAR = "chain"
GRAPH_COMPLEXITY_BRANCH = "complex"
GRAPH_COMPLEXITY_DAG = "complex"
GRAPH_COMPLEXITY_WORKFLOW = "complex"

# === Approval statuses (R-P canonical: rejected | expired; no "approved" status) ===
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
