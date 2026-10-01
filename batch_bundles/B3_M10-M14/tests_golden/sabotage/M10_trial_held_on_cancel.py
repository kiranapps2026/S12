"""M10 sabotage: a call cancelled while the adapter runs keeps its half-open trial (C37: the breaker is never stuck)."""
def apply():
    import asyncio
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("guard_base", pathlib.Path(__file__).with_name("_guard_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)

    def ignored(breaker, provider):
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            return None
        return breaker.record_ignored(provider)

    def transform(kw):
        kw["breaker"] = base.BreakerProxy(kw["breaker"], record_ignored=ignored)
        return kw
    base.capture(transform)
