"""M8 sabotage: selection ignores state locality (the current owner gets no preference)."""
def apply():
    import engine.stages.s12_execute.selection as s
    original = s.select_worker

    def select_worker(candidates, *, current_owner):
        return original(candidates, current_owner=None)
    s.select_worker = select_worker
