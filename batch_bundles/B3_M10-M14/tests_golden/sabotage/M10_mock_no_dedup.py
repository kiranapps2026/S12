"""M10 sabotage: the mock provider executes a repeated idempotency key again (§15.3: a repeated key never executes twice)."""
def apply():
    from adapters.runtime.mock_adapter import MockAdapter
    original = MockAdapter.call

    async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
        if call_meta is not None:
            from dataclasses import replace
            call_meta = replace(call_meta, idempotency_key=f"{call_meta.idempotency_key}#{call_meta.attempt_id}")
        return await original(self, kernel_op_id, params, binding, context, call_meta=call_meta)
    MockAdapter.call = call
