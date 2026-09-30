"""M10 sabotage: a client error (401/403/404/422) counts as a provider failure (C37: it never counts)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("guard_base", pathlib.Path(__file__).with_name("_guard_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)

    def transform(kw):
        kw["breaker"] = base.BreakerProxy(kw["breaker"], record_ignored=lambda b, p: b.record_failure(p))
        return kw
    base.capture(transform)
