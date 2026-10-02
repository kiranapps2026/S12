"""M8 sabotage: gates evaluated in reverse (the last failing gate decides, not the first)."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.admission_control as ac
    original = ac.evaluate
    fields = ["system_overloaded", "budget_available", "db_pool_pressure", "circuit_open", "worker_capacity_available",
              "provider_allowed", "mode_allowed", "workspace_active", "tenant_active", "tenant_quota_exceeded",
              "kill_switch_engaged"]
    passing = {"system_overloaded": False, "budget_available": True, "db_pool_pressure": False, "circuit_open": False,
               "worker_capacity_available": True, "provider_allowed": True, "mode_allowed": True,
               "workspace_active": True, "tenant_active": True, "tenant_quota_exceeded": False,
               "kill_switch_engaged": False}

    def evaluate(snapshot):
        for name in fields:                           # the latest gate that fails, alone
            if getattr(snapshot, name) != passing[name]:
                only = dataclasses.replace(snapshot, **{k: v for k, v in passing.items() if k != name})
                return original(only)
        return original(snapshot)
    ac.evaluate = evaluate
