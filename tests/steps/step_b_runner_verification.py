"""
Step B: Verify PipelineState runner stage list matches PIPELINE_STAGES.md sections.

Reads the doc's section headings (## N. S{X} — Title) and compares against
the STAGE_OUTPUT_FIELD ordered dict in contracts/pipeline_state.py.

The runner must execute stages in the exact order listed in PIPELINE_STAGES.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from contracts.pipeline_state import STAGE_OUTPUT_FIELD


def _extract_stage_ids_from_doc(doc_path: Path) -> list[str]:
    """Extract S{X} stage IDs from PIPELINE_STAGES.md headings."""
    content = doc_path.read_text(encoding='utf-8')
    # Match headings like: ## 8. S6 — Task Profile Assembly
    pattern = re.compile(r'^##\s+\d+\.\s+(S\d+)', re.MULTILINE)
    return pattern.findall(content)


def test_runner_stage_order_matches_doc():
    """PipelineState stage outputs are in the same order as PIPELINE_STAGES.md."""
    doc_path = Path(__file__).parent.parent.parent / "docs" / "implementation" / "PIPELINE_STAGES.md"
    assert doc_path.exists(), f"PIPELINE_STAGES.md not found at {doc_path}"
    doc_stages = _extract_stage_ids_from_doc(doc_path)
    assert len(doc_stages) >= 10, f"Expected >=10 stage sections, found {len(doc_stages)}"

    # STAGE_OUTPUT_FIELD is an OrderedDict mapping stage_id → field_name
    # The key order is the stage execution order.
    code_stages = list(STAGE_OUTPUT_FIELD.keys())

    # S0-S11 should match the doc order exactly (S12+ are future stages)
    doc_s0_s11 = doc_stages[:len(code_stages)]
    assert code_stages == doc_s0_s11, (
        f"Stage order mismatch (S0-S11).\n"
        f"PIPELINE_STAGES.md: {doc_s0_s11}\n"
        f"STAGE_OUTPUT_FIELD: {code_stages}\n"
        f"First divergence at index: "
        f"{next((i for i, (a, b) in enumerate(zip(code_stages, doc_s0_s11)) if a != b), len(code_stages))}"
    )
