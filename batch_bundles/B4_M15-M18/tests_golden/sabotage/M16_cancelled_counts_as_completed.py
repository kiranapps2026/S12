"""M16 sabotage: a CANCELLED step is counted like a COMPLETED one, so a run with a cancelled step consolidates to
COMPLETED (§10: CANCELLED counts as not completed; I13)."""
def apply():
    from engine.stages.s13_reconciliation import consolidation
    original = consolidation.consolidation_outcome

    def consolidation_outcome(steps):
        steps = [("completed", None) if s == "cancelled" and r != "run_dead_lettered" else (s, r) for s, r in steps]
        return original(steps)
    consolidation.consolidation_outcome = consolidation_outcome
    import sys
    adapter = sys.modules.get("adapters.postgres.consolidation")
    if adapter is not None:
        adapter.consolidation_outcome = consolidation_outcome
