"""M10 sabotage: a half-open trial that is not a success or a failure is never released (C37: never stuck)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("guard_base", pathlib.Path(__file__).with_name("_guard_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)

    def transform(kw):
        kw["breaker"] = base.BreakerProxy(kw["breaker"], record_ignored=lambda b, p: None)
        return kw
    base.capture(transform)
