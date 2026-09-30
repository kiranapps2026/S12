"""M12 sabotage: steps run in plan-list order, ignoring depends_on (C11: topological order, ties by index)."""
def apply():
    import engine.stages.s12_execute.loop as loop

    def topological_order(steps):
        return list(steps)
    loop.topological_order = topological_order
