"""
Step F: Verify StageResult alias and compatibility adapter are removed.

Source: Item 1 (remove StageResult alias), Item 3 compatibility adapter removal.
"""

from __future__ import annotations

import pytest


class TestDeadCodeRemoved:
    """StageResult alias and compatibility adapter must not exist in src/."""

    def test_stage_result_not_in_contracts(self):
        """StageResult alias was removed from contracts (no longer needed — PipelineState is the contract)."""
        import contracts
        assert not hasattr(contracts, 'StageResult'), \
            "StageResult alias still exists — remove it and update all imports"

    def test_no_adapter_in_engine_stages(self):
        """No compatibility adapter class in engine/stages."""
        import importlib
        for mod_name in [
            'engine.stages.s0_entry',
            'engine.stages.s1_normalize',
            'engine.stages.s2_intent_analysis',
            'engine.stages.s3_capability_discovery',
            'engine.stages.s4_graph_classification',
            'engine.stages.s5_provider_resolution',
            'engine.stages.s6_task_profile_assembly',
            'engine.stages.s7_path_decision',
            'engine.stages.s8_safety_gate',
            'engine.stages.s9_plan_creation',
            'engine.stages.s10_confirmation',
            'engine.stages.s11_plan_validation',
        ]:
            mod = importlib.import_module(mod_name)
            assert not hasattr(mod, 'Adapter'), \
                f"{mod_name} has an Adapter class — remove compatibility adapter"
