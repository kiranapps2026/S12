"""M10 sabotage: the BaseAdapter default probe claims success (C32: the default is INCONCLUSIVE, safe by construction)."""
def apply():
    from contracts.adapter_interface import BaseAdapter, ProbeOutcome

    async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
        return ProbeOutcome.EXECUTED_SUCCESS
    BaseAdapter.probe = probe
