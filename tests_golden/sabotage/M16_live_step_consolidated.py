"""M16 sabotage: steps that are not terminal are ignored, so a run is consolidated while it still has live steps
(§10, I3: every step terminal first)."""
def apply():
    from engine.stages.s13_reconciliation import consolidation
    original = consolidation.consolidation_outcome

    def consolidation_outcome(steps):
        steps = [(s, r) for s, r in steps if s in ("completed", "failed", "cancelled", "skipped", "dead_letter")]
        return original(steps or [("failed", None)])
    consolidation.consolidation_outcome = consolidation_outcome
    import sys
    adapter = sys.modules.get("adapters.postgres.consolidation")
    if adapter is not None:
        adapter.consolidation_outcome = consolidation_outcome
